"""Motor de coleta do PNCP — API pública do pacote.

Fronteira deliberada: o motor faz HTTP + resiliência contra o portal e
devolve dados crus (dicts do jeito que o PNCP manda, ou perto disso).
Quem persiste decide schema, upsert e o que já tem gravado — o motor não
conhece banco nenhum. Essa fronteira já existia de fato entre os sistemas
que o originaram (um grava SQLite direto, outro tem storage próprio); o
motor só torna explícito o que já era verdade.

Ver docs/licoes.md para o porquê de cada limiar de resiliência.
"""
import concurrent.futures
import http.client
import json
import urllib.error
import urllib.request
from datetime import date

from ._http import USER_AGENT_PADRAO, Cliente
from ._resiliencia import Adaptativo, Disjuntor
from .dominio import DATA_INICIO_PNCP, JANELA_MAX_DIAS, MODALIDADES, amd, janelas
from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado

BASE = "https://pncp.gov.br/api/consulta"
# Itens e resultados por item ficam na API interna do portal, não na de
# consulta; devolvem array puro (sem envelope data/totalPaginas).
BASE_PNCP = "https://pncp.gov.br/api/pncp"

_URL_IPCA = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"
            "?formato=json&dataInicial={inicio}")

__all__ = [
    "Motor", "PncpErro", "SyncCancelado", "ItensIndisponiveis",
    "MODALIDADES", "DATA_INICIO_PNCP", "JANELA_MAX_DIAS", "janelas", "amd",
]


