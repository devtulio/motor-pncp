# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [1.1.0] — 2026-09-08

Revisão contra a literatura de resiliência (Brooker/AWS, SRE cap. 22,
RFC 9110, Mercator/Olston & Najork, HOWTO de logging do Python).
Mudanças de comportamento validadas com smoke contra o portal real.

### Added
- `Motor(cancelado=threading.Event)`: token de parada separado do beacon
  `progresso`. Interrompe antes da próxima requisição e acorda na hora
  qualquer espera de backoff/`Retry-After` — o beacon fica silenciado
  pelo agrupamento de avisos repetidos durante um storm, e por ele a
  parada podia demorar minutos.
- Logger `motor_pncp` (com `NullHandler`, mudo por padrão): `DEBUG` por
  requisição e por retry (caminho, status, tentativa, latência, causa,
  espera), `WARNING` ao esgotar tentativas.
- `Config.retry_after_teto` (default 120 s).

### Changed
- Backoff com *full jitter*: sorteio em `[0, 2^tentativa]` em vez de
  `2^tentativa + até 0,5 s`. Um desvio de meio segundo não descorrelaciona
  conexões que falharam juntas.
- `Retry-After` honrado também em 503 (não só 429), aceitando data HTTP
  além de segundos, limitado a `retry_after_teto`.
- Espera de 429 sem header passa a ter sorteio (`[2,5–5] × tentativa`),
  nunca zero.
- Pacing (`intervalo_min`) vale também entre as threads em paralelo: o
  intervalo mínimo é por host, não por conexão. Antes, 4 threads sem
  pacing eram 4 rajadas simultâneas. Teto teórico com os defaults: 2
  req/s — como a latência do portal raramente fica abaixo de 1 s, a
  vazão medida não mudou.
- `resultado_do_item(pacing=...)` mantido por compatibilidade; o motor
  não passa mais `False`.

## [1.0.0] — 2026-09-08

Declara o contrato. Sem mudança de comportamento em relação à 0.4.4 — o
que muda é a promessa: a partir daqui a API pública descrita em
[RELEASING.md](RELEASING.md) §1 só quebra em major, com depreciação
antes. O motor está em produção e a API está estável há várias tags;
SemVer diz que isso já é 1.0.0.

### Added
- `RELEASING.md`: política de versão e release (o que é API pública,
  como o número muda, gates, depreciação, cadência).

### Changed
- Versão em fonte única: `src/motor_pncp/__init__.py`; `pyproject.toml`
  passa a ler de lá (`dynamic = ["version"]`).
- Só documentação não bumpa mais versão (era patch nas 0.4.1, 0.4.3 e
  0.4.4). Versão reflete comportamento.

## [0.4.4] — 2026-09-08

Sem mudança de código.

### Added
- Licença MIT (`LICENSE`), © 2026 Túlio Ribeiro de Moura e Silva —
  declarada também em `pyproject.toml` e no README.

## [0.4.3] — 2026-09-08

Sem mudança de código.

### Docs
- README reescrito: seção "Princípios que o código segue" no lugar dos
  arquivos de notas na raiz (removidos). Docstrings, testes e histórico
  sem referências a projetos externos.

## [0.4.2] — 2026-09-07

Resultado de comparar o motor com o que o monitor independente
`statuslicitacoes.com.br/api-pncp` documenta sobre a API de consulta.
Limites (tamanho de página por endpoint, formato de data, `pagina`
obrigatório, PCA com `dataInicio`/`dataFim`, 204 sem corpo, 400 sem
retry) já estavam corretos. Três ajustes:

### Fixed
- `Cliente.paginar` decidia "acabou" por `totalPaginas` com default 1 —
  envelope sem esse campo truncava na página 1 em silêncio. Agora prefere
  `paginasRestantes` (o campo que a spec indica), cai pra `totalPaginas`,
  e sem nenhum dos dois num envelope com dados levanta `PncpErro`.

### Changed
- HTTP 422 retenta no máximo 2 vezes (era a escada inteira). A spec o
  classifica como erro do cliente; o incidente real que o pôs entre os
  transitórios foi um 422 espúrio sob carga — duas tentativas cobrem
  isso, e um 422 legítimo (parâmetro errado) falha em segundos com o
  motivo do corpo na mensagem.

### Added
- `Motor.sonda()`: uma requisição barata em `/v1/atas` (o endpoint que o
  monitor usa como health-check), uma tentativa, devolve o tempo de
  resposta — pra decidir em 1s se vale iniciar uma coleta. O diagnóstico
  `python -m motor_pncp` passa a começar por ela.

### Verified
- Execução completa contra o portal real (município grande, 60 dias):
  649 contratações em várias páginas com `contar` = baixadas; itens,
  resultados e órgão respondendo; envelope real com `paginasRestantes`,
  `totalPaginas`, `totalRegistros`, `numeroPagina`, `empty`.

## [0.4.1] — 2026-09-06

Repositório passou a ser **público**. Sem mudança de código.

### Docs
- Removidas menções a caminhos locais da máquina de desenvolvimento.
- Instalação em modo editável: `pip install -e .`.

## [0.4.0] — 2026-09-06

### Added
- `python -m motor_pncp <ibge>`: diagnóstico ao vivo contra o PNCP real,
  fase a fase, com resumo separado por host (`api/consulta` × `api/pncp`
  caem independentemente). Responde "o motor quebrou ou o portal caiu?"
  sem abrir código; código de saída 1 se alguma fase falhou.
- Tag `v0.4.0` — primeira versão pinável. README passa a instruir
  `pip install "git+...@v0.4.0"`, nunca `master`.

