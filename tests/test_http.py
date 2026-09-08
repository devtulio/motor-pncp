import http.client
import urllib.error

import pytest
from conftest import resposta_json

from motor_pncp._http import Cliente
from motor_pncp._resiliencia import Adaptativo
from motor_pncp.excecoes import ItensIndisponiveis, PncpErro


def erro_http(codigo, headers=None):
    return urllib.error.HTTPError("http://x", codigo, "erro", headers or {}, None)


def cliente():
    return Cliente(Adaptativo())


# ── casos de sucesso ─────────────────────────────────────────────────────

def test_get_devolve_json(urlopen_fake):
    urlopen_fake.append(resposta_json({"data": [1, 2]}))
    assert cliente().get("https://x", "/y", {}) == {"data": [1, 2]}


def test_get_204_devolve_none(urlopen_fake):
    from conftest import RespostaFalsa
    urlopen_fake.append(RespostaFalsa(204, b""))
    assert cliente().get("https://x", "/y", {}) is None


def test_get_200_corpo_vazio_devolve_none(urlopen_fake):
    from conftest import RespostaFalsa
    urlopen_fake.append(RespostaFalsa(200, b""))
    assert cliente().get("https://x", "/y", {}) is None


# ── retry e classificação de erro ────────────────────────────────────────

def test_429_retenta_e_depois_funciona(urlopen_fake):
    urlopen_fake.append(erro_http(429))
    urlopen_fake.append(resposta_json({"ok": True}))
    assert cliente().get("https://x", "/y", {}, tentativas=3) == {"ok": True}


def test_5xx_retenta_e_depois_funciona(urlopen_fake):
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": True}))
    assert cliente().get("https://x", "/y", {}, tentativas=3) == {"ok": True}


def test_5xx_persistente_vira_pncperro(urlopen_fake):
    urlopen_fake.extend([erro_http(503)] * 3)
    with pytest.raises(PncpErro):
        cliente().get("https://x", "/y", {}, tentativas=3)


def test_422_retenta_e_depois_funciona(urlopen_fake):
    """Achado real: numa madrugada de 429/500/503/504 o portal também
    devolveu 422 numa janela que, refeita, respondeu normalmente."""
    urlopen_fake.append(erro_http(422))
    urlopen_fake.append(resposta_json({"ok": True}))
    assert cliente().get("https://x", "/y", {}, tentativas=3) == {"ok": True}


def test_erro_persistente_inclui_motivo_do_corpo_na_mensagem(urlopen_fake):
    class ErroComCorpo(urllib.error.HTTPError):
        def read(self):
            return b"Data inicial invalida ou anterior a 20210401"

    urlopen_fake.append(ErroComCorpo("http://x", 422, "erro", {}, None))
    with pytest.raises(PncpErro, match="Data inicial invalida"):
        cliente().get("https://x", "/y", {}, tentativas=1)


def test_erro_sem_corpo_legivel_nao_quebra_a_mensagem(urlopen_fake):
    urlopen_fake.append(erro_http(422))  # fp=None — .read() não funciona
    with pytest.raises(PncpErro, match="HTTP 422 em /y"):
        cliente().get("https://x", "/y", {}, tentativas=1)


def test_404_sem_flag_devolve_none(urlopen_fake):
    urlopen_fake.append(erro_http(404))
    assert cliente().get("https://x", "/y", {}, tentativas=3) is None


def test_404_com_modo_erro_vira_itens_indisponiveis(urlopen_fake):
    urlopen_fake.append(erro_http(404))
    with pytest.raises(ItensIndisponiveis):
        cliente().get("https://x", "/y", {}, tentativas=3, modo_404="erro")


def test_404_com_modo_retry_retenta_e_desiste_com_pncperro(urlopen_fake):
    urlopen_fake.extend([erro_http(404)] * 3)
    with pytest.raises(PncpErro):
        cliente().get("https://x", "/y", {}, tentativas=3, modo_404="retry")


def test_404_com_modo_retry_recupera(urlopen_fake):
    urlopen_fake.append(erro_http(404))
    urlopen_fake.append(resposta_json({"data": []}))
    assert cliente().get("https://x", "/y", {}, tentativas=3,
                         modo_404="retry") == {"data": []}


def test_json_ilegivel_retenta_e_desiste_com_pncperro(urlopen_fake):
    from conftest import RespostaFalsa
    urlopen_fake.extend([RespostaFalsa(200, b"<html>erro</html>")] * 3)
    with pytest.raises(PncpErro):
        cliente().get("https://x", "/y", {}, tentativas=3)


def test_conexao_cortada_nao_e_oserror_mas_e_tratada(urlopen_fake):
    """http.client.HTTPException (ex.: IncompleteRead) não é OSError —
    tinha que ter ramo próprio, senão escapa inteira (achado real)."""
    urlopen_fake.extend([http.client.IncompleteRead(b"")] * 3)
    with pytest.raises(PncpErro):
        cliente().get("https://x", "/y", {}, tentativas=3)


