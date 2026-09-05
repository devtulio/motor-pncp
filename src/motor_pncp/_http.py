"""Cliente HTTP do PNCP: pacing, retry com backoff, beacon de progresso.

Só stdlib de propósito: os sistemas que consomem este motor são builds
PyInstaller onefile, e o gargalo real (timeout de socket, que não cobre
DNS) é o mesmo em urllib/requests/httpx — trocar não resolve nada e soma
uma dependência nova ao empacotamento. Ver docs/licoes.md.
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

from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado

USER_AGENT_PADRAO = "motor-pncp/0.1 (coleta de contratacoes; open-source)"

_INTERVALO_MIN = 0.5  # s entre requisições — o PNCP tem throttling agressivo

# O PNCP não costuma recusar: ele demora. Insistir com o mesmo prazo curto
# só repete a falha; por isso cada tentativa espera mais que a anterior.
TIMEOUTS = (30, 45, 60, 75, 90)


def _timeout(tentativa):
    return TIMEOUTS[min(tentativa, len(TIMEOUTS) - 1)]


def _espera(tentativa):
    """Backoff com sorteio: 1, 2, 4, 8s + até meio segundo de desvio.

    Sem o desvio, conexões que falharam juntas voltam juntas e repetem a
    mesma rajada contra um portal que já estava sobrecarregado.
    """
    return 2 ** tentativa + random.uniform(0, 0.5)


class Cliente:
    """Uma conexão lógica com o PNCP — pacing e retry por instância, não
    de módulo, para não vazar estado entre coletas."""

    def __init__(self, adaptativo, *, user_agent=USER_AGENT_PADRAO,
                 progresso=None):
        self._adaptativo = adaptativo
        self._user_agent = user_agent
        self._progresso = progresso
        self._ultima_req = 0.0
        self._trava_pacing = threading.Lock()

    def avisar_progresso(self, msg):
        """Beacon: chamado a cada tentativa de retry (não só no fim de uma
        fase) — sem isso, os até ~5,3min de retry de uma única requisição
        ficam mudos, indistinguíveis de travamento de verdade."""
        if not self._progresso:
            return
        try:
            self._progresso(msg)
        except SyncCancelado:
            raise  # parada a pedido não é cortesia
        except Exception:
            pass  # aviso é cortesia; não pode derrubar o retry por isso

    def get(self, url_base, caminho, params, *, tentativas=None, pacing=True,
            erro_404=False, retry_404=False):
        """GET com pacing e retry/backoff. Dict do JSON, ou None sem dados.

        `retry_404=True` para LISTAGENS (contratações/itens): "sem
        registros" ali é 204/corpo vazio, nunca 404 — um 404 é falha
        transitória do portal; sem isso ele vira "janela vazia" e quem
        persiste avança a marca d'água sobre dados nunca baixados.

        `erro_404=True` faz 404 virar `ItensIndisponiveis` em vez de
        `None`: usado na listagem de itens de UMA contratação, onde 404
        também não significa "sem itens" (ver `ItensIndisponiveis`).
        """
        if tentativas is None:
            tentativas = self._adaptativo.tentativas_atual()
        url = f"{url_base}{caminho}?{urllib.parse.urlencode(params)}"
        for tentativa in range(tentativas):
            if pacing:
                with self._trava_pacing:
                    espera = _INTERVALO_MIN - (time.monotonic() - self._ultima_req)
                    if espera > 0:
                        time.sleep(espera)
                    self._ultima_req = time.monotonic()
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": self._user_agent,
                                  "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=_timeout(tentativa)) as resp:
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
                if e.code == 404 and erro_404:
                    raise ItensIndisponiveis(f"HTTP 404 em {caminho}") from e
                if e.code == 404 and retry_404:
                    if tentativa < tentativas - 1:
                        self._adaptativo.registrar_bloqueio()
                        self.avisar_progresso(
                            f"PNCP com HTTP 404 — tentativa {tentativa + 2}"
                            f"/{tentativas}…")
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
                    self.avisar_progresso(
                        f"PNCP pedindo pra esperar (429) — tentativa "
                        f"{tentativa + 2}/{tentativas}…")
                    retry_after = e.headers.get("Retry-After")
                    time.sleep(int(retry_after) if (retry_after or "").isdigit()
                               else 5 * (tentativa + 1))
                    continue
                if e.code in (500, 502, 503, 504) and tentativa < tentativas - 1:
                    # portal sobrecarregado conta como bloqueio: o
                    # paralelismo cai sozinho na próxima leva, em vez de
                    # insistir com várias conexões contra quem já está
                    # pedindo trégua
                    self._adaptativo.registrar_bloqueio()
                    self.avisar_progresso(
                        f"PNCP respondeu HTTP {e.code} — tentativa "
                        f"{tentativa + 2}/{tentativas} (timeout "
                        f"{_timeout(tentativa + 1)}s)…")
                    time.sleep(_espera(tentativa))
                    continue
                raise PncpErro(f"HTTP {e.code} em {caminho}") from e
            except ValueError as e:
                # 200 com corpo que não é JSON: o portal devolve página de
                # erro HTML sob carga. json.loads levanta ValueError, que
                # não é OSError nem HTTPException — sem este ramo a exceção
                # escapa inteira e mata a coleta sem log nenhum do lado de
                # quem chama.
                if tentativa < tentativas - 1:
                    self._adaptativo.registrar_bloqueio()
                    self.avisar_progresso(
                        f"PNCP devolveu resposta ilegível — tentativa "
                        f"{tentativa + 2}/{tentativas}…")
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
                    self.avisar_progresso(
                        f"PNCP lento ou fora do ar — tentativa "
                        f"{tentativa + 2}/{tentativas} (timeout "
                        f"{_timeout(tentativa + 1)}s)…")
                    time.sleep(_espera(tentativa))
                    continue
                # "sem conexão" faz o usuário procurar defeito na internet
                # dele; o que costuma acontecer de fato é o portal demorar
                if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                    raise PncpErro(
                        f"o PNCP não respondeu em {_timeout(tentativa)}s — "
                        "o portal está lento ou fora do ar") from e
                raise PncpErro(f"sem conexão com o PNCP ({e})") from e

    def paginar(self, url_base, caminho, params, tamanho_pagina, pacing=True):
        """Itera todos os registros de todas as páginas de uma consulta."""
        pagina = 1
        while True:
            dados = self.get(url_base, caminho,
                             {**params, "pagina": pagina,
                              "tamanhoPagina": tamanho_pagina},
                             pacing=pacing, retry_404=True)
            if not dados or not dados.get("data"):
                return
            yield from dados["data"]
            if pagina >= dados.get("totalPaginas", 1):
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
