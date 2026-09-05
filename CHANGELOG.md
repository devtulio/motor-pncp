# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

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
