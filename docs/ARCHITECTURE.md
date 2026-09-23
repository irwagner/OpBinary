# AI Trading Research Lab — Arquitetura Técnica

> Documento derivado de `MASTER_SPEC.md`, já incorporando as decisões
> registradas em `docs/decisions/ADR-001` a `ADR-006`. Nenhuma integração real
> com corretora, nenhuma API de corretora inventada, nenhum cálculo numérico
> delegado a LLM. Documentos relacionados: `docs/AGENT_CONTRACTS.md`,
> `docs/SECURITY_MODEL.md`, `docs/IMPLEMENTATION_PLAN.md`.

---

## 1. Visão geral

O sistema é um pipeline de pesquisa quantitativa orientado a estados, com
agentes de responsabilidade única orquestrados por um Supervisor central. Três
camadas concêntricas, isoladas por permissão:

```text
┌─────────────────────────────────────────────────────┐
│  KIRO IDE — desenvolvimento, testes, versionamento   │
└───────────────────────┬───────────────────────────────┘
                         │ release estável (Git)
┌───────────────────────▼───────────────────────────────┐
│  KIRO CREW — operação autônoma controlada             │
│                                                        │
│   Agente ──request_permission()──▶ SUPERVISOR         │
│   Agente ◀──────PASS / DENY──────  (ADR-001)          │
│   Agente ──publish(output)───────▶ EVENT BUS           │
│                                                        │
│   CORE: engine · models · events · state · config     │
│   PERSISTÊNCIA: database (append-only para auditoria) │
│   DASHBOARD: leitura de status/experimentos/risco      │
└────────────────────────┬───────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                                    ▼
┌──────────────┐                    ┌──────────────────┐
│ EXECUÇÃO DEMO│                    │ EXECUÇÃO REAL     │
│ credenciais  │                    │ bloqueada por     │
│ próprias,    │                    │ padrão, requer     │
│ corretora com│                    │ aprovação humana   │
│ modo demo    │                    │ explícita          │
│ nativo       │                    │                    │
│ (ADR-002)    │                    │                    │
└──────────────┘                    └──────────────────┘
```

Princípios inegociáveis (MASTER_SPEC seções 2.1–2.3, regra final seção 78):

1. Nenhuma etapa do pipeline `RESEARCH → BACKTEST → VALIDATION → OUT-OF-SAMPLE
   → MONTE_CARLO → DEMO → HUMAN_REVIEW → REAL` pode ser pulada.
2. LLM nunca é o motor matemático. Cálculo crítico é código determinístico e
   testado; LLM gera hipótese, interpreta resultado, procura inconsistência.
3. Promoção DEMO → REAL nunca é automática — exige aprovação humana explícita.
4. O sistema prefere sempre "menos operações + mais validação + mais
   transparência + mais controle" sobre "mais operações + mais complexidade".

---

## 2. Roteamento entre agentes (ADR-001)

Nenhum agente chama outro agente diretamente. Todo agente solicita permissão ao
Supervisor antes de iniciar uma tarefa com efeito (mudar estado, consumir output
de outro agente, disparar execução):

```text
Agente A ──request_permission(task)──▶ Supervisor
Agente A ◀────────PASS / DENY─────────  Supervisor
Agente A ──executa (se PASS)
Agente A ──publish(output)────────────▶ Event Bus
Agente B ──request_permission(task, depende_de=output)──▶ Supervisor
```

O Supervisor verifica pré-condições, concede ou nega, e registra o evento em
auditoria (`system_events`). Ele não microgerencia a execução interna de cada
agente — apenas autoriza o início da tarefa. Comunicação é assíncrona via Event
Bus (`core/events`), nunca por chamada de função direta entre módulos de agente.

---

## 3. Coleta de dados — sem dataset externo (ADR-005)

Não há importação de histórico de terceiros. O Data Agent é um **coletor
contínuo** que grava, a partir da própria corretora-alvo (via mecanismo
oficialmente suportado — seção 67 da spec), o histórico usado depois em
backtest.

Consequências arquiteturais:

- A Fase 2 (Data Engine) não é um importador de CSV/API de terceiro — é um
  processo de captura ativa, rodando durante `RESEARCH`/`DEMO`.
