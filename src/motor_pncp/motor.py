"""Motor de coleta do PNCP — API pública do pacote.

Fronteira deliberada: o motor faz HTTP + resiliência contra o portal e
devolve registros tipados que embrulham o JSON cru do PNCP (`.raw`
continua sendo a fonte da verdade — ver `tipos.py`). Quem persiste decide
schema, upsert e o que já tem gravado; o motor não conhece banco nenhum.
Essa fronteira já existia de fato entre os sistemas que o originaram (um
grava SQLite direto, outro tem storage próprio); o motor só torna
explícito o que já era verdade.

Ver README.md para o porquê de cada limiar de resiliência (em `Config`).
"""
import concurrent.futures
import time
from datetime import date

from ._http import USER_AGENT_PADRAO, Cliente
from ._resiliencia import Adaptativo, Disjuntor
from .configuracao import Config
from .dominio import (
    DATA_INICIO_PCA,
    DATA_INICIO_PNCP,
    JANELA_MAX_DIAS,
    MODALIDADES,
    amd,
    janelas,
)
from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado
from .tipos import Ata, Contratacao, Contrato, Item, Orgao, PlanoPca, Resultado, TermoAditivo

BASE = "https://pncp.gov.br/api/consulta"
# Itens, resultados, termos aditivos e órgãos ficam na API interna do
# portal, não na de consulta; alguns endpoints devolvem array puro (sem
# envelope data/totalPaginas).
BASE_PNCP = "https://pncp.gov.br/api/pncp"

_URL_BCB = "https://api.bcb.gov.br"

__all__ = [
    "Motor", "Config", "PncpErro", "SyncCancelado", "ItensIndisponiveis",
    "MODALIDADES", "DATA_INICIO_PNCP", "DATA_INICIO_PCA", "JANELA_MAX_DIAS",
    "janelas", "amd",
]


