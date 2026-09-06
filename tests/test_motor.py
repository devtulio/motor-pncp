import time
from datetime import date

import pytest

from motor_pncp._http import Cliente
from motor_pncp.configuracao import Config
from motor_pncp.dominio import MODALIDADES
from motor_pncp.excecoes import ItensIndisponiveis, PncpErro
from motor_pncp.motor import Motor
from motor_pncp.tipos import Contratacao, Item

# ── contratacoes() ─────────────────────────────────────────────────────

def test_contratacoes_gera_um_registro_tipado_por_consulta_bem_sucedida(monkeypatch):
    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        for nome, params in consultas:
            yield nome, [{"nome": nome}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    itens = list(Motor().contratacoes(123, date(2024, 1, 1), date(2024, 1, 1)))
    assert len(itens) == len(MODALIDADES)  # 1 janela x 13 modalidades
    assert all(isinstance(item, Contratacao) for item in itens)
    assert {item.raw["nome"] for item in itens} == set(MODALIDADES.values())


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
    assert [c.raw["nome"] for c in coletados] == ["Leilão eletrônico"]


def test_contratacoes_usa_config_customizado_no_disjuntor(monkeypatch):
    relogio = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        for nome, params in consultas:
            relogio[0] += 1  # bem menos que o sem_sucesso_limite default
            yield nome, [], PncpErro("morto")

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    cfg = Config(falhas_consecutivas_limite=2, sem_sucesso_limite=1)
    with pytest.raises(PncpErro, match="parado após 2 falhas"):
        list(Motor(config=cfg).contratacoes(123, date(2024, 1, 1), date(2024, 1, 1)))


# ── contratos / atas / pca (fase por CNPJ) ──────────────────────────────

def test_contratos_gera_registros_tipados(monkeypatch):
    from motor_pncp.tipos import Contrato

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        assert caminho == "/v1/contratos/atualizacao"
        for rotulo, params in consultas:
            assert params["cnpjOrgao"] == "123"
            yield rotulo, [{"id": rotulo}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    resultado = list(Motor().contratos("123", date(2024, 1, 1), date(2024, 1, 1)))
    assert len(resultado) == 1
    assert isinstance(resultado[0], Contrato)


def test_atas_gera_registros_tipados(monkeypatch):
    from motor_pncp.tipos import Ata

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        assert caminho == "/v1/atas/atualizacao"
        for rotulo, params in consultas:
            assert params["cnpj"] == "123"
            yield rotulo, [{"id": rotulo}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    resultado = list(Motor().atas("123", date(2024, 1, 1), date(2024, 1, 1)))
    assert len(resultado) == 1
    assert isinstance(resultado[0], Ata)


def test_pca_usa_chaves_de_data_proprias_e_respeita_data_minima(monkeypatch):
    from motor_pncp.dominio import DATA_INICIO_PCA
    from motor_pncp.tipos import PlanoPca

    vistos = []

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        assert caminho == "/v1/pca/atualizacao"
        for rotulo, params in consultas:
            vistos.append(params)
            assert "dataInicio" in params and "dataFim" in params
            yield rotulo, [{"itens": [{"numeroItem": 1}]}], None

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    resultado = list(Motor().pca("123", date(2020, 1, 1), DATA_INICIO_PCA))
    assert len(resultado) == 1
    assert isinstance(resultado[0], PlanoPca)
    assert resultado[0].itens == [{"numeroItem": 1}]
    # data pedida era anterior ao mínimo do endpoint — foi ajustada pra ele
    assert vistos[0]["dataInicio"] == DATA_INICIO_PCA.strftime("%Y%m%d")


def test_pca_nao_consulta_nada_se_janela_inteira_e_anterior_ao_minimo(monkeypatch):
    from datetime import timedelta

    from motor_pncp.dominio import DATA_INICIO_PCA

    def baixar_fake(self, url_base, caminho, consultas, tamanho_pagina):
        raise AssertionError("não deveria consultar nada")

    monkeypatch.setattr(Cliente, "baixar", baixar_fake)
    fim = DATA_INICIO_PCA - timedelta(days=1)
    resultado = list(Motor().pca("123", date(2019, 1, 1), fim))
    assert resultado == []


# ── itens_da_compra() ────────────────────────────────────────────────────

def test_itens_da_compra_pagina_vazia_apos_pagina_cheia_vira_pncperro(monkeypatch):
    """Mesmo achado do sistema irmão (2026-08-29) aplicado ao paginador
    de itens, que não usa o envelope totalPaginas — o único sinal de
    página cheia é vir com exatamente 100 registros."""
    pagina_cheia = [{"numeroItem": i} for i in range(100)]
    respostas = iter([pagina_cheia, []])
    monkeypatch.setattr(
        Cliente, "get",
        lambda self, *a, **k: next(respostas))
    with pytest.raises(PncpErro, match="página 2 veio vazia"):
        list(Motor().itens_da_compra("1", 2024, 1))


def test_itens_da_compra_pagina_1_vazia_e_legitima(monkeypatch):
    monkeypatch.setattr(Cliente, "get", lambda self, *a, **k: [])
    assert list(Motor().itens_da_compra("1", 2024, 1)) == []


# ── contar_contratacoes() ────────────────────────────────────────────────

def test_contar_contratacoes_404_persistente_marca_parcial(monkeypatch):
    """`modo_404="retry"` faltava aqui — um 404 transitório do portal
    virava 0 silencioso, sem marcar `parcial`, violando o próprio
    contrato da função."""
    monkeypatch.setattr(
        Cliente, "get",
        lambda self, *a, **k: (_ for _ in ()).throw(PncpErro("HTTP 404")))
    resultado = Motor().contar_contratacoes(123, date(2024, 1, 1), date(2024, 1, 1))
    assert resultado["parcial"] is True
    assert resultado["total"] == 0


# ── ipca() ───────────────────────────────────────────────────────────────

def test_ipca_usa_o_cliente_e_gera_competencias(monkeypatch):
    monkeypatch.setattr(
        Cliente, "get",
        lambda self, *a, **k: [{"data": "01/01/2026", "valor": "0.5"}])
    resultado = list(Motor().ipca())
    assert resultado == [{"competencia": "2026-01", "variacao": 0.5}]


def test_ipca_none_nao_quebra(monkeypatch):
    monkeypatch.setattr(Cliente, "get", lambda self, *a, **k: None)
    assert list(Motor().ipca()) == []


def test_ipca_propaga_pncperro_do_cliente(monkeypatch):
    def get_fake(self, *a, **k):
        raise PncpErro("BCB fora do ar")

    monkeypatch.setattr(Cliente, "get", get_fake)
    with pytest.raises(PncpErro, match="BCB fora do ar"):
        list(Motor().ipca())


# ── itens_e_resultados() ─────────────────────────────────────────────────

def test_itens_e_resultados_busca_resultado_so_dos_itens_com_resultado(monkeypatch):
    contratacao = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    itens = [Item({"numeroItem": 1, "temResultado": True}),
            Item({"numeroItem": 2, "temResultado": False})]
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
    assert pares == [(itens[0], {"vencedor": "x"}), (itens[1], None)]


def test_itens_e_resultados_respeita_filtro_pendente(monkeypatch):
    contratacao = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    itens = [Item({"numeroItem": 1, "temResultado": True}),
            Item({"numeroItem": 2, "temResultado": True})]
    monkeypatch.setattr(Motor, "itens_da_compra",
                        lambda self, cnpj, ano, seq: iter(itens))
    chamados = []
    monkeypatch.setattr(Motor, "resultado_do_item",
                        lambda self, cnpj, ano, seq, n, pacing=True:
                        chamados.append(n) or {"vencedor": "x"})

    def pendente(c, item):
        return item.numero_item == 1

    m = Motor()
    [(c, pares)] = list(m.itens_e_resultados([contratacao], pendente=pendente))
    assert chamados == [1]
    assert [item.numero_item for item, _ in pares] == [1]


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
    resultado = list(m.itens_e_resultados(
        [ruim, boa], on_erro=lambda c, e: erros.append(c["id"])))
    assert [c["id"] for c, _ in resultado] == ["boa"]
    assert erros == ["ruim"]


# ── termos_aditivos() ────────────────────────────────────────────────────

def test_termos_aditivos_pula_chamada_cara_quando_quantidade_e_zero(monkeypatch):
    contrato = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    monkeypatch.setattr(Motor, "_quantidade_termos", lambda self, *a: 0)

    def termos_fake(self, *a):
        raise AssertionError("não deveria buscar termos sem quantidade")

    monkeypatch.setattr(Motor, "_termos_do_contrato", termos_fake)
    [(c, termos)] = list(Motor().termos_aditivos([contrato]))
    assert termos == []


def test_termos_aditivos_busca_quando_ha_quantidade(monkeypatch):
    from motor_pncp.tipos import TermoAditivo

    contrato = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1}
    monkeypatch.setattr(Motor, "_quantidade_termos", lambda self, *a: 2)
    monkeypatch.setattr(Motor, "_termos_do_contrato",
                        lambda self, *a: [{"sequencialTermoContrato": 1},
                                          {"sequencialTermoContrato": 2}])
    [(c, termos)] = list(Motor().termos_aditivos([contrato]))
    assert len(termos) == 2
    assert all(isinstance(t, TermoAditivo) for t in termos)


def test_termos_aditivos_continua_apos_falha_de_um_contrato(monkeypatch):
    boa = {"orgao_cnpj": "1", "ano": 2024, "sequencial": 1, "id": "boa"}
    ruim = {"orgao_cnpj": "2", "ano": 2024, "sequencial": 2, "id": "ruim"}

    def quantidade_fake(self, cnpj, ano, seq):
        if cnpj == "2":
            raise ItensIndisponiveis("404")
        return 0

    monkeypatch.setattr(Motor, "_quantidade_termos", quantidade_fake)
    erros = []
    resultado = list(Motor().termos_aditivos(
        [ruim, boa], on_erro=lambda c, e: erros.append(c["id"])))
    assert [c["id"] for c, _ in resultado] == ["boa"]
    assert erros == ["ruim"]
