"""Diagnóstico ao vivo: `python -m motor_pncp <ibge> [--dias N]`.

Roda cada fase do motor contra o PNCP real, num município, numa janela
curta, e diz o que respondeu e o que não. Serve pra uma coisa só:
separar "o motor quebrou" de "o portal caiu" — a dúvida que toda
sessão de integração vai ter, e que os testes com mock não respondem.
Não grava nada.

Os endpoints vivem em dois hosts com saúde independente: `api/consulta`
(contratações, contratos, atas, PCA) e `api/pncp` (itens, resultados,
órgão, termos). É comum um estar de pé e o outro não — o resumo no fim
separa os dois.
"""
import argparse
import sys
import time
from datetime import date, timedelta

from . import Motor, PncpErro, __version__


def _fase(nome, funcao, mostrar=repr):
    """Roda uma fase, imprime resultado + tempo, nunca deixa escapar."""
    inicio = time.monotonic()
    try:
        resultado = funcao()
    except PncpErro as e:
        print(f"  FALHA  {nome}: {e}  [{time.monotonic() - inicio:.1f}s]")
        return None, False
    print(f"  ok     {nome}: {mostrar(resultado)}  [{time.monotonic() - inicio:.1f}s]")
    return resultado, True


def main(argv=None):
    for fluxo in (sys.stdout, sys.stderr):
        # console do Windows costuma vir em cp1252; acento quebrado no
        # diagnóstico atrapalha justamente quem está tentando ler um erro
        fluxo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    p = argparse.ArgumentParser(prog="python -m motor_pncp",
                                description=__doc__.split("\n\n")[1])
    p.add_argument("ibge", type=int, help="código IBGE do município (7 dígitos)")
    p.add_argument("--dias", type=int, default=90, help="janela em dias (default 90)")
    p.add_argument("--itens", type=int, default=2,
                   help="quantas contratações buscar itens/resultados (default 2)")
    p.add_argument("--silencioso", action="store_true",
                   help="não imprimir o beacon de progresso (stderr)")
    args = p.parse_args(argv)

    fim = date.today()
    inicio = fim - timedelta(days=args.dias)
    beacon = None if args.silencioso else (lambda m: print(f"    · {m}", file=sys.stderr))
    motor = Motor(progresso=beacon)
    print(f"motor_pncp {__version__} — município {args.ibge}, {inicio} a {fim}\n")
    consulta, pncp = [], []  # sucesso/falha por host

    print("host api/consulta:")
    _, s = _fase("sonda (/v1/atas, 1 tentativa)", motor.sonda,
                 mostrar=lambda t: f"respondeu em {t:.1f}s")
    consulta.append(s)
    contagem, s = _fase(
        "contar_contratacoes", lambda: motor.contar_contratacoes(args.ibge, inicio, fim))
    consulta.append(s)

    lista, s = _fase(
        "contratacoes", lambda: list(motor.contratacoes(args.ibge, inicio, fim)),
        mostrar=len)
    consulta.append(s)
    lista = lista or []
    if lista:
        c = lista[0]
        print(f"         exemplo: {c.numero_controle} — {c.orgao_nome} — "
              f"{(c.objeto or '')[:60]!r}")
        if contagem and contagem["total"] != len(lista):
            print(f"         aviso: contar={contagem['total']} vs baixadas="
                  f"{len(lista)} (normal se houve falha parcial)")

    cnpj = next((c.orgao_cnpj for c in lista if c.orgao_cnpj), None)
    if cnpj:
        _, s1 = _fase("contratos", lambda: len(list(motor.contratos(cnpj, inicio, fim))))
        _, s2 = _fase("atas", lambda: len(list(motor.atas(cnpj, inicio, fim))))
        _, s3 = _fase("pca", lambda: len(list(motor.pca(cnpj, inicio, fim))))
        consulta += [s1, s2, s3]

    print("\nhost api/pncp:")
    if cnpj:
        _, s = _fase("consultar_orgao", lambda: (lambda o: o and (o.razao_social, o.esfera))(
            motor.consultar_orgao(cnpj)))
        pncp.append(s)

    alvo = [{"orgao_cnpj": c.orgao_cnpj, "ano": c.ano, "sequencial": c.sequencial,
             "id": c.numero_controle} for c in lista[:args.itens]]
    if alvo:
        erros = []
        pares, s = _fase(
            f"itens_e_resultados ({len(alvo)} contratações)",
            lambda: [(c["id"], len(it), sum(1 for _, r in it if r))
                     for c, it in motor.itens_e_resultados(
                         alvo, on_erro=lambda c, e: erros.append(f"{c['id']}: {e}"))],
            mostrar=lambda p: f"{len(p)} de {len(alvo)} concluída(s)")
        for e in erros:
            print(f"         on_erro: {e}")
        if s and not pares:
            # gerador não levantou (disjuntor não disparou), mas nenhuma
            # contratação foi concluída — pro diagnóstico isso é falha
            print(f"         0 de {len(alvo)} concluídas — contando como FALHA")
            s = False
        pncp.append(s)

    print("\nBanco Central:")
    _, s = _fase("ipca (60 dias)", lambda: len(list(motor.ipca(
        (fim - timedelta(days=60)).strftime("%d/%m/%Y")))))

    def resumo(nome, fases):
        if not fases:
            return f"{nome}: não testado"
        f = fases.count(False)
        return f"{nome}: {len(fases) - f}/{len(fases)} ok" + (f", {f} FALHA(S)" if f else "")

    print(f"\n{resumo('api/consulta', consulta)} | {resumo('api/pncp', pncp)} | "
          f"BCB: {'ok' if s else 'FALHA'}")
    return 1 if (False in consulta or False in pncp or not s) else 0


if __name__ == "__main__":
    sys.exit(main())
