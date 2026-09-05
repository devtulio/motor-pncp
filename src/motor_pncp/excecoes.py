"""Exceções do motor de coleta do PNCP."""


class PncpErro(Exception):
    """Falha de comunicação com o PNCP após esgotar as tentativas."""


class SyncCancelado(Exception):
    """Quem chama pediu para parar a coleta.

    Não herda de PncpErro de propósito: se herdasse, um `except PncpErro`
    de quem persiste engoliria o cancelamento e a coleta seguiria para a
    fase seguinte — o contrário do pedido. Quem levanta esta exceção é o
    próprio callback `progresso` passado ao `Motor`; ele é chamado em todo
    ponto natural da coleta (inclusive durante retry), e por isso a
    parada acontece no próximo desses pontos, não no meio de uma
    requisição em voo.
    """


class ItensIndisponiveis(PncpErro):
    """O portal respondeu 404 na listagem de itens de uma contratação.

    Não é o mesmo que "esta contratação não tem item nenhum" — um 404 sob
    carga é portal ocupado. Tratar como ausência faz quem persiste
    carimbar a contratação como concluída, e ela nunca mais é revisitada:
    os itens dela desaparecem do acervo em silêncio. Quem recebe esta
    exceção não deve marcar a contratação como sincronizada.
    """
