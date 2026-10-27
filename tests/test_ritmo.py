"""1.8.0: ritmo pedido pelo PNCP em resposta oficial (out/2026) — sem
paralelismo, mais de 1 s entre chamadas, PARAR no 429 e respeitar o
bloqueio — e coordenado entre processos, porque o limite é por IP."""
import json
import subprocess
import sys
import textwrap
import time
import urllib.error

import pytest
from conftest import resposta_json

from motor_pncp import Config, PncpErro, _http
from motor_pncp._http import Cliente
from motor_pncp._resiliencia import Adaptativo
from motor_pncp._ritmo import Ritmo, chave_do_host


def erro_429(corpo=b""):
    import io
    return urllib.error.HTTPError("http://x", 429, "erro", {}, io.BytesIO(corpo))


PAGINA_429 = ("<html><head><title>Limite de Requisições Excedido</title></head><body>"
              "<h2>Limite de requisições excedido</h2><p>Aguarde alguns instantes.</p>"
              "<p>Seu Support ID é: <strong><14140211365997677061></strong></p>"
              "</body></html>").encode()


# ── padrões ─────────────────────────────────────────────────────────────

def test_padroes_seguem_o_pedido_do_pncp():
    c = Config()
    assert c.conexoes_paralelas == 1
    assert c.intervalo_min > 1 and c.intervalo_consulta >= 3
    assert c.bloqueio_429 >= 40 and c.repescagem_pausa > c.bloqueio_429
    assert c.ritmo_compartilhado is True


def test_paralelismo_adaptativo_nunca_passa_do_teto():
    """O degrau intermediário era 2 fixo: com teto 1, 'recuar' AUMENTAVA."""
    a = Adaptativo(Config(conexoes_paralelas=1))
    for _ in range(6):
        a.registrar_sucesso()
    for _ in range(4):
        a.registrar_bloqueio()
    assert a.paralelismo_atual() == 1


def test_config_recusa_valores_sem_sentido():
    with pytest.raises(ValueError):
        Config(conexoes_paralelas=0)
    with pytest.raises(ValueError):
        Config(intervalo_consulta=-1)


# ── intervalo por host ─────────────────────────────────────────────────

def test_consulta_e_integracao_tem_intervalos_proprios(urlopen_fake, monkeypatch):
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(round(s, 1)))
    c = Cliente(Adaptativo())
    urlopen_fake.extend([resposta_json({"ok": 1})] * 4)
    c.get("https://pncp.gov.br/api/consulta", "/v1/a", {})
    c.get("https://pncp.gov.br/api/consulta", "/v1/a", {})
    c.get("https://pncp.gov.br/api/pncp", "/v1/b", {})
    c.get("https://pncp.gov.br/api/pncp", "/v1/b", {})
    # time.sleep é falso nos testes: o relógio não anda, então cada espera
    # mede o intervalo inteiro do host, e o primeiro de cada host não espera
    assert dormidas == [3.0, 1.1]


def test_chave_do_host_separa_as_duas_apis():
    assert chave_do_host("https://pncp.gov.br/api/consulta") != chave_do_host(
        "https://pncp.gov.br/api/pncp")


# ── 429 ─────────────────────────────────────────────────────────────────

def test_429_tenta_so_uma_vez_mais_e_guarda_o_support_id(urlopen_fake):
    urlopen_fake.extend([erro_429(PAGINA_429), erro_429(PAGINA_429), resposta_json({})])
    with pytest.raises(PncpErro) as info:
        Cliente(Adaptativo()).get("https://x", "/y", {}, tentativas=5)
    assert info.value.support_id == "14140211365997677061"
    assert "Support ID 14140211365997677061" in str(info.value)
    assert len(urlopen_fake) == 1  # 2 tentativas, não 5


def test_429_abre_bloqueio_que_vale_para_a_proxima_requisicao(urlopen_fake, monkeypatch):
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    urlopen_fake.extend([erro_429(), resposta_json({"ok": 1})])
    Cliente(Adaptativo()).get("https://x", "/y", {})
    assert any(39 <= d <= 41 for d in dormidas)


def test_erro_sem_support_id_fica_none(urlopen_fake):
    urlopen_fake.append(urllib.error.HTTPError("http://x", 400, "erro", {}, None))
    with pytest.raises(PncpErro) as info:
        Cliente(Adaptativo()).get("https://x", "/y", {})
    assert info.value.support_id is None
    assert PncpErro("x").support_id is None


# ── entre processos ────────────────────────────────────────────────────

def test_dois_clientes_do_mesmo_processo_dividem_o_ritmo(urlopen_fake, monkeypatch):
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(round(s, 1)))
    urlopen_fake.extend([resposta_json({})] * 2)
    Cliente(Adaptativo()).get("https://pncp.gov.br/api/pncp", "/a", {})
    Cliente(Adaptativo()).get("https://pncp.gov.br/api/pncp", "/a", {})
    assert dormidas == [1.1]   # o segundo Cliente esperou a vez do primeiro


def test_ritmo_entre_processos_de_verdade(tmp_path):
    """Três processos Python reais disputando o mesmo host: o menor
    intervalo entre duas requisições QUAISQUER respeita o alvo."""
    script = textwrap.dedent(f"""
        import json, sys, time
        sys.path.insert(0, {str(_src())!r})
        from motor_pncp._ritmo import Ritmo
        r = Ritmo({str(tmp_path)!r})
        marcas = []
        for _ in range(4):
            r.aguardar("host", 0.3, time.sleep)
            marcas.append(time.time())
        print(json.dumps(marcas))
    """)
    ps = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
          for _ in range(3)]
    marcas = sorted(m for p in ps for m in json.loads(p.communicate(timeout=60)[0]))
    menor = min(b - a for a, b in zip(marcas, marcas[1:]))
    assert menor >= 0.29, menor


def test_processo_que_morre_nao_deixa_trava_presa(tmp_path):
    script = textwrap.dedent(f"""
        import sys, time, os
        sys.path.insert(0, {str(_src())!r})
        from motor_pncp import _ritmo
        f = open(os.path.join({str(tmp_path)!r}, "ritmo-host.lock"), "a+b")
        assert _ritmo._tentar_travar(f)
        print("travado", flush=True)
        time.sleep(60)
    """)
    p = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "travado"
    p.kill()
    p.wait(timeout=10)
    inicio = time.monotonic()
    Ritmo(str(tmp_path)).aguardar("host", 0, time.sleep)
    assert time.monotonic() - inicio < 5


def test_pasta_inutilizavel_cai_para_o_ritmo_local(tmp_path, caplog):
    arquivo_no_lugar_da_pasta = tmp_path / "nao_e_pasta"
    arquivo_no_lugar_da_pasta.write_text("x")
    r = Ritmo(str(arquivo_no_lugar_da_pasta))
    dormidas = []
    r.aguardar("h", 2, dormidas.append)
    r.aguardar("h", 2, dormidas.append)
    assert len(dormidas) == 1                      # o ritmo segue valendo, em memória
    assert any("ritmo compartilhado indisponível" in m for m in caplog.messages)


def test_sem_ritmo_compartilhado_nao_toca_o_disco(tmp_path, monkeypatch):
    monkeypatch.setenv("MOTOR_PNCP_RITMO", str(tmp_path / "nao_deve_existir"))
    _http._ritmo_para(Config(ritmo_compartilhado=False)).aguardar("h", 0, lambda s: None)
    assert not (tmp_path / "nao_deve_existir").exists()


def _src():
    import pathlib
    return pathlib.Path(__file__).resolve().parent.parent / "src"
