from motor_pncp.tipos import Contratacao, Orgao


def test_orgao_esfera_le_o_campo_real_da_api():
    """esferaId (M/E/F/N) é o campo de verdade — poderId nunca apareceu em
    nenhum consumidor; não inventar chave sem uso real."""
    assert Orgao({"esferaId": "M"}).esfera == "M"
    assert Orgao({}).esfera is None


def test_contratacao_acessores_de_conveniencia_nao_tocam_o_raw():
    raw = {"numeroControlePNCP": "123", "anoCompra": 2026,
          "orgaoEntidade": {"cnpj": "1", "razaoSocial": "Prefeitura"},
          "valorTotalEstimado": "1000.5"}
    c = Contratacao(raw)
    assert c.numero_controle == "123"
    assert c.orgao_cnpj == "1"
    assert c.orgao_nome == "Prefeitura"
    assert c.valor_estimado == 1000.5
    assert c.raw is raw
