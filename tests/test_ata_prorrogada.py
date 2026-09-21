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
