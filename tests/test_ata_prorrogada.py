"""Como uma prorrogação de ata (Lei 14.133, art. 84) aparece no PNCP.

Fatos travados aqui, a partir de envelopes reais de UMA ata prorrogada:

1. Não existe "termo aditivo de ata". A prorrogação é uma RETIFICAÇÃO do
   próprio registro: `vigenciaFim` é sobrescrito no lugar.
2. O registro retificado volta em `api/consulta /v1/atas/atualizacao` com
   `dataAtualizacao` nova — quem sincroniza por atualização recebe.
3. A vigência original se perde na fonte: o histórico registra QUE houve
   retificação e QUANDO, não o valor anterior. A justificativa é texto
   livre e costuma ser genérica.
4. Os dois hosts dão nomes diferentes ao mesmo campo: `vigenciaFim` em
   api/consulta, `dataVigenciaFim` em api/pncp.
"""
import json
import pathlib
from datetime import date

from motor_pncp import Ata

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def carregar(nome):
    return json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def _dia(texto):
    return date.fromisoformat(texto[:10])


def test_prorrogacao_sobrescreve_vigencia_fim_no_registro_da_consulta():
    raw = carregar("ata_prorrogada_consulta")["data"][0]
    ata = Ata(raw)
    inicio, fim = _dia(raw["vigenciaInicio"]), _dia(ata.vigencia_fim)
    assert (fim - inicio).days > 700  # nasceu com 1 ano, hoje tem ~2
    # ...e a alteração é visível só pela distância entre publicar e atualizar
    assert (_dia(ata.data_atualizacao) - _dia(raw["dataPublicacaoPncp"])).days > 300
    assert ata.orgao_cnpj == raw["cnpjOrgao"]


def test_os_dois_hosts_concordam_mas_com_nomes_de_campo_diferentes():
    consulta = carregar("ata_prorrogada_consulta")["data"][0]
    registro = carregar("ata_prorrogada_registro")
    assert "dataVigenciaFim" in registro and "vigenciaFim" not in registro
    assert "vigenciaFim" in consulta and "dataVigenciaFim" not in consulta
    assert registro["dataVigenciaFim"][:10] == consulta["vigenciaFim"][:10]
    assert registro["numeroControlePNCP"] == consulta["numeroControlePNCPAta"]


def test_historico_registra_a_retificacao_mas_nao_o_valor_anterior():
    eventos = carregar("ata_prorrogada_historico")
    tipos = [(e["tipoLogManutencaoNome"], e["categoriaLogManutencaoNome"]) for e in eventos]
    assert ("Inclusão", "Ata") in tipos
    assert ("Retificação", "Ata") in tipos
    retificacao = next(e for e in eventos if e["tipoLogManutencaoNome"] == "Retificação")
    inclusao = next(e for e in eventos if (e["tipoLogManutencaoNome"],
                                           e["categoriaLogManutencaoNome"]) == ("Inclusão", "Ata"))
    assert retificacao["logManutencaoDataInclusao"] > inclusao["logManutencaoDataInclusao"]
    # nenhum campo guarda a vigência de antes: só o texto livre da justificativa
    assert not any("vigencia" in chave.lower() for chave in retificacao)
    assert isinstance(retificacao["justificativa"], str)
    # o Swagger declara estes dois como string; o portal manda inteiro
    assert isinstance(retificacao["tipoLogManutencao"], int)


# ── 1.5.0: o tipo Ata expõe o que o radar de vencimento precisa ──────────

def test_ata_expoe_inicio_publicacao_e_cancelamento():
    raw = carregar("ata_prorrogada_consulta")["data"][0]
    ata = Ata(raw)
    assert ata.vigencia_inicio == raw["vigenciaInicio"] == "2025-09-12"
    assert ata.data_publicacao == raw["dataPublicacaoPncp"]
    assert ata.cancelado is False
    assert ata.data_cancelamento is None
    # dá pra calcular a duração sem ir ao .raw
    assert (_dia(ata.vigencia_fim) - _dia(ata.vigencia_inicio)).days > 700


def test_ata_le_a_vigencia_nas_duas_grafias_do_portal():
    """api/consulta manda `vigenciaFim`; o registro individual em api/pncp
    manda `dataVigenciaFim`. O mesmo tipo lê os dois."""
    da_consulta = Ata(carregar("ata_prorrogada_consulta")["data"][0])
    do_registro = Ata(carregar("ata_prorrogada_registro"))
    assert do_registro.vigencia_inicio is not None
    assert do_registro.vigencia_fim is not None
    assert do_registro.vigencia_inicio[:10] == da_consulta.vigencia_inicio[:10]
    assert do_registro.vigencia_fim[:10] == da_consulta.vigencia_fim[:10]


def test_ata_cancelada_e_lida_como_booleano():
    ata = Ata({"cancelado": True, "dataCancelamento": "2026-01-10T00:00:00"})
    assert ata.cancelado is True and ata.data_cancelamento.startswith("2026-01-10")
    assert Ata({}).cancelado is False  # campo ausente não vira None