def test_timeout_vira_mensagem_de_portal_lento(urlopen_fake):
    urlopen_fake.append(TimeoutError("timed out"))
    with pytest.raises(PncpErro, match="lento ou fora do ar"):
        cliente().get("https://x", "/y", {}, tentativas=1)


def test_sucesso_registra_no_adaptativo(urlopen_fake):
    a = Adaptativo()
    c = Cliente(a)
    urlopen_fake.append(resposta_json({"ok": True}))
    c.get("https://x", "/y", {})
    assert a.bloqueios_recentes() == 0
    assert a._recentes(a._sucessos) == 1


def test_bloqueio_e_registrado_apos_5xx_seguido_de_sucesso(urlopen_fake):
    a = Adaptativo()
    c = Cliente(a)
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": True}))
    c.get("https://x", "/y", {}, tentativas=3)
    assert a.bloqueios_recentes() == 1


# ── beacon ────────────────────────────────────────────────────────────────

def test_beacon_avisa_a_cada_tentativa(urlopen_fake):
    avisos = []
    c = Cliente(Adaptativo(), progresso=avisos.append)
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": True}))
    c.get("https://x", "/y", {}, tentativas=3)
    assert len(avisos) == 1
    assert "503" in avisos[0]


def test_beacon_quebrado_nao_derruba_o_retry(urlopen_fake):
    def quebrado(msg):
        raise RuntimeError("boom")

    c = Cliente(Adaptativo(), progresso=quebrado)
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": True}))
    assert c.get("https://x", "/y", {}, tentativas=3) == {"ok": True}


def test_paginar_pagina_vazia_apos_pagina_cheia_vira_pncperro(urlopen_fake):
    """Incidente real: página 2 vazia depois de
    uma página 1 que anunciou mais totalPaginas é o portal engasgado no
    meio da listagem, não "acabou" — devolver o que veio até ali gravaria
    a janela como completa e perderia o resto pra sempre."""
    urlopen_fake.append(resposta_json(
        {"data": [{"id": 1}], "totalPaginas": 2}))
    urlopen_fake.append(resposta_json({"data": [], "totalPaginas": 2}))
    with pytest.raises(PncpErro, match="página 2 veio vazia"):
        list(cliente().paginar("https://x", "/y", {}, 50))


def test_paginar_pagina_1_vazia_e_legitima(urlopen_fake):
    urlopen_fake.append(resposta_json({"data": [], "totalPaginas": 1}))
    assert list(cliente().paginar("https://x", "/y", {}, 50)) == []


def test_paginar_prefere_paginasRestantes(urlopen_fake):
    """Campo canônico da spec pra decidir se continua; totalPaginas é
    reserva. Aqui os dois discordam de propósito — vence paginasRestantes."""
    urlopen_fake.append(resposta_json(
        {"data": [1], "paginasRestantes": 1, "totalPaginas": 1}))
    urlopen_fake.append(resposta_json(
        {"data": [2], "paginasRestantes": 0, "totalPaginas": 1}))
    assert list(cliente().paginar("https://x", "/y", {}, 50)) == [1, 2]


def test_paginar_cai_para_totalPaginas_sem_paginasRestantes(urlopen_fake):
    urlopen_fake.append(resposta_json({"data": [1], "totalPaginas": 2}))
    urlopen_fake.append(resposta_json({"data": [2], "totalPaginas": 2}))
    assert list(cliente().paginar("https://x", "/y", {}, 50)) == [1, 2]


def test_paginar_sem_nenhum_campo_de_paginacao_falha_alto(urlopen_fake):
    """Assumir "só esta página" truncaria em silêncio — mesma perda que a
    guarda de página vazia evita, por outra porta."""
    urlopen_fake.append(resposta_json({"data": [1]}))
    with pytest.raises(PncpErro, match="sem paginasRestantes/totalPaginas"):
        list(cliente().paginar("https://x", "/y", {}, 50))


def test_422_retenta_no_maximo_duas_vezes(urlopen_fake):
    """A spec classifica 422 como erro do cliente; o incidente real era um
    422 espúrio sob carga. Duas tentativas cobrem o espúrio; um 422
    legítimo falha rápido em vez de pagar a escada inteira."""
    urlopen_fake.extend([erro_http(422)] * 5)
    with pytest.raises(PncpErro, match="HTTP 422"):
        cliente().get("https://x", "/y", {}, tentativas=5)
    assert len(urlopen_fake) == 3  # consumiu 2 das 5, não 5


def test_beacon_agrupa_a_mesma_falha_entre_requisicoes_diferentes(urlopen_fake):
    """O storm real que motivou isso: centenas de contratações DIFERENTES
    batendo 503 — não é retry de uma só requisição, é a mesma causa se
    repetindo em chamadas `get()` independentes."""
    avisos = []
    c = Cliente(Adaptativo(), progresso=avisos.append)
    # requisição 1: falha uma vez com 503, depois funciona
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": 1}))
    c.get("https://x", "/a", {}, tentativas=3)
    # requisição 2 (outra contratação, mesma causa): deveria ficar em
    # silêncio — já avisamos sobre HTTP 503 há poucos segundos
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": 2}))
    c.get("https://x", "/b", {}, tentativas=3)
    assert len(avisos) == 1
    assert "/a" in avisos[0] and "/b" not in avisos[0]


