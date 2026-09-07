"""Cliente HTTP do PNCP: pacing, retry com backoff, beacon de progresso.

Só stdlib de propósito: os sistemas que consomem este motor são builds
PyInstaller onefile, e o gargalo real (timeout de socket, que não cobre
DNS) é o mesmo em urllib/requests/httpx — trocar não resolve nada e soma
uma dependência nova ao empacotamento. Ver README.md.
"""
import concurrent.futures
import http.client
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from ._resiliencia import Dedup
from .configuracao import Config
from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado

USER_AGENT_PADRAO = "motor-pncp/0.1 (coleta de contratacoes; open-source)"

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
    """Backoff com sorteio: 1, 2, 4, 8s + até meio segundo de desvio.

    Sem o desvio, conexões que falharam juntas voltam juntas e repetem a
    mesma rajada contra um portal que já estava sobrecarregado.
    """
    return 2 ** tentativa + random.uniform(0, 0.5)


class Cliente:
    """Uma conexão lógica com o PNCP — pacing e retry por instância, não
    de módulo, para não vazar estado entre coletas."""

    def __init__(self, adaptativo, *, config: Config = Config(),
                 user_agent=USER_AGENT_PADRAO, progresso=None):
        self._adaptativo = adaptativo
        self._config = config
        self._dedup = Dedup(config.janela_operacional)
        self._user_agent = user_agent
        self._progresso = progresso
        self._ultima_req = 0.0
        self._trava_pacing = threading.Lock()

    def _timeout(self, tentativa):
        timeouts = self._config.timeouts
        return timeouts[min(tentativa, len(timeouts) - 1)]

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
        for tentativa in range(tentativas):
            if pacing:
                with self._trava_pacing:
                    espera = (self._config.intervalo_min
                             - (time.monotonic() - self._ultima_req))
                    if espera > 0:
                        time.sleep(espera)
                    self._ultima_req = time.monotonic()
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
                        self._adaptativo.registrar_bloqueio()
                        self._avisar_causa_recorrente(
                            "http404", f"PNCP com HTTP 404 em {caminho}")
                        time.sleep(_espera(tentativa))
                        continue
                    raise PncpErro(
                        f"HTTP 404 persistente em {caminho} — listagem não "
                        "responde; abortando para não gravar a janela como "
                        "vazia") from e
                if e.code in (204, 404):
                    return None  # sem registros para o filtro
                if e.code == 429 and tentativa < tentativas - 1:
                    self._adaptativo.registrar_bloqueio()
                    self._avisar_causa_recorrente(
                        "http429", f"PNCP pedindo pra esperar (429) em {caminho}")
                    retry_after = e.headers.get("Retry-After")
                    time.sleep(int(retry_after) if (retry_after or "").isdigit()
                               else 5 * (tentativa + 1))
                    continue
                teto = min(tentativas, TENTATIVAS_422) if e.code == 422 else tentativas
                if e.code in HTTP_TRANSITORIOS and tentativa < teto - 1:
                    # portal sobrecarregado conta como bloqueio: o
                    # paralelismo cai sozinho na próxima leva, em vez de
                    # insistir com várias conexões contra quem já está
                    # pedindo trégua
                    self._adaptativo.registrar_bloqueio()
                    self._avisar_causa_recorrente(
                        f"http{e.code}", f"PNCP respondeu HTTP {e.code} em {caminho}")
                    time.sleep(_espera(tentativa))
                    continue
                # o corpo do 4xx do PNCP costuma trazer o motivo de
                # verdade — descartá-lo deixa só o código, sem nada pra
                # diagnosticar sem reproduzir a chamada à mão
                raise PncpErro(f"HTTP {e.code} em {caminho}{_motivo(e)}") from e
            except ValueError as e:
                # 200 com corpo que não é JSON: o portal devolve página de
                # erro HTML sob carga. json.loads levanta ValueError, que
                # não é OSError nem HTTPException — sem este ramo a exceção
                # escapa inteira e mata a coleta sem log nenhum do lado de
                # quem chama.
                if tentativa < tentativas - 1:
                    self._adaptativo.registrar_bloqueio()
                    self._avisar_causa_recorrente(
                        "corpo_invalido",
                        f"PNCP devolveu resposta ilegível em {caminho}")
                    time.sleep(_espera(tentativa))
                    continue
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
                    self._adaptativo.registrar_bloqueio()
                    self._avisar_causa_recorrente(
                        f"rede:{type(e).__name__}",
                        f"PNCP lento ou fora do ar em {caminho} "
                        f"({type(e).__name__})")
                    time.sleep(_espera(tentativa))
                    continue
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
        completa e a marca d'água engoliria o resto pra sempre (achado
        real de um sistema irmão, 2026-08-29); por isso levanta `PncpErro`
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
                    url_base, caminho, p, tamanho_pagina, pacing=False))): rotulo
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