class Motor:
    """Uma coleta do PNCP.

    Crie uma instância nova por sincronização: todo o estado adaptativo
    (bloqueios/sucessos recentes, pacing) é por instância, não de módulo
    — duas coletas no mesmo processo não se atrapalham, e o beacon nunca
    aponta para o `progresso` de uma coleta que já terminou.

    `progresso`, se passado, é chamado com uma string a cada ponto natural
    da coleta — inclusive durante retry, o "beacon" que evita minutos de
    silêncio indistinguíveis de travamento. Levantar `SyncCancelado` de
    dentro dele interrompe a coleta no próximo ponto de checagem (não no
    meio de uma requisição em voo).
    """

    def __init__(self, *, user_agent=USER_AGENT_PADRAO, progresso=None,
                 base=BASE, base_pncp=BASE_PNCP):
        self._adaptativo = Adaptativo()
        self._cliente = Cliente(self._adaptativo, user_agent=user_agent,
                                progresso=progresso)
        self._base = base
        self._base_pncp = base_pncp

    # ── contratações ─────────────────────────────────────────────────────

    def contratacoes(self, codigo_ibge, inicio, fim):
        """Gera contratações atualizadas de um município, por modalidade e
        janela de datas — dicts crus do jeito que o PNCP manda.

        São 13 modalidades × janelas de até 364 dias, todas independentes
        (a API exige o loop por modalidade mesmo quando a maioria não
        devolve nada para um município pequeno). Baixadas em paralelo
        conforme a saúde do portal.

        Levanta `PncpErro` se alguma consulta falhar — o que já foi
        gerado antes disso quem consome já processou; não avance sua
        marca d'água de sincronização se isso acontecer, ou o buraco
        fica no acervo pra sempre (falha ≠ ausência). Se o disjuntor
        decidir que a fase morreu (muitas falhas seguidas, tempo demais
        sem nenhum sucesso), as consultas restantes nem são tentadas.
        """
        consultas = [(nome, {"dataInicial": amd(a), "dataFinal": amd(b),
                             "codigoModalidadeContratacao": codigo,
                             "codigoMunicipioIbge": codigo_ibge})
                    for codigo, nome in MODALIDADES.items()
                    for a, b in janelas(inicio, fim)]
        disjuntor = Disjuntor()
        falhas = []
        gerador = self._cliente.baixar(self._base, "/v1/contratacoes/atualizacao",
                                       consultas, 50)
        try:
            for feitas, (nome, lote, erro) in enumerate(gerador, 1):
                self._cliente.avisar_progresso(
                    f"Contratações — {nome} ({feitas}/{len(consultas)})…")
                if erro:
                    falhas.append(f"{nome}: {erro}")
                    if disjuntor.falha():
                        raise PncpErro(
                            f"parado após {disjuntor.seguidas} falhas "
                            f"seguidas e {disjuntor.mudo_ha}min sem "
                            f"nenhuma resposta boa — "
                            f"{len(consultas) - feitas} consultas não "
                            f"tentadas — {falhas[0]}")
                    continue
                disjuntor.sucesso()
                yield from lote
        finally:
            gerador.close()
        if falhas:
            raise PncpErro(f"{len(falhas)} de {len(consultas)} consultas "
                           f"falharam — {falhas[0]}")

    def contar_contratacoes(self, codigo_ibge, inicio=DATA_INICIO_PNCP, fim=None):
        """Quantas contratações um município tem, sem baixar nenhuma.

        Lê `totalRegistros` do envelope da primeira página de cada
        consulta — paginar tudo só pra contar custa centenas de
        requisições e, num município grande, não termina. Devolve
        `{"total": int, "parcial": bool}`; `parcial=True` quando alguma
        consulta falhou (o total é subestimado, nunca superestimado).
        """
        fim = fim or date.today()
        consultas = [{"dataInicial": amd(a), "dataFinal": amd(b),
                     "codigoModalidadeContratacao": codigo,
                     "codigoMunicipioIbge": str(codigo_ibge),
                     "pagina": 1, "tamanhoPagina": 10}
                    for codigo in MODALIDADES
                    for a, b in janelas(inicio, fim)]
        conexoes = min(self._adaptativo.paralelismo_atual(), len(consultas))
        falhas = 0

        def uma(params):
            nonlocal falhas
            try:
                d = self._cliente.get(self._base, "/v1/contratacoes/atualizacao",
                                      params, pacing=conexoes <= 1)
            except PncpErro:
                falhas += 1
                return 0
            return (d or {}).get("totalRegistros") or 0

        if conexoes <= 1:
            total = sum(uma(p) for p in consultas)
        else:
            with concurrent.futures.ThreadPoolExecutor(conexoes) as ex:
                total = sum(ex.map(uma, consultas))
        return {"total": total, "parcial": falhas > 0}

    # ── órgãos ───────────────────────────────────────────────────────────

    def consultar_orgao(self, cnpj):
        """Registro do CNPJ no PNCP (razão social, esfera) — `None` se o
        CNPJ não existe no portal."""
        return self._cliente.get(self._base_pncp, f"/v1/orgaos/{cnpj}", {})

    # ── itens e resultados ───────────────────────────────────────────────

    def itens_da_compra(self, cnpj, ano, sequencial):
        """Itens de uma contratação (array puro, paginado).

        Levanta `ItensIndisponiveis` em 404 — não confundir com "esta
        contratação não tem item nenhum" (ver a exceção).
        """
        pagina = 1
        while True:
            lote = self._cliente.get(
                self._base_pncp,
                f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens",
                {"pagina": pagina, "tamanhoPagina": 100}, erro_404=True)
            if not lote:
                return
            yield from lote
            if len(lote) < 100:
                return
            pagina += 1

    def resultado_do_item(self, cnpj, ano, sequencial, numero_item, pacing=True):
        """Resultado homologado de um item: vencedor e valor unitário
        fechado, ou `None` se o item ainda não tem resultado."""
        lote = self._cliente.get(
            self._base_pncp,
            f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/"
            f"{numero_item}/resultados", {}, pacing=pacing)
        if not lote:
            return None
        # o mais recente não cancelado é o que vale
        validos = [r for r in lote if not r.get("dataCancelamento")]
        return (validos or lote)[0]

    def itens_e_resultados(self, contratacoes, *, pendente=None, on_erro=None):
        """Para cada contratação, busca itens e resultados homologados.

        `contratacoes`: iterável de dicts com pelo menos `orgao_cnpj`,
        `ano`, `sequencial` — qualquer outra chave passa intacta para
        `pendente`/o registro gerado, útil pra você casar de volta com a
        sua própria linha.

        `pendente(contratacao, item) -> bool`, opcional (default: todos os
        itens): decide se um item precisa de resultado buscado de novo.
        Sem isso, todo item com `temResultado` busca resultado sempre —
        caro numa contratação já conhecida onde só a `dataAtualizacao`
        cosmética mudou. Você decide com base no que já tem gravado; o
        motor não sabe.

        `on_erro(contratacao, excecao)`, opcional: chamado a cada
        contratação que falhar. O motor continua as demais e só desiste
        da fase inteira via disjuntor (mesmo critério de `contratacoes`:
        falhas seguidas E tempo sem nenhum sucesso) — uma contratação
        quebrada não pode travar a fila inteira.

        Gera `(contratacao, [(item, resultado_ou_none), ...])` — uma
        tupla por contratação, só depois que TODOS os itens dela (e
        resultados, buscados em paralelo) chegaram. Contratação com 404
        na listagem de itens não aparece nesta chamada — fica pendente
        para a próxima; as demais continuam normalmente.
        """
        pendente = pendente or (lambda contratacao, item: True)
        disjuntor = Disjuntor()
        pendentes = list(contratacoes)
        for i, c in enumerate(pendentes, 1):
            self._cliente.avisar_progresso(
                f"Itens — contratação {i} de {len(pendentes)}…")
            try:
                todos = list(self.itens_da_compra(c["orgao_cnpj"], c["ano"],
                                                   c["sequencial"]))
                itens = [item for item in todos if pendente(c, item)]
                com_resultado = [item for item in itens
                                 if item.get("temResultado")]
                resultados = {}
                if com_resultado:
                    # os resultados são independentes entre si: buscar em
                    # paralelo
                    conexoes = min(self._adaptativo.paralelismo_atual(),
                                  len(com_resultado))
                    paralelo = conexoes > 1
                    ex = concurrent.futures.ThreadPoolExecutor(conexoes)
                    try:
                        futuros = {
                            ex.submit(self.resultado_do_item, c["orgao_cnpj"],
                                     c["ano"], c["sequencial"],
                                     item["numeroItem"], not paralelo):
                                item["numeroItem"]
                            for item in com_resultado}
                        for f in concurrent.futures.as_completed(futuros):
                            resultados[futuros[f]] = f.result()
                    finally:
                        ex.shutdown(wait=True, cancel_futures=True)
                disjuntor.sucesso()
                yield c, [(item, resultados.get(item.get("numeroItem")))
                         for item in itens]
            except ItensIndisponiveis as e:
                if on_erro:
                    on_erro(c, e)
                if disjuntor.falha():
                    raise PncpErro(
                        f"parado após {disjuntor.seguidas} listagens de "
                        f"itens seguidas sem resposta (404) e "
                        f"{disjuntor.mudo_ha}min sem nenhuma contratação "
                        f"concluída, em {i} de {len(pendentes)} "
                        "contratações") from e
            except PncpErro as e:
                if on_erro:
                    on_erro(c, e)
                if disjuntor.falha():
                    raise PncpErro(
                        f"parado após {disjuntor.seguidas} falhas seguidas "
                        f"e {disjuntor.mudo_ha}min sem nenhuma contratação "
                        f"concluída, em {i} de {len(pendentes)} "
                        f"contratações — {e}") from e

    # ── correção monetária ───────────────────────────────────────────────

    def ipca(self, inicio=None):
        """Variação mensal do IPCA desde `inicio` (dd/mm/aaaa) — gera
        dicts `{"competencia": "aaaa-mm", "variacao": float}`.

        Fonte: Banco Central (série SGS 433), citável no processo. Preço
        de anos diferentes não se compara sem essa correção — a inflação
        acumulada num acervo de vários anos passa de 20%.
        """
        inicio = inicio or f"01/01/{DATA_INICIO_PNCP.year}"
        req = urllib.request.Request(
            _URL_IPCA.format(inicio=inicio),
            headers={"User-Agent": self._cliente._user_agent})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError,
                http.client.HTTPException) as e:
            raise PncpErro(f"não consegui baixar o IPCA: {e}") from e
        for linha in dados:
            try:
                dia, mes, ano = linha["data"].split("/")
                variacao = float(linha["valor"])
            except (KeyError, ValueError):
                continue  # linha estranha não derruba a série inteira
            yield {"competencia": f"{ano}-{mes}", "variacao": variacao}
