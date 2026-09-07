# Motor de Coleta

[![CI](https://github.com/devtulio/motor-pncp/actions/workflows/ci.yml/badge.svg)](https://github.com/devtulio/motor-pncp/actions/workflows/ci.yml)

Pacote `motor_pncp` (`src/`) — motor de coleta do PNCP, extraído do
`pncp.py` do Pretiarium Free (2026-09-05, depois de 3 rodadas de auditoria
sobre travamentos reais) para ser usado por qualquer sistema, sem cópia.
Auditado contra as variantes de origem (Licitarium Free, Pretiarium Free e
um sistema irmão) — ver [CHANGELOG.md](CHANGELOG.md).

Referência completa da API: [MANUAL.md](MANUAL.md).

**Fronteira:** o motor faz HTTP resiliente contra o portal (retry com
backoff, paralelismo e nº de tentativas que recuam sozinhos sob storm,
disjuntor por tempo sem sucesso) e devolve **registros tipados** que
embrulham o JSON cru do PNCP (`.raw` continua sendo a fonte da verdade —
ver `tipos.py`). Não conhece banco de dados, schema ou upsert — isso é
decisão de quem consome. Essa fronteira já existia de fato entre os 3
sistemas que originaram este código (um grava SQLite direto, outro tem
storage próprio); o motor só torna explícito o que já era verdade.

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
pip install "git+https://github.com/devtulio/motor-pncp.git@v0.4.2"
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
avisos, classificação de erro HTTP, e o vazamento de thread do achado 8).
`ruff check src tests` e `bandit -q -c pyproject.toml -r src` rodam no CI
a cada push/PR (Python 3.10 e 3.12).

## Lições de coleta e interpretação de dados públicos

Extraídas das notas de trabalho dos sistemas de origem.

Origem: pesquisas com PNCP, Compras.gov, Siconfi e portais de transparência
(2026). Cada arquivo mantém o formato de memória: fato, **Why** e
**How to apply**. As lições de "Mecânica da coleta" abaixo são exatamente o
que o `motor_pncp` implementa em código.

## Mecânica da coleta

Como falar com uma API pública sem inventar resultado.

| Arquivo | Lição |
|---|---|
| `feedback_api_publica_falha_vs_ausencia.md` | 429 e 500 não são "não existe". Nunca cachear falha como ausência; e conferir se o filtro que você passou é de fato aplicado. |
| `feedback_contar_sem_paginar.md` | Volume de API paginada se lê no envelope (`totalRegistros`), nunca baixando tudo. |
| `feedback_medicao_de_api_expira.md` | Número medido de serviço de terceiro tem validade. Remedir antes de usar como premissa. |
| `feedback_watcher_sem_saida.md` | Monitor em background precisa de segunda condição de saída: processo morto ou teto de tempo. |
| `feedback_auditoria_estatica_nao_ve_a_fronteira.md` | Ler o código não basta. Rodar contra a API e os arquivos reais é segunda passada obrigatória. |

## Semântica do dado

O campo vem bem-formado e significa outra coisa. Todo erro caro desta família
tem essa assinatura.

| Arquivo | Lição |
|---|---|
| `feedback_agregar_por_cnpj_sem_unidade.md` | Somar por CNPJ de órgão sem olhar a unidade: há unidade de terceiro pendurada no CNPJ de outro ente. |
| `feedback_cruzar_dentro_do_orgao.md` | Prefeitura e Câmara são CNPJs distintos. Não cruzar plano de uma com execução de outra. |
| `feedback_modalidade_nao_e_amparo.md` | Classificar pelo dispositivo legal invocado, nunca pelo rótulo da modalidade. |
| `feedback_ni_fornecedor_cnpj_ou_cpf.md` | O mesmo campo carrega CNPJ ou CPF. Decidir pelo número de dígitos, contando antes de formatar. |
| `feedback_denominador_populacao_residente.md` | Escolha de denominador muda o resultado. Perguntar antes de tratar outlier como achado. |

## Classificação automática

| Arquivo | Lição |
|---|---|
| `feedback_regra_automatica_acusa_pelo_nome.md` | Classificador por texto produz falso positivo antes de produzir achado. Imprimir os valores que a regra casou e ler, antes de o número existir. |

## Fontes

| Arquivo | Lição |
|---|---|
| `reference_api_dadosabertos_comprasgov.md` | Cobertura parcial; não substitui o PNCP. |

## Não copiado

`project_pncp_piloto.md` — memória de projeto ativo, não lição de motor. Continua
na memória de trabalho.
