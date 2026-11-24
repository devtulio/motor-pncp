"""1.9.0: `data_atualizacao_global`, lida contra envelopes REAIS em
`tests/fixtures/`. A global muda também com itens, resultados e
documentos; a `data_atualizacao` é só a do próprio registro."""
import json
import pathlib

from motor_pncp import Ata, Contratacao, Contrato, PlanoPca

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def carregar(nome):
    return json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def test_contratacao_global():
    for raw in carregar("contratacoes")["data"]:
        c = Contratacao(raw)
        assert c.data_atualizacao_global == raw["dataAtualizacaoGlobal"]
        assert c.data_atualizacao_global


def test_contrato_global():
    for raw in carregar("contratos")["data"]:
        assert Contrato(raw).data_atualizacao_global == raw["dataAtualizacaoGlobal"]


def test_ata_global_nos_dois_formatos():
    # consulta manda só a data; o registro individual manda data e hora
    assert Ata(carregar("atas")["data"][0]).data_atualizacao_global == "2026-07-07"
    assert (Ata(carregar("ata_prorrogada_registro")).data_atualizacao_global
            == "2026-09-14T09:43:47")


def test_pca_global_vem_de_outro_nome():
    planos = [PlanoPca(r) for r in carregar("pca")["data"]]
    assert any(p.data_atualizacao_global == "2026-08-18T18:50:20" for p in planos)


def test_global_ausente_vira_none():
    for tipo in (Contratacao, Contrato, Ata, PlanoPca):
        assert tipo({}).data_atualizacao_global is None
