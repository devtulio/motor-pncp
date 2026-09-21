"""`on_item`: progresso por item dentro de uma contratação.

O registro de uma contratação só é gerado depois de TODOS os resultados
dela. Numa compra com centenas de itens e o portal lento são dezenas de
minutos sem sinal nenhum — `on_item` é o que mostra que a coleta anda.
"""
import threading

import pytest

from motor_pncp._http import Cliente
from motor_pncp.excecoes import PncpErro, SyncCancelado
from motor_pncp.motor import Motor

C = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}


def portal_falso(monkeypatch, itens, falha_no_item=None):
    """Listagem devolve `itens`; resultado de cada item devolve um
    vencedor — ou falha, se for o `falha_no_item`."""
    def get(self, url_base, caminho, params, **kw):
        if caminho.endswith("/itens"):
            return itens if params.get("pagina") == 1 else []
        numero = int(caminho.split("/itens/")[1].split("/")[0])
        if numero == falha_no_item:
            raise PncpErro("HTTP 500")
        return [{"niFornecedor": "123", "numeroItem": numero}]

    monkeypatch.setattr(Cliente, "get", get)


def itens(n, com_resultado=True):
    return [{"numeroItem": i, "temResultado": com_resultado} for i in range(1, n + 1)]


def test_on_item_avisa_zero_e_depois_cada_resultado(monkeypatch):
    portal_falso(monkeypatch, itens(5))
    visto = []
    list(Motor().itens_e_resultados([C], on_item=lambda c, f, t: visto.append((c, f, t))))
    assert [(f, t) for _, f, t in visto] == [(0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    assert all(c is C for c, _, _ in visto)  # a contratação volta intacta


def test_total_conta_so_o_que_passou_pelo_pendente_e_tem_resultado(monkeypatch):
    lista = itens(6)
    lista[5]["temResultado"] = False  # item 6 não tem resultado a buscar
    portal_falso(monkeypatch, lista)
    visto = []
    list(Motor().itens_e_resultados(
        [C], pendente=lambda c, item: item.numero_item % 2 == 0,  # só 2, 4 e 6
        on_item=lambda c, f, t: visto.append((f, t))))
    assert visto == [(0, 2), (1, 2), (2, 2)]  # 2 e 4; o 6 passou mas não tem resultado


def test_contratacao_sem_resultado_avisa_zero_de_zero(monkeypatch):
    portal_falso(monkeypatch, itens(3, com_resultado=False))
    visto = []
    list(Motor().itens_e_resultados([C], on_item=lambda c, f, t: visto.append((f, t))))
    assert visto == [(0, 0)]


def test_excecao_no_on_item_nao_derruba_a_coleta(monkeypatch):
    portal_falso(monkeypatch, itens(3))

    def quebrado(c, feitos, total):
        raise RuntimeError("banco do consumidor caiu")

    saida = list(Motor().itens_e_resultados([C, dict(C, sequencial=2)], on_item=quebrado))
    assert len(saida) == 2
    assert all(len(pares) == 3 and all(r is not None for _, r in pares) for _, pares in saida)


def test_sync_cancelado_no_on_item_para_a_coleta(monkeypatch):
    portal_falso(monkeypatch, itens(4))
    chamadas = []

    def parar(c, feitos, total):
        chamadas.append(feitos)
        if feitos == 2:
            raise SyncCancelado()

    with pytest.raises(SyncCancelado):
        list(Motor().itens_e_resultados([C, dict(C, sequencial=2)], on_item=parar))
    assert chamadas == [0, 1, 2]  # parou na hora; a 2ª contratação nem começou


def test_on_item_roda_na_thread_de_quem_itera(monkeypatch):
    """É o que deixa o consumidor gravar no banco de dentro do callback
    sem se preocupar com conexão por thread."""
    portal_falso(monkeypatch, itens(8))
    threads = set()
    list(Motor().itens_e_resultados(
        [C], on_item=lambda c, f, t: threads.add(threading.get_ident())))
    assert threads == {threading.get_ident()}


def test_falha_num_resultado_vai_pro_on_erro_e_feitos_nao_chega_ao_total(monkeypatch):
    portal_falso(monkeypatch, itens(3), falha_no_item=2)
    visto, erros = [], []
    saida = list(Motor().itens_e_resultados(
        [C], on_item=lambda c, f, t: visto.append((f, t)),
        on_erro=lambda c, e: erros.append(str(e))))
    assert saida == [] and len(erros) == 1
    assert visto[0] == (0, 3) and visto[-1][0] < 3


def test_sem_on_item_a_saida_e_a_mesma(monkeypatch):
    """Regressão: o parâmetro é só leitura; com ou sem ele, mesmos dados."""
    portal_falso(monkeypatch, itens(4))
    sem = list(Motor().itens_e_resultados([C]))
    com = list(Motor().itens_e_resultados([C], on_item=lambda c, f, t: None))
    assert sem == com
    assert [i.numero_item for i, _ in sem[0][1]] == [1, 2, 3, 4]
    assert all(r.fornecedor_ni == "123" for _, r in sem[0][1])
