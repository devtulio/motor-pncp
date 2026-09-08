"""Cliente HTTP do PNCP: pacing, retry com backoff, beacon de progresso.

Só stdlib de propósito: os sistemas que consomem este motor são builds
PyInstaller onefile, e o gargalo real (timeout de socket, que não cobre
DNS) é o mesmo em urllib/requests/httpx — trocar não resolve nada e soma
uma dependência nova ao empacotamento. Ver README.md.
"""
import concurrent.futures
import email.utils
import http.client
import json
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Literal

from ._resiliencia import Dedup
from .configuracao import Config
from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado

USER_AGENT_PADRAO = "motor-pncp/0.1 (coleta de contratacoes; open-source)"

# Logger de biblioteca: sem handler próprio (NullHandler em __init__.py);
# quem consome liga `logging.getLogger("motor_pncp")` se quiser contar
# tentativas, status e latência por requisição. O callback `progresso`
# continua sendo o canal pra UI — isto é diagnóstico.
_log = logging.getLogger("motor_pncp")

# Códigos que o PNCP devolve por sobrecarga, não por defeito no pedido.
# 422 entrou depois de um incidente real: numa madrugada de 429/500/503/504,
# o portal também devolveu 422 numa janela que, refeita depois, respondeu
# 204 normalmente. Um 422 "de verdade" (parâmetro inválido) esgota as
# tentativas e falha do mesmo jeito — custa uma escada a mais numa consulta
# que morreria de qualquer forma, contra confundir portal instável com
# parâmetro errado.
HTTP_TRANSITORIOS = (422, 500, 502, 503, 504)
# 422 retenta, mas pouco: a spec o classifica como erro do cliente (sem
# retry), e o incidente real que o pôs na lista acima foi um 422 espúrio
# sob carga. Duas tentativas cobrem o espúrio; um 422 legítimo (parâmetro
# errado — bug de desenvolvimento) falha em segundos, com o motivo do corpo
# na mensagem, em vez de pagar a escada inteira (~5min) pra descobrir.
TENTATIVAS_422 = 2
_LIMITE_MOTIVO = 200


def _motivo(erro):
    """Trecho do corpo da resposta de erro, pra mensagem dizer o porquê.

    O corpo de um 4xx do PNCP costuma trazer o motivo de verdade (ex.:
    "Data inicial inválida ou anterior a 20210401"). Descartá-lo deixa a
    mensagem só com "HTTP 422 em /caminho" — diagnosticar exige reproduzir
    a chamada à mão.
    """
    try:
        corpo = " ".join(erro.read().decode("utf-8", "replace").split())
    except Exception:
        return ""
    if not corpo or corpo.lstrip().startswith("<"):
        return ""  # página HTML de erro do portal não informa nada
    return f" — {corpo[:_LIMITE_MOTIVO]}"


def _espera(tentativa):
    """Backoff exponencial com *full jitter*: sorteio em [0, 2^tentativa].

    Um desvio pequeno somado ao expoente (o desenho anterior, +0,5s) não
    desfaz a sincronização: conexões que falharam juntas voltam dentro de
    meio segundo uma da outra e repetem a rajada. Sortear o intervalo
    inteiro espalha as voltas de verdade (é a variante com menos chamadas
    totais na simulação de Brooker, AWS 2015). O piso de 0s é coberto
    pelo pacing, que vale também em paralelo.
    """
    return random.uniform(0, 2 ** tentativa)


def _retry_after(headers, teto):
    """Segundos pedidos em `Retry-After` (inteiro ou data HTTP, RFC 9110
    §10.2.3), limitados a `teto`; `None` se ausente ou ilegível.

    Vale para 429 e 503 — a spec define o header para os dois. O teto
    existe porque um portal pode pedir uma hora; a coleta não pode ficar
    muda numa thread esse tempo todo.
    """
    valor = (headers.get("Retry-After") or "").strip()
    if not valor:
        return None
    if valor.isdigit():
        segundos = int(valor)
    else:
        try:
            quando = email.utils.parsedate_to_datetime(valor)
        except (TypeError, ValueError):
            return None
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        segundos = (quando - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, min(float(segundos), teto))