- Backtest/Monte Carlo/walk-forward só ficam estatisticamente úteis após um
  volume mínimo de dados coletados (threshold a definir na Fase 2/3).
- `basis_risk` (seção 16.1) é reduzido — dado histórico e dado ao vivo
  compartilham a mesma origem — mas não eliminado, porque a corretora pode
  mudar seu comportamento de precificação entre a coleta e a execução real.
- O sistema evolui de forma incremental: hipóteses são testadas contra o
  histórico próprio que cresce a cada ciclo de pesquisa.

---

## 4. Corretoras-alvo (ADR-002, ADR-003, ADR-006)

Duas corretoras-alvo (seção 67 do MASTER_SPEC): **Polarium Broker** e
**DayProfit**. Ambas possuem modo DEMO nativo (confirmado pelo usuário) — não é
necessário fallback para corretora sem DEMO.

O Broker Risk Agent (seção 16.1) é obrigatório e bloqueante antes de qualquer
uso de DEMO, e roda **totalmente autônomo**: pesquisa por conta própria status
regulatório, reclamações, padrão de recusa de saque, etc.

- É o único agente do sistema com acesso de leitura à internet. Todo outro
  agente opera exclusivamente sobre dados internos.
- Todo conteúdo obtido da web é dado não confiável, nunca instrução. Toda
  conclusão cita fontes (URL + data) em `findings[]`.
- Reavaliação periódica é obrigatória. Regressão `PASS → FAIL` numa corretora em
  uso **suspende automaticamente** todas as estratégias em DEMO nela (histórico
  preservado) e abre revisão humana obrigatória antes de qualquer retomada.
  Regressão para `WARN` gera alerta e reduz o intervalo até a próxima
  reavaliação, sem suspender.

---

## 5. Critério de expectancy entre folds (ADR-004)

Threshold default: **100% dos folds do walk-forward devem ter `expectancy > 0`**
para a estratégia avançar de `OUT_OF_SAMPLE` para `MONTE_CARLO`. Configurável
via `validation.min_fold_pass_ratio` (default `1.0`), nunca hardcoded no
Validator.

```text
expectancy = (win_rate × payout) - (loss_rate × 1)
```

`payout` vem sempre do dataset (nunca hardcoded no código) — varia por ativo,
horário e corretora.

---

## 6. Estrutura de pastas

```text
ai-trading-lab/
├── agents/
│   ├── base/                    # classe base de agente + enforcement de permissões
│   ├── supervisor/
│   ├── researcher/
│   ├── quant/
│   ├── data/                    # coletor contínuo, não importador
│   ├── backtester/
│   ├── statistician/
│   ├── adversarial/
│   ├── risk/
│   ├── broker_risk/             # único agente com acesso de rede
│   ├── validator/
│   └── reporter/
├── core/
│   ├── engine/                  # backtest, walk-forward, monte carlo, métricas
│   ├── models/                  # entidades (dataclasses/ORM)
│   ├── events/                  # event bus
│   ├── state/                   # state machine (estratégia + sistema)
│   └── configuration/           # loader + schema de configs por modo
├── contracts/                    # schemas de I/O entre agentes (ver AGENT_CONTRACTS.md)
├── data/
│   ├── raw/                      # captura bruta da corretora
│   ├── validated/
│   ├── processed/
│   └── datasets/                 # snapshots versionados do histórico coletado
├── strategies/
│   ├── candidates/
│   ├── validated/
│   └── rejected/                 # nunca apagado (seção 56)
├── backtests/
│   ├── runs/
│   └── reports/
├── simulations/
│   ├── monte_carlo/
│   └── scenarios/
├── demo/
├── execution/
│   ├── demo/
│   └── real/                     # existe mas fica bloqueado até Fase 10
├── risk/
├── broker_risk/
├── dashboard/                     # leitura de status/experimentos/risco
├── database/
│   └── migrations/
├── logs/
├── tests/
│   ├── unit/ integration/ regression/ backtest/ risk/ security/ agents/
├── configs/
│   ├── research.yaml · demo.yaml · real.yaml
├── crew/                          # workflows/tasks do Kiro Crew (Fase 7)
└── docs/
```

