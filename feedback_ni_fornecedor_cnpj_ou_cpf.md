---
name: feedback_ni_fornecedor_cnpj_ou_cpf
description: O niFornecedor do PNCP guarda CNPJ e CPF — máscara de CNPJ às cegas adultera o documento de pessoa física
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 265c7a90-356a-4fd9-a7f9-5d6b5e7b391b
  modified: 2026-08-01T18:16:19.994Z
---

O campo `niFornecedor` do PNCP (coluna `fornecedor_ni` no Licitarium) guarda
**CNPJ de 14 dígitos e CPF de 11**. No acervo real de Orindiúva são 34 pessoas
físicas — 14 em `contratos` e 20 em `itens`.

Formatar como CNPJ sem olhar o tamanho transforma `01472188616` em
`01.472.188/616-`: documento adulterado saindo em relatório oficial.

**Why:** o nome do campo e o contexto ("fornecedor") sugerem pessoa jurídica, e
a amostra que se olha primeiro costuma ser toda de CNPJ. Só contando os
tamanhos no banco (`SELECT LENGTH(...) GROUP BY`) é que a pessoa física
aparece.

**How to apply:** decidir pelo número de dígitos — 14 → `00.000.000/0000-00`,
11 → `000.000.000-00`, qualquer outro tamanho sai como veio (identificador
estrangeiro ou ausente). É o que faz `relatorios.documento()`. Antes de
formatar qualquer identificador vindo de API pública, contar os tamanhos
distintos no acervo real. Ver [[project_licitarium_free]].
