"""Limiares de resiliência — configuráveis por sistema, com os valores
medidos contra o PNCP real como default (ver docs no README e nos
módulos `_resiliencia.py`/`_http.py` pra por que cada um existe).

Sistemas com perfil diferente (ex.: um que atende clientes externos e
tolera menos silêncio que uma coleta em lote noturna) ajustam aqui sem
precisar dar fork no motor.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    conexoes_paralelas: int = 4
    """Tentativas simultâneas quando o portal está saudável."""

    janela_eventos: float = 120
    """Segundos: só bloqueios/sucessos dentro desta janela contam pra
    decidir paralelismo e nº de tentativas — um evento antigo não pesa
    pra sempre numa coleta que roda por horas."""

    taxa_recuo: float = 0.2
    """Fração de bloqueios recentes acima da qual já vale recuar
    (2 conexões, ou escada de retry mais curta)."""

    taxa_tregua: float = 0.5
    """Fração acima da qual o portal está recusando mais do que
    respondendo — cai pra 1 conexão / retry curto."""

    tentativas_padrao: int = 5
    tentativas_curtas: int = 2

    timeouts: tuple[float, ...] = (30, 45, 60, 75, 90)
    """Timeout de cada tentativa sucessiva — cresce porque o PNCP tende a
    demorar, não a recusar; repetir o mesmo prazo curto só repete a
    falha."""

    intervalo_min: float = 0.5
    """Segundos mínimos entre requisições sequenciais (pacing) — o PNCP
    tem throttling agressivo."""

    falhas_consecutivas_limite: int = 5
    """Nº de falhas seguidas a partir do qual o disjuntor passa a olhar
    o tempo sem sucesso (sozinho não basta: fila grande tropeça por
    ruído normal do portal)."""

    sem_sucesso_limite: float = 600
    """Segundos sem nenhum sucesso, combinados com
    `falhas_consecutivas_limite`, a partir dos quais o disjuntor desiste
    da fase."""

    janela_operacional: float = 300
    """Segundos: avisos de retry da MESMA causa (ex.: HTTP 503) em
    requisições diferentes ficam em silêncio dentro desta janela depois
    do primeiro, e a próxima emissão resume quantos ficaram represados —
    sem isso, um storm em uma fila de milhares produz uma linha idêntica
    por requisição."""
