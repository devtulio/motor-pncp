---
name: feedback_watcher_sem_saida
description: Watcher em background precisa de condição de saída além do sinal esperado — e matar um processo exige desfazer quem esperava por ele
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 265c7a90-356a-4fd9-a7f9-5d6b5e7b391b
  modified: 2026-08-01T23:59:47.937Z
---

Monitor em background que espera um sinal (`until grep -q FIM arquivo; do
sleep 30; done`) tem **condição de saída única**: se o sinal nunca vier, ele
roda para sempre.

Aconteceu em 2026-08-01: lancei o watcher, depois **matei o processo que
escreveria o `FIM`** ao trocar o método de medição, e não voltei para
encerrar o watcher. Ficou em laço até o usuário perceber e avisar — eu não
notei sozinho.

**Why:** ao trocar de abordagem no meio do caminho, a atenção vai para o
método novo; o que dependia do antigo some do radar. E watcher parado
consome quase nada, então nada denuncia o vazamento.

**How to apply:**

- Todo watcher recebe **duas saídas**: o sinal esperado **e** o fim do
  processo observado (ou um teto de iterações). Ex.:
  `until grep -q FIM f || ! tasklist //FI "PID eq N" | grep -q N; do ...`
- Antes de matar um processo, perguntar **quem esperava por ele** e encerrar
  junto.
- Ao dar por encerrado um assunto que envolveu background, conferir as tarefas
  em execução (`TaskOutput` com `block:false`; `TaskStop` para encerrar) em
  vez de assumir que terminaram.
