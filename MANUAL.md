# Manual — motor_pncp

Referência completa da API pública. Para instalação e um exemplo rápido,
ver [README.md](README.md). Tudo que está documentado aqui é **contrato**
— só muda em major, com depreciação antes; o que não está (módulos com
`_`, texto de mensagens, valores dos limiares) não é. Regras completas em
[RELEASING.md](RELEASING.md).

## Índice

- [Motor](#motor)
- [Config](#config)
- [Registros tipados](#registros-tipados)
- [Exceções](#exceções)
- [Helpers de domínio](#helpers-de-domínio)
- [Padrões de uso](#padrões-de-uso)
- [Armadilhas do dado](#armadilhas-do-dado)
- [Diagnóstico ao vivo](#diagnóstico-ao-vivo)

---

## Motor

```python
Motor(*, config: Config = Config(), user_agent: str = ..., progresso=None,
     cancelado: threading.Event | None = None,
     base: str = BASE, base_pncp: str = BASE_PNCP)
```

Uma instância = uma coleta. Crie uma nova por sincronização — todo o
estado adaptativo (bloqueios/sucessos recentes, pacing, dedup de avisos)
é por instância, não de módulo.

| Parâmetro | Descrição |
|---|---|
| `config` | Limiares de resiliência. Ver [Config](#config). |
| `user_agent` | Enviado em toda requisição. Identifique seu sistema — o PNCP não exige, mas ajuda a instituição a saber quem está batendo na API dela. |
| `progresso` | `callable(str)` opcional, chamado a cada ponto natural da coleta (contratação processada, retry em andamento). Levantar `SyncCancelado` de dentro dele interrompe a coleta no próximo ponto de checagem — não no meio de uma requisição em voo. **Precisa ser thread-safe**: `itens_e_resultados` busca resultados em paralelo, e retries de requisições concorrentes chamam `progresso` de threads diferentes ao mesmo tempo. |
| `cancelado` | `threading.Event` opcional. Acionado, interrompe a coleta antes da próxima requisição e **acorda na hora** qualquer espera de backoff/`Retry-After` em andamento, levantando `SyncCancelado`. É o caminho mais rápido de parar: o `progresso` fica silenciado pelo agrupamento de avisos repetidos durante um storm, e por ele a parada pode demorar minutos. Ver [Cancelamento cooperativo](#cancelamento-cooperativo). |
| `base` / `base_pncp` | URLs base — normalmente não precisam mudar; existem pra testes/mocks. |

### `contratacoes(codigo_ibge, inicio, fim) -> Iterator[Contratacao]`

Contratações atualizadas de um município, por modalidade (13) e janela de
até 364 dias. Baixadas em paralelo conforme a saúde do portal.

Levanta `PncpErro` se alguma consulta falhar — **o que já foi gerado
antes disso quem consome já processou**; não avance sua marca d'água de
sincronização se isso acontecer (falha ≠ ausência). Se o disjuntor
decidir que a fase morreu, as consultas restantes nem são tentadas.

### `sonda() -> float`

Uma requisição barata em `/v1/atas` (vigência de hoje, 10 registros, o
endpoint que o monitor independente do PNCP usa como health-check), com
**uma** tentativa — sem escada de retry. Devolve o tempo de resposta em
segundos; levanta `PncpErro` se `api/consulta` não respondeu. Serve pra
decidir em 1s se vale iniciar uma coleta ou esperar o portal. Não diz
nada sobre `api/pncp` (itens/resultados), que cai separado.

### `contar_contratacoes(codigo_ibge, inicio=DATA_INICIO_PNCP, fim=None) -> dict`

Quantas contratações um município tem, sem baixar nenhuma — lê
`totalRegistros` do envelope de cada consulta. Devolve
`{"total": int, "parcial": bool}`; `parcial=True` quando alguma consulta
falhou (o total é subestimado, nunca superestimado).

### `contratos(cnpj, inicio, fim) -> Iterator[Contrato]`

Contratos de um órgão atualizados na janela — a API filtra por CNPJ, não
por município.

### `atas(cnpj, inicio, fim) -> Iterator[Ata]`

Atas de registro de preços de um órgão atualizadas na janela.

### `pca(cnpj, inicio, fim) -> Iterator[PlanoPca]`

Planos de Contratação Anual de um órgão atualizados na janela. Usa
`dataInicio`/`dataFim` (os outros endpoints usam `dataInicial`/
`dataFinal`) e ajusta `inicio` para `DATA_INICIO_PCA` se vier anterior —
o endpoint rejeita datas mais antigas.

### `consultar_orgao(cnpj) -> Orgao | None`

Registro do CNPJ no PNCP — `None` se o CNPJ não existe no portal.

### `itens_da_compra(cnpj, ano, sequencial) -> Iterator[Item]`

Itens de uma contratação (página vazia = fim, em qualquer posição — além do fim o portal devolve `[]`). Levanta `ItensIndisponiveis` em 404 — não é o
mesmo que "sem itens" (ver [Exceções](#exceções)).

### `resultado_do_item(cnpj, ano, sequencial, numero_item, pacing=True) -> Resultado | None`

Resultado homologado de um item — `None` se ainda não tem.

### `itens_e_resultados(contratacoes, *, pendente=None, on_erro=None) -> Iterator[tuple[dict, list[tuple[Item, Resultado | None]]]]`

Para cada contratação, busca itens e (em paralelo) os resultados dos que
têm. Ver [Padrões de uso](#padrões-de-uso) para `pendente`/`on_erro`.

`contratacoes`: iterável de **dicts seus**, com pelo menos `orgao_cnpj`,
`ano`, `sequencial` — o motor não impõe tipo aqui porque é você quem sabe
quais contratações precisam de revisita.

Gera `(contratacao, [(Item, Resultado | None), ...])` — uma tupla por
contratação, só depois que todos os itens dela chegaram. Contratação com
404 na listagem não aparece nesta chamada (fica pendente); as demais
continuam.

### `termos_aditivos(contratos, *, on_erro=None) -> Iterator[tuple[dict, list[TermoAditivo]]]`

Para cada contrato, verifica (chamada barata) se há termo aditivo antes
de buscá-los (chamada cara). `contratos`: mesmo formato de dict que
`itens_e_resultados`. Gera `(contrato, [TermoAditivo, ...])` — lista
vazia quando não há aditivo (ainda assim gerado, pra você saber que já
foi verificado).

### `ipca(inicio=None) -> Iterator[dict]`

Variação mensal do IPCA (Banco Central, série SGS 433) desde `inicio`
(`dd/mm/aaaa`). Gera `{"competencia": "aaaa-mm", "variacao": float}`.

**Passe `inicio` incremental, não `None` toda vez.** Sem isso a série
inteira (2021 → hoje, ~70 competências) é rebaixada em toda
sincronização — desperdício puro, medido em 58x numa noite de
diagnóstico. O motor não sabe quando você sincronizou pela última vez;
guarde isso e passe **60 dias antes** da última sincronização (não 1
dia, como nas outras janelas: o BCB revisa o índice do mês corrente por
semanas depois da publicação original). `None` só na primeira vez.

---

## Config

Dataclass congelado — todos os limiares de resiliência, com os valores
medidos contra o PNCP real como default.

| Campo | Default | O que é |
|---|---|---|
| `conexoes_paralelas` | `4` | Requisições simultâneas com o portal saudável. |
| `janela_eventos` | `120` (s) | Só bloqueios/sucessos dentro desta janela contam pra decidir paralelismo/tentativas. |
| `taxa_recuo` | `0.2` | Fração de bloqueios recentes acima da qual já vale recuar. |
| `taxa_tregua` | `0.5` | Fração acima da qual o portal está recusando mais do que respondendo. |
| `tentativas_padrao` | `5` | Tentativas por requisição em condição normal. |
| `tentativas_curtas` | `2` | Tentativas quando um storm já está confirmado. |
| `timeouts` | `(30,45,60,75,90)` | Timeout de cada tentativa sucessiva. |
| `intervalo_min` | `0.5` (s) | Intervalo mínimo entre requisições ao portal — vale também entre as threads em paralelo (é por host, não por conexão). |
| `retry_after_teto` | `120` (s) | Teto do que o portal pede em `Retry-After` (429 e 503). |
| `falhas_consecutivas_limite` | `5` | Falhas seguidas a partir das quais o disjuntor passa a olhar o tempo sem sucesso. |
| `sem_sucesso_limite` | `600` (s) | Combinado com o limite acima, quando o disjuntor desiste da fase (falha lenta). |
| `falhas_seguidas_teto` | `40` | Teto absoluto: desiste mesmo com o relógio aberto. Cobre a falha barata (escada curta durante storm), em que só o tempo deixaria mastigar a fila inteira. |
| `janela_operacional` | `300` (s) | Avisos de retry da mesma causa ficam agrupados dentro desta janela. |

```python
from motor_pncp import Motor, Config

# sistema com perfil mais impaciente (ex.: atende cliente esperando na tela)
motor = Motor(config=Config(sem_sucesso_limite=180, tentativas_padrao=3))
```

---

## Registros tipados

Cada um embrulha o JSON cru do PNCP em `.raw` — **fonte da verdade**. As
`@property` são conveniência para os campos mais usados; a API do PNCP
pode ganhar campo novo sem quebrar nada aqui. Precisa de um campo sem
`@property`? Pegue de `.raw` diretamente.

| Tipo | Campos de conveniência |
|---|---|
| `Contratacao` | `numero_controle`, `ano`, `sequencial`, `orgao_cnpj`, `orgao_nome`, `unidade_nome`, `modalidade_id`, `situacao`, `objeto`, `valor_estimado`, `valor_homologado`, `data_atualizacao`, `data_publicacao` |
| `Item` | `numero_item`, `descricao`, `tem_resultado`, `quantidade`, `valor_unitario_estimado`, `valor_total_estimado`, `data_atualizacao` |
| `Resultado` | `cancelado`, `fornecedor_ni`, `fornecedor_nome`, `valor_unitario_homologado`, `valor_total_homologado`, `quantidade_homologada`, `data_resultado` |
| `Contrato` | `numero_controle`, `ano`, `sequencial`, `orgao_cnpj`, `valor_global`, `data_atualizacao` |
| `Ata` | `numero_controle`, `orgao_cnpj`, `vigencia_fim`, `data_atualizacao` |
| `PlanoPca` | `id_pca`, `ano`, `orgao_cnpj`, `itens` (lista crua — achatar em linhas é decisão sua), `data_atualizacao` |
| `TermoAditivo` | `sequencial`, `tipo`, `valor_global`, `valor_acrescido`, `data_assinatura` |
| `Orgao` | `cnpj`, `razao_social`, `esfera` (`M`/`E`/`F`/`N`) |

Valores numéricos de conveniência já passam por `num()` (string
malformada vira `None`, não quebra silenciosamente numa coluna REAL).
Datas ficam como **string crua** do PNCP — use `dt()` se seu schema
precisa de um `datetime` de verdade (ver abaixo).

---

## Exceções

| Exceção | Quando |
|---|---|
| `PncpErro` | Falha de comunicação após esgotar as tentativas, ou fase abortada pelo disjuntor. Base de todas as outras. |
| `SyncCancelado` | Você levantou de dentro do `progresso` pra interromper a coleta. **Não herda de `PncpErro`** — se herdasse, um `except PncpErro` engoliria o cancelamento. |
| `ItensIndisponiveis` | 404 numa listagem de UM registro específico (itens de uma contratação, termos de um contrato). Não é "sem registro" — é o portal ocupado; não marque como concluído. |

---

## Helpers de domínio

```python
from motor_pncp import janelas, amd, num, primeiro, dt
```

| Função | Uso |
|---|---|
| `janelas(inicio, fim, max_dias=364)` | Fatia um intervalo em janelas — usado internamente, exposto pra quem monta suas próprias consultas por CNPJ. |
| `amd(data)` | Formata `date` como `AAAAMMDD` (formato exigido pela API). |
| `num(valor)` | Converte campo numérico da API pra `float`, ou `None` se malformado. |
| `primeiro(item, *chaves)` | Primeiro valor não-nulo entre variantes de grafia de um campo. |
| `dt(valor)` | String de data/hora do PNCP → `datetime` ciente de fuso (UTC). String sem fuso explícito vira UTC direto — **nunca** passa por horário local. Só precisa disso quem grava num tipo de data/hora real (Postgres, etc.); quem grava como TEXT não precisa. |

---

## Padrões de uso

### Fronteira: o motor não persiste

Todo método devolve dados — nenhum grava em lugar nenhum. `schema`,
`upsert`, `config`/`last_sync`, `log` de sincronização: tudo isso é seu.

### Fronteira: o motor não orquestra

De propósito, não existe um `Motor.sincronizar_tudo()`: decidir **qual**
fase roda, a janela incremental (`last_sync_contratacoes`, etc.), o
throttle contra rodar de novo cedo demais e o VACUUM do banco dependem
de estado que só o seu sistema tem (config/log próprios) — e sistemas
consumidores orquestram de formas incompatíveis entre si (um app
multi-tenant roda a fase de itens GLOBAL, uma passada por ciclo; um app
por município roda por cidade, com "municípios de referência"). Cada
sistema mantém o próprio `sincronizar_tudo`, chamando os métodos do
`Motor`.

### Índice em `municipio_ibge` (do seu schema, não do motor)

Todo registro que o motor devolve carrega o município (você passa o
`codigo_ibge`; guarde-o na linha). Toda consulta sua por município —
inclusive a listagem de referência que uma tela costuma fazer no boot —
varre a tabela inteira sem índice nessa coluna. Medido num acervo real
(acervo real): **22,7s → 0,4s** só criando o índice em
`itens` e `contratacoes`, zero mudança de query. Escala mal exatamente
com o que cresce (mais municípios de referência = pior).

### `pendente()` — evite refetch caro

`itens_e_resultados` busca resultado de TODO item com `temResultado` a
menos que você diga o contrário:

```python
def pendente(contratacao, item: Item) -> bool:
    """True = precisa buscar de novo."""
    antigo = meu_banco.item(contratacao["numero_controle"], item.numero_item)
    if antigo is None or antigo.data_atualizacao != item.data_atualizacao:
        return True
    return item.tem_resultado and antigo.valor_unitario_homologado is None
```

Sem isso, uma contratação já conhecida onde só a `dataAtualizacao`
cosmética mudou paga uma requisição de resultado por item à toa.

### `on_erro()` — uma contratação quebrada não trava a fila

`itens_e_resultados` e `termos_aditivos` continuam as demais contratações
quando uma falha — só desistem da fase inteira via disjuntor (falhas
seguidas **e** tempo sem sucesso, nunca só contagem — fila grande
tropeça por ruído normal do portal). `on_erro(item, excecao)` é onde você
registra o que falhou pra tentar de novo na próxima passada.

### Cancelamento cooperativo

```python
cancelado = threading.Event()
motor = Motor(progresso=print, cancelado=cancelado)
# ... de outra thread (botão "Parar", sinal do SO):
cancelado.set()
```

A parada acontece antes da próxima requisição, ou no meio de uma espera
de backoff/`Retry-After` (a espera acorda na hora) — nunca no meio de
uma requisição em voo; o `SyncCancelado` sai do método que estava sendo
iterado. Beacon (informar) e token (parar) são coisas separadas de
propósito: o beacon pode ficar em silêncio dentro da janela de um aviso
repetido, o token não.

A forma antiga — levantar `SyncCancelado` de dentro do `progresso` —
continua valendo; só é mais lenta num storm.

### Logging (diagnóstico, opcional)

O motor escreve no logger `motor_pncp` e, por padrão, não emite nada
(`NullHandler`). Ligue quando quiser contar tentativas, status e latência
por requisição:

```python
import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("motor_pncp").setLevel(logging.DEBUG)
```

`DEBUG`: uma linha por requisição bem-sucedida (`GET /caminho status=200
tentativa=1 0.84s`) e por retry (`retry /caminho tentativa=2
causa=http503 espera=3.1s`). `WARNING`: uma linha quando as tentativas
se esgotam. O callback `progresso` continua sendo o canal pra UI; o log
é pra diagnóstico e métricas.

### Disjuntor: falha ≠ ausência

Quando `PncpErro` escapa de `contratacoes`/`contratos`/`atas`/`pca`, **o
que já foi gerado antes já foi processado por você** — mas a fase não
terminou. Não avance sua marca d'água de sincronização (`last_sync_*`)
para essa fase; refaça a mesma janela na próxima passada. Avançar sobre
uma falha parcial abre um buraco permanente no acervo.

---

## Armadilhas do dado

O motor devolve o dado como o PNCP manda e não interpreta — de propósito.
Mas quem interpreta tropeça sempre nos mesmos lugares. Cada item abaixo é
um erro que produz **resultado bem-formado e errado**: o total fecha, o
relatório sai bonito, e a conclusão descreve outra coisa.

### `niFornecedor` carrega CNPJ *ou* CPF

`Resultado.fornecedor_ni` vem com 14 dígitos (CNPJ) **ou** 11 (CPF) — pessoa
física vence licitação com frequência (agricultura familiar, serviços
avulsos). Formatar tudo como CNPJ transforma um CPF em documento adulterado
saindo em relatório oficial. Decida pelo tamanho: 14 → `00.000.000/0000-00`,
11 → `000.000.000-00`, qualquer outro → deixe como veio (identificador
estrangeiro ou ausente). Antes de formatar qualquer identificador de API
pública, conte os tamanhos distintos no seu acervo.

### Unidade de terceiro pendurada no CNPJ de outro ente

O PNCP organiza contratação em **órgão** (`Contratacao.orgao_cnpj`) e
**unidade** (`Contratacao.unidade_nome`, `raw["unidadeOrgao"]`). Sob o CNPJ
de um ente aparecem unidades que pertencem a outros — um fundo, uma
prefeitura, um hospital — e o `codigoIbge` da unidade é o município **da
unidade**, não do órgão. Somar por CNPJ (ou filtrar por IBGE) sem olhar a
unidade atribui a um ente compras que não são dele. Antes de agregar,
liste as unidades distintas do CNPJ e decida o que entra. Dois cuidados:
não filtre pelo texto do objeto (órgão grande compra de tudo pra uso
interno), e confira os nomes reais das unidades antes de excluir por regra
(departamento interno com nome genérico não é ente estranho).

### Prefeitura, Câmara, autarquia e fundo são CNPJs distintos

Num município convivem vários entes, cada um com CNPJ, orçamento, plano
(`pca`) e prestação de contas próprios. Escopar "por município" e cruzar
tudo junto compara o plano de um com a execução de outro — interseção
zero e um indicador sem significado. Qualquer confronto de duas fontes
(planejado × executado, previsto × realizado) tem que casar pelo CNPJ que
publica **os dois lados**; confira no dado real quais CNPJs aparecem de
cada lado antes de construir. E trate ausência como achado: órgão que
executou sem plano publicado é uma linha "não publicou o PCA" (obrigatório
pelo art. 12, VII, da Lei 14.133/2021), não N acusações derivadas.

### Modalidade não é amparo legal

`Contratacao.modalidade_id == 8` ("Dispensa") diz qual foi o procedimento,
não qual teto se aplica. Quem define se há limite de valor, e qual, é
`raw["amparoLegal"]`: art. 75, II (compras e serviços comuns — o teto
usual), art. 75, I (obras — teto próprio, o dobro), os demais incisos e
outras leis (emergência, licitação deserta, agricultura familiar via PNAE —
dispensa pela natureza do objeto, **sem** teto contra o qual comparar).
Um indicador de conformidade que filtra por modalidade acusa como
irregular exatamente a compra grande e legítima. Classifique pelo
dispositivo invocado, nunca pelo rótulo — e valide contra o acervo real:
fixture de teste nasce com o amparo que o autor imaginou.

### Falha ≠ ausência (o motor já protege; não desfaça)

429, 5xx, timeout, corpo ilegível, página vazia no meio de uma listagem —
o motor trata todos como falha e levanta `PncpErro`, nunca como "não tem
dado". Do seu lado, o equivalente: não avance marca d'água sobre falha
parcial, não carimbe uma contratação como concluída depois de
`ItensIndisponiveis`, e não use `None` de `resultado_do_item` como prova
de que não há resultado se a chamada falhou antes.

### Volume se lê no envelope

Pra saber quantos registros uma consulta tem, use `contar_contratacoes`
(lê `totalRegistros`), nunca pagine tudo pra contar — em município grande
isso não termina, e o rate-limit do portal chega antes.

---

## Diagnóstico ao vivo

```bash
python -m motor_pncp <ibge> [--dias N] [--itens N] [--silencioso]
```

Roda cada fase do motor contra o PNCP **real**, num município, numa
janela curta (default 90 dias), e imprime o que respondeu e o que não,
com tempo por fase. Não grava nada. Sai com código 1 se alguma fase
falhou — dá pra usar em script.

Existe pra uma pergunta só, a que toda sessão de integração vai fazer:
**"o motor quebrou ou o portal caiu?"** Os testes com mock provam a
lógica; só uma chamada real prova que o envelope ainda se chama
`totalPaginas`, que o endpoint de itens ainda devolve array puro, que
204 ainda vem como 204.

O resumo separa por host, porque eles caem independentemente:

| Host | Fases | 2026-09-06 | 2026-09-07 |
|---|---|---|---|
| `api/consulta` | `sonda`, `contar_contratacoes`, `contratacoes`, `contratos`, `atas`, `pca` | 5/5 ok | 6/6 ok — 649 contratações em várias páginas, `contar` = baixadas |
| `api/pncp` | `consultar_orgao`, `itens_e_resultados` (itens, resultados, termos) | 0/2 — HTTP 503 sustentado há >24h | 2/2 ok |
| Banco Central | `ipca` | ok | ok |

Leitura do dia 06: motor íntegro, portal parcialmente fora — sem código
de retry/timeout que extraia dado de um endpoint que não responde;
parar e esperar. Leitura do dia 07: portal de pé, todas as fases
validadas contra resposta real (envelope traz `paginasRestantes`,
`totalPaginas`, `totalRegistros`, `numeroPagina`, `empty`). `--silencioso`
desliga o beacon de progresso (stderr) quando só o resumo interessa.

Rodando de dentro do repositório do motor, use `PYTHONPATH=src` — uma
cópia do pacote instalada por tag no site-packages ganha do `src/` na
resolução de import, e o diagnóstico rodaria a versão errada sem avisar
(o cabeçalho mostra a versão; confira).
