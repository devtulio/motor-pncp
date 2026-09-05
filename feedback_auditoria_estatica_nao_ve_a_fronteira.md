---
name: feedback_auditoria_estatica_nao_ve_a_fronteira
description: Auditoria de código + testes verdes não acha defeito de fronteira; rodar contra a API e os arquivos reais é uma segunda passada obrigatória
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 05271d3a-b116-43f5-b137-3acfc8ff3d1b
  modified: 2026-08-04T21:39:44.179Z
---

Auditoria estática (leitura integral + testes de unidade + mutação) e auditoria
de fronteira (rodar contra a API e os arquivos de verdade) acham **classes
diferentes** de defeito. Fazer só a primeira dá falsa sensação de cobertura.

Caso real (Peculium, 2026-08-04, duas rodadas no mesmo dia):

- **1ª rodada, estática:** 25 achados em 10,6k linhas, 91% de cobertura, tudo
  verificado por mutação. Nenhum dos três abaixo apareceu.
- **2ª rodada, contra a realidade:** 3 defeitos, todos invisíveis sem rede e sem
  documento real.
  1. `series.baixar()` pedia a série diária inteira; a API do BCB devolve **406**
     acima de ~10 anos. A curva de renda fixa **nunca funcionou** — dizia "ligue
     a rede" com a rede ligada.
  2. `atualizar_curvas` pedia a curva de HOJE; o BCB publica o CDI com um dia
     útil de atraso. Falharia **todo dia**, para sempre.
  3. Débito+crédito na MESMA corretora virava transferência de A para A: o
     importador (`INSERT` direto) gravava o que a porta manual recusa, e o razão
     acusava saldo negativo falso.

**Why:** os três só existem no encontro com o mundo. Nenhum teste de unidade os
pega, porque o mock devolve o que o autor imaginou que a API devolve. E o
sintoma dos três era mensagem enganosa, não exceção — a suíte fica verde.

**How to apply:**
- Depois da auditoria estática, fazer uma passada **de fronteira**: toda função
  que fala com rede, lê arquivo de terceiro ou usa `date.today()` roda contra o
  alvo real, uma vez, e o resultado é lido.
- **`date.today()` em código que consulta série externa é suspeito por
  definição**: toda fonte publica com atraso.
- Limite de API se descobre medindo em degraus (sem intervalo / 11 anos / 10 /
  2), não lendo documentação.
- Cruzar os números **entre si** acha o que não estoura: no Peculium, custo de
  aquisição por 5 caminhos diferentes (razão, painel, carteira, 2 relatórios).
  Divergência entre duas telas sobre o mesmo dado é o cheiro.
- Importador que faz `INSERT` direto foge da validação do domínio. Vale o teste
  de invariante: *o importador nunca grava o que a porta manual recusaria*.

Relacionado: [[feedback_kwargs_ignorado_em_silencio]] (mesma família: log verde
não prova efeito), [[feedback_conferir_teste_falhando]], [[project_peculium]].
