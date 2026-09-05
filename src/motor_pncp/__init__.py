"""Motor de coleta do PNCP.

Faz HTTP resiliente contra o portal (retry com backoff, paralelismo e nº
de tentativas que recuam sozinhos sob storm, disjuntor por tempo sem
sucesso) e devolve dados crus. Não tem opinião sobre onde os dados vão
parar — isso é problema de quem consome. Ver README.md.
"""
from .motor import (
    BASE,
    BASE_PNCP,
    DATA_INICIO_PNCP,
    JANELA_MAX_DIAS,
    MODALIDADES,
    ItensIndisponiveis,
    Motor,
    PncpErro,
    SyncCancelado,
    amd,
    janelas,
)

__all__ = [
    "Motor", "PncpErro", "SyncCancelado", "ItensIndisponiveis",
    "MODALIDADES", "DATA_INICIO_PNCP", "JANELA_MAX_DIAS", "BASE",
    "BASE_PNCP", "janelas", "amd",
]

__version__ = "0.1.0"
