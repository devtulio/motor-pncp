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
    """Segundos mínimos entre requisições ao portal (pacing), valendo
    também entre as threads em paralelo — o PNCP tem throttling
    agressivo, e o intervalo é por host, não por conexão."""

    retry_after_teto: float = 120
    """Teto em segundos para o que o portal pede em `Retry-After` (429 e
    503). Acima disso a espera é cortada: uma thread não pode ficar muda
    por uma hora porque o header mandou."""

    falhas_consecutivas_limite: int = 5
    """Nº de falhas seguidas a partir do qual o disjuntor passa a olhar
    o tempo sem sucesso (sozinho não basta: fila grande tropeça por
    ruído normal do portal)."""

    sem_sucesso_limite: float = 600
    """Segundos sem nenhum sucesso, combinados com
    `falhas_consecutivas_limite`, a partir dos quais o disjuntor desiste
    da fase."""

    falhas_seguidas_teto: int = 40
    """Teto absoluto de falhas seguidas — desiste da fase mesmo que o
    relógio de `sem_sucesso_limite` ainda não tenha fechado. Existe
    porque `sem_sucesso_limite` foi calibrado pra falha LENTA (~5min pela
    escada cheia); quando um storm confirmado encurta a escada
    (`tentativas_curtas`), cada falha passa a custar segundos, e só o
    relógio deixaria o disjuntor mastigar a fila inteira antes de
    desistir (medido: 139-196 falhas seguidas, 36-86% da fila, 0 itens
    gravados). 40 é o pior caso normal de ruído que o próprio limiar de
    tempo já esperava — preserva a tolerância a tropeço isolado, só corta
    o caso em que a contagem passa MUITO disso."""

    janela_operacional: float = 300
    """Segundos: avisos de retry da MESMA causa (ex.: HTTP 503) em
    requisições diferentes ficam em silêncio dentro desta janela depois
    do primeiro, e a próxima emissão resume quantos ficaram represados —
    sem isso, um storm em uma fila de milhares produz uma linha idêntica
    por requisição."""

    def __post_init__(self):
        # tentativas=0 faria `for tentativa in range(0):` não executar
        # nenhuma vez — `Cliente.get` cairia direto no `return None`
        # implícito, uma falha de configuração virando silenciosamente
        # "sem dados" (exatamente o "falha ≠ ausência" que o resto do
        # motor existe pra evitar).
        if self.tentativas_padrao < 1 or self.tentativas_curtas < 1:
            raise ValueError(
                "tentativas_padrao e tentativas_curtas precisam ser >= 1")
