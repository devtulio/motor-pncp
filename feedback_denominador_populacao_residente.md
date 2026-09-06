---
name: feedback_denominador_populacao_residente
description: População residente não descreve quem o município atende — Olímpia recebe 1 milhão de visitantes/ano para 55 mil habitantes
metadata: 
  type: feedback
---

Normalizar por **população residente** (IBGE) trata todo município como se
servisse apenas o próprio povo. **Olímpia tem 55.477 habitantes e recebe mais
de 1 milhão de visitantes por ano** — contexto que o usuário conhece da região
e que nenhum dado nosso revelava.

**Why:** o denominador errado não é erro de cálculo, é erro de leitura: um
município com grande população flutuante aparece gastando mais por habitante
sem gastar mais por pessoa atendida. O IBGE não publica população flutuante
por município, então não há como corrigir o número — só declarar o limite dele.

**How to apply:** ao normalizar qualquer indicador por população, perguntar ao
usuário se algum município da amostra tem demanda muito acima da residente
(turismo, distrito industrial, hospital regional, universidade). Registrar em
`RESSALVAS_DE_DENOMINADOR` (em `servicos/consultas/comparativo.py`) e imprimir
a nota junto do indicador. Não inventar fator de correção sem fonte.

Vale a lição geral: **o usuário tem contexto de domínio que o dado não tem.**
Antes de tratar um outlier como achado, perguntar — foi assim que a leitura
de Olímpia mudou de "gasta muito" para "publica com rigor" (ver
[[project_comparativo_municipios]]).
