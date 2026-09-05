from datetime import timezone

from motor_pncp.dominio import amd, dt, num, primeiro


def test_num_converte_string_numerica():
    assert num("12.5") == 12.5


def test_num_devolve_none_para_valor_invalido():
    assert num("") is None
    assert num(None) is None
    assert num("não é número") is None


def test_primeiro_pega_a_primeira_chave_presente():
    assert primeiro({"b": 2}, "a", "b") == 2
    assert primeiro({}, "a", "b") is None


def test_amd_formata_no_padrao_do_pncp():
    from datetime import date
    assert amd(date(2026, 1, 5)) == "20260105"


def test_dt_none_para_vazio():
    assert dt(None) is None
    assert dt("") is None


def test_dt_string_sem_fuso_vira_utc_direto():
    """Achado real: o acervo já gravado tinha a string do PNCP persistida
    sem conversão nenhuma (equivalente a UTC). Assumir fuso local pra
    converter introduziria um desvio de horas contra o que já existe."""
    resultado = dt("2026-01-05T10:00:00")
    assert resultado.tzinfo == timezone.utc
    assert resultado.hour == 10  # não deslocou pra horário local


def test_dt_string_com_fuso_explicito_e_preservada():
    resultado = dt("2026-01-05T10:00:00-03:00")
    assert resultado.utcoffset().total_seconds() == -3 * 3600
