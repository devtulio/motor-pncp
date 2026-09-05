---
name: feedback_cruzar_dentro_do_orgao
description: Município não é a unidade de comparação — Prefeitura e Câmara são entes distintos; cruzar plano de um com execução de outro produz número sem sentido
metadata: 
  node_type: memory
  type: feedback
  originSessionId: daa359fa-07cd-4f8d-920f-7a48974844d1
  modified: 2026-08-12T23:45:05.552Z
---

Num município convivem **entes distintos com CNPJ próprio** — Prefeitura,
Câmara, autarquias, fundos. Cada um publica seu próprio Plano de Contratações
Anual, executa seu próprio orçamento e presta contas separadamente. Escopar
por município e cruzar tudo junto mistura entes que não se correspondem.

**O caso:** em Orindiúva a **Câmara** publicou PCA para 2026 (R$ 254.249,95) e
a **Prefeitura** não publicou nenhum. O relatório cruzava no nível do
município e comparava o plano da Câmara com a execução da Prefeitura
(R$ 15.837.262,73) — **zero interseção**. Resultado: "1,6% executado" sem
significado, e as 248 famílias contratadas pela Prefeitura acusadas de estar
"fora do PCA", quando o que existe é ausência de plano.

**Como aplicar:** qualquer indicador que confronte duas fontes (planejado ×
executado, previsto × realizado, cota × consumo) tem que casar pela unidade
que de fato publica os dois lados. Antes de construir, checar no dado real
**quais CNPJs aparecem de cada lado** — se os conjuntos não se sobrepõem, o
cruzamento está errado por construção.

**A ausência é o achado.** Órgão que executou sem plano publicado não deve
virar N acusações de fracionamento: deve virar uma linha dizendo que não
publicou o plano — que é obrigatório (art. 12, VII, da Lei 14.133/2021). E
distinguir "0% executado" de "nenhum dado de execução": a Câmara tem 131 itens
planejados e **nenhum** item executado no acervo, que é ausência de dado, não
fracasso de execução. Por isso o quadro traz a contagem dos dois lados.

Mesma família de [[feedback_agregar_por_cnpj_sem_unidade]] (unidade de
terceiro pendurada no CNPJ de outro ente) e de
[[feedback_modalidade_nao_e_amparo]] (classificar pelo rótulo errado produz
acusação falsa). Achado pelo usuário em 2026-08-12, no `licitarium-relatorios`;
corrigido em `consultas/pca.py::aderencia`, que passou a calcular por órgão e
somar depois.
