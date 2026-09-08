# Motor de Coleta

![Versão](https://img.shields.io/github/v/release/devtulio/motor-pncp?label=vers%C3%A3o&color=blue) [![CI](https://github.com/devtulio/motor-pncp/actions/workflows/ci.yml/badge.svg)](https://github.com/devtulio/motor-pncp/actions/workflows/ci.yml) ![Licença](https://img.shields.io/badge/licença-MIT-green) ![Tecnologia](https://img.shields.io/badge/tecnologia-Python%20stdlib-orange) ![Fonte](https://img.shields.io/badge/fonte-PNCP-informational)

Pacote `motor_pncp` (`src/`) — motor de coleta do PNCP (Portal Nacional de
Contratações Públicas) pra ser usado por qualquer sistema. Só stdlib.

Referência completa da API: [MANUAL.md](MANUAL.md). Histórico:
[CHANGELOG.md](CHANGELOG.md). O que é contrato, como a versão muda e
como sai release: [RELEASING.md](RELEASING.md).

**Fronteira:** o motor faz HTTP resiliente contra o portal (retry com
backoff, paralelismo e nº de tentativas que recuam sozinhos sob storm,
disjuntor por tempo sem sucesso) e devolve **registros tipados** que
embrulham o JSON cru do PNCP (`.raw` continua sendo a fonte da verdade —
ver `tipos.py`). Não conhece banco de dados, schema ou upsert — isso é
decisão de quem consome; sistemas diferentes persistem de jeitos
diferentes, e o motor não escolhe por eles.

Cobertura atual: contratações (`contratacoes`), itens e resultados
homologados (`itens_e_resultados`), contratos/atas/PCA de um órgão
(`contratos`/`atas`/`pca`), termos aditivos (`termos_aditivos`), consulta
de órgão (`consultar_orgao`), IPCA (`ipca`) e um health-check barato do
portal (`sonda`, 1 requisição, 1 tentativa — pra decidir em segundos se
vale iniciar uma coleta).

## Uso

```python
from datetime import date
from motor_pncp import Motor, Config, PncpErro

# limiares de resiliência são configuráveis — o default é o medido
# contra o PNCP real; um sistema com perfil diferente ajusta aqui
motor = Motor(progresso=print, config=Config(conexoes_paralelas=6))

# fase 1 — contratações de um município
total = 0
try:
    for contratacao in motor.contratacoes(3550308, date(2026, 1, 1), date.today()):
        total += meu_upsert_contratacao(contratacao)  # você decide o schema
        # contratacao.numero_controle, .orgao_cnpj, .valor_estimado, ...
        # contratacao.raw tem o JSON completo do PNCP
except PncpErro as e:
    registrar_falha("contratacoes", e)  # o que já veio antes já foi processado

# fase 2 — itens e resultados, só dos que você ainda não tem
def esta_pendente(contratacao, item):
    return preciso_rebuscar(contratacao, item)  # sua lógica, seu banco

for contratacao, pares in motor.itens_e_resultados(minhas_pendentes,
                                                    pendente=esta_pendente,
                                                    on_erro=registrar_falha_item):
    for item, resultado in pares:  # resultado é None se o item não tem
        meu_upsert_item(contratacao, item, resultado)

# fase 2 (órgão) — contratos, atas, PCA
for contrato in motor.contratos(cnpj, inicio, date.today()):
    meu_upsert_contrato(contrato)
for ata in motor.atas(cnpj, inicio, date.today()):
    meu_upsert_ata(ata)
for plano in motor.pca(cnpj, inicio, date.today()):
    for item_pca in plano.itens:  # achatar em linhas é decisão sua
        meu_upsert_pca(plano, item_pca)

# termos aditivos — fase opcional sobre contratos já sincronizados
for contrato, termos in motor.termos_aditivos(meus_contratos_pendentes):
    for termo in termos:
        meu_upsert_termo(contrato, termo)
```

Instalação em cada sistema consumidor — **pinada numa tag**, nunca em
`master` (uma correção no motor não pode mudar o comportamento do seu
sistema sem você pedir):

```bash
pip install "git+https://github.com/devtulio/motor-pncp.git@v1.1.0"
```

Em modo editável durante o desenvolvimento do próprio motor:

```bash
pip install -e .
```

## Diagnóstico ao vivo

```bash
python -m motor_pncp 3553401 --dias 60
```

Roda cada fase contra o PNCP real num município e separa por host
(`api/consulta` × `api/pncp`, que caem independentemente) — pra responder
"o motor quebrou ou o portal caiu?" sem abrir código. Não grava nada.
Sai com código 1 se alguma fase falhou. Ver [MANUAL.md](MANUAL.md#diagnóstico-ao-vivo).

Testes: `pip install -e ".[dev]" && pytest` (85 testes, focados na lógica
de resiliência — disjuntor, paralelismo/tentativas adaptativos, dedup de
avisos, classificação de erro HTTP, limpeza de thread ao parar cedo).
`ruff check src tests` e `bandit -q -c pyproject.toml -r src` rodam no CI
a cada push/PR (Python 3.10 e 3.12).

## Princípios que o código segue

Cada um destes virou uma decisão concreta no motor; quem consome herda.

- **Falha ≠ ausência.** 429, 5xx, timeout, resposta ilegível ou página
  vazia no meio de uma listagem nunca viram "não existe" — viram retry
  e, esgotado, `PncpErro`. Quem persiste não avança marca d'água sobre
  uma falha parcial.
- **Contar sem paginar.** Volume de uma consulta se lê no envelope
  (`totalRegistros`), nunca baixando tudo (`contar_contratacoes`).
- **Desistir por tempo, não por contagem.** Numa fila de milhares, falhas
  seguidas são ruído normal; o disjuntor exige falhas seguidas **e** tempo
  sem sucesso — com um teto absoluto pra quando a falha fica barata.
- **Recuar por proporção.** Paralelismo e nº de tentativas caem pela
  fração de respostas ruins na janela recente, não por contagem
  absoluta, e voltam sozinhos.
- **Nunca ficar mudo.** Toda espera de retry avisa (`progresso`), com
  avisos da mesma causa agrupados por janela pra não inundar.
- **Parar cedo de verdade.** Gerador fechado no meio não espera as
  requisições já enfileiradas pagarem o orçamento inteiro de retry.
- **Mock não prova fronteira.** Toda mudança de comportamento é validada
  contra o portal real (`python -m motor_pncp`) antes de virar tag.

## Licença

[MIT](LICENSE) — © 2026 Túlio Ribeiro de Moura e Silva.
