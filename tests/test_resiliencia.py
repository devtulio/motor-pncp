import time

from motor_pncp._resiliencia import (
    FALHAS_CONSECUTIVAS_LIMITE,
    SEM_SUCESSO_LIMITE,
    TAXA_RECUO,
    TAXA_TREGUA,
    Adaptativo,
    Disjuntor,
)

# ── Disjuntor ────────────────────────────────────────────────────────────

def test_disjuntor_nao_para_por_falhas_seguidas_sozinhas(monkeypatch):
    """Fila grande tropeça por ruído normal: falhas seguidas sem tempo
    parado não bastam pra desistir da fase (achado real: 5 x HTTP 503 de
    órgãos diferentes encerravam uma fila de 7.398 contratações)."""
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor()
    for _ in range(FALHAS_CONSECUTIVAS_LIMITE + 10):
        relogio[0] += 1  # cada falha "custa" 1s — bem abaixo do limiar
        assert d.falha() is False


def test_disjuntor_para_depois_de_tempo_sem_sucesso(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor()
    parou = False
    for _ in range(FALHAS_CONSECUTIVAS_LIMITE + 5):
        relogio[0] += SEM_SUCESSO_LIMITE / FALHAS_CONSECUTIVAS_LIMITE + 1
        if d.falha():
            parou = True
            break
    assert parou is True


def test_disjuntor_sucesso_intercalado_reseta_o_relogio(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor()
    for _ in range(FALHAS_CONSECUTIVAS_LIMITE - 1):
        relogio[0] += 1000  # tempo suficiente pra disparar, se não resetasse
        d.falha()
    relogio[0] += 1000
    d.sucesso()
    assert d.seguidas == 0
    assert d.falha() is False  # relógio zerado, só 1 falha seguida agora


# ── Adaptativo: paralelismo e tentativas por proporção ──────────────────

def test_paralelismo_maximo_sem_bloqueio_recente():
    a = Adaptativo()
    assert a.paralelismo_atual() == 4


def test_paralelismo_ignora_ruido_de_fila_grande():
    """3 bloqueios contra 95 sucessos (~0.03) fica abaixo de TAXA_RECUO —
    não pode recuar por isso."""
    a = Adaptativo()
    for _ in range(95):
        a.registrar_sucesso()
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.paralelismo_atual() == 4


def test_paralelismo_recua_para_2_com_taxa_moderada():
    a = Adaptativo()
    for _ in range(6):
        a.registrar_sucesso()
    for _ in range(4):  # taxa = 4/10 = 0.4, entre TAXA_RECUO e TAXA_TREGUA
        a.registrar_bloqueio()
    assert TAXA_RECUO <= 4 / 10 < TAXA_TREGUA
    assert a.paralelismo_atual() == 2


def test_paralelismo_vai_sequencial_com_portal_recusando():
    a = Adaptativo()
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.paralelismo_atual() == 1


def test_tentativas_padrao_com_poucos_bloqueios():
    a = Adaptativo()
    a.registrar_bloqueio()
    a.registrar_bloqueio()
    assert a.tentativas_atual() == 5


def test_tentativas_encurta_com_storm_confirmado():
    a = Adaptativo()
    for _ in range(5):
        a.registrar_bloqueio()
    assert a.tentativas_atual() == 2


def test_janela_de_eventos_expira(monkeypatch):
    from motor_pncp._resiliencia import JANELA_EVENTOS

    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    a = Adaptativo()
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.bloqueios_recentes() == 3
    relogio[0] += JANELA_EVENTOS + 1
    assert a.bloqueios_recentes() == 0
    assert a.paralelismo_atual() == 4
