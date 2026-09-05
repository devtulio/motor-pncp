import threading
import time as time_module

from motor_pncp._http import Cliente
from motor_pncp._resiliencia import Adaptativo


def test_baixar_agrega_paralelo_sem_perder_rotulo(monkeypatch):
    def paginar_fake(self, url_base, caminho, params, tamanho_pagina, pacing=True):
        yield {"rotulo": params["rotulo"]}

    monkeypatch.setattr(Cliente, "paginar", paginar_fake)
    c = Cliente(Adaptativo())
    consultas = [(f"c{i}", {"rotulo": f"c{i}"}) for i in range(6)]
    resultado = {rotulo: lote for rotulo, lote, erro in
                c.baixar("https://x", "/y", consultas, 50)}
    assert set(resultado) == {f"c{i}" for i in range(6)}
    for rotulo, lote in resultado.items():
        assert lote == [{"rotulo": rotulo}]


def test_baixar_falha_de_uma_consulta_nao_derruba_as_outras(monkeypatch):
    from motor_pncp.excecoes import PncpErro

    def paginar_fake(self, url_base, caminho, params, tamanho_pagina, pacing=True):
        if params["rotulo"] == "quebrada":
            raise PncpErro("boom")
        yield {"rotulo": params["rotulo"]}

    monkeypatch.setattr(Cliente, "paginar", paginar_fake)
    c = Cliente(Adaptativo())
    consultas = [("ok1", {"rotulo": "ok1"}), ("quebrada", {"rotulo": "quebrada"}),
                ("ok2", {"rotulo": "ok2"})]
    resultado = {rotulo: (lote, erro) for rotulo, lote, erro in
                c.baixar("https://x", "/y", consultas, 50)}
    assert resultado["ok1"] == ([{"rotulo": "ok1"}], None)
    assert resultado["ok2"] == ([{"rotulo": "ok2"}], None)
    lote, erro = resultado["quebrada"]
    assert lote == [] and isinstance(erro, PncpErro)


def test_baixar_nao_espera_a_leva_inteira_ao_parar_cedo(monkeypatch):
    """O achado que mais doeu: `_baixar` é gerador, e um `.close()` (o que
    o disjuntor de quem chama faz ao desistir cedo) não pode ficar minutos
    esperando as consultas já em voo pagarem o próprio orçamento de retry.
    """
    liberar = threading.Event()

    def paginar_fake(self, url_base, caminho, params, tamanho_pagina, pacing=True):
        if params["rotulo"] != "rapida":
            liberar.wait(5)
        return iter([{"rotulo": params["rotulo"]}])

    monkeypatch.setattr(Cliente, "paginar", paginar_fake)
    c = Cliente(Adaptativo())
    consultas = [("rapida", {"rotulo": "rapida"})] + [
        (f"lenta{i}", {"rotulo": f"lenta{i}"}) for i in range(6)]
    gerador = c.baixar("https://x", "/y", consultas, 50)
    try:
        inicio = time_module.monotonic()
        next(gerador)  # espera só a primeira que terminar (a rápida)
        gerador.close()
        duracao = time_module.monotonic() - inicio
        assert duracao < 2.0
    finally:
        liberar.set()  # libera as threads penduradas pra não travar o teste
