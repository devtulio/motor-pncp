import time

from motor_pncp._resiliencia import Adaptativo, Dedup, Disjuntor
from motor_pncp.configuracao import Config

CFG = Config()


# ── Disjuntor ────────────────────────────────────────────────────────────

def test_disjuntor_nao_para_por_falhas_seguidas_sozinhas(monkeypatch):
    """Fila grande tropeça por ruído normal: falhas seguidas sem tempo
    parado não bastam pra desistir da fase (achado real: 5 x HTTP 503 de
    órgãos diferentes encerravam uma fila de 7.398 contratações)."""
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor(CFG)
    for _ in range(CFG.falhas_consecutivas_limite + 10):
        relogio[0] += 1  # cada falha "custa" 1s — bem abaixo do limiar
        assert d.falha() is False


def test_disjuntor_para_depois_de_tempo_sem_sucesso(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor(CFG)
    parou = False
    for _ in range(CFG.falhas_consecutivas_limite + 5):
        relogio[0] += CFG.sem_sucesso_limite / CFG.falhas_consecutivas_limite + 1
        if d.falha():
            parou = True
            break
    assert parou is True


def test_disjuntor_sucesso_intercalado_reseta_o_relogio(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor(CFG)
    for _ in range(CFG.falhas_consecutivas_limite - 1):
        relogio[0] += 1000  # tempo suficiente pra disparar, se não resetasse
        d.falha()
    relogio[0] += 1000
    d.sucesso()
    assert d.seguidas == 0
    assert d.falha() is False  # relógio zerado, só 1 falha seguida agora


def test_disjuntor_teto_absoluto_corta_mesmo_com_falha_rapida(monkeypatch):
    """Incidente real: com a escada curta, cada
    falha custa segundos, e só o relógio de sem_sucesso_limite deixava o
    disjuntor mastigar 139-196 itens antes de desistir. O teto de
    contagem corta bem antes do relógio fechar."""
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Disjuntor(CFG)
    for _ in range(CFG.falhas_seguidas_teto - 1):
        relogio[0] += 3  # falha barata: 3s, não minutos
        assert d.falha() is False
    relogio[0] += 3
    assert d.falha() is True
    # prova de que foi o teto, não o relógio: ainda longe do limite de tempo
    assert relogio[0] < CFG.sem_sucesso_limite


def test_disjuntor_respeita_config_customizado(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    cfg = Config(falhas_consecutivas_limite=2, sem_sucesso_limite=10)
    d = Disjuntor(cfg)
    relogio[0] += 5
    assert d.falha() is False  # 1 falha
    relogio[0] += 10
    assert d.falha() is True  # 2 falhas, 15s >= 10s


# ── Adaptativo: paralelismo e tentativas por proporção ──────────────────

def test_paralelismo_maximo_sem_bloqueio_recente():
    a = Adaptativo(CFG)
    assert a.paralelismo_atual() == CFG.conexoes_paralelas


def test_paralelismo_ignora_ruido_de_fila_grande():
    """3 bloqueios contra 95 sucessos (~0.03) fica abaixo de TAXA_RECUO —
    não pode recuar por isso."""
    a = Adaptativo(CFG)
    for _ in range(95):
        a.registrar_sucesso()
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.paralelismo_atual() == CFG.conexoes_paralelas


def test_paralelismo_recua_para_2_com_taxa_moderada():
    a = Adaptativo(CFG)
    for _ in range(6):
        a.registrar_sucesso()
    for _ in range(4):  # taxa = 4/10 = 0.4, entre taxa_recuo e taxa_tregua
        a.registrar_bloqueio()
    assert CFG.taxa_recuo <= 4 / 10 < CFG.taxa_tregua
    assert a.paralelismo_atual() == 2


def test_paralelismo_vai_sequencial_com_portal_recusando():
    a = Adaptativo(CFG)
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.paralelismo_atual() == 1


def test_tentativas_padrao_com_poucos_bloqueios():
    a = Adaptativo(CFG)
    a.registrar_bloqueio()
    a.registrar_bloqueio()
    assert a.tentativas_atual() == CFG.tentativas_padrao


def test_tentativas_encurta_com_storm_confirmado():
    a = Adaptativo(CFG)
    for _ in range(5):
        a.registrar_bloqueio()
    assert a.tentativas_atual() == CFG.tentativas_curtas


def test_janela_de_eventos_expira(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    a = Adaptativo(CFG)
    for _ in range(3):
        a.registrar_bloqueio()
    assert a.bloqueios_recentes() == 3
    relogio[0] += CFG.janela_eventos + 1
    assert a.bloqueios_recentes() == 0
    assert a.paralelismo_atual() == CFG.conexoes_paralelas


def test_adaptativo_respeita_conexoes_paralelas_customizado():
    a = Adaptativo(Config(conexoes_paralelas=8))
    assert a.paralelismo_atual() == 8


# ── Dedup ────────────────────────────────────────────────────────────────

def test_dedup_emite_a_primeira_ocorrencia_sem_sufixo():
    d = Dedup(janela=300)
    assert d.registrar("http503", "PNCP 503") == "PNCP 503"


def test_dedup_silencia_ocorrencias_dentro_da_janela(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Dedup(janela=300)
    assert d.registrar("http503", "PNCP 503") == "PNCP 503"
    relogio[0] += 100
    assert d.registrar("http503", "PNCP 503") is None
    relogio[0] += 100
    assert d.registrar("http503", "PNCP 503") is None


def test_dedup_resume_a_contagem_apos_a_janela(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    d = Dedup(janela=300)
    d.registrar("http503", "PNCP 503")
    relogio[0] += 100
    d.registrar("http503", "PNCP 503")  # suprimido, 1ª represada
    relogio[0] += 100
    d.registrar("http503", "PNCP 503")  # suprimido, 2ª represada
    relogio[0] += 200  # passa dos 300s desde a última EMISSÃO (t=0)
    emitido = d.registrar("http503", "PNCP 503")
    assert emitido == "PNCP 503 (×3 em 5min)"


def test_dedup_nao_mistura_chaves_diferentes():
    d = Dedup(janela=300)
    assert d.registrar("http503", "A") == "A"
    assert d.registrar("http429", "B") == "B"  # chave diferente, não suprime
