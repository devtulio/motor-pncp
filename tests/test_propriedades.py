"""Testes de propriedade (Claessen & Hughes, QuickCheck 2000) com o
`random` da stdlib — sem Hypothesis de propósito: 500 amostras por
propriedade bastam pra pegar limite errado, e não somam dependência.

Propriedades, não exemplos: valem pra QUALQUER entrada do domínio.
"""
import random
from datetime import date, timedelta

from conftest import resposta_json

from motor_pncp._http import Cliente
from motor_pncp._resiliencia import Adaptativo
from motor_pncp.dominio import janelas
from motor_pncp.motor import Motor

SEMENTE = 20260908  # reprodutível; troque pra explorar
AMOSTRAS = 500


def _datas(rng):
    inicio = date(2021, 1, 1) + timedelta(days=rng.randint(0, 3000))
    fim = inicio + timedelta(days=rng.randint(0, 2000))
    return inicio, fim


# ── janelas(): cobre [inicio, fim] sem lacuna, sem sobreposição, ≤ max ──

def test_janelas_cobrem_o_intervalo_exatamente_sem_lacuna_nem_sobreposicao():
    rng = random.Random(SEMENTE)
    for _ in range(AMOSTRAS):
        inicio, fim = _datas(rng)
        max_dias = rng.randint(1, 400)
        fatias = list(janelas(inicio, fim, max_dias))
        assert fatias, (inicio, fim)
        assert fatias[0][0] == inicio
        assert fatias[-1][1] == fim
        for (a, b), (c, _) in zip(fatias, fatias[1:]):
            assert c == b + timedelta(days=1), (a, b, c)  # contíguas
        for a, b in fatias:
            assert a <= b
            assert (b - a).days + 1 <= max_dias, (a, b, max_dias)


def test_janelas_intervalo_de_um_dia_e_uma_janela_so():
    d = date(2024, 2, 29)
    assert list(janelas(d, d)) == [(d, d)]


def test_janelas_inicio_depois_do_fim_nao_gera_nada():
    assert list(janelas(date(2024, 1, 2), date(2024, 1, 1))) == []


# ── paginar(): concatenar páginas devolve cada registro uma vez ─────────

def _paginas(total, tamanho, campo):
    """Envelopes como o portal manda, com `paginasRestantes` OU
    `totalPaginas` (o motor aceita os dois)."""
    n = max(1, -(-total // tamanho))
    for p in range(1, n + 1):
        dados = list(range((p - 1) * tamanho, min(p * tamanho, total)))
        env = {"data": dados, "totalRegistros": total, "empty": not dados}
        if campo == "paginasRestantes":
            env["paginasRestantes"] = n - p
        else:
            env["totalPaginas"] = n
        yield env


def test_paginar_devolve_todos_os_registros_uma_vez(urlopen_fake):
    rng = random.Random(SEMENTE)
    cliente = Cliente(Adaptativo())
    for _ in range(AMOSTRAS):
        total = rng.randint(0, 1200)
        tamanho = rng.choice([1, 7, 50, 100, 500])
        campo = rng.choice(["paginasRestantes", "totalPaginas"])
        urlopen_fake.clear()
        urlopen_fake.extend(resposta_json(e) for e in _paginas(total, tamanho, campo))
        vistos = list(cliente.paginar("https://x", "/y", {}, tamanho))
        assert vistos == list(range(total)), (total, tamanho, campo)
        assert not urlopen_fake, "pediu menos páginas do que o portal anunciou"


# ── itens_da_compra(): array puro, fim = página curta ──────────────────

def test_itens_da_compra_devolve_todos_os_itens_uma_vez(urlopen_fake):
    rng = random.Random(SEMENTE)
    motor = Motor()
    for _ in range(AMOSTRAS // 5):
        total = rng.randint(0, 450)
        paginas = [[{"numeroItem": i} for i in range(p, min(p + 100, total))]
                   for p in range(0, total, 100)] or [[]]
        # página cheia no fim: o portal ainda manda uma vazia depois
        if total and total % 100 == 0:
            paginas.append([])
        urlopen_fake.clear()
        urlopen_fake.extend(resposta_json(p) for p in paginas)
        itens = [i.numero_item for i in motor.itens_da_compra("1", 2024, 1)]
        assert itens == list(range(total)), total
        assert not urlopen_fake