### Verified
- Primeira execução contra o portal real: `api/consulta` 5/5 (envelope
  `totalPaginas`, campos `numeroControlePNCP`/`orgaoEntidade`/`esferaId`
  confirmados como o motor espera); `api/pncp` 0/2 por HTTP 503
  sustentado no portal — motor classificou certo, sem tratar como bug
  próprio.

## [0.3.2] — 2026-09-06

### Fixed
- **Disjuntor sem teto de contagem**: `sem_sucesso_limite` (600s) foi
  calibrado pra falha lenta (~5min, escada cheia). Quando um storm
  confirmado encurta a escada (`tentativas_curtas`), cada falha passa a
  custar segundos e só o relógio deixava o disjuntor mastigar a fila
  inteira — medido em produção: 139-196 falhas seguidas, 36-86% da fila,
  0 itens gravados. Novo `Config.falhas_seguidas_teto` (40) corta antes.

### Docs
- `ipca()`: passar `inicio` incremental (60 dias antes da última
  sincronização), não `None` toda vez — senão a série inteira é rebaixada
  em toda sync (a parte de persistência fica com o chamador).
- Dica de índice em `municipio_ibge` no schema do consumidor (22,7s →
  0,4s medido).

## [0.3.1] — 2026-09-06

Resultado de `/code-review high` (4 agentes independentes: linha a linha,
regressão, reuso/simplificação/eficiência, altitude) e `/security-review`
(zero achados — sem superfície de ataque).

### Fixed
- **Perda de dados silenciosa** — `Cliente.paginar` e `Motor.itens_da_compra`
  não distinguiam "consulta sem registros" de "portal engasgou no meio da
  listagem": página 2+ vazia depois de uma página que anunciou mais era
  tratada como fim normal, a janela/contratação era marcada como concluída
  e os registros restantes sumiam pra sempre. Agora levanta `PncpErro`.
- `contar_contratacoes()` não passava `modo_404="retry"`: um 404
  transitório virava 0 sem marcar `parcial=True`, violando o próprio
  contrato da função.
- `ipca()` fazia requisição avulsa fora do `Cliente`, sem retry/backoff —
  agora usa o mesmo caminho resiliente das outras fases.
- `Config` aceitava `tentativas_padrao`/`tentativas_curtas` = 0, o que
  fazia `Cliente.get` devolver `None` sem nunca tentar (falha virando
  ausência). Agora valida `>= 1`.
- Docstring de `pendente()` e do parâmetro `progresso` (thread-safety)
  encorpados com casos de borda que faltavam.

### Changed
- `Cliente.get`: `erro_404`/`retry_404` (dois booleanos independentes)
  viram `modo_404: Literal["ausente", "erro", "retry"]` — a 4ª combinação
  deixa de ser "não usada" pra ser impossível. Interno (`Cliente` não é
  API pública).
- `Motor._baixar_com_disjuntor`: extrai o loop de disjuntor/progresso/
  falha que `contratacoes()` e `_janela_generica()` duplicavam idêntico.
  Comportamento e mensagens preservados.

### Deferred (decisão, não omissão)
- Unificar `itens_e_resultados()`/`termos_aditivos()`: mensagens de
  disjuntor divergem por domínio; abstração pra 2 call sites não compensa.

## [0.3.0] — 2026-09-05

### Added
- `Dedup`: agrupa avisos de retry da mesma causa (ex.: HTTP 503) entre
  requisições diferentes — sem isso, um storm numa fila de milhares
  produzia uma linha idêntica por ocorrência no callback de `progresso`.
  Configurável via `Config.janela_operacional` (default 300s).
- `dominio.dt()`: parser de data/hora do PNCP ciente de fuso (string sem
  fuso explícito vira UTC direto, nunca horário local).

### Fixed
- HTTP 422 agora é tratado como transitório (retry), não só
  500/502/503/504 — incidente real: o portal devolveu 422 numa noite de
  429/500/503/504, numa janela que, refeita depois, respondeu 204 normal.
- Corpo da resposta de erro (`_motivo`) anexado na mensagem final de
  `PncpErro` — antes a mensagem era só "HTTP 422 em /caminho", sem nada
  pra diagnosticar sem reproduzir a chamada à mão.
- `Orgao.esfera` lia um campo (`poderId`) sem uso — corrigido para
  `esferaId` (M/E/F/N), o campo real.

## [0.2.0] — 2026-09-05

### Added
- `Config` (dataclass congelado): limiares de resiliência
  (`conexoes_paralelas`, `falhas_consecutivas_limite`,
  `sem_sucesso_limite`, etc.) deixam de ser constantes fixas de módulo —
  cada sistema consumidor ajusta sem precisar de fork.
- Registros tipados (`tipos.py`): `Contratacao`, `Item`, `Resultado`,
  `Contrato`, `Ata`, `PlanoPca`, `TermoAditivo`, `Orgao` — envelopes finos
  sobre o JSON cru do PNCP (`.raw` continua sendo a fonte da verdade).
- Cobertura completa da API: `Motor.contratos`, `.atas`, `.pca` (via
  `_janela_generica`) e `.termos_aditivos`.
- CI (GitHub Actions): pytest + ruff + bandit em push/PR, Python 3.10 e
  3.12.

## [0.1.0] — 2026-09-05

### Added
- Versão inicial: motor de coleta do PNCP independente de sistema.
- Fronteira: o motor faz HTTP resiliente contra o portal (retry com
  backoff, paralelismo e nº de tentativas adaptativos, disjuntor por
  tempo sem sucesso) e devolve dados crus — sem opinião sobre
  persistência.
- Estado de resiliência por instância (`Motor`/`Cliente`/`Adaptativo`),
  nunca de módulo — duas coletas no mesmo processo não se pisam.
- Cobertura: `contratacoes`, `itens_e_resultados`, `consultar_orgao`,
  `contar_contratacoes`, `ipca`.
