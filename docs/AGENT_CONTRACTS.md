# AI Trading Research Lab — Contratos entre Agentes

> Define o contrato formal de entrada/saída de cada agente. Nenhum agente
> chama outro diretamente (ADR-001) — todo contrato é mediado pelo Supervisor
> e publicado no Event Bus. Campos numéricos/estatísticos são sempre produzidos
> por `core/engine` (determinístico), nunca inventados por um LLM.

---

## 0. Convenções comuns a todo contrato

Todo output de agente, independentemente do domínio, inclui o envelope abaixo
(exigido pela auditoria da seção 35 do MASTER_SPEC):

```yaml
agent_name: string
agent_version: string
software_version: string
timestamp: iso8601
experiment_id: string | null
input_ref: string          # id/hash do input consumido
output: <payload específico do agente>
decision: string | null    # quando aplicável (PASS/WARN/FAIL, aprovado/rejeitado)
reason: string | null      # obrigatório quando decision != null
```

Regra de permissão embutida no contrato: nenhum agente pode iniciar a produção
de um output sem antes obter `PASS` do Supervisor para a tarefa correspondente
(ADR-001). O envelope é gravado em `agent_runs` de forma append-only.

---

## 1. Supervisor Agent

Não produz output de domínio — é o roteador do workflow (seção 9, 40 do
MASTER_SPEC).

**Input:** `PermissionRequest{agent_name, task_type, depends_on[], experiment_id}`

**Output:** `PermissionDecision{status: PASS|DENY, reason, checked_preconditions[]}`

Responsabilidades de contrato:
- verificar pré-condição (o insumo esperado existe e está no estado correto);
- impedir avanço de estado fora de ordem (nunca autoriza pular etapa da state
  machine de estratégia);
- registrar toda decisão em `system_events`.

Não pode: emitir resultado numérico, aprovar promoção REAL, desativar kill
switch, apagar log (seção 9, 34).

---

## 2. Research Agent

**Input:** contexto da base de conhecimento (seção 57 — estratégias já
rejeitadas e motivo), restrições de mercado/timeframe configuradas.

**Output:** `Hypothesis`

```yaml
strategy_id: string        # HYP-XXXXXX, único
market:
  asset: string
  timeframe: string
entry:
  conditions: [string]
exit:
  rule: string
filters: [string]
parameters:
  <chave>: <valor>
```

Regra de contrato: toda hipótese recebe ID único e imutável. Nunca reescreve
uma hipótese existente — nova versão gera novo `strategy_id-vN` (seção 22).

---

## 3. Quant Agent

**Input:** `Hypothesis`

**Output:** `FormalStrategy`

```yaml
strategy_id: string
rule_ast: object            # representação computável, não texto livre
reproducible: bool          # deve ser sempre true para aceitar
rejection_reason: string | null
```

Regra de contrato: rejeita qualquer `Hypothesis` cujas condições não sejam
mensuráveis (ex: "mercado forte" sem definição objetiva) — devolve
`reproducible: false` com `rejection_reason`, e o Supervisor não autoriza
avanço para Backtester nesse caso.

---

## 4. Data Agent

**Input:** `CollectionRequest{broker, asset, timeframe, since}`

**Output:** `Dataset`

```yaml
dataset_id: string
broker: string              # Polarium | DayProfit (ADR-002)
asset: string
timeframe: string
source: "broker_capture"    # nunca "third_party_import" (ADR-005)
version: string
coverage:
  start: iso8601
  end: iso8601
  sample_size: int
quality_report:
  gaps: [object]
  duplicates: int
  timezone_issues: [object]
split:
  train_pct: float
  validation_pct: float
  test_pct: float
```

Regra de contrato: `Dataset` nunca é sobrescrito — cada captura gera uma nova
versão/snapshot. `sample_size` deve ser conferido contra um mínimo configurável
antes que qualquer consumidor (Backtester) aceite o dataset como válido.

---

## 5. Backtester Agent

**Input:** `FormalStrategy` + `Dataset` + `capital_scenarios[]`

**Output:** `BacktestResult`

```yaml
experiment_id: string        # nunca reaproveitado (seção 21)
strategy_id: string
dataset_id: string
asset: string
timeframe: string
period: {start: iso8601, end: iso8601}
parameters: object
capital_scenario: int         # 100 | 300 | 500 | 700 | 1000
trades: int
wins: int
losses: int
payout: float                 # vem do dataset, nunca hardcoded
profit: float
drawdown: float
max_loss_streak: int
expectancy: float             # = (win_rate*payout) - (loss_rate*1)
```

Regra de contrato: motor 100% determinístico (`core/engine/backtest_engine.py`).
Mesmo `FormalStrategy` + `Dataset` + `parameters` produz sempre o mesmo
`BacktestResult` — é a garantia de reprodutibilidade exigida na seção 13/45.

---

## 6. Statistician Agent

**Input:** `BacktestResult[]` (incluindo execuções de walk-forward/Monte Carlo)

**Output:** `StatisticalReport`

