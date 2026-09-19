"""Repescagem: o lote repete sozinho, uma vez, as consultas que falharam —
e, se ainda assim sobrar falha, o erro diz QUAIS, pra `Motor.refazer`
repetir só elas em vez da janela inteira."""
from datetime import date

import pytest

from motor_pncp._http import Cliente
from motor_pncp.configuracao import Config
from motor_pncp.dominio import MODALIDADES
from motor_pncp.excecoes import PncpErro
from motor_pncp.motor import Motor
from motor_pncp.tipos import Contratacao, Contrato

DIA = date(2024, 1, 1)


def baixar_que_falha(falhas_por_modalidade):
    """`Cliente.baixar` falso: cada modalidade falha N vezes e depois
    responde. Devolve também o registro de chamadas, por passada."""
    restantes = dict(falhas_por_modalidade)
    chamadas = []

    def fake(self, url_base, caminho, consultas, tamanho_pagina):
        chamadas.append([str(r) for r, _ in consultas])
        for rotulo, params in consultas:
            if restantes.get(str(rotulo), 0) > 0:
                restantes[str(rotulo)] -= 1
                yield rotulo, [], PncpErro("HTTP 429")
            else:
                yield rotulo, [{"nome": str(rotulo)}], None

    return fake, chamadas


def test_falha_passageira_e_repetida_e_a_fase_termina_sem_erro(monkeypatch):
    fake, chamadas = baixar_que_falha({"Pregão eletrônico": 1})
    monkeypatch.setattr(Cliente, "baixar", fake)
    registros = list(Motor().contratacoes(123, DIA, DIA))
    assert len(registros) == len(MODALIDADES)  # nenhuma ficou pra trás
    assert all(isinstance(r, Contratacao) for r in registros)
    assert chamadas[1] == ["Pregão eletrônico"]  # 2ª passada: só a que falhou


def test_repescagem_espera_a_pausa_configurada(monkeypatch):
    fake, _ = baixar_que_falha({"Concurso": 1})
    monkeypatch.setattr(Cliente, "baixar", fake)
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    list(Motor(config=Config(repescagem_pausa=7)).contratacoes(123, DIA, DIA))
    assert dormidas == [7]


def test_sem_falha_nao_ha_segunda_passada_nem_pausa(monkeypatch):
    fake, chamadas = baixar_que_falha({})
    monkeypatch.setattr(Cliente, "baixar", fake)
    dormidas = []
    monkeypatch.setattr(Cliente, "_dormir", lambda self, s: dormidas.append(s))
    list(Motor().contratacoes(123, DIA, DIA))
    assert len(chamadas) == 1 and dormidas == []


def test_falha_persistente_diz_quais_consultas_e_refazer_repete_so_elas(monkeypatch):
    fake, chamadas = baixar_que_falha({"Pregão eletrônico": 2, "Concurso": 2})
    monkeypatch.setattr(Cliente, "baixar", fake)
    motor = Motor()
    vistos = []
    with pytest.raises(PncpErro, match="2 de 13 consultas falharam") as info:
        for r in motor.contratacoes(123, DIA, DIA):
            vistos.append(r)
    assert len(vistos) == len(MODALIDADES) - 2  # o resto já foi entregue
    falhas = info.value.consultas_falhas
    assert sorted(r for r, _ in falhas) == ["Concurso", "Pregão eletrônico"]
    assert all(p["codigoMunicipioIbge"] == 123 for _, p in falhas)

    # as duas já gastaram suas 2 falhas: refazer traz só elas, tipadas
    refeitos = list(motor.refazer(info.value))
    assert sorted(r.raw["nome"] for r in refeitos) == ["Concurso", "Pregão eletrônico"]
    assert all(isinstance(r, Contratacao) for r in refeitos)
    assert sorted(chamadas[-1]) == ["Concurso", "Pregão eletrônico"]


def test_refazer_que_ainda_falha_levanta_erro_so_com_o_que_sobrou(monkeypatch):
    fake, _ = baixar_que_falha({"Pregão eletrônico": 99, "Concurso": 2})
    monkeypatch.setattr(Cliente, "baixar", fake)
    motor = Motor()
    with pytest.raises(PncpErro) as primeiro:
        list(motor.contratacoes(123, DIA, DIA))
    with pytest.raises(PncpErro) as segundo:
        list(motor.refazer(primeiro.value))
    assert [r for r, _ in segundo.value.consultas_falhas] == ["Pregão eletrônico"]


def test_disjuntor_inclui_as_consultas_nem_tentadas(monkeypatch):
    def fake(self, url_base, caminho, consultas, tamanho_pagina):
        for rotulo, params in consultas:
            yield rotulo, [], PncpErro("morto")

    monkeypatch.setattr(Cliente, "baixar", fake)
    cfg = Config(falhas_consecutivas_limite=1, sem_sucesso_limite=0,
                 falhas_seguidas_teto=3)
    with pytest.raises(PncpErro, match="parado após") as info:
        list(Motor(config=cfg).contratacoes(123, DIA, DIA))
    # parou cedo: tudo segue pendente, inclusive o que nem foi tentado
    assert len(info.value.consultas_falhas) == len(MODALIDADES)


def test_rotulo_repetido_entre_janelas_nao_confunde_a_repescagem(monkeypatch):
    """Duas janelas = o mesmo nome de modalidade duas vezes. Só a consulta
    que falhou pode voltar na 2ª passada — identificar por nome traria as
    duas (ou daria a errada por concluída)."""
    estado = {"falhou": False}
    chamadas = []

    def fake(self, url_base, caminho, consultas, tamanho_pagina):
        chamadas.append([(str(r), p["dataInicial"]) for r, p in consultas])
        for rotulo, params in consultas:
            alvo = str(rotulo) == "Concurso" and params["dataInicial"] == "20240101"
            if alvo and not estado["falhou"]:
                estado["falhou"] = True
                yield rotulo, [], PncpErro("HTTP 429")
            else:
                yield rotulo, [{"x": 1}], None

    monkeypatch.setattr(Cliente, "baixar", fake)
    registros = list(Motor().contratacoes(123, date(2024, 1, 1), date(2025, 6, 1)))
    assert len(registros) == 2 * len(MODALIDADES)
    assert chamadas[1] == [("Concurso", "20240101")]


def test_refazer_vale_para_as_fases_por_cnpj(monkeypatch):
    fake, _ = baixar_que_falha({"20240101": 2})
    monkeypatch.setattr(Cliente, "baixar", fake)
    motor = Motor()
    with pytest.raises(PncpErro) as info:
        list(motor.contratos("123", DIA, DIA))
    refeitos = list(motor.refazer(info.value))
    assert len(refeitos) == 1 and isinstance(refeitos[0], Contrato)


def test_refazer_recusa_erro_que_nao_veio_de_fase_em_lote():
    with pytest.raises(ValueError, match="não há o que refazer"):
        list(Motor().refazer(PncpErro("HTTP 500 em /v1/orgaos/1")))


def test_erro_comum_tem_consultas_falhas_vazio():
    assert PncpErro("x").consultas_falhas == []
