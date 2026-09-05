---
name: feedback_contar_sem_paginar
description: "Para saber quantos registros uma API tem, ler o total do envelope — nunca paginar tudo para contar"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 265c7a90-356a-4fd9-a7f9-5d6b5e7b391b
  modified: 2026-08-01T23:45:00.325Z
---

Para medir volume numa API paginada, ler o **total do envelope** (no PNCP,
`totalRegistros` na primeira página) em vez de baixar tudo e contar.

Custo real da diferença, medido em 2026-08-01 no Licitarium: contar paginando
levou de 220 a 700 segundos **por município** e **falhou por timeout** justo no
maior (Olímpia-SP, 5.982 contratações). Lendo o envelope, a mesma resposta sai
em uma requisição por consulta.

**Why:** gastei uma tarde inteira medindo do jeito errado, e o número que eu
queria estava no envelope desde a primeira resposta. Pior: o município que não
foi medido era exatamente o que mudava a decisão de projeto — 286 MB e ~7 h de
coleta, contra ~10 MB dos vizinhos pequenos.

**How to apply:** antes de escrever qualquer contagem sobre API paginada,
inspecionar o envelope da primeira página (`totalRegistros`, `totalPaginas`,
`count`, `X-Total-Count`). Vale também para estimar: no Licitarium,
`pncp.estimar_volume` deriva itens/MB/tempo do total e acertou 2.672 itens
contra 2.674 reais. E não presumir volume por população: Nova Granada (21 mil
habitantes) tem zero registros; Olímpia (53 mil) tem 5.982. Ver
[[project_licitarium_free]] e [[feedback_api_publica_falha_vs_ausencia]].
