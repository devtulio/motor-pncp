---
name: feedback_agregar_por_cnpj_sem_unidade
description: "No PNCP, agregar contratação por CNPJ de órgão sem olhar o campo unidade produz número errado sem nenhum aviso"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f839e097-c77b-44b4-abee-ba4dd28ac2e4
  modified: 2026-07-31T00:18:31.285Z
---

O PNCP organiza contratação em **órgão** (CNPJ) e **unidade**. Há unidades de
terceiros penduradas no CNPJ de outro ente: sob o CNPJ do TCE-RO existem
`FUNDO ESTADUAL DE SAÚDE DE RO`, `PREFEITURA MUNICIPAL DE BURITIS`,
`HOSPITAL INFANTIL COSME E DAMIÃO` e mais vinte — 766 registros, 71% do valor que
o tribunal aparenta declarar.

Somar por CNPJ sem filtrar unidade produz total bem-formado e errado. No caso, o
TCE-RO aparecia com 34% dos contratos fora do prazo do art. 94; limpo, são 2% em
2024 e 0% em 2025.

**Dois cuidados ao aplicar o filtro:**

1. **Filtrar por unidade, não pelo texto do objeto.** Regex no objeto acusa
   falsamente: tribunal grande compra medicamento e material odontológico porque
   mantém ambulatório para os servidores.
2. **Conferir os nomes reais das unidades antes de excluir.** Uma regra que
   exigia "tribunal" no nome da unidade acusou cinco tribunais inocentes, cujas
   unidades se chamam `COORD. AQUISIÇÃO DE BENS E SERV.`,
   `SECRETARIA EXECUTIVA DE ADMINISTRAÇÃO`, `INSTITUTO SERZEDELLO CORRÊA` —
   departamento interno, não ente estranho.

**Why:** é erro invisível. O CSV sai bonito, o total fecha, e a conclusão do
trabalho passa a descrever compras de outra entidade.

**How to apply:** em qualquer agregação de PNCP por órgão, listar
`Counter(unidade)` antes de somar qualquer coisa. Ver
[[feedback_api_publica_falha_vs_ausencia]].
