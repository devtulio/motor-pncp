"""Sinais que decidem paralelismo, nº de tentativas e quando desistir.

Todo limiar aqui existe por um incidente medido contra o PNCP real — ver
docs/licoes.md para o porquê de cada um. Não ajustar sem medição nova.
"""
import collections
import threading
import time

# Só contam os eventos RECENTES: um contador acumulado desde o início do
# processo não serve — uma rajada antiga não pode pesar pra sempre numa
# coleta que roda por horas contra uma fila de milhares.
JANELA_EVENTOS = 120  # s

CONEXOES_PARALELAS = 4
# Fração de tentativas ruins na janela a partir da qual vale recuar. Cada
# requisição que falha de vez registra várias tentativas (uma por retry
# que ainda vai reintentar) e uma que responde registra 1 sucesso — 5% de
# requisições perdidas (ruído normal do PNCP) precisa ficar abaixo disso,
# senão uma fila grande recua por tropeço estatisticamente inevitável.
TAXA_RECUO = 0.2    # acima disso, 2 conexões / escada curta de tentativas
TAXA_TREGUA = 0.5   # acima disso, sequencial: o portal recusa mais do que
                    # responde

FALHAS_CONSECUTIVAS_LIMITE = 5
# O que separa "portal fora do ar" de "ruído normal" não é quantas
# falharam seguidas — é há quanto tempo nada dá certo. Enquanto alguma
# consulta responde, a fila anda e desistir só joga fora trabalho já
# pago; enquanto nada responde, o tempo é o recurso que isto protege.
SEM_SUCESSO_LIMITE = 600  # s

TENTATIVAS_PADRAO = 5
TENTATIVAS_CURTAS = 2


class Adaptativo:
    """Rastreia bloqueios/sucessos recentes e decide paralelismo e nº de
    tentativas a partir disso.

    Uma instância por `Motor`, não estado de módulo — duas coletas no
    mesmo processo (ou dois testes em sequência) não se pisam.
    """

    def __init__(self):
        self._bloqueios = collections.deque()
        self._sucessos = collections.deque()
        self._trava = threading.Lock()

    def _registrar(self, fila):
        agora = time.monotonic()
        with self._trava:
            while fila and fila[0] < agora - JANELA_EVENTOS:
                fila.popleft()
            fila.append(agora)

    def registrar_bloqueio(self):
        self._registrar(self._bloqueios)

    def registrar_sucesso(self):
        self._registrar(self._sucessos)

    def _recentes(self, fila):
        limite = time.monotonic() - JANELA_EVENTOS
        with self._trava:
            while fila and fila[0] < limite:
                fila.popleft()
            return len(fila)

    def bloqueios_recentes(self):
        return self._recentes(self._bloqueios)

    def paralelismo_atual(self):
        """Recua por degraus e volta sozinho quando o portal para de
        reclamar.

        Olha a PROPORÇÃO de tentativas ruins, não a contagem: contagem
        pura escala com o tamanho da fila — numa coleta de milhares de
        contratações, três bloqueios em dois minutos acontecem com o
        portal saudável, e um degrau por contagem prendia a coleta em 1
        conexão (4x mais lenta) sem nenhum ganho real.
        """
        n = self.bloqueios_recentes()
        if not n:
            return CONEXOES_PARALELAS
        taxa = n / (n + self._recentes(self._sucessos))
        if taxa < TAXA_RECUO:
            return CONEXOES_PARALELAS
        if n >= 3 and taxa >= TAXA_TREGUA:
            return 1
        return 2

    def tentativas_atual(self):
        """Encurta a escada de retry quando um storm já está confirmado,
        pelo mesmo sinal de `paralelismo_atual`.

        Insistir 5 tentativas completas (~5,3min) numa consulta nova só
        confirma devagar o que as últimas chamadas já mostraram. O item
        que falhar aqui não é descartado — fica pendente e volta na
        próxima passada, como qualquer outra falha.
        """
        n = self.bloqueios_recentes()
        if n < 3:
            return TENTATIVAS_PADRAO
        taxa = n / (n + self._recentes(self._sucessos))
        return TENTATIVAS_CURTAS if taxa >= TAXA_TREGUA else TENTATIVAS_PADRAO


class Disjuntor:
    """Decide quando desistir de uma FASE inteira — não de uma requisição.

    Uma instância por fase/chamada: o que interessa é o progresso daquela
    fila específica. Falhas seguidas sozinhas não bastam (fila grande
    tropeça por ruído normal do PNCP mesmo com o portal saudável); só
    desiste quando falhas seguidas E tempo sem nenhum sucesso passam do
    limiar — a combinação que separa "portal fora do ar" de "ruído".
    """

    def __init__(self):
        self.seguidas = 0
        self.desde = time.monotonic()  # último sucesso (ou início da fase)

    def sucesso(self):
        self.seguidas = 0
        self.desde = time.monotonic()

    def falha(self):
        """True quando é hora de desistir da fase."""
        self.seguidas += 1
        return (self.seguidas >= FALHAS_CONSECUTIVAS_LIMITE
                and time.monotonic() - self.desde >= SEM_SUCESSO_LIMITE)

    @property
    def mudo_ha(self):
        """Minutos desde o último sucesso (ou desde o início da fase)."""
        return round((time.monotonic() - self.desde) / 60)
