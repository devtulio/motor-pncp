"""1.6.0: properties de leitura para campos que o portal já mandava e só
estavam no `.raw` — plataforma, fonte orçamentária, modo de disputa,
situação, benefício ME/EPP, critério de julgamento, porte e natureza
jurídica. Lidos contra envelopes REAIS em `tests/fixtures/`."""
import json
import pathlib

from motor_pncp import Contratacao, Item, Resultado

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def carregar(nome):
    return json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


# ── Contratacao ─────────────────────────────────────────────────────────

def test_contratacao_plataforma_link_e_modo_de_disputa():
    for raw in carregar("contratacoes")["data"]:
        c = Contratacao(raw)
        assert c.plataforma == raw["usuarioNome"] and c.plataforma
        assert c.modo_disputa == raw["modoDisputaNome"] and c.modo_disputa
        assert c.link_sistema_origem == (raw.get("linkSistemaOrigem") or None)


def test_fontes_orcamentarias_vira_lista_de_nomes():
    nomes = [Contratacao(r).fontes_orcamentarias for r in carregar("contratacoes")["data"]]
    assert [] in nomes                      # o envelope real tem compra sem fonte informada
    assert any(n == ["Municipal"] for n in nomes)
    assert all(isinstance(n, list) for n in nomes)


def test_fontes_orcamentarias_tolera_lixo_e_ausencia():
    assert Contratacao({}).fontes_orcamentarias == []
    assert Contratacao({"fontesOrcamentarias": None}).fontes_orcamentarias == []
    duas = Contratacao({"fontesOrcamentarias": [
        {"codigo": 2, "nome": "Municipal"}, {"codigo": 4, "nome": "Federal"}, {"codigo": 9}, "x"]})
    assert duas.fontes_orcamentarias == ["Municipal", "Federal"]


def test_link_vazio_vira_none():
    assert Contratacao({"linkSistemaOrigem": ""}).link_sistema_origem is None


# ── Item ────────────────────────────────────────────────────────────────

def test_item_situacao_beneficio_e_criterio():
    for raw in carregar("itens"):
        i = Item(raw)
        assert i.situacao == raw["situacaoCompraItemNome"] and i.situacao
        assert i.tipo_beneficio == raw["tipoBeneficioNome"] and i.tipo_beneficio
        assert i.criterio_julgamento == raw["criterioJulgamentoNome"] and i.criterio_julgamento


# ── Resultado ───────────────────────────────────────────────────────────

def test_resultado_porte_natureza_situacao_e_beneficio():
    for raw in carregar("resultados"):
        r = Resultado(raw)
        assert r.porte_fornecedor == raw["porteFornecedorNome"] and r.porte_fornecedor
        assert r.natureza_juridica == raw["naturezaJuridicaNome"] and r.natureza_juridica
        assert r.situacao == raw["situacaoCompraItemResultadoNome"] and r.situacao
        assert r.beneficio_me_epp is bool(raw["aplicacaoBeneficioMeEpp"])
        # o código da natureza jurídica vem como TEXTO no portal
        assert isinstance(raw["naturezaJuridicaId"], str)


def test_beneficio_me_epp_ausente_e_false_nao_none():
    assert Resultado({}).beneficio_me_epp is False
    assert Resultado({"aplicacaoBeneficioMeEpp": True}).beneficio_me_epp is True
