# Política de versão e release

Vale para este repositório. Baseada em SemVer 2.0.0, Keep a Changelog e
no que a literatura de release engineering mediu (referências no fim).

## 1. O que é a API pública (o contrato)

Só isto é coberto pelo número de versão:

- Tudo exportado em `motor_pncp/__init__.py`: `Motor` e seus métodos
  públicos (nome, assinatura, tipo de retorno, exceções levantadas),
  `Config` (campos e defaults), os dataclasses de `tipos` (properties),
  as exceções, os helpers de `dominio`.
- O CLI `python -m motor_pncp`: argumentos e código de saída.

**Não é contrato** (mesmo que alguém dependa — Hyrum's Law): módulos com
`_` (`_http`, `_resiliencia`), texto de mensagens de erro e de progresso,
ordem interna de requisições, nomes de chaves usadas pelo `Dedup`, e os
**valores** dos limiares de `Config` (podem ser recalibrados em patch;
o que é contrato é o campo existir com o mesmo significado).

## 2. Como o número muda (SemVer estrito)

| Mudança | Bump | Exemplo |
|---|---|---|
| Quebra do contrato | **major** | remover/renomear método público, mudar tipo de retorno, exceção nova em caminho que não levantava |
| Adição compatível | **minor** | método novo, campo novo em `Config` com default, property nova em um tipo |
| Correção compatível, recalibração de limiar, refactor interno | **patch** | fix de retry, ajuste de `sem_sucesso_limite`, otimização |
| Só documentação (README, MANUAL, CHANGELOG, docstring, comentário) | **nenhum** | commit em `master`, sem tag |

Versão reflete comportamento. Mudança que não altera comportamento não
altera versão.

## 3. Toda versão = tag anotada + release no GitHub

Sem exceção e sem meio-termo: o release é o sinal que o consumidor lê.
Notas do release = a seção daquela versão no `CHANGELOG.md`.

```bash
git tag -a vX.Y.Z -m "motor_pncp X.Y.Z — <uma linha>"
git push && git push origin vX.Y.Z
gh release create vX.Y.Z --title "motor_pncp vX.Y.Z" --notes-file notas.md --latest
```

Consumidor instala **sempre por tag**, nunca `master`:
`pip install "git+https://github.com/devtulio/motor-pncp.git@vX.Y.Z"`.

## 4. Cadência: sob demanda, lote pequeno

Cada correção vira o próprio patch assim que passa nos gates. Não
acumular. Release pequeno e frequente não piora qualidade e faz bug ser
corrigido mais rápido (Khomh et al.).

## 5. Gates antes de qualquer tag

1. `pytest` verde (roda contra `src/`, não contra uma cópia instalada).
2. `ruff check src tests` e `bandit -q -c pyproject.toml -r src` limpos.
3. **Mudança de comportamento exige smoke contra o portal real**:
   `PYTHONPATH=src python -m motor_pncp <ibge>` com todas as fases
   verdes (ou a falha explicada como externa). Mock não prova fronteira.
4. `CHANGELOG.md` com a seção da versão (Added / Changed / Deprecated /
   Removed / Fixed / Security), escrita no mesmo commit.
5. Versão bumpada em **um** lugar: `src/motor_pncp/__init__.py`
   (`pyproject.toml` lê de lá).
6. Push, CI verde, aí a tag. Nunca tag antes do CI.

## 6. Depreciação

Nada é removido sem antes viver **pelo menos uma minor** emitindo
`DeprecationWarning` e listado em *Deprecated* no CHANGELOG. Remoção só
em major, com *Removed* no CHANGELOG e nota de migração.

Churn rule: quando o motor quebra contrato, é a mudança no motor que
traz a nota de migração pronta pro consumidor — o consumidor não deve
descobrir lendo diff.

## 7. Suporte e pré-release

- Só a última release recebe correção. Sem backport.
- Pré-release (`X.Y.ZrcN`, PEP 440) só para mudança arriscada que precise
  de smoke no consumidor antes de fechar. Não vira `--latest`.

## Referências

- SemVer 2.0.0 — <https://semver.org/> (§4: 0.x é desenvolvimento
  inicial; FAQ: "se está em produção, já deveria ser 1.0.0").
- Keep a Changelog — <https://keepachangelog.com/pt-BR/1.0.0/>.
- PEP 440 — esquema de versão do Python.
- Adams & McIntosh, "Modern Release Engineering in a Nutshell", SANER
  2016 — o pipeline integração → CI → build → release, cada etapa com gate.
- Raemaekers, van Deursen & Visser, "Semantic versioning and impact of
  breaking changes in the Maven repository", JSS 2017; replicação por
  Ochoa et al., EMSE 2022 — ~1/3 dos releases quebram algo e quase metade
  viola SemVer: o contrato só vale se estiver escrito.
- Khomh, Adams, Dhaliwal & Zou, "Understanding the impact of rapid
  releases on software quality", EMSE 2015 — ciclos curtos não aumentam
  bugs pós-release e encurtam o tempo de correção.
- Winters, Manshreck & Wright, *Software Engineering at Google*, cap. 15
  (Deprecation) e Hyrum's Law — todo comportamento observável vira
  dependência; declarar o contrato e absorver a migração.
