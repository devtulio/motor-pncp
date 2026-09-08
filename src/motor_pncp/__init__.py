"""Motor de coleta do PNCP.

Faz HTTP resiliente contra o portal (retry com backoff, paralelismo e nº
de tentativas que recuam sozinhos sob storm, disjuntor por tempo sem
sucesso) e devolve registros tipados que embrulham o JSON cru do PNCP.
Não tem opinião sobre onde os dados vão parar — isso é problema de quem
consome. Ver README.md.
"""
import logging

from .configuracao import Config
from .dominio import (
    DATA_INICIO_PCA,
    DATA_INICIO_PNCP,
    JANELA_MAX_DIAS,
    MODALIDADES,
    amd,
    dt,
    janelas,
    num,
    primeiro,
)
from .excecoes import ItensIndisponiveis, PncpErro, SyncCancelado
from .motor import BASE, BASE_PNCP, Motor
from .tipos import Ata, Contratacao, Contrato, Item, Orgao, PlanoPca, Resultado, TermoAditivo

__all__ = [
    "Motor", "Config", "PncpErro", "SyncCancelado", "ItensIndisponiveis",
    "MODALIDADES", "DATA_INICIO_PNCP", "DATA_INICIO_PCA", "JANELA_MAX_DIAS",
    "BASE", "BASE_PNCP", "janelas", "amd", "num", "primeiro", "dt",
    "Contratacao", "Item", "Resultado", "Contrato", "Ata", "PlanoPca",
    "TermoAditivo", "Orgao",
]

# biblioteca não configura logging: só declara o logger e cala por padrão
# (HOWTO oficial). Quem consome liga com
# `logging.getLogger("motor_pncp").setLevel(logging.DEBUG)` + um handler.
logging.getLogger("motor_pncp").addHandler(logging.NullHandler())

# fonte única da versão — pyproject.toml lê daqui (RELEASING.md §5)
__version__ = "1.1.0"
