"""Envelopes REAIS gravados do portal (dado público), um por endpoint.

Os outros testes usam dicts inventados — provam o motor, não o PNCP. Estes
provam que o que o portal manda hoje ainda casa com o que os tipos e o
paginador esperam: campo renomeado ou envelope mudado quebra aqui, no CI,
antes de quebrar numa coleta. Regravar quando a API mudar de propósito
(script no histórico do repo: `Cliente.get` em cada endpoint com
`tamanhoPagina` pequeno, `json.dump` em `tests/fixtures/<nome>.json`).
"""
import json
import pathlib

import pytest
from conftest import resposta_json

from motor_pncp import (
    Ata,
    Contratacao,
    Contrato,
    Item,
    Orgao,
    PlanoPca,
    Resultado,
    TermoAditivo,
)
from motor_pncp._http import Cliente
from motor_pncp._resiliencia import Adaptativo

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def carregar(nome):
    caminho = FIXTURES / f"{nome}.json"
    if not caminho.exists():
        pytest.skip(f"fixture {nome} não gravada (endpoint sem dado na captura)")
    return json.loads(caminho.read_text(encoding="utf-8"))


def _todas_as_properties(obj):
    """Lê cada @property do tipo — um KeyError/AttributeError aqui é o
    schema do portal tendo mudado por baixo do envelope."""
    lidas = {}
    for nome, attr in type(obj).__dict__.items():
        if isinstance(attr, property):
            lidas[nome] = getattr(obj, nome)
    return lidas


def test_envelope_de_listagem_tem_os_campos_que_o_paginador_usa():
    env = carregar("contratacoes")
    assert "data" in env
    assert "paginasRestantes" in env or "totalPaginas" in env
    assert "totalRegistros" in env  # contar_contratacoes lê daqui


def test_paginar_termina_com_o_envelope_real(urlopen_fake):
    env = carregar("contratacoes")
    urlopen_fake.append(resposta_json({**env, "paginasRestantes": 0, "totalPaginas": 1}))
    registros = list(Cliente(Adaptativo()).paginar("https://x", "/y", {}, 3))
    assert registros == env["data"]


@pytest.mark.parametrize("nome,tipo,chaves_obrigatorias", [
    ("contratacoes", Contratacao, ("numero_controle", "ano", "sequencial", "orgao_cnpj")),
    ("contratos", Contrato, ("numero_controle", "ano", "sequencial", "orgao_cnpj")),
    ("atas", Ata, ("numero_controle", "orgao_cnpj")),
    ("pca", PlanoPca, ("id_pca", "ano", "orgao_cnpj")),
])
def test_tipos_de_listagem_leem_o_registro_real(nome, tipo, chaves_obrigatorias):
    env = carregar(nome)
    if not env.get("data"):
        pytest.skip(f"{nome}: captura sem registros")
    registro = tipo(env["data"][0])
    lidas = _todas_as_properties(registro)
    for chave in chaves_obrigatorias:
        assert lidas[chave] is not None, (nome, chave)


def test_orgao_real():
    lidas = _todas_as_properties(Orgao(carregar("orgao")))
    assert lidas["cnpj"] and lidas["razao_social"]
    assert lidas["esfera"] in ("M", "E", "F", "N", "D")


def test_item_real():
    itens = carregar("itens")
    assert isinstance(itens, list) and itens  # array puro, sem envelope
    lidas = _todas_as_properties(Item(itens[0]))
    assert lidas["numero_item"] is not None
    assert lidas["descricao"]


def test_resultado_real():
    resultados = carregar("resultados")
    assert isinstance(resultados, list) and resultados
    lidas = _todas_as_properties(Resultado(resultados[0]))
    assert lidas["fornecedor_ni"]
    assert lidas["valor_unitario_homologado"] is not None


def test_termo_aditivo_real():
    termos = carregar("termos")
    assert isinstance(termos, list) and termos
    lidas = _todas_as_properties(TermoAditivo(termos[0]))
    assert lidas["sequencial"] is not None
    assert lidas["tipo"]
    quantidade = carregar("termos_quantidade")
    n = quantidade.get("quantidade") if isinstance(quantidade, dict) else quantidade
    assert n >= 1
