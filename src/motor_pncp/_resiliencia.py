"""Sinais que decidem paralelismo, nº de tentativas e quando desistir.

Todo limiar (em `Config`) existe por um incidente medido contra o PNCP
real — ver docs no README. Os defaults não devem mudar sem medição nova;
um sistema com perfil diferente ajusta passando seu próprio `Config`.
"""
import collections
import threading
import time

from .configuracao import Config


class Adaptativo:
    """Rastreia bloqueios/sucessos recentes e decide paralelismo e nº de
    tentativas a partir disso.

    Uma instância por `Motor`, não estado de módulo — duas coletas no
    mesmo processo (ou dois testes em sequência) não se pisam.
    """

    def __init__(self, config: Config = Config()):
        self._config = config
        self._bloqueios = collections.deque()
        self._sucessos = collections.deque()
        self._trava = threading.Lock()

    def _registrar(self, fila):
        agora = time.monotonic()
        with self._trava:
            while fila and fila[0] < agora - self._config.janela_eventos:
                fila.popleft()
            fila.append(agora)

    def registrar_bloqueio(self):
        self._registrar(self._bloqueios)

    def registrar_sucesso(self):
        self._registrar(self._sucessos)

    def _recentes(self, fila):
        limite = time.monotonic() - self._config.janela_eventos
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
        cfg = self._config
        n = self.bloqueios_recentes()
        if not n:
            return cfg.conexoes_paralelas
        taxa = n / (n + self._recentes(self._sucessos))
        if taxa < cfg.taxa_recuo:
            return cfg.conexoes_paralelas
        if n >= 3 and taxa >= cfg.taxa_tregua:
            return 1
        return 2

    def tentativas_atual(self):
        """Encurta a escada de retry quando um storm já está confirmado,
        pelo mesmo sinal de `paralelismo_atual`.

        Insistir a escada completa (~5,3min com os timeouts default) numa
        consulta nova só confirma devagar o que as últimas chamadas já
        mostraram. O item que falhar aqui não é descartado — fica
        pendente e volta na próxima passada, como qualquer outra falha.
        """
        cfg = self._config
        n = self.bloqueios_recentes()
        if n < 3:
            return cfg.tentativas_padrao
        taxa = n / (n + self._recentes(self._sucessos))
        return cfg.tentativas_curtas if taxa >= cfg.taxa_tregua else cfg.tentativas_padrao


class Disjuntor:
    """Decide quando desistir de uma FASE inteira — não de uma requisição.

    Uma instância por fase/chamada: o que interessa é o progresso daquela
    fila específica. Falhas seguidas sozinhas não bastam (fila grande
    tropeça por ruído normal do PNCP mesmo com o portal saudável); só
    desiste quando falhas seguidas E tempo sem nenhum sucesso passam do
    limiar — a combinação que separa "portal fora do ar" de "ruído".
    """

    def __init__(self, config: Config = Config()):
        self._config = config
        self.seguidas = 0
        self.desde = time.monotonic()  # último sucesso (ou início da fase)

    def sucesso(self):
        self.seguidas = 0
        self.desde = time.monotonic()

    def falha(self):
        """True quando é hora de desistir da fase."""
        self.seguidas += 1
        return (self.seguidas >= self._config.falhas_consecutivas_limite
                and time.monotonic() - self.desde >= self._config.sem_sucesso_limite)

    @property
    def mudo_ha(self):
        """Minutos desde o último sucesso (ou desde o início da fase)."""
        return round((time.monotonic() - self.desde) / 60)
