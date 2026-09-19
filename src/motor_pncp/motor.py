"""Motor de coleta do PNCP — API pública do pacote.

Fronteira deliberada: o motor faz HTTP + resiliência contra o portal e
devolve registros tipados que embrulham o JSON cru do PNCP (`.raw`
continua sendo a fonte da verdade — ver `tipos.py`). Quem persiste decide
schema, upsert e o que já tem gravado; o motor não conhece banco nenhum.
Sistemas diferentes persistem de jeitos diferentes (um grava SQLite
direto, outro tem storage próprio); o motor não escolhe por eles.

Ver README.md para o porquê de cada limiar de resiliência (em `Config`).
"""
import concurrent.futures
import time
import warnings
from collections.abc import Iterable, Iterator
from datetime import date

from . import bcb
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

__all__ = [
    "Motor", "Config", "PncpErro", "SyncCancelado", "ItensIndisponiveis",
    "MODALIDADES", "DATA_INICIO_PNCP", "DATA_INICIO_PCA", "JANELA_MAX_DIAS",
    "janelas", "amd",
]


class _Rotulo(str):
    """Rótulo de consulta que lembra a posição dela no lote."""

    def __new__(cls, texto, indice):
        self = super().__new__(cls, texto)
        self.indice = indice
        return self


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

    `cancelado`, se passado, é um `threading.Event`: acioná-lo interrompe
    a coleta antes da próxima requisição e acorda na hora qualquer espera
    de backoff/`Retry-After` em andamento — o beacon `progresso` não
    chega nesses trechos (fica silenciado pelo agrupamento de avisos
    repetidos), então a parada por ele pode demorar minutos num storm.
    Os dois mecanismos convivem; este é o mais rápido.
    """

    def __init__(self, *, config: Config = Config(), user_agent=USER_AGENT_PADRAO,
                 progresso=None, cancelado=None, base=BASE, base_pncp=BASE_PNCP):
        self._config = config
        self._user_agent = user_agent
        self._adaptativo = Adaptativo(config)
        self._cliente = Cliente(self._adaptativo, config=config,
                                user_agent=user_agent, progresso=progresso,
                                cancelado=cancelado)
        self._base = base
        self._base_pncp = base_pncp

    # ── sonda ────────────────────────────────────────────────────────────

    def sonda(self) -> float:
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

    def _baixar_com_disjuntor(self, caminho, consultas, *, rotulo_fase, tipo,
                              tamanho_pagina=500):
        """Baixa uma lista de `(rótulo, params)` com disjuntor e beacon de
        progresso, gerando os registros (já embrulhados em `tipo`)
        conforme chegam.

        Compartilhada por toda fase que baixa uma lista fixa de consultas
        (contratações, contratos, atas, PCA) — a única diferença entre
        elas é como cada uma monta `consultas` e em que tipo embrulha o
        resultado; a resiliência é uma preocupação só, não uma por fase.

        **Repescagem:** as consultas que falharam na primeira passada são
        repetidas UMA vez ao fim do lote, depois de
        `Config.repescagem_pausa` segundos. O caso medido que motivou: o
        WAF do portal barra 1 ou 2 consultas de 26 com 429 e libera
        sozinho em ~15s — sem isto, quem consome refazia a janela inteira
        por causa de uma consulta. É retry de transporte, não
        orquestração: a lista de consultas é a mesma, nada é inferido.

        Levanta `PncpErro` — cedo, se o disjuntor desistir da fase, ou no
        fim, se alguma consulta seguiu falhando depois da repescagem. Em
        ambos os casos o erro carrega `consultas_falhas` (as que falharam
        E as que nem foram tentadas), pra `Motor.refazer(erro)` repetir só
        elas. O que já foi gerado antes quem consome já processou (falha
        ≠ ausência; não avance sua marca d'água sobre uma falha parcial).
        """
        disjuntor = Disjuntor(self._config)
        total = len(consultas)
        # rótulo não é único (o mesmo nome de modalidade se repete a cada
        # janela); o índice viaja junto pra saber QUAL consulta voltou,
        # sem mudar o protocolo (rótulo, lote, erro) de `Cliente.baixar`
        pendentes = dict(enumerate(consultas))
        primeiro_erro = None
        feitas = 0

        def erro_final(mensagem):
            erro = PncpErro(mensagem)
            erro.consultas_falhas = [pendentes[i] for i in sorted(pendentes)]
            erro._refazer = (caminho, tamanho_pagina, rotulo_fase, tipo)
            return erro

        for passada in (1, 2):
            if passada == 2:
                self._cliente.avisar_progresso(
                    f"{rotulo_fase} — repetindo {len(pendentes)} consulta(s) "
                    f"que falharam, em {self._config.repescagem_pausa:.0f}s…")
                self._cliente._dormir(self._config.repescagem_pausa)
            lote_atual = [(_Rotulo(r, i), p) for i, (r, p) in pendentes.items()]
            gerador = self._cliente.baixar(self._base, caminho, lote_atual,
                                           tamanho_pagina)
            try:
                for rotulo, lote, erro in gerador:
                    if passada == 1:
                        feitas += 1
                    self._cliente.avisar_progresso(
                        f"{rotulo_fase} — {rotulo} ({feitas}/{total})…")
                    if erro:
                        primeiro_erro = primeiro_erro or f"{rotulo}: {erro}"
                        if disjuntor.falha():
                            raise erro_final(
                                f"{rotulo_fase}: parado após {disjuntor.seguidas} "
                                f"falhas seguidas e {disjuntor.mudo_ha}min sem "
                                f"nenhuma resposta boa — {len(pendentes)} "
                                f"consultas por fazer — {primeiro_erro}")
                        continue
                    disjuntor.sucesso()
                    pendentes.pop(getattr(rotulo, "indice", None), None)
                    for raw in lote:
                        yield tipo(raw)
            finally:
                gerador.close()
            if not pendentes:
                return
        raise erro_final(
            f"{rotulo_fase}: {len(pendentes)} de {total} consultas falharam "
            f"(mesmo depois de repetidas) — {primeiro_erro}")

    def refazer(self, erro: PncpErro) -> Iterator:
        """Repete só as consultas que falharam numa fase em lote.

        `erro` é o `PncpErro` levantado por `contratacoes`, `contratos`,
        `atas` ou `pca`. Gera os mesmos registros tipados daquela fase,
        só das consultas em `erro.consultas_falhas` — em vez de refazer a
        janela inteira por causa de uma consulta. Se alguma seguir
        falhando, levanta outro `PncpErro`, com as que sobraram; pode
        chamar de novo com ele. Só avance sua marca d'água quando um
        `refazer` terminar sem erro.
        """
        if not getattr(erro, "_refazer", None):
            raise ValueError(
                "este erro não veio de uma fase em lote do Motor "
                "(contratacoes/contratos/atas/pca) — não há o que refazer")
        caminho, tamanho_pagina, rotulo_fase, tipo = erro._refazer
        yield from self._baixar_com_disjuntor(
            caminho, list(erro.consultas_falhas), rotulo_fase=rotulo_fase,
            tipo=tipo, tamanho_pagina=tamanho_pagina)

    def _janela_generica(self, caminho, params_extra, inicio, fim, *, rotulo_fase,
                         tipo, chaves_data=("dataInicial", "dataFinal"),
                         tamanho_pagina=500):
        """Monta as consultas de uma fase que consulta por CNPJ + janela
        de datas, sem o loop de modalidade de `contratacoes` (contratos,
        atas, PCA), e delega o download pra `_baixar_com_disjuntor`."""
        ini_chave, fim_chave = chaves_data
        consultas = [(amd(a), {**params_extra, ini_chave: amd(a), fim_chave: amd(b)})
                    for a, b in janelas(inicio, fim)]
        yield from self._baixar_com_disjuntor(caminho, consultas,
                                              rotulo_fase=rotulo_fase, tipo=tipo,
                                              tamanho_pagina=tamanho_pagina)

    # ── contratações ─────────────────────────────────────────────────────

    def contratacoes(self, codigo_ibge, inicio: date, fim: date) -> Iterator[Contratacao]:
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
        yield from self._baixar_com_disjuntor(
            "/v1/contratacoes/atualizacao", consultas, rotulo_fase="Contratações",
            tipo=Contratacao, tamanho_pagina=50)

    def contar_contratacoes(self, codigo_ibge, inicio: date = DATA_INICIO_PNCP,
                            fim: date | None = None) -> dict:
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
                                      params, modo_404="retry")
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

    def contratos(self, cnpj, inicio: date, fim: date) -> Iterator[Contrato]:
        """Gera `Contrato` de um órgão atualizados na janela — a API não
        filtra por município, só por CNPJ."""
        yield from self._janela_generica("/v1/contratos/atualizacao",
                                         {"cnpjOrgao": cnpj}, inicio, fim,
                                         rotulo_fase="Contratos", tipo=Contrato)

    def atas(self, cnpj, inicio: date, fim: date) -> Iterator[Ata]:
        """Gera `Ata` de registro de preços de um órgão atualizadas na
        janela."""
        yield from self._janela_generica("/v1/atas/atualizacao",
                                         {"cnpj": cnpj}, inicio, fim,
                                         rotulo_fase="Atas", tipo=Ata)

    def pca(self, cnpj, inicio: date, fim: date) -> Iterator[PlanoPca]:
        """Gera `PlanoPca` (Plano de Contratações Anual) de um órgão
        atualizados na janela.

        Este endpoint usa `dataInicio`/`dataFim` — os demais usam
        `dataInicial`/`dataFinal` (verificado contra a API real,
        2026-07-29) — e rejeita datas anteriores a `DATA_INICIO_PCA`.
        """
        inicio = max(inicio, DATA_INICIO_PCA)
        if inicio > fim:
            return
        yield from self._janela_generica("/v1/pca/atualizacao", {"cnpj": cnpj},
                                         inicio, fim, rotulo_fase="PCA",
                                         tipo=PlanoPca,
                                         chaves_data=("dataInicio", "dataFim"))

    # ── órgãos ───────────────────────────────────────────────────────────

    def consultar_orgao(self, cnpj) -> Orgao | None:
        """`Orgao` do CNPJ no PNCP (razão social, esfera) — `None` se o
        CNPJ não existe no portal."""
        raw = self._cliente.get(self._base_pncp, f"/v1/orgaos/{cnpj}", {})
        return Orgao(raw) if raw else None

    # ── itens e resultados ───────────────────────────────────────────────

    def itens_da_compra(self, cnpj, ano, sequencial) -> Iterator[Item]:
        """Gera `Item` de uma contratação (endpoint devolve array puro,
        paginado — sem envelope `totalPaginas`; o único sinal de fim é a
        página vir com MENOS de `tamanhoPagina`).

        Levanta `ItensIndisponiveis` em 404 — não confundir com "esta
        contratação não tem item nenhum" (ver a exceção).

        Página vazia é fim, em qualquer posição — inclusive depois de uma
        página cheia. Não dá pra ter aqui o guard de `Cliente.paginar`
        ("página 2+ vazia = portal engasgado"): sem envelope, uma página
        cheia obriga a pedir a próxima, e numa contratação com múltiplo
        exato de 100 itens a próxima vem legitimamente `[]` (verificado
        contra o portal: além do fim é 200 com array vazio, não 404).
        Um guard ali condenava essas contratações a falhar pra sempre —
        achado de teste de propriedade, não de incidente. O soluço real
        do portal chega como 5xx/timeout/HTML, que o retry cobre.
        """
        pagina = 1
        while True:
            lote = self._cliente.get(
                self._base_pncp,
                f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens",
                {"pagina": pagina, "tamanhoPagina": 100}, modo_404="erro")
            if not lote:
                return
            for raw in lote:
                yield Item(raw)
            if len(lote) < 100:
                return
            pagina += 1

    def resultado_do_item(self, cnpj, ano, sequencial, numero_item,
                          pacing=True) -> Resultado | None:
        """`Resultado` homologado de um item: vencedor e valor unitário
        fechado, ou `None` se o item ainda não tem resultado.

        `pacing=False` desliga o intervalo mínimo só nesta chamada — o
        motor não usa mais isso (o pacing vale também em paralelo); o
        parâmetro fica por compatibilidade."""
        lote = self._cliente.get(
            self._base_pncp,
            f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/"
            f"{numero_item}/resultados", {}, pacing=pacing)
        if not lote:
            return None
        # o mais recente não cancelado é o que vale
        validos = [r for r in lote if not r.get("dataCancelamento")]
        return Resultado((validos or lote)[0])

    def itens_e_resultados(
            self, contratacoes: Iterable[dict], *, pendente=None, on_erro=None,
    ) -> Iterator[tuple[dict, list[tuple[Item, Resultado | None]]]]:
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
                    ex = concurrent.futures.ThreadPoolExecutor(conexoes)
                    try:
                        futuros = {
                            ex.submit(self.resultado_do_item, c["orgao_cnpj"],
                                     c["ano"], c["sequencial"], item.numero_item):
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

    def termos_aditivos(self, contratos: Iterable[dict], *,
                        on_erro=None) -> Iterator[tuple[dict, list[TermoAditivo]]]:
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

    # ── correção monetária (DEPRECADO — ver `motor_pncp.ipca`) ──────────

    def ipca(self, inicio: str | None = None) -> Iterator[dict]:
        """DEPRECADO desde 1.2.0; sai em 2.0.0. Use `motor_pncp.ipca(inicio,
        config=..., user_agent=...)` — mesma saída, mas com cliente próprio:
        uma falha do BCB não suja mais o contador de bloqueios do PNCP.
        """
        warnings.warn(
            "Motor.ipca() está deprecado desde 1.2.0 e sai em 2.0.0; use "
            "motor_pncp.ipca(inicio, config=..., user_agent=...)",
            DeprecationWarning, stacklevel=2)
        return bcb.ipca(inicio, config=self._config, user_agent=self._user_agent)
