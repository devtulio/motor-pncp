"""Séries do Banco Central usadas pra corrigir preço — fora do `Motor`.

O `Motor` é o PNCP; o BCB é outra API, com outro perfil de falha. Quando
`ipca` morava dentro dele, um soluço do BCB somava no mesmo contador de
bloqueios que decide o paralelismo contra o PNCP. Aqui cada chamada tem
seu próprio cliente (mesmo retry/backoff, mesma classificação de erro em
`PncpErro` — o nome é histórico), sem tocar no estado da coleta.
"""
from collections.abc import Iterator

from ._http import USER_AGENT_PADRAO, Cliente
from ._resiliencia import Adaptativo
from .configuracao import Config
from .dominio import DATA_INICIO_PNCP

URL_BCB = "https://api.bcb.gov.br"


def ipca(inicio: str | None = None, *, config: Config = Config(),
         user_agent: str = USER_AGENT_PADRAO) -> Iterator[dict]:
    """Variação mensal do IPCA desde `inicio` (dd/mm/aaaa) — gera dicts
    `{"competencia": "aaaa-mm", "variacao": float}`.

    Fonte: Banco Central (série SGS 433), citável no processo. Preço de
    anos diferentes não se compara sem essa correção — a inflação
    acumulada num acervo de vários anos passa de 20%.

    Passe `inicio` incremental (60 dias antes da última sincronização —
    o BCB revisa o mês corrente por semanas); `None` só na primeira vez.
    """
    inicio = inicio or f"01/01/{DATA_INICIO_PNCP.year}"
    cliente = Cliente(Adaptativo(config), config=config, user_agent=user_agent)
    dados = cliente.get(URL_BCB, "/dados/serie/bcdata.sgs.433/dados",
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
