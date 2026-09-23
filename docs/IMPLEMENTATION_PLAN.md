# AI Trading Research Lab — Plano de Implementação

> Plano de fases, plano de testes e riscos técnicos, derivado de
> MASTER_SPEC.md (seções 44–47, 76–78) e das decisões ADR-001 a ADR-006.
> Nenhuma execução real é implementada antes da infraestrutura e dos testes
> (seções 47 FASE 1, regra explícita do usuário).

---

## 1. Fases de implementação

### FASE 0 — Especificação (em andamento)

```text
[x] arquitetura        → docs/ARCHITECTURE.md
[x] contratos          → docs/AGENT_CONTRACTS.md
[x] segurança           → docs/SECURITY_MODEL.md
[x] decisões/ambiguidades → docs/decisions/ADR-001..006
[ ] aprovação final do usuário para iniciar Fase 1
```

### FASE 1 — Infraestrutura *(nenhuma execução real)*

Implementar:

- `core/configuration`: loader + schema de validação de `research.yaml`,
  `demo.yaml`, `real.yaml`.
- `core/events`: event bus interno (publish/subscribe).
- `core/state`: state machine de estratégia + state machine de sistema,
  com persistência que sobrevive a restart (seção 41).
- `database`: schema das 12 entidades + migrations.
- `core/models`: entidades como dataclasses/ORM.
- Logging estruturado com scrubbing automático de secrets.
- `agents/base/`: classe base de agente + enforcement de permissões
  (`permissions.py`), implementando a matriz do SECURITY_MODEL.md.
- `tests/unit`, `tests/security` básicos.

Critério de saída da fase: testes de config inválida rejeitada, secrets não
logados, e enforcement de permissão negando ação fora da matriz — todos
passando.

### FASE 2 — Data Engine

- Coletor contínuo (não importador — ADR-005) a partir da corretora-alvo via
  mecanismo oficialmente suportado.
- Validação, normalização, deduplicação, detecção de gaps, timezone.
- Split TRAIN/VALIDATION/TEST configurável (seção 23).
- Versionamento de dataset por snapshot (nunca sobrescreve).
- Definição do volume mínimo de amostra antes de um dataset ser aceito por
  qualquer consumidor (novo ADR quando o valor for escolhido).

### FASE 3 — Backtest Engine

- Motor determinístico, independente de LLM.
- Métricas: profit, drawdown, max_loss_streak, expectancy.
- Cenários de capital (100/300/500/700/1000).
- Walk-forward e Monte Carlo como módulos de `core/engine` (motor), consumidos
  depois pelo Statistician Agent.
- `tests/backtest` completo (seção 45): entradas, saídas, timestamps, payout,
  capital, drawdown, sequência de perdas, dados ausentes/duplicados, timezone.

### FASE 4 — Research Agents

- Researcher, Quant, Supervisor.
- Contratos formais conforme `docs/AGENT_CONTRACTS.md`.
- Enforcement de permissões ativo (Supervisor nega o que não está na matriz).

### FASE 5 — Validation

- Statistician (consome walk-forward/Monte Carlo do core/engine).
- Adversarial (PASS/WARN/FAIL).
- Risk.
- Broker Risk (autônomo, com acesso à web — ADR-006).
- Validator (única autoridade de transição de estado da estratégia).

### FASE 6 — Dashboard

- Somente leitura (status do sistema, experimentos, estratégias, risco, logs,
  DEMO).
- Ação de escrita (ex: aprovar `promotion_request`) fica fora do dashboard por
  padrão, a menos que o usuário decida abrir essa superfície — se abrir, herda
  as mesmas exigências de auditoria de qualquer ação sensível.

### FASE 7 — Kiro Crew

- Workflows, permissões, execução, observabilidade (CPU/RAM/tempo/erros —
  seção 60).
- Nenhuma integração de corretora ainda nesta fase.

### FASE 8 — DEMO

- Pré-requisito bloqueante: Broker Risk Agent = `PASS` para a corretora
  escolhida (Polarium ou DayProfit).
- Credenciais DEMO isoladas de REAL por processo/ambiente.
- Execução real de operações DEMO só depois do checklist da seção 74 completo.

### FASE 9 — Validação prolongada

- Observação de estabilidade ao longo do tempo.
- Proibido ajustar estratégia apenas para melhorar resultado histórico
  (seção 78).

### FASE 10 — REAL

