---
name: feedback_regra_automatica_acusa_pelo_nome
description: Regra que classifica entidade por texto sempre acusa inocente; ler os nomes reais antes de o resultado virar número
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f839e097-c77b-44b4-abee-ba4dd28ac2e4
  modified: 2026-07-31T00:39:48.288Z
---

Em pesquisa com dado público, toda regra que classifica por casamento de texto
produziu falso positivo antes de produzir achado. Aconteceu quatro vezes numa pesquisa com dados do PNCP (2026-07):

1. Regex de objeto para achar compra alheia acusou tribunais que compram
   medicamento por terem **ambulatório próprio**.
2. Regra que exigia "tribunal" no nome da unidade acusou cinco tribunais cujas
   unidades se chamam `COORD. AQUISIÇÃO DE BENS E SERV.` ou
   `INSTITUTO SERZEDELLO CORRÊA` — departamento interno.
3. Auditoria que procurava "município" em nome de unidade acusou os próprios
   TCMs: `TRIBUNAL DE CONTAS DOS MUNICIPIOS DA BAHIA`.
4. Sonda de portal deu 8 tribunais como "sem jurisprudência"; os 8 eram artefato
   (casca em JavaScript, subdomínio, URL fora do padrão, TLS quebrado).

O mesmo vale para deduplicação, que erra dos dois lados: chave
`órgão+fornecedor+data+valor` apagou dois contratos reais de vigilância em
unidades regionais diferentes; exigir objeto idêntico deixou passar republicação
cuja descrição vinha truncada em 139 contra 215 caracteres. A regra correta era
comparar objetos por **prefixo** — mesmo contrato se um texto é começo do outro.

**Why:** o resultado da regra sai bem-formado e plausível. Se ninguém ler os
nomes que ela casou, uma acusação falsa entra no artigo com aparência de dado.

**How to apply:** depois de rodar qualquer classificador por texto, imprimir os
valores distintos que ele casou e ler. Antes disso, o número não existe. Ver
[[feedback_api_publica_falha_vs_ausencia]] e
[[feedback_agregar_por_cnpj_sem_unidade]].
