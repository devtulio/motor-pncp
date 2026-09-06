---
name: reference_api_dadosabertos_comprasgov
description: "API dadosabertos.compras.gov.br — cobertura PARCIAL (só quem opera via Compras.gov), modalidades no domínio SIASG (Dispensa=6, não 8), medida ao vivo em 2026-08-13"
metadata: 
  type: reference
---

# API Compras.gov.br Dados Abertos (dadosabertos.compras.gov.br)

Analisada ao vivo em 2026-08-13 (OpenAPI + sondas reais) para o projeto
Rationarium (descontinuado — mantido aqui pelo valor genérico dos fatos).
**NÃO substitui o PNCP como fonte.**

Fatos medidos (não documentação — sondas):
- **Cobertura parcial**: os endpoints `*_PNCP_14133` só têm o que tramitou
  PELO Compras.gov.br. Orindiúva (3534203) = **0 dispensas em 11 meses**
  (PNCP tem 17 só em 2026); Rio Preto = 277 (usa a plataforma); Cuiabá
  aparece. Município que licita por BLL/BNC/BEC e publica direto no PNCP é
  invisível aqui.
- **`codigoModalidade` é domínio SIASG, não PNCP**: Dispensa = **6** (8.324
  registros em mar/2025); o código 8 do PNCP devolve **0 em silêncio** —
  mesma classe do [[feedback_api_publica_falha_vs_ausencia]].
- `tamanhoPagina` obrigatório entre **10 e 500**; janela de datas **≤365
  dias**; envelope `{resultado, totalRegistros, totalPaginas,
  paginasRestantes}`.
- **Sem autenticação** nos módulos de consulta; bearer só para `/usuarios/*`
  e `/alice/*` (ALICE = analisador de editais; conta é ação do usuário).

Oportunidades reais (opt-in, nunca substituição):
- módulo 03 (preços praticados por CATMAT/CATSER, filtro por
  município/UF/data) — banco de preços NACIONAL por código de catálogo,
  complementa a pesquisa regional por descrição;
- módulo 07/2_ e 3_ (itens e resultados EM LOTE por janela) — substituiria a
  fase 3 (item a item na API interna do portal) SE a cobertura fosse total;
  não é;
- resultados trazem `porteFornecedorId`/`naturezaJuridicaId` (roadmap
  ME/EPP); endpoints `_CSV` para cargas.

## CSVs de repositorio.dados.gov.br/seges/comprasgov/ (medido 2026-08-13)

Mesma cobertura parcial da API — o diário tem `usuario_nome` =
"Compras.gov.br" em **100%** das 1.531 compras; Orindiúva ausente.
Vistas `VW_FT_PNCP_COMPRA` / `COMPRA_ITEM` / `DM_PNCP_ITEM_RESULTADO`
em anual/mensal/diário + `compras_legado` (8.666) + `catalogo_cnbs`;
anual de itens ≈ 2,2 GB. RESULTADO traz `porte_fornecedor`,
`natureza_juridica`, `percentual_desconto`, `ordem_classificacao_srp`.
Aviso: o "diario-latest" continha dados de 2024-05 com Last-Modified de
jul/2026 — conferir o CONTEÚDO, nunca confiar no nome do arquivo.

## Decisões 2026-08-14 sobre os dois usos propostos

- **B (porte/benefício ME/EPP): ENTREGUE sem Compras.gov** — descoberto que
  `aplicacaoBeneficioMeEpp`, porte e natureza jurídica já vinham no
  resultado de item do PNCP, gravados no ItemRaw. Materializado por
  migração (0.7.0); indicador no relatório de Análise (Orindiúva: 55,4%
  do valor a pequeno porte, 6,6% com benefício formal).
- **A (quadro nacional de preços por CATMAT): INVIÁVEL hoje** — amostra
  aleatória de 4.000 itens dos 16 municípios: **0,0% com
  `catalogoCodigoItem`** (fora do Compras.gov ninguém usa o catálogo).
  Sem chave de join honesta; casar por descrição seria falso positivo em
  série. Gatilho de reabertura: cliente que use Compras.gov, ou itens
  passarem a vir com CATMAT.
- **ALICE**: exige conta/bearer; alertas voltados ao gestor DENTRO do
  Compras.gov; sem valor direto para os sistemas hoje — é o
  "concorrente" estatal de trilhas de auditoria (CGU), referência de
  método.
