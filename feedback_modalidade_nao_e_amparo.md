---
name: feedback_modalidade_nao_e_amparo
description: Modalidade do PNCP não determina o limite legal — o amparo determina; classificar por modalidade produz acusação falsa de irregularidade
metadata: 
  type: feedback
---

Em dados do PNCP, **modalidade não é amparo legal**. `modalidade_id=8`
("Dispensa") NÃO significa "sujeita ao limite do art. 75, II da Lei
14.133/2021" — é só o rótulo do procedimento. Quem define se existe teto de
valor, e qual, é o `amparoLegal` (que vem dentro do `raw`, não é campo).

No acervo real do sistema de origem (13.891 dispensas) convivem três situações que
um filtro por modalidade mistura:

- **Art. 75, II** (8.838) — compras e serviços comuns; único que responde ao
  teto de compras.
- **Art. 75, I** (4.124) — obras e engenharia; teto próprio, o dobro.
- **Demais incisos (~800) e outras leis (23)** — Lei 11.947/2009 (PNAE), Lei
  14.284/2021, Lei 14.628/2023: a dispensa decorre da NATUREZA do objeto
  (emergência, licitação deserta, hortifruti direto do produtor), não do
  valor. Não há teto contra o qual comparar.

**Por que importa:** o relatório acusava a compra de gêneros da agricultura
familiar (R$ 1.057.448,50) como "1688,1% do limite do art. 75, II" — uma
acusação de irregularidade grave, sobre o maior valor da lista, onde não
havia irregularidade nenhuma. Falso positivo em relatório vendido a
prefeitura é pior que indicador ausente: é justamente o número que chamaria
atenção numa reunião ou numa defesa perante o TCE.

**Como aplicar:** ao construir qualquer indicador de conformidade sobre
contratação pública, classificar pelo dispositivo legal invocado, nunca pelo
rótulo do procedimento. Verificar o defeito rodando contra o acervo real e
OLHANDO o PDF — nenhum teste de fixture pegaria, porque a fixture nasce com
o amparo que o autor do teste imaginou. Ver também
[[feedback_regra_automatica_acusa_pelo_nome]] (mesma família: classificador
automático produz falso positivo antes de achado) e
[[feedback_auditoria_estatica_nao_ve_a_fronteira]].

Achado em 2026-08-12, no `licitarium-relatorios`; corrigido em
`painel.teto_da_dispensa()`, usada pelos dois consumidores que tinham o
defeito copiado.