class Cliente:
    """Uma conexão lógica com o PNCP — pacing e retry por instância, não
    de módulo, para não vazar estado entre coletas."""

    def __init__(self, adaptativo, *, config: Config = Config(),
                 user_agent=USER_AGENT_PADRAO, progresso=None, cancelado=None):
        self._adaptativo = adaptativo
        self._config = config
        self._dedup = Dedup(config.janela_operacional)
        self._user_agent = user_agent
        self._progresso = progresso
        self._cancelado = cancelado
        self._ultima_req = 0.0
        self._trava_pacing = threading.Lock()

    def _timeout(self, tentativa):
        timeouts = self._config.timeouts
        return timeouts[min(tentativa, len(timeouts) - 1)]

    def _checar_cancelado(self):
        if self._cancelado is not None and self._cancelado.is_set():
            raise SyncCancelado("coleta cancelada")

    def _dormir(self, segundos):
        """`time.sleep` que acorda na hora se `cancelado` for acionado.

        Sem isto, o backoff (até 8s) e a espera de `Retry-After` são o
        único trecho da coleta em que o pedido de parada não chega: o
        callback `progresso` (o outro ponto de checagem) pode estar
        silenciado pelo `Dedup` dentro da janela de uma causa repetida.
        """
        if self._cancelado is None:
            time.sleep(segundos)
        elif self._cancelado.wait(segundos):
            raise SyncCancelado("coleta cancelada")

    def avisar_progresso(self, msg):
        """Beacon: chamado a cada tentativa de retry (não só no fim de uma
        fase) — sem isso, os até ~5min de retry de uma única requisição
        ficam mudos, indistinguíveis de travamento de verdade."""
        if not self._progresso:
            return
        try:
            self._progresso(msg)
        except SyncCancelado:
            raise  # parada a pedido não é cortesia
        except Exception:
            pass  # aviso é cortesia; não pode derrubar o retry por isso

    def _avisar_causa_recorrente(self, chave, mensagem):
        """Como `avisar_progresso`, mas agrupado por `chave` — ver `Dedup`.
        Usado só nos avisos de retry por falha (a fonte real do storm de
        linhas repetidas); progresso de item/contratação não passa por
        aqui, cada um já é informação nova."""
        emitir = self._dedup.registrar(chave, mensagem)
        if emitir:
            self.avisar_progresso(emitir)

    def get(self, url_base, caminho, params, *, tentativas=None, pacing=True,
            modo_404: Literal["ausente", "erro", "retry"] = "ausente"):
        """GET com pacing e retry/backoff. Dict do JSON, ou None sem dados.

        `modo_404` decide o que um 404 significa — não é sempre a mesma
        coisa no PNCP, e as três leituras têm cada uma um consumidor real
        (por isso um valor só, não dois booleanos independentes: as três
        opções são mutuamente exclusivas por natureza, nunca "um pouco de
        cada").

        `"ausente"` (default): 404 é semântico — "CNPJ não existe", "item
        sem resultado homologado" — devolve `None`.

        `"retry"`: para LISTAGENS (contratações/itens/contratos/atas/
        PCA), onde "sem registros" é 204/corpo vazio, nunca 404 — um 404
        aqui é falha transitória do portal; sem isso ele vira "janela
        vazia" e quem persiste avança a marca d'água sobre dados nunca
        baixados. Retenta e, se persistir, levanta `PncpErro`.

        `"erro"`: 404 vira `ItensIndisponiveis` na hora — usado em
        listagens de UM registro específico (itens de uma contratação,
        termos de um contrato), onde 404 também não significa "sem
        registro" (ver `ItensIndisponiveis`).
        """
        if tentativas is None:
            tentativas = self._adaptativo.tentativas_atual()
        url = f"{url_base}{caminho}?{urllib.parse.urlencode(params)}"

        def retentar(chave, mensagem, espera):
            # caminho comum de toda falha transitória: conta como bloqueio
            # (o paralelismo cai sozinho na próxima leva, em vez de insistir
            # com várias conexões contra quem já pede trégua), avisa uma vez
            # por causa, loga e dorme — acordando se a coleta for cancelada
            self._adaptativo.registrar_bloqueio()
            self._avisar_causa_recorrente(chave, mensagem)
            _log.debug("retry %s tentativa=%d causa=%s espera=%.1fs",
                       caminho, tentativa + 1, chave, espera)
            self._dormir(espera)

        for tentativa in range(tentativas):
            self._checar_cancelado()
            if pacing:
                # uma trava por Cliente, valendo também pras threads em
                # paralelo: o intervalo mínimo é entre requisições ao
                # portal, não por conexão — sem isso, 4 threads sem pacing
                # eram 4 rajadas simultâneas contra um host com throttling
                with self._trava_pacing:
                    espera = (self._config.intervalo_min
                             - (time.monotonic() - self._ultima_req))
                    if espera > 0:
                        self._dormir(espera)
                    self._ultima_req = time.monotonic()
            inicio = time.monotonic()
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": self._user_agent,
                                  "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self._timeout(tentativa)) as resp:
                    # resposta boa é o contrapeso dos bloqueios: sem contar
                    # as que dão certo, o paralelismo/tentativas adaptativos
                    # não sabem se alguns 429 numa janela são o portal
                    # recusando ou o ruído normal de uma fila grande andando
                    self._adaptativo.registrar_sucesso()
                    _log.debug("GET %s status=%d tentativa=%d %.2fs", caminho,
                               resp.status, tentativa + 1, time.monotonic() - inicio)
                    if resp.status == 204:
                        return None
                    corpo = resp.read()
                    # alguns endpoints (ex.: PCA) devolvem 200 com corpo
                    # vazio quando não há registros na janela
                    return json.loads(corpo) if corpo.strip() else None
            except urllib.error.HTTPError as e:
                if e.code == 404 and modo_404 == "erro":
                    raise ItensIndisponiveis(f"HTTP 404 em {caminho}") from e
                if e.code == 404 and modo_404 == "retry":
                    if tentativa < tentativas - 1:
                        retentar("http404", f"PNCP com HTTP 404 em {caminho}",
                                 _espera(tentativa))
                        continue
                    _log.warning("HTTP 404 persistente em %s", caminho)
                    raise PncpErro(
                        f"HTTP 404 persistente em {caminho} — listagem não "
                        "responde; abortando para não gravar a janela como "
                        "vazia") from e
                if e.code in (204, 404):
                    return None  # sem registros para o filtro
                if e.code == 429 and tentativa < tentativas - 1:
                    pedido = _retry_after(e.headers, self._config.retry_after_teto)
                    # sem header: espera conservadora (5, 10, 15s…) com
                    # sorteio na metade de cima — piso de 429 não pode ser 0
                    espera = (pedido if pedido is not None
                              else random.uniform(2.5, 5) * (tentativa + 1))
                    retentar("http429", f"PNCP pedindo pra esperar (429) em {caminho}",
                             espera)
                    continue
                teto = min(tentativas, TENTATIVAS_422) if e.code == 422 else tentativas
                if e.code in HTTP_TRANSITORIOS and tentativa < teto - 1:
                    pedido = (_retry_after(e.headers, self._config.retry_after_teto)
                              if e.code == 503 else None)
                    retentar(f"http{e.code}", f"PNCP respondeu HTTP {e.code} em {caminho}",
                             pedido if pedido is not None else _espera(tentativa))
                    continue
                # o corpo do 4xx do PNCP costuma trazer o motivo de
                # verdade — descartá-lo deixa só o código, sem nada pra
                # diagnosticar sem reproduzir a chamada à mão
                _log.warning("HTTP %d em %s após %d tentativa(s)", e.code, caminho,
                             tentativa + 1)
                raise PncpErro(f"HTTP {e.code} em {caminho}{_motivo(e)}") from e
            except ValueError as e:
                # 200 com corpo que não é JSON: o portal devolve página de
                # erro HTML sob carga. json.loads levanta ValueError, que
                # não é OSError nem HTTPException — sem este ramo a exceção
                # escapa inteira e mata a coleta sem log nenhum do lado de
                # quem chama.
                if tentativa < tentativas - 1:
                    retentar("corpo_invalido",
                             f"PNCP devolveu resposta ilegível em {caminho}",
                             _espera(tentativa))
                    continue
                _log.warning("resposta ilegível em %s após %d tentativa(s)",
                             caminho, tentativa + 1)
                raise PncpErro(
                    f"o PNCP devolveu resposta ilegível em {caminho} "
                    f"(não era JSON: {e})") from e
            except (urllib.error.URLError, TimeoutError, OSError,
                    http.client.HTTPException) as e:
                # http.client.HTTPException (ex.: IncompleteRead, resposta
                # cortada no meio) não é OSError — sem tratar aqui, escapa
                # inteira e mata a coleta sem log nenhum do lado de quem
                # chama.
                if tentativa < tentativas - 1:
                    retentar(f"rede:{type(e).__name__}",
                             f"PNCP lento ou fora do ar em {caminho} "
                             f"({type(e).__name__})",
                             _espera(tentativa))
                    continue
                _log.warning("rede em %s após %d tentativa(s): %s", caminho,
                             tentativa + 1, type(e).__name__)
                # "sem conexão" faz o usuário procurar defeito na internet
                # dele; o que costuma acontecer de fato é o portal demorar
                if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                    raise PncpErro(
                        f"o PNCP não respondeu em {self._timeout(tentativa)}s "
                        "— o portal está lento ou fora do ar") from e
                raise PncpErro(f"sem conexão com o PNCP ({e})") from e

    def paginar(self, url_base, caminho, params, tamanho_pagina, pacing=True):
        """Itera todos os registros de todas as páginas de uma consulta.

        Página 1 vazia é legítima (consulta sem nenhum registro). Página
        2+ vazia depois de uma página anterior que anunciou mais
        `totalPaginas` **não é** — é o portal engasgado no meio da
        listagem. Devolver o que já veio até ali gravaria a janela como
        completa e a marca d'água engoliria o resto pra sempre (incidente
        real em produção); por isso levanta `PncpErro`
        em vez de simplesmente parar.
        """
        pagina = 1
        while True:
            dados = self.get(url_base, caminho,
                             {**params, "pagina": pagina,
                              "tamanhoPagina": tamanho_pagina},
                             pacing=pacing, modo_404="retry")
            if not dados or not dados.get("data"):
                if pagina > 1:
                    raise PncpErro(
                        f"paginação interrompida em {caminho}: página "
                        f"{pagina} veio vazia mas havia mais anunciadas")
                return
            yield from dados["data"]
            # `paginasRestantes` é o campo que a spec indica pra decidir se
            # continua; `totalPaginas` é o reserva. Sem NENHUM dos dois num
            # envelope com dados, assumir "só esta página" seria truncar em
            # silêncio — a mesma perda que a guarda acima evita, por outra
            # porta. Falhar alto e deixar a janela pendente.
            restantes = dados.get("paginasRestantes")
            if restantes is None:
                total = dados.get("totalPaginas")
                if total is None:
                    raise PncpErro(
                        f"envelope sem paginasRestantes/totalPaginas em "
                        f"{caminho} (página {pagina}) — não dá pra saber se "
                        "acabou; não gravar a janela como completa")
                restantes = total - pagina
            if restantes <= 0:
                return
            pagina += 1

    def baixar(self, url_base, caminho, consultas, tamanho_pagina):
        """Baixa várias consultas independentes: gera (rótulo, registros,
        erro|None) conforme cada uma termina.

        Só as requisições vão para as threads — quem consome decide o que
        fazer com a falha; o que ela não pode fazer é dar a fase por
        completa, porque aí a marca d'água de quem persiste avança sobre
        uma janela nunca baixada.
        """
        # Em levas curtas de propósito: é ENTRE uma leva e outra que o
        # paralelismo adaptativo é relido. Com uma leva única cobrindo
        # tudo, a escada de recuo nunca seria relida e a fase inteira
        # seguiria no paralelismo original contra um portal já recusando.
        pendentes = list(consultas)
        while pendentes:
            conexoes = min(self._adaptativo.paralelismo_atual(), len(pendentes))
            leva, pendentes = pendentes[:4 * conexoes], pendentes[4 * conexoes:]
            if conexoes <= 1:
                for rotulo, params in leva:
                    try:
                        lote, erro = list(self.paginar(
                            url_base, caminho, params, tamanho_pagina)), None
                    except PncpErro as e:
                        lote, erro = [], e
                    yield rotulo, lote, erro
                continue
            ex = concurrent.futures.ThreadPoolExecutor(conexoes)
            try:
                futuros = {ex.submit(lambda p=p: list(self.paginar(
                    url_base, caminho, p, tamanho_pagina))): rotulo
                    for rotulo, p in leva}
                for f in concurrent.futures.as_completed(futuros):
                    try:
                        lote, erro = f.result(), None
                    except PncpErro as e:
                        lote, erro = [], e
                    yield futuros[f], lote, erro
            finally:
                # Isto é um GERADOR: se quem consome parar de iterar antes
                # do fim (o disjuntor de quem chama fazendo break/raise), o
                # GeneratorExit chega aqui. `shutdown(wait=True)` (padrão)
                # ficaria esperando as até `4*conexoes` consultas já
                # enfileiradas da leva pagarem o orçamento cheio de retry —
                # a "parada cedo" continuaria minutos em silêncio depois de
                # decidir parar. `wait=False` não segura a saída pelo que
                # já está em voo (termina sozinho, sem ninguém esperando);
                # `cancel_futures` descarta o que ainda nem começou.
                ex.shutdown(wait=False, cancel_futures=True)