class Motor:
    """Uma coleta do PNCP.

    Crie uma instância nova por sincronização: todo o estado adaptativo
    (bloqueios/sucessos recentes, pacing) é por instância, não de módulo
    — duas coletas no mesmo processo não se atrapalham, e o beacon nunca
    aponta para o `progresso` de uma coleta que já terminou.

    `config`, se passado, troca os limiares de resiliência (paralelismo,
    nº de tentativas, quando o disjuntor desiste) pelos do seu sistema —
    ver `Config`. O default é o medido contra o PNCP real.

    `progresso`, se passado, é chamado com uma string a cada ponto natural
    da coleta — inclusive durante retry, o "beacon" que evita minutos de
    silêncio indistinguíveis de travamento. Levantar `SyncCancelado` de
    dentro dele interrompe a coleta no próximo ponto de checagem (não no
    meio de uma requisição em voo).
    """

    def __init__(self, *, config: Config = Config(), user_agent=USER_AGENT_PADRAO,
                 progresso=None, base=BASE, base_pncp=BASE_PNCP):
        self._config = config
        self._adaptativo = Adaptativo(config)
        self._cliente = Cliente(self._adaptativo, config=config,
                                user_agent=user_agent, progresso=progresso)
        self._base = base
        self._base_pncp = base_pncp

    # ── sonda ────────────────────────────────────────────────────────────

    def sonda(self):
        """Uma requisição barata pra saber se `api/consulta` responde.

        Bate em `/v1/atas` (vigência de hoje, 10 registros) — o endpoint
        que o monitor independente do PNCP usa como health-check por ser
        o mais rápido — com UMA tentativa, sem escada de retry. Devolve o
        tempo de resposta em segundos; levanta `PncpErro` se não
        respondeu. Serve pra decidir em 1s se vale iniciar uma coleta ou
        se é melhor esperar o portal — não diz nada sobre `api/pncp`
        (itens/resultados), que cai separado.
        """
        hoje = amd(date.today())
        inicio = time.monotonic()
        self._cliente.get(self._base, "/v1/atas",
                          {"dataInicial": hoje, "dataFinal": hoje,
                           "pagina": 1, "tamanhoPagina": 10},
                          tentativas=1, modo_404="retry")
        return time.monotonic() - inicio

    # ── infraestrutura comum das fases baixadas em paralelo com disjuntor ─

    def _baixar_com_disjuntor(self, caminho, consultas, *, rotulo_fase,
                              tamanho_pagina=500):
        """Baixa uma lista de `(rótulo, params)` com disjuntor e beacon de
        progresso, gerando os registros crus conforme chegam.

        Compartilhada por toda fase que baixa uma lista fixa de consultas
        em paralelo (contratações, contratos, atas, PCA) — a única
        diferença entre elas é como cada uma monta `consultas` e em que
        tipo embrulha o resultado; a resiliência (disjuntor, mensagens de
        falha, fechamento do gerador) é uma preocupação só, não uma por
        fase. Levanta `PncpErro` — cedo, se o disjuntor desistir da fase,
        ou no final, se alguma consulta falhou sem disparar o disjuntor —
        sempre preservando o que já foi gerado antes disso (falha ≠
        ausência; não avance sua marca d'água sobre uma falha parcial).
        """
        disjuntor = Disjuntor(self._config)
        falhas = []
        gerador = self._cliente.baixar(self._base, caminho, consultas, tamanho_pagina)
        try:
            for feitas, (rotulo, lote, erro) in enumerate(gerador, 1):
                self._cliente.avisar_progresso(
                    f"{rotulo_fase} — {rotulo} ({feitas}/{len(consultas)})…")
                if erro:
                    falhas.append(f"{rotulo}: {erro}")
                    if disjuntor.falha():
                        raise PncpErro(
                            f"{rotulo_fase}: parado após {disjuntor.seguidas} "
                            f"falhas seguidas e {disjuntor.mudo_ha}min sem "
                            f"nenhuma resposta boa — "
                            f"{len(consultas) - feitas} consultas não "
                            f"tentadas — {falhas[0]}")
                    continue
                disjuntor.sucesso()
                yield from lote
        finally:
            gerador.close()
        if falhas:
            raise PncpErro(f"{rotulo_fase}: {len(falhas)} de {len(consultas)} "
                           f"consultas falharam — {falhas[0]}")

    def _janela_generica(self, caminho, params_extra, inicio, fim, *, rotulo_fase,
                         chaves_data=("dataInicial", "dataFinal"),
                         tamanho_pagina=500):
        """Monta as consultas de uma fase que consulta por CNPJ + janela
        de datas, sem o loop de modalidade de `contratacoes` (contratos,
        atas, PCA), e delega o download pra `_baixar_com_disjuntor`."""
        ini_chave, fim_chave = chaves_data
        consultas = [(amd(a), {**params_extra, ini_chave: amd(a), fim_chave: amd(b)})
                    for a, b in janelas(inicio, fim)]
        yield from self._baixar_com_disjuntor(caminho, consultas,
                                              rotulo_fase=rotulo_fase,
                                              tamanho_pagina=tamanho_pagina)

    # ── contratações ─────────────────────────────────────────────────────

    def contratacoes(self, codigo_ibge, inicio, fim):
        """Gera `Contratacao` atualizadas de um município, por modalidade e
        janela de datas.

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
        for raw in self._baixar_com_disjuntor("/v1/contratacoes/atualizacao",
                                              consultas, rotulo_fase="Contratações",
                                              tamanho_pagina=50):
            yield Contratacao(raw)

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
                                      params, pacing=conexoes <= 1, modo_404="retry")
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

    # ── contratos, atas, PCA (fase 2 — por CNPJ de órgão) ───────────────

    def contratos(self, cnpj, inicio, fim):
        """Gera `Contrato` de um órgão atualizados na janela — a API não
        filtra por município, só por CNPJ."""
        for raw in self._janela_generica("/v1/contratos/atualizacao",
                                         {"cnpjOrgao": cnpj}, inicio, fim,
                                         rotulo_fase="Contratos"):
            yield Contrato(raw)

    def atas(self, cnpj, inicio, fim):
        """Gera `Ata` de registro de preços de um órgão atualizadas na
        janela."""
        for raw in self._janela_generica("/v1/atas/atualizacao",
                                         {"cnpj": cnpj}, inicio, fim,
                                         rotulo_fase="Atas"):
            yield Ata(raw)

    def pca(self, cnpj, inicio, fim):
        """Gera `PlanoPca` (Plano de Contratações Anual) de um órgão
        atualizados na janela.

        Este endpoint usa `dataInicio`/`dataFim` — os demais usam
        `dataInicial`/`dataFinal` (verificado contra a API real,
        2026-07-29) — e rejeita datas anteriores a `DATA_INICIO_PCA`.
        """
        inicio = max(inicio, DATA_INICIO_PCA)
        if inicio > fim:
            return
        for raw in self._janela_generica("/v1/pca/atualizacao", {"cnpj": cnpj},
                                         inicio, fim, rotulo_fase="PCA",
                                         chaves_data=("dataInicio", "dataFim")):
            yield PlanoPca(raw)

    # ── órgãos ───────────────────────────────────────────────────────────

    def consultar_orgao(self, cnpj):
        """`Orgao` do CNPJ no PNCP (razão social, esfera) — `None` se o
        CNPJ não existe no portal."""
        raw = self._cliente.get(self._base_pncp, f"/v1/orgaos/{cnpj}", {})
        return Orgao(raw) if raw else None

    # ── itens e resultados ───────────────────────────────────────────────

    def itens_da_compra(self, cnpj, ano, sequencial):
        """Gera `Item` de uma contratação (endpoint devolve array puro,
        paginado — sem envelope `totalPaginas`; o único sinal de fim é a
        página vir com MENOS de `tamanhoPagina`).

        Levanta `ItensIndisponiveis` em 404 — não confundir com "esta
        contratação não tem item nenhum" (ver a exceção). Página 1 vazia
        é legítima; página 2+ vazia depois de uma página cheia não é —
        mesmo raciocínio (e mesmo incidente real, 2026-08-29) do guard em
        `Cliente.paginar`: sem ele, um soluço do portal no meio da
        listagem terminava a coleta calada, a contratação era carimbada
        como concluída, e os itens que faltaram ficavam faltando pra
        sempre.
        """
        pagina = 1
        while True:
            lote = self._cliente.get(
                self._base_pncp,
                f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens",
                {"pagina": pagina, "tamanhoPagina": 100}, modo_404="erro")
            if not lote:
                if pagina > 1:
                    raise PncpErro(
                        f"paginação de itens interrompida em "
                        f"{cnpj}/{ano}/{sequencial}: página {pagina} veio "
                        "vazia depois de uma página cheia")
                return
            for raw in lote:
                yield Item(raw)
            if len(lote) < 100:
                return
            pagina += 1

    def resultado_do_item(self, cnpj, ano, sequencial, numero_item, pacing=True):
        """`Resultado` homologado de um item: vencedor e valor unitário
        fechado, ou `None` se o item ainda não tem resultado."""
        lote = self._cliente.get(
            self._base_pncp,
            f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/"
            f"{numero_item}/resultados", {}, pacing=pacing)
        if not lote:
            return None
        # o mais recente não cancelado é o que vale
        validos = [r for r in lote if not r.get("dataCancelamento")]
        return Resultado((validos or lote)[0])

    def itens_e_resultados(self, contratacoes, *, pendente=None, on_erro=None):
        """Para cada contratação, busca itens e resultados homologados.

        `contratacoes`: iterável de dicts com pelo menos `orgao_cnpj`,
        `ano`, `sequencial` — qualquer outra chave passa intacta para
        `pendente`/o registro gerado, útil pra você casar de volta com a
        sua própria linha.

        `pendente(contratacao, item: Item) -> bool`, opcional (default:
        todos os itens): decide se um item precisa de resultado buscado
        de novo. Sem isso, todo item com `temResultado` busca resultado
        sempre — caro numa contratação já conhecida onde só a
        `dataAtualizacao` cosmética mudou. Você decide com base no que já
        tem gravado; o motor não sabe. **Cuidado ao implementar**: não
        basta comparar `item.data_atualizacao` com o que você já tem —
        uma coleta anterior pode ter sido interrompida DEPOIS de listar o
        item mas ANTES de buscar o resultado dele; nesse caso a
        `dataAtualizacao` não muda, e um `pendente` que só olha a data
        deixa esse item sem resultado pra sempre. Trate como pendente
        também quando `item.tem_resultado` é `True` mas o resultado que
        você já tem gravado pra ele é `None`.

        `on_erro(contratacao, excecao)`, opcional: chamado a cada
        contratação que falhar. O motor continua as demais e só desiste
        da fase inteira via disjuntor (mesmo critério de `contratacoes`:
        falhas seguidas E tempo sem nenhum sucesso) — uma contratação
        quebrada não pode travar a fila inteira.

        Gera `(contratacao, [(Item, Resultado | None), ...])` — uma
        tupla por contratação, só depois que TODOS os itens dela (e
        resultados, buscados em paralelo) chegaram. Contratação com 404
        na listagem de itens não aparece nesta chamada — fica pendente
        para a próxima; as demais continuam normalmente.
        """
        pendente = pendente or (lambda contratacao, item: True)
        disjuntor = Disjuntor(self._config)
        pendentes = list(contratacoes)
        for i, c in enumerate(pendentes, 1):
            self._cliente.avisar_progresso(
                f"Itens — contratação {i} de {len(pendentes)}…")
            try:
                todos = list(self.itens_da_compra(c["orgao_cnpj"], c["ano"],
                                                   c["sequencial"]))
                itens = [item for item in todos if pendente(c, item)]
                com_resultado = [item for item in itens if item.tem_resultado]
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
                                     item.numero_item, not paralelo):
                                item.numero_item
                            for item in com_resultado}
                        for f in concurrent.futures.as_completed(futuros):
                            resultados[futuros[f]] = f.result()
                    finally:
                        ex.shutdown(wait=True, cancel_futures=True)
                disjuntor.sucesso()
                yield c, [(item, resultados.get(item.numero_item))
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

    # ── termos aditivos (fase opcional — contratos já sincronizados) ────

    def _quantidade_termos(self, cnpj, ano, sequencial):
        """Chamada barata antes da cara: pula contrato sem aditivo
        nenhum, sem pagar o custo de listar termos que não existem."""
        r = self._cliente.get(
            self._base_pncp,
            f"/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/termos/quantidade",
            {}, modo_404="erro")
        if isinstance(r, dict):
            return r.get("quantidade", 0)
        return r or 0

    def _termos_do_contrato(self, cnpj, ano, sequencial):
        return self._cliente.get(
            self._base_pncp,
            f"/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/termos",
            {}, modo_404="erro") or []

    def termos_aditivos(self, contratos, *, on_erro=None):
        """Para cada contrato, busca os termos aditivos (se houver).

        `contratos`: iterável de dicts com pelo menos `orgao_cnpj`, `ano`,
        `sequencial`. `on_erro`, mesmo contrato do `itens_e_resultados`.

        Gera `(contrato, [TermoAditivo, ...])` — lista vazia quando o
        contrato não tem aditivo (ainda assim é gerado, pra você saber
        que já foi verificado e não precisa checar de novo). Termo
        aditivo é evento raro e definitivo por contrato — ao contrário de
        itens, não há necessidade de revisitar o que já foi verificado.
        """
        disjuntor = Disjuntor(self._config)
        pendentes = list(contratos)
        for i, c in enumerate(pendentes, 1):
            self._cliente.avisar_progresso(
                f"Termos aditivos — contrato {i} de {len(pendentes)}…")
            try:
                qtd = self._quantidade_termos(c["orgao_cnpj"], c["ano"],
                                              c["sequencial"])
                termos = []
                if qtd:
                    termos = [TermoAditivo(t) for t in self._termos_do_contrato(
                        c["orgao_cnpj"], c["ano"], c["sequencial"])]
                disjuntor.sucesso()
                yield c, termos
            except ItensIndisponiveis as e:
                if on_erro:
                    on_erro(c, e)
                if disjuntor.falha():
                    raise PncpErro(
                        f"parado após {disjuntor.seguidas} consultas de "
                        f"termos seguidas sem resposta (404) e "
                        f"{disjuntor.mudo_ha}min sem nenhum contrato "
                        f"concluído, em {i} de {len(pendentes)} "
                        "contratos") from e
            except PncpErro as e:
                if on_erro:
                    on_erro(c, e)
                if disjuntor.falha():
                    raise PncpErro(
                        f"parado após {disjuntor.seguidas} falhas seguidas "
                        f"e {disjuntor.mudo_ha}min sem nenhum contrato "
                        f"concluído, em {i} de {len(pendentes)} "
                        f"contratos — {e}") from e

    # ── correção monetária ───────────────────────────────────────────────

    def ipca(self, inicio=None):
        """Variação mensal do IPCA desde `inicio` (dd/mm/aaaa) — gera
        dicts `{"competencia": "aaaa-mm", "variacao": float}`.

        Fonte: Banco Central (série SGS 433), citável no processo. Preço
        de anos diferentes não se compara sem essa correção — a inflação
        acumulada num acervo de vários anos passa de 20%.

        Passa pelo mesmo `Cliente` das demais fases — mesmo retry/backoff
        e classificação de erro em `PncpErro`, em vez de uma tentativa
        única sem chance de se recuperar de um soluço passageiro do BCB.
        Efeito colateral aceito: uma falha do BCB soma no mesmo contador
        de bloqueios do PNCP (`Adaptativo` é por `Motor`, não por host) —
        chamada única no início da coleta, se autocorrige no primeiro
        sucesso da fase seguinte.
        """
        inicio = inicio or f"01/01/{DATA_INICIO_PNCP.year}"
        dados = self._cliente.get(
            _URL_BCB, "/dados/serie/bcdata.sgs.433/dados",
            {"formato": "json", "dataInicial": inicio})
        if dados is None:
            return
        for linha in dados:
            try:
                dia, mes, ano = linha["data"].split("/")
                variacao = float(linha["valor"])
            except (KeyError, ValueError):
                continue  # linha estranha não derruba a série inteira
            yield {"competencia": f"{ano}-{mes}", "variacao": variacao}
