import time
from datetime import date

import pytest

from motor_pncp._http import Cliente
from motor_pncp.dominio import MODALIDADES
from motor_pncp.excecoes import ItensIndisponiveis, PncpErro
from motor_pncp.motor import Motor

# ── contratacoes() ─────────────────────────────────────────────────────

def test_contratacoes_gera_um_item_por_consulta_bem_sucedida(monkeypatch):
    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        for nome, params in consultas:
            yield nome, [{"nome": nome}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    itens = list(Motor().contratacoes(123, date(2024, 1, 1), date(2024, 1, 1)))
    assert len(itens) == len(MODALIDADES)  # 1 janela x 13 modalidades


def test_contratacoes_levanta_erro_se_alguma_consulta_falhar(monkeypatch):
    """Mesmo sem o disjuntor disparar, uma janela que falhou não pode
    passar batido — quem persiste precisa saber pra não avançar a marca
    d'água sobre um buraco no acervo."""
    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        primeira = True
        for nome, params in consultas:
            if primeira:
                primeira = False
                yield nome, [], PncpErro("falhou uma vez")
            else:
                yield nome, [{"nome": nome}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    with pytest.raises(PncpErro):
        list(Motor().contratacoes(123, date(2024, 1, 1), date(2024, 1, 1)))


def test_contratacoes_disjuntor_para_cedo_e_preserva_o_ja_coletado(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        for i, (nome, params) in enumerate(consultas):
            if i == 0:
                yield nome, [{"nome": nome}], None  # 1 sucesso primeiro
                continue
            relogio[0] += 200  # cada falha "custa" tempo até o disjuntor bater
            yield nome, [], PncpErro("morto")

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    coletados = []
    with pytest.raises(PncpErro, match="parado após"):
        for item in Motor().contratacoes(123, date(2024, 1, 1), date(2024, 1, 1)):
            coletados.append(item)
    assert coletados == [{"nome": "Leilão eletrônico"}]  # o único sucesso


# ── itens_e_resultados() ─────────────────────────────────────────────────

def test_itens_e_resultados_busca_resultado_so_dos_itens_com_resultado(monkeypatch):
    contratacao = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    itens = [{"numeroItem": 1, "temResultado": True},
            {"numeroItem": 2, "temResultado": False}]
    monkeypatch.setattr(Motor, "itens_da_compra",
                        lambda self, cnpj, ano, seq: iter(itens))
    chamados = []

    def resultado_fake(self, cnpj, ano, seq, numero_item, pacing=True):
        chamados.append(numero_item)
        return {"vencedor": "x"}

    monkeypatch.setattr(Motor, "resultado_do_item", resultado_fake)
    m = Motor()
    [(c, pares)] = list(m.itens_e_resultados([contratacao]))
    assert chamados == [1]
    assert pares == [({"numeroItem": 1, "temResultado": True}, {"vencedor": "x"}),
                     ({"numeroItem": 2, "temResultado": False}, None)]


def test_itens_e_resultados_respeita_filtro_pendente(monkeypatch):
    contratacao = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    itens = [{"numeroItem": 1, "temResultado": True},
            {"numeroItem": 2, "temResultado": True}]
    monkeypatch.setattr(Motor, "itens_da_compra",
                        lambda self, cnpj, ano, seq: iter(itens))
    chamados = []
    monkeypatch.setattr(Motor, "resultado_do_item",
                        lambda self, cnpj, ano, seq, n, pacing=True:
                        chamados.append(n) or {"vencedor": "x"})
    def pendente(c, item):
        return item["numeroItem"] == 1

    m = Motor()
    [(c, pares)] = list(m.itens_e_resultados([contratacao], pendente=pendente))
    assert chamados == [1]
    assert [item["numeroItem"] for item, _ in pares] == [1]


def test_itens_e_resultados_continua_apos_404_de_uma_contratacao(monkeypatch):
    boa = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1, "id": "boa"}
    ruim = {"orgao_cnpj": "2", "ano": 2024, "sequencial": 2, "id": "ruim"}

    def itens_da_compra_fake(self, cnpj, ano, seq):
        if cnpj == "2":
            raise ItensIndisponiveis("404")
        return iter([])

    monkeypatch.setattr(Motor, "itens_da_compra", itens_da_compra_fake)
    erros = []
    m = Motor()
    resultado = list(m.itens_e_resultados([ruim, boa], on_erro=lambda c, e: erros.append(c["id"])))
    assert [c["id"] for c, _ in resultado] == ["boa"]
    assert erros == ["ruim"]
