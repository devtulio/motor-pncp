---
name: feedback_api_publica_falha_vs_ausencia
description: "Em coleta de dados por API, nunca cachear falha de rede como ausência de dado — e conferir se o filtro que você passou é de fato aplicado"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f839e097-c77b-44b4-abee-ba4dd28ac2e4
  modified: 2026-07-30T04:07:24.041Z
---

Ao coletar dados de API pública para análise, dois erros silenciosos já
produziram resultado inventado:

1. **Falha de rede gravada como "não existe".** Se um HTTP 500/429 for tratado
   como resposta vazia e cacheado, a instabilidade (ou o rate limit) do servidor
   entra na análise como achado. No PNCP isso marcou 248 de 249 órgãos como "sem
   contratos". Coletor tem de distinguir "o servidor disse que não existe" (400,
   404) de "o servidor não respondeu", só gravar cache após resposta válida, e
   reportar no fim os pares sem resposta.
2. **Filtro aceito e ignorado.** `cnpjOrgao` em `/contratacoes/publicacao` do
   PNCP não é rejeitado nem sinalizado — só não é aplicado, e a resposta traz o
   país inteiro. Antes de confiar em qualquer filtro de API, conferir se o
   resultado realmente só contém o que foi pedido.

Corolário: HTTP 500 pode ser rate limit disfarçado. Se 500 aparece sob
paralelismo, testar sequencialmente antes de culpar o servidor — no PNCP era 429
por rajada, e um intervalo mínimo global entre requisições resolveu e ficou mais
rápido no total, por não gastar minutos em backoff.

**Why:** os dois erros são invisíveis — produzem CSV bem-formado, com números
plausíveis, que sustentam conclusão falsa.

**How to apply:** em qualquer coletor novo, escrever a função de busca devolvendo
`(existe, dados)` e levantando exceção na falha; e validar um filtro conferindo a
amostra de retorno antes de rodar a coleta inteira.