---

## 7. Módulos Python (mapa de responsabilidade)

```text
core/configuration/   loader.py, schema.py           — valida YAML por modo
core/events/          bus.py, types.py                — publish/subscribe interno
core/state/           machine.py, store.py            — transições válidas + persistência
core/engine/          backtest_engine.py, walk_forward.py,
                       monte_carlo.py, metrics.py       — determinístico, sem LLM
agents/base/          agent.py, permissions.py         — contrato comum + enforcement
agents/<nome>/        agent.py                         — lógica específica de cada agente
contracts/            um módulo por agente              — schemas de input/output
database/             connection.py, repository.py,
                       migrations/                       — um repositório por entidade
dashboard/            app.py                            — somente leitura
```

Regra de dependência: cada agente depende apenas de `contracts/` e `core/`,
nunca de outro módulo de agente diretamente (reforça seção 2).

---

## 8. Entidades de banco (resumo)

`strategies, datasets, experiments, backtests, trades, simulations,
risk_reports, broker_risk_reports, agent_runs, system_events, demo_sessions,
promotion_requests`.

`experiments`, `system_events` e `agent_runs` são **append-only** — nunca
sobrescritos ou deletados (seções 21, 34, 56). Detalhamento de campos: ver
`docs/AGENT_CONTRACTS.md` (schemas de output que alimentam essas tabelas).

---

## 9. Máquinas de estado

### 9.1 Estratégia (seção 17)

```text
IDEA → BACKTEST → VALIDATION → OUT_OF_SAMPLE → MONTE_CARLO
     → DEMO_CANDIDATE → DEMO → HUMAN_REVIEW → REAL

Qualquer estado → REJECTED
Qualquer estado → NEEDS_RESEARCH
```

Apenas o Validator Agent pode mover esta máquina. `REAL` só é alcançável a
partir de `HUMAN_REVIEW` com `promotion_requests.status = APPROVED`.

### 9.2 Sistema/runtime (seção 41)

```text
IDLE → RUNNING → PAUSED → RUNNING
RUNNING → ERROR → (retry) → RUNNING | STOPPED
qualquer estado → EMERGENCY_STOPPED
```

`EMERGENCY_STOPPED` congela também a máquina de estratégia — nenhuma
transição de estado ocorre enquanto o sistema estiver neste estado.

### 9.3 Corretora / Broker Risk (seção 16.1, ADR-003)

```text
PENDING → PASS | WARN | FAIL
PASS → FAIL   (reavaliação periódica) → suspende DEMO em uso + revisão humana
PASS → WARN   → alerta + reavaliação mais frequente, sem suspender
```

---

## 10. Interfaces de entrada e saída

- **Entrada humana:** arquivos de configuração YAML, decisão sobre
  `promotion_requests` (`PENDING/APPROVED/REJECTED/EXPIRED`), definição inicial
  de corretoras-alvo.
- **Entrada de dados de mercado:** exclusivamente a captura própria da
  corretora-alvo (ADR-005) — nunca dataset de terceiro.
- **Saída para humano:** Dashboard (somente leitura), relatórios em
  markdown/texto (diário, estratégia, risco, DEMO, falha, promoção).
- **Saída entre agentes:** contratos estruturados (`docs/AGENT_CONTRACTS.md`),
  nunca texto livre não estruturado quando envolve números.
- **Saída de execução DEMO:** registros em `demo_sessions`, nunca ordem real.
- **Fora de escopo, deliberadamente não implementado:** qualquer interface de
  saída para execução em corretora real.

---

## 11. Referências

- `MASTER_SPEC.md` — especificação original (79 seções).
- `docs/decisions/ADR-001` a `ADR-006` — decisões que resolvem as ambiguidades
  da especificação original.
- `docs/AGENT_CONTRACTS.md` — contratos formais de input/output por agente.
- `docs/SECURITY_MODEL.md` — política de permissões, kill switch, isolamento
  DEMO/REAL, credenciais, auditoria.
- `docs/IMPLEMENTATION_PLAN.md` — plano de fases, riscos técnicos, plano de
  testes.