def test_beacon_cancelamento_nao_e_engolido(urlopen_fake):
    from motor_pncp.excecoes import SyncCancelado

    def cancela(msg):
        raise SyncCancelado()

    c = Cliente(Adaptativo(), progresso=cancela)
    urlopen_fake.append(erro_http(503))
    urlopen_fake.append(resposta_json({"ok": True}))
    with pytest.raises(SyncCancelado):
        c.get("https://x", "/y", {}, tentativas=3)


# ── 1.1.0: jitter, Retry-After, pacing em paralelo, cancelamento, logging ──

def test_espera_e_full_jitter_no_intervalo_inteiro():
    """Brooker (AWS 2015): sortear em [0, 2^n], nao somar meio segundo."""
    from motor_pncp._http import _espera
    amostras = [_espera(3) for _ in range(500)]
    assert all(0 <= a <= 8 for a in amostras)
    assert min(amostras) < 2 and max(amostras) > 6  # espalha de verdade


def test_retry_after_inteiro_data_http_e_teto():
    import email.utils
    import time as _t

    from motor_pncp._http import _retry_after
    assert _retry_after({"Retry-After": "7"}, 120) == 7
    assert _retry_after({"Retry-After": "900"}, 120) == 120
    assert _retry_after({}, 120) is None
    assert _retry_after({"Retry-After": "daqui a pouco"}, 120) is None
    futuro = email.utils.formatdate(_t.time() + 30, usegmt=True)
    assert 25 <= _retry_after({"Retry-After": futuro}, 120) <= 30
    passado = email.utils.formatdate(_t.time() - 30, usegmt=True)
    assert _retry_after({"Retry-After": passado}, 120) == 0


def test_503_honra_retry_after(urlopen_fake, monkeypatch):
    """RFC 9110 define Retry-After pra 503 tambem, nao so 429."""
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    urlopen_fake.append(erro_http(503, {"Retry-After": "9"}))
    urlopen_fake.append(resposta_json({"ok": True}))
    cliente().get("https://x", "/y", {}, tentativas=3)
    assert 9 in dormidas


def test_429_sem_header_nunca_espera_zero(urlopen_fake, monkeypatch):
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    urlopen_fake.append(erro_http(429))
    urlopen_fake.append(resposta_json({"ok": True}))
    cliente().get("https://x", "/y", {}, tentativas=3)
    assert any(2.5 <= d <= 5 for d in dormidas)  # o resto e pacing


def test_pacing_vale_em_paralelo(urlopen_fake, monkeypatch):
    """Intervalo minimo e por host, nao por thread: 4 threads sem pacing
    eram 4 rajadas simultaneas (Mercator; Olston & Najork)."""
    import threading

    from motor_pncp.configuracao import Config
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    urlopen_fake.extend([resposta_json({"ok": True})] * 4)
    c = Cliente(Adaptativo(), config=Config(intervalo_min=0.5))
    threads = [threading.Thread(target=c.get, args=("https://x", "/y", {}))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(dormidas) >= 3  # a 1a passa; as outras esperam o intervalo


def test_cancelado_acorda_o_backoff(urlopen_fake):
    """Event acionado durante a espera de retry interrompe na hora, mesmo
    com o beacon silenciado pelo Dedup."""
    import threading

    from motor_pncp.excecoes import SyncCancelado
    evento = threading.Event()
    urlopen_fake.append(erro_http(503))
    c = Cliente(Adaptativo(), cancelado=evento)
    # o pedido de parada chega enquanto o retry esta sendo preparado
    c._avisar_causa_recorrente = lambda chave, msg: evento.set()
    with pytest.raises(SyncCancelado):
        c.get("https://x", "/y", {}, tentativas=3)
    assert len(urlopen_fake) == 0  # consumiu o 503 e nao tentou de novo


def test_cancelado_antes_da_primeira_tentativa(urlopen_fake):
    import threading

    from motor_pncp.excecoes import SyncCancelado
    evento = threading.Event()
    evento.set()
    urlopen_fake.append(resposta_json({"ok": True}))
    with pytest.raises(SyncCancelado):
        Cliente(Adaptativo(), cancelado=evento).get("https://x", "/y", {})
    assert len(urlopen_fake) == 1  # urlopen nem foi chamado


def test_logging_registra_tentativas_e_esgotamento(urlopen_fake, caplog):
    import logging
    urlopen_fake.extend([erro_http(503), erro_http(503)])
    with caplog.at_level(logging.DEBUG, logger="motor_pncp"):
        with pytest.raises(PncpErro):
            cliente().get("https://x", "/y", {}, tentativas=2)
    textos = [r.getMessage() for r in caplog.records]
    assert any("retry /y tentativa=1 causa=http503" in t for t in textos)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_logger_da_biblioteca_tem_nullhandler():
    import logging

    import motor_pncp  # noqa: F401
    assert any(isinstance(h, logging.NullHandler)
               for h in logging.getLogger("motor_pncp").handlers)
