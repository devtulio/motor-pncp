import json

import pytest


class RespostaFalsa:
    """Simula o retorno de `urllib.request.urlopen` como gerenciador de
    contexto (`with urlopen(...) as resp:`)."""

    def __init__(self, status=200, corpo=b""):
        self.status = status
        self._corpo = corpo

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def resposta_json(dados, status=200):
    return RespostaFalsa(status, json.dumps(dados).encode("utf-8"))


@pytest.fixture(autouse=True)
def sem_espera_de_verdade(monkeypatch):
    """Nenhum teste deve esperar o backoff/pacing reais — só a lógica de
    quantas vezes e com que exceção importa aqui."""
    monkeypatch.setattr("time.sleep", lambda *_: None)


@pytest.fixture
def urlopen_fake(monkeypatch):
    """Substitui `urllib.request.urlopen` por uma fila de respostas/exceções
    programada pelo teste. Cada chamada consome o próximo item da fila.

    Item pode ser: um `RespostaFalsa`/resultado de `resposta_json`, ou uma
    exceção (instância) a ser levantada.
    """
    fila = []

    def fake(req, timeout=None):
        if not fila:
            raise AssertionError("urlopen chamado mais vezes que o programado")
        item = fila.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fila
