---
name: feedback_medicao_de_api_expira
description: Medição de comportamento de API de terceiro envelhece — remedir antes de tratar como premissa de desenho; e não calibrar ritmo contra recusa que não é função do nosso ritmo
metadata: 
  type: feedback
---

Número medido contra API pública que virou premissa em documento de
arquitetura precisa ser **remedido** antes de embasar decisão nova. No
sistema de origem, o DESIGN.md afirmava "4 conexões sem pacing fazem 13 consultas
em 0,9 s sem nenhum 429" (medido em sessão anterior); em 2026-08-14 o mesmo
portal devolveu 429 em 13 de 60 requisições com **uma** conexão só.

**Why:** o comentário de código e o doc descreviam um portal que já não se
comportava assim, e a defesa desenhada em cima daquele número ("o PNCP não
recusa: ele demora") deixava o caminho de recusa mal coberto.

**How to apply:**
- Antes de otimizar contra um limite de terceiro, remedir. Datar a medição
  no doc, para a próxima sessão saber a idade dela.
- Se a taxa de recusa **não** é monotônica no seu intervalo entre
  requisições (0,5 s deu 3/12 e 1,0 s deu 5/12), então não é função do seu
  ritmo — pare de calibrar pacing e passe a **tolerar a perda**: a consulta
  que cai não pode derrubar as irmãs. Ver [[project_licitarium_free]].
- Tolerar não é engolir: grave o que veio, mas **não deixe o marcador de
  "sincronizado até" avançar** sobre a janela que faltou, senão vira buraco
  silencioso — mesma lição de [[feedback_api_publica_falha_vs_ausencia]].
- Medição de API travada por retry: sonda que só repete em timeout perde o
  caso; repetir também em 5xx foi o que revelou os dois regimes distintos
  (500 lento vs. 429 rápido) do mesmo endpoint na mesma noite.
