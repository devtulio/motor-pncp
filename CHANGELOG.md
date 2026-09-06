# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [0.3.2] — 2026-09-06

Portado do `relatorio_correcoes_motor_sync_pncp.md` (rodadas 4-5, sessão
do Pretiarium Free, 2026-09-06).

### Fixed
- **Disjuntor sem teto de contagem** (achado 11): `sem_sucesso_limite`
  (600s) foi calibrado pra falha lenta (~5min, escada cheia). Quando um
  storm confirmado encurta a escada (`tentativas_curtas`), cada falha
  passa a custar segundos e só o relógio deixava o disjuntor mastigar a
  fila inteira — medido: 139-196 falhas seguidas, 36-86% da fila, 0
  itens gravados. Novo `Config.falhas_seguidas_teto` (40) corta antes.
  O motor tinha exatamente a combinação que dispara isso (achados 5+10)
  sem o 11.

### Docs
- `ipca()`: passar `inicio` incremental (60 dias antes da última
  sincronização), não `None` toda vez — a série inteira era rebaixada em
  toda sync (achado 12; a parte de persistência fica com o chamador).
- Dica de índice em `municipio_ibge` no schema do consumidor (22,7s →
  0,4s medido).

## [0.3.1] — 2026-09-06

Resultado de `/code-review high` (4 agentes independentes: linha a linha,
regressão contra os 3 `pncp.py` de origem, reuso/simplificação/eficiência,
altitude) e `/security-review` (zero achados — sem superfície de ataque).

### Fixed
- **Perda de dados silenciosa** — `Cliente.paginar` e `Motor.itens_da_compra`
  não distinguiam "consulta sem registros" de "portal engasgou no meio da
  listagem": página 2+ vazia depois de uma página que anunciou mais era
  tratada como fim normal, a janela/contratação era marcada como concluída
  e os registros restantes sumiam pra sempre. Proteção que o Licitarium
  Pro já tinha (achado 2026-08-29) e não tinha sido portada. Agora levanta
  `PncpErro`.
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
  Configurável via `Config.janela_operacional` (default 300s). Portado do
  padrão `_registrar_operacional` do Licitarium Pro.
- `dominio.dt()`: parser de data/hora do PNCP ciente de fuso (string sem
  fuso explícito vira UTC direto, nunca horário local).

### Fixed
- HTTP 422 agora é tratado como transitório (retry), não só
  500/502/503/504 — achado real: o portal devolveu 422 numa noite de
  429/500/503/504, numa janela que, refeita depois, respondeu 204 normal.
- Corpo da resposta de erro (`_motivo`) anexado na mensagem final de
  `PncpErro` — antes a mensagem era só "HTTP 422 em /caminho", sem nada
  pra diagnosticar sem reproduzir a chamada à mão.
- `Orgao.esfera` lia um campo (`poderId`) que nunca existiu em nenhum dos
  3 sistemas de origem — corrigido para `esferaId` (M/E/F/N), o campo
  real.

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
  `_janela_generica`, generalizando o padrão `_sync_por_janela` do
  Licitarium Free/Pro) e `.termos_aditivos` (padrão do Licitarium Pro,
  com o disjuntor que lá não tinha).
- CI (GitHub Actions): pytest + ruff + bandit em push/PR, Python 3.10 e
  3.12.

## [0.1.0] — 2026-09-05

### Added
- Extração inicial do `pncp.py` do Pretiarium Free v0.1.40 (baseline —
  3 rodadas de auditoria sobre travamentos reais, 2026-09-05) para um
  motor independente de sistema.
- Fronteira: o motor faz HTTP resiliente contra o portal (retry com
  backoff, paralelismo e nº de tentativas adaptativos, disjuntor por
  tempo sem sucesso) e devolve dados crus — sem opinião sobre
  persistência.
- Estado de resiliência movido de módulo para instância (`Motor`/
  `Cliente`/`Adaptativo`), eliminando por construção o vazamento de
  beacon entre coletas (achado do Pretiarium Free).
- Cobertura: `contratacoes`, `itens_e_resultados`, `consultar_orgao`,
  `contar_contratacoes`, `ipca`.
