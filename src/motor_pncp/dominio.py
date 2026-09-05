"""Constantes e helpers de domínio do PNCP — não mudam por sistema consumidor."""
from datetime import date, datetime, timedelta, timezone

DATA_INICIO_PNCP = date(2021, 1, 1)  # portal entrou no ar em ago/2021
DATA_INICIO_PCA = date(2021, 4, 1)  # /v1/pca/atualizacao rejeita datas anteriores
JANELA_MAX_DIAS = 364  # a API de consulta limita o range de datas por chamada

# Modalidades da Lei 14.133/2021 — /v1/contratacoes/* exige
# codigoModalidadeContratacao, por isso quem consulta por período tem que
# iterar por modalidade mesmo quando a maioria não devolve nada.
MODALIDADES = {
    1: "Leilão eletrônico",
    2: "Diálogo competitivo",
    3: "Concurso",
    4: "Concorrência eletrônica",
    5: "Concorrência presencial",
    6: "Pregão eletrônico",
    7: "Pregão presencial",
    8: "Dispensa de licitação",
    9: "Inexigibilidade",
    10: "Manifestação de interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão presencial",
}


def janelas(inicio, fim, max_dias=JANELA_MAX_DIAS):
    """Fatia [inicio, fim] em janelas de no máximo `max_dias`."""
    atual = inicio
    while atual <= fim:
        ate = min(atual + timedelta(days=max_dias - 1), fim)
        yield atual, ate
        atual = ate + timedelta(days=1)


def amd(d):
    """Data no formato AAAAMMDD exigido pela API do PNCP."""
    return d.strftime("%Y%m%d")


def primeiro(item, *chaves):
    """Primeiro valor não-nulo entre variantes de grafia de um campo da API."""
    for chave in chaves:
        if item.get(chave) is not None:
            return item[chave]
    return None


def num(v):
    """Campo numérico da API convertido para float, ou None se malformado.

    Quem persiste numa coluna de afinidade numérica (ex.: REAL do SQLite)
    precisa disso: um valor que não seja número JSON limpo (string vazia,
    placeholder textual) fica gravado como TEXT e a corrupção só se
    manifesta bem depois (formatação quebra, SUM em Python quebra, filtro
    `> 0` deixa a linha passar sem entrar no total).
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dt(valor):
    """String de data/hora do PNCP convertida pra `datetime` ciente de
    fuso, em UTC — sem assumir fuso local (América/São_Paulo).

    Uma string sem fuso explícito vira UTC direto, nunca passa por
    horário local antes. Achado real ao migrar um acervo gravado por raw
    SQL: o banco já tinha a string do PNCP persistida sem conversão
    nenhuma (equivalente a "já é UTC"); um parser que assumisse fuso
    local pra converter introduziria um desvio de horas contra o que já
    estava gravado. Quem persiste como TEXT (sem precisar de um
    `datetime` de verdade) não precisa chamar isto — é só pra quem
    grava num tipo de data/hora real.
    """
    if not valor:
        return None
    d = datetime.fromisoformat(valor)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