- Bloqueado até: validação técnica + estatística + DEMO concluído + revisão de
  risco + revisão humana + aprovação explícita (checklist seção 75).
- Fora de escopo para qualquer trabalho de implementação atual.

---

## 2. Plano de testes

```text
tests/unit/           funções puras: expectancy, drawdown, loss streak
tests/integration/    fluxo agente→agente via contratos, persistência real (DB de teste)
tests/regression/     snapshot de resultados de backtest conhecidos (não pode mudar silenciosamente)
tests/backtest/       seção 45: entradas/saídas, timestamps, payout, capital, drawdown,
                        sequência de perdas, dados ausentes/duplicados, timezone
tests/risk/           risk of ruin, capital depletion, cenários adversos configurados
tests/security/       ver checklist completo em SECURITY_MODEL.md seção 7
tests/agents/         cada agente respeita seu contrato de AGENT_CONTRACTS.md e não excede permissão
```

Critério de release estável: nenhuma release avança para o Kiro Crew sem 100%
dos testes críticos (security + backtest) passando. Gate de CI, não checagem
manual.

---

## 3. Riscos técnicos

1. **Basis risk em ativos OTC** — mitigado, não eliminado, pela coleta própria
   (ADR-005). Preço ao vivo pode ainda divergir do preço histórico coletado se
   a corretora mudar seu comportamento de precificação.
2. **Ausência de histórico no início do projeto** — Backtest/Monte Carlo/
   walk-forward não são estatisticamente úteis até volume mínimo de dados
   coletados. Isso atrasa a Fase 3 na prática, mesmo que o código já exista.
3. **Corretoras-alvo com sinais de risco já conhecidos** (seção 67: histórico
   de recusa de saque, reclamações de indisponibilidade). Risco real de que o
   Broker Risk Agent retorne `FAIL` para ambas — risco de viabilidade do
   projeto, não apenas técnico.
4. **Overfitting via iteração de versões de hipótese** (`HYP-001-v2, v3...`) —
   detecção de "loop inútil" (seção 58) precisa de critério objetivo (ex: N
   tentativas com mesma causa raiz) para não ser subjetiva. A definir na
   Fase 4/5.
5. **Persistência de estado que sobrevive a reinicializações** exige
   transação atômica ou idempotência — Crew interrompido no meio de uma
   escrita multi-tabela não pode deixar estado inconsistente.
6. **Enforcement de permissão apenas por convenção é frágil** — por isso a
   Fase 1 já inclui `agents/base/permissions.py` como middleware central, não
   como checagem espalhada por agente.
7. **Comportamento do kill switch em voo** — escrita em andamento no momento
   de `EMERGENCY_STOP()` precisa de garantia transacional (ver
   SECURITY_MODEL.md seção 3).
8. **`configs/real.yaml` como superfície de erro humano** — mitigado por
   exigir revisão/segunda aprovação para qualquer diff nesse arquivo
   especificamente, além do bloqueio programático de escrita por agente.
9. **Broker Risk Agent autônomo com acesso à web é a maior superfície de risco
   de confiabilidade do sistema** — fontes externas podem estar desatualizadas
   ou tendenciosas. Mitigado por exigir citação de fonte em todo finding
   (ADR-006), mas não elimina a possibilidade de avaliação equivocada.

---

## 4. Definição de pronto (seção 77, sem alteração)

```text
✓ dados são rastreáveis
✓ experimentos são reproduzíveis
✓ backtests são determinísticos
✓ resultados são auditáveis
✓ OOS funciona
✓ walk-forward funciona
✓ Monte Carlo funciona
✓ agentes possuem permissões corretas
✓ DEMO está isolado
✓ REAL está bloqueado
✓ kill switch funciona
✓ logs funcionam
✓ testes passam
✓ Crew consegue executar o workflow
✓ humano consegue revisar tudo
```

---

## 5. Próximo passo imediato

Ao final desta documentação (FASE 0), o próximo passo é a **FASE 1 —
Infraestrutura**, que ainda não foi iniciada. Nenhum código de aplicação foi
criado até este ponto — apenas documentação e estrutura de pastas vazias.

---

## 6. Referências

- `MASTER_SPEC.md` seções 44–78.
- `docs/ARCHITECTURE.md`, `docs/AGENT_CONTRACTS.md`, `docs/SECURITY_MODEL.md`.
- `docs/decisions/ADR-001` a `ADR-006`.
