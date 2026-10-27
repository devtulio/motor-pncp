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
    conexoes_paralelas: int = 1
    """Requisições simultâneas com o portal saudável. O PNCP pede, em
    resposta oficial a um chamado (out/2026), chamadas em sequência e sem
    paralelismo — o limite é por IP, e duas conexões só disputam a mesma
    cota. Medido antes disso: 1 conexão zerou consulta perdida numa sync
    real em que 2 e 4 perdiam. O paralelismo adaptativo nunca passa
    deste teto."""

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

    intervalo_min: float = 1.1
    """Segundos mínimos entre requisições ao mesmo host (pacing), valendo
    entre threads e — com `ritmo_compartilhado` — entre processos. Vale
    para todo host exceto a API de Consulta (ver `intervalo_consulta`):
    a API de Integração do PNCP (itens, resultados, órgão) tem o limite
    mais folgado (150 req/10 s) e o PNCP pede espaçamento acima de 1 s."""

    intervalo_consulta: float = 3.0
    """Intervalo mínimo na API de Consulta (`/api/consulta`). O PNCP
    informou três classes de limite ali (5 req/15 s, 5 req/5 s e
    50 req/10 s) sem dizer qual endpoint é de qual; 3 s cabe na mais
    restrita."""

    bloqueio_429: float = 40
    """Segundos de espera depois de um HTTP 429 sem `Retry-After` (o PNCP
    não manda o header). É o maior bloqueio que o PNCP informou; repetir
    antes disso cai dentro do bloqueio e conta como novo excesso. Vale
    para todo processo que compartilha o ritmo."""

    ritmo_compartilhado: bool = True
    """Coordena o intervalo e o bloqueio de 429 entre PROCESSOS da mesma
    máquina, por um arquivo pequeno por host em `~/.motor_pncp/` — o
    limite do PNCP é por IP, e uma sincronização e um monitor rodando
    juntos somariam requisições sem se ver. Se o arquivo não puder ser
    usado, o motor volta ao ritmo só deste processo e avisa no log."""

    pasta_ritmo: str | None = None
    """Onde ficam os arquivos do ritmo compartilhado. `None` = variável
    de ambiente `MOTOR_PNCP_RITMO` ou, sem ela, `~/.motor_pncp/`."""

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

    repescagem_pausa: float = 45
    """Segundos de espera antes de repetir, uma única vez, as consultas
    que falharam numa fase em lote. Acima do maior bloqueio de 429 que o
    PNCP informou (40 s); só espera quando houve falha."""

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
        if self.conexoes_paralelas < 1:
            raise ValueError("conexoes_paralelas precisa ser >= 1")
        if min(self.intervalo_min, self.intervalo_consulta, self.bloqueio_429) < 0:
            raise ValueError("intervalos e bloqueio_429 não podem ser negativos")