```yaml
experiment_id: string
sample_size: int
stability: object            # variância entre folds/janelas
distribution: object
loss_streak_analysis: object
drawdown_analysis: object
oos_result: object
monte_carlo_ref: string | null
walk_forward_folds:
  - fold_index: int
    expectancy: float
    passed: bool             # expectancy > 0
fold_pass_ratio: float        # calculado, comparado a min_fold_pass_ratio (ADR-004)
```

Regra de contrato: nunca decide sozinho a promoção — apenas produz o relatório
estatístico que o Validator vai consumir junto com Adversarial/Risk/Broker Risk.

---

## 7. Adversarial Agent

**Input:** `FormalStrategy` + `Dataset` + `BacktestResult`

**Output:** `AdversarialVerdict`

```yaml
experiment_id: string
verdict: PASS | WARN | FAIL
findings:
  - category: string          # overfitting | look_ahead_bias | data_leakage |
                                # bad_period | bad_asset | parameter_sensitivity
    severity: WARN | FAIL
    description: string
    evidence_ref: string
```

Regra de contrato: procura ativamente quebrar a estratégia (seção 15) — não é
um agente de confirmação, é adversarial por design. `FAIL` em qualquer
`category` crítica bloqueia avanço, independente do resultado do backtest.

---

## 8. Risk Agent

**Input:** `BacktestResult` + `capital_scenarios[]`

**Output:** `RiskReport`

```yaml
experiment_id: string
capital_scenario: int
max_drawdown: float
max_consecutive_losses: int
risk_of_ruin: float
capital_depletion_probability: float
recovery_time_estimate: object
exposure: float
adverse_scenarios_tested: [object]
```

Regra de contrato: nunca otimizado para maximizar lucro (seção 16) — reporta
risco cru, mesmo que isso reprove uma estratégia com bom retorno médio.

---

## 9. Broker Risk Agent

**Input:** `BrokerAssessmentRequest{broker_name}`

**Output:** `BrokerRiskReport`

```yaml
broker_name: string           # Polarium Broker | DayProfit
status: PENDING | PASS | WARN | FAIL
basis_risk: bool               # true para qualquer corretora OTC (seção 16.1)
findings:
  - category: string           # regulatory | complaints | withdrawal_pattern |
                                 # pricing_transparency | demo_availability |
                                 # historical_data_availability
    detail: string
    source_url: string          # obrigatório — evidência auditável (ADR-006)
    accessed_at: iso8601
evaluated_at: iso8601
next_review_due: iso8601        # reavaliação periódica obrigatória
previous_status: string | null  # para detectar regressão PASS→FAIL/WARN
```

Regra de contrato: único agente com acesso de rede (ADR-006). Todo `finding`
deve citar `source_url` e `accessed_at` — sem fonte, o finding não é aceito
pelo Supervisor como evidência válida. `FAIL` bloqueia entrada em DEMO
independente do resultado de qualquer outro agente (seção 16.1).

---

## 10. Validator Agent

**Input:** `StatisticalReport` + `AdversarialVerdict` + `RiskReport` +
`BrokerRiskReport` (mais recente e não expirado)

**Output:** `ValidationDecision`

```yaml
experiment_id: string
strategy_id: string
previous_state: string
new_state: string             # única fonte de transição da state machine
reason: string
checklist:
  sufficient_sample: bool
  no_data_leakage: bool
  no_look_ahead_bias: bool
  oos_passed: bool
  walk_forward_passed: bool     # fold_pass_ratio >= min_fold_pass_ratio
  monte_carlo_passed: bool
  temporal_stability: bool
  drawdown_reviewed: bool
  loss_streak_reviewed: bool
  adversarial_passed: bool      # verdict != FAIL
  expectancy_positive_net_payout: bool
  risk_reviewed: bool
  broker_risk_passed: bool      # status == PASS
  documentation_complete: bool
```

Regra de contrato: é o **único** agente com permissão de escrever uma nova
transição na state machine de estratégia (reforça seção 2 do ARCHITECTURE.md).
Se qualquer item do checklist for `false`, a transição só pode ir para
`REJECTED` ou `NEEDS_RESEARCH`, nunca adiante.

---

## 11. Reporter Agent

**Input:** qualquer combinação dos outputs acima, por `experiment_id` ou
`strategy_id`.

**Output:** documento formatado (markdown/json) — relatório de experimento,
diário, de estratégia, de risco, de DEMO, de falha, ou de promoção (seção 18).

Regra de contrato: **sem side-effect em estado**. O Reporter lê e formata, nunca
decide, nunca grava em `strategies`/`experiments`. Não pode omitir resultado
negativo (seção 34: "ocultar resultados negativos" é proibido).

---

## 12. Matriz de dependência (quem consome o quê)

```text
Research      → Quant
Quant         → Backtester
Data          → Backtester
Backtester    → Statistician, Risk
Statistician  → Validator
Adversarial   → Validator
Risk          → Validator
Broker Risk   → Validator (gate obrigatório antes de DEMO)
Validator     → Reporter (e state machine)
Reporter      → Humano (dashboard/relatório)
```

Toda seta desta matriz é, na prática, mediada pelo Supervisor (ADR-001) — a
matriz descreve dependência de dados, não uma chamada direta de código.
