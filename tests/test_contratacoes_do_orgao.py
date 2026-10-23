"""1.7.0: contratações de UM órgão (por CNPJ), pela rota de publicação.

A rota de atualização declara o filtro `cnpj`, mas com ele responde 500 ou
não responde; a de publicação responde e devolve só o órgão pedido. Estes
testes travam a escolha da rota e o filtro, sobre um envelope real.
"""
import json
import pathlib
import urllib.parse
import urllib.request
from datetime import date

import pytest
from conftest import RespostaFalsa

from motor_pncp import Contratacao, Motor, PncpErro
from motor_pncp.dominio import MODALIDADES

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures" / "contratacoes_do_orgao.json")
                     .read_text(encoding="utf-8"))
CNPJ = FIXTURE["data"][0]["orgaoEntidade"]["cnpj"]
UM_DIA = (date(2025, 6, 1), date(2025, 6, 1))


def portal(monkeypatch, *, so_pregao=True, falha_modalidade=None):
    """Responde a página real para a modalidade 6 (pregão eletrônico) e
    vazio para as outras; registra cada URL pedida."""
    pedidas = []

    def urlopen(req, timeout=None):
        url = req.full_url
        pedidas.append(url)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        mod = int(q["codigoModalidadeContratacao"][0])
        if mod == falha_modalidade:
            raise urllib.error.HTTPError(url, 500, "erro", {}, None)
        if mod == 6 or not so_pregao:
            env = {**FIXTURE, "paginasRestantes": 0, "totalPaginas": 1}
            return RespostaFalsa(200, json.dumps(env).encode("utf-8"))
        return RespostaFalsa(204, b"")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return pedidas


def test_usa_a_rota_de_publicacao_com_filtro_cnpj_e_sem_municipio(monkeypatch):
    pedidas = portal(monkeypatch)
    registros = list(Motor().contratacoes_do_orgao(CNPJ, *UM_DIA))
    assert len(pedidas) == len(MODALIDADES)          # 13 modalidades × 1 janela
    for url in pedidas:
        partes = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(partes.query)
        assert partes.path.endswith("/v1/contratacoes/publicacao")
        assert q["cnpj"] == [CNPJ]
        assert "codigoMunicipioIbge" not in q
    assert len(registros) == len(FIXTURE["data"])
    assert all(isinstance(r, Contratacao) and r.orgao_cnpj == CNPJ for r in registros)


def test_falha_numa_modalidade_vira_pncperro_com_consultas_falhas(monkeypatch):
    portal(monkeypatch, falha_modalidade=8)
    motor = Motor()
    with pytest.raises(PncpErro) as info:
        list(motor.contratacoes_do_orgao(CNPJ, *UM_DIA))
    assert [r for r, _ in info.value.consultas_falhas] == [MODALIDADES[8]]
    _, params = info.value.consultas_falhas[0]
    assert params["cnpj"] == CNPJ
    # refazer volta pela MESMA rota de publicação
    pedidas = portal(monkeypatch)
    list(motor.refazer(info.value))
    assert pedidas and all("/v1/contratacoes/publicacao" in u for u in pedidas)


def test_contar_do_orgao_soma_o_envelope_pela_rota_de_publicacao(monkeypatch):
    pedidas = portal(monkeypatch)
    contagem = Motor().contar_contratacoes_do_orgao(CNPJ, *UM_DIA)
    assert contagem == {"total": FIXTURE["totalRegistros"], "parcial": False}
    assert all("/v1/contratacoes/publicacao" in u and f"cnpj={CNPJ}" in u for u in pedidas)


def test_contar_do_orgao_marca_parcial_quando_uma_consulta_falha(monkeypatch):
    portal(monkeypatch, falha_modalidade=6)
    contagem = Motor().contar_contratacoes_do_orgao(CNPJ, *UM_DIA)
    assert contagem["parcial"] is True and contagem["total"] == 0


def test_contar_contratacoes_do_municipio_segue_na_rota_de_atualizacao(monkeypatch):
    """Regressão: a extração do contador comum não pode mudar a rota da
    contagem por município."""
    pedidas = portal(monkeypatch)
    Motor().contar_contratacoes(3549805, *UM_DIA)
    assert all("/v1/contratacoes/atualizacao" in u and "codigoMunicipioIbge=3549805" in u
               for u in pedidas)
