"""O diagnóstico ao vivo é um orquestrador fino em cima da API pública —
o que vale testar é a classificação (ok/FALHA por host, código de
saída), não as fases, que já têm teste próprio."""
import pytest

from motor_pncp import __main__ as cli
from motor_pncp.excecoes import PncpErro
from motor_pncp.tipos import Contratacao, Item

CONTRATACAO = Contratacao({
    "numeroControlePNCP": "1-1-1/2026", "anoCompra": 2026, "sequencialCompra": 1,
    "orgaoEntidade": {"cnpj": "1", "razaoSocial": "X"}, "objetoCompra": "obj"})


class MotorFake:
    """Portal saudável em api/consulta e BCB; api/pncp configurável."""

    def __init__(self, *, progresso=None, pncp_fora=False):
        self.pncp_fora = pncp_fora

    def sonda(self):
        return 0.01

    def contar_contratacoes(self, ibge, inicio, fim):
        return {"total": 1, "parcial": False}

    def contratacoes(self, ibge, inicio, fim):
        yield CONTRATACAO

    def contratos(self, cnpj, inicio, fim):
        return iter([])

    atas = pca = contratos

    def consultar_orgao(self, cnpj):
        if self.pncp_fora:
            raise PncpErro("HTTP 503")
        return None

    def itens_e_resultados(self, alvo, *, on_erro=None):
        for c in alvo:
            if self.pncp_fora:
                on_erro(c, PncpErro("HTTP 503"))
                continue
            yield c, [(Item({"numeroItem": 1}), None)]

    def ipca(self, inicio=None):
        yield {"competencia": "2026-08", "variacao": 0.1}


@pytest.mark.parametrize("pncp_fora, esperado", [(False, 0), (True, 1)])
def test_codigo_de_saida_reflete_falha_por_host(monkeypatch, capsys, pncp_fora, esperado):
    monkeypatch.setattr(cli, "Motor",
                        lambda **kw: MotorFake(pncp_fora=pncp_fora, **kw))
    assert cli.main(["3553401", "--dias", "30", "--silencioso"]) == esperado
    saida = capsys.readouterr().out
    assert "api/consulta: 6/6 ok" in saida
    assert ("api/pncp: 0/2 ok" in saida) is pncp_fora
    assert ("0 de 1 concluída" in saida) is pncp_fora


def test_help_nao_quebra():
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
