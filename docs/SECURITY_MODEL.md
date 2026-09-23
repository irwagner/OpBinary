# AI Trading Research Lab — Modelo de Segurança

> Consolida política de permissões, kill switch, isolamento DEMO/REAL,
> gestão de credenciais e auditoria, conforme MASTER_SPEC.md seções 9, 16.1,
> 31–36, 46, 65–68, e decisões ADR-001, ADR-003, ADR-006.

---

## 1. Política de permissões por agente

Enforcement centralizado em `agents/base/permissions.py` — não é convenção de
código, é um gate obrigatório verificado pelo Supervisor antes de qualquer ação
com efeito (ADR-001).

| Ação | Quem pode | Quem NÃO pode |
|---|---|---|
| Criar hipótese | Research Agent | qualquer outro agente |
| Formalizar regra matemática | Quant Agent | — |
| Executar backtest | Backtester Agent | — |
| Avançar estado da estratégia | **Validator Agent, exclusivamente** | Supervisor, qualquer outro agente, humano fora do fluxo de `promotion_requests` |
| Aprovar DEMO → REAL | **Humano, via `promotion_requests.status = APPROVED`** | qualquer agente, mesmo o Validator |
| Apagar logs/auditoria (`system_events`, `agent_runs`) | **Ninguém** | inclui humano operando por fora do processo formal — auditoria é append-only por design |
| Alterar kill switch | Humano / infraestrutura de sistema | qualquer agente |
| Remover ou relaxar limites de risco | Ninguém programaticamente sem trilha de auditoria e nova versão de config | agentes, em qualquer circunstância |
| Acessar credenciais REAL | Bloqueado por padrão; requer processo de aprovação fora do runtime de agentes | processo DEMO, qualquer agente autônomo |
| Integrar corretora sem Broker Risk = PASS | Proibido (seção 67) | — |
| Ocultar resultado negativo | Proibido — todo resultado negativo é persistido em `strategies/rejected/` com motivo (seção 56) | — |
| Acesso de rede (internet) | **Somente Broker Risk Agent** (ADR-006) | todos os demais agentes operam só sobre dados internos |

Qualquer tentativa de ação fora dessa matriz deve ser negada pelo Supervisor e
registrada como `system_event` de severidade alta — uma tentativa de violação é,
em si, um evento auditável, não apenas uma operação silenciosamente ignorada.

---

## 2. Isolamento DEMO / REAL

### 2.1 Isolamento de credenciais

```text
DEMO_API_KEY / DEMO_SECRET       — usadas exclusivamente pelo processo DEMO
REAL_API_KEY / REAL_SECRET       — usadas exclusivamente pelo processo REAL
```

Regras (seção 31, 36, 66):

- O processo que executa DEMO **não tem acesso** às variáveis/segredos de REAL,
  nem por herança de ambiente nem por leitura acidental de config — devem ser
  processos ou contêineres logicamente separados, não apenas branches de código
  dentro do mesmo processo.
- Nunca hardcode de credencial no código-fonte.
- Nunca commit de secret no repositório.
- Nunca `print(secret)` ou `log(secret)` — logging deve ter scrubbing automático
  que detecta e mascara padrões de chave/segredo antes de persistir qualquer
  linha de log.
- Preferência de armazenamento: variáveis de ambiente → secret manager (quando
  disponível) → arquivo local protegido com permissão mínima. Nunca em texto
  puro versionado.

### 2.2 Isolamento de configuração

```yaml
# configs/research.yaml
mode: RESEARCH
execution: {enabled: false}
real: {enabled: false}

# configs/demo.yaml
mode: DEMO
execution: {enabled: true}
real: {enabled: false}

# configs/real.yaml
mode: REAL
execution: {enabled: false}   # nunca alterado automaticamente por agente
human_approval: {required: true}
kill_switch: {enabled: true}
```

`real.yaml` é o arquivo mais sensível do projeto:

- `execution.enabled` só pode virar `true` por edição manual humana revisada
  (equivalente a uma segunda assinatura/PR), nunca por escrita de agente.
- Recomenda-se proteção adicional a nível de sistema de arquivos (permissão
  restrita) e revisão obrigatória de qualquer diff nesse arquivo específico.
- O modo `REAL` precisa de uma barreira além do campo `mode` (seção 68) — ou
  seja, mesmo com `mode: REAL` configurado, a execução real exige checagem
  independente de `human_approval` e `kill_switch` antes de qualquer ordem.

### 2.3 Isolamento de execução

`execution/demo/` e `execution/real/` são módulos separados. `execution/real/`
permanece sem implementação funcional até a Fase 10 (após checklist completo
da seção 75) — sua existência no repositório antes disso é apenas estrutural
(placeholder), nunca operacional.

---

## 3. Kill switch (três níveis — seção 33)

```text
disable_strategy(strategy_id)   — nível estratégia
disable_agent(agent_name)       — nível agente
EMERGENCY_STOP()                 — nível sistema
```

Regras:

- Qualquer um dos três níveis só pode ser acionado por humano ou por lógica de
  infraestrutura de sistema (ex: watchdog de erro repetido) — nunca por decisão
  autônoma de um agente de pesquisa/execução.
- `EMERGENCY_STOP()` define o estado global do sistema como `EMERGENCY_STOPPED`
  (seção 41), que:
  - bloqueia toda nova ação de execução (DEMO e REAL);
  - congela toda transição na state machine de estratégia;
  - não interrompe leitura/relatório — apenas ações com efeito.
- **Comportamento em voo (gap identificado na análise inicial):** se
  `EMERGENCY_STOP()` for acionado enquanto uma escrita de operação DEMO está em
  andamento, a escrita em andamento deve ser finalizada ou revertida de forma
  atômica (nunca deixar um registro parcial) — isso deve ser garantido pela
  camada de persistência (transação), não pelo agente.
- Reversão de `EMERGENCY_STOPPED` exige ação humana explícita, nunca automática
  por timeout ou retry.

---

## 4. Broker Risk como gate de segurança de contraparte

Além do risco de mercado (Risk Agent) e do risco de execução interna (kill
switch), o Broker Risk Agent (seção 16.1, ADR-006) é uma camada de segurança
específica contra risco de contraparte:

- `FAIL` bloqueia entrada em DEMO, independente de qualquer resultado de
  estratégia — é uma condição eliminatória, não um score ponderado.
- Regressão `PASS → FAIL` numa corretora já em uso **suspende automaticamente**
  todas as estratégias DEMO associadas (ADR-003), preservando histórico, e
  força revisão humana antes de retomada.
- Toda conclusão do Broker Risk Agent deve citar fonte (`source_url`,
  `accessed_at`) — sem isso, o finding não é aceito como evidência válida pelo
  Supervisor/Validator.

---

## 5. Auditoria (seção 35)

Todo `agent_run` registra:

```yaml
timestamp: iso8601
agent: string
experiment_id: string | null
input: object
output: object
model: string | null           # quando aplicável (agente usa LLM)
model_version: string | null
software_version: string
dataset_version: string | null
decision: string | null
reason: string | null
```

Regras estruturais:

- `system_events` e `agent_runs` são **append-only** — não existe operação de
  UPDATE ou DELETE exposta a nenhum agente. Idealmente, isso é reforçado por
  permissão de banco/role, não apenas por ausência de método no código.
- Deve ser possível reconstruir a cadeia de decisão completa de qualquer
  `experiment_id` — da hipótese original até a decisão final do Validator —
  a partir apenas dos registros de auditoria.
- Nenhum agente pode apagar ou modificar retroativamente um registro de
  auditoria, mesmo em caso de erro — correções acontecem por novo registro que
  referencia o anterior, nunca por edição.

---

## 6. Regras para integração com corretoras (seção 67)

- Integração usa somente APIs oficiais, mecanismos oficialmente suportados,
  credenciais autorizadas e ambientes de teste/demo quando disponíveis.
- Proibido contornar autenticação, controle, limite ou mecanismo de segurança
  do provedor (ex: engenharia reversa de endpoint não documentado).
- Nenhuma corretora entra em DEMO sem Broker Risk = `PASS`. Corretora com `FAIL`
  fica registrada em `strategies/rejected/` (ou entidade equivalente) com o
  motivo, para não ser reavaliada sem justificativa nova.
- Corretoras-alvo atuais (Polarium Broker, DayProfit) têm sinais de risco
  previamente conhecidos (histórico de recusa de saque, reclamações de
  indisponibilidade — seção 67) que devem ser reavaliados pelo Broker Risk
  Agent no momento da integração, nunca descartados por já estarem listados.

---

## 7. Testes de segurança obrigatórios antes de qualquer release (seção 46)

```text
[ ] DEMO não acessa credenciais/config de REAL
[ ] REAL exige aprovação explícita registrada em promotion_requests
[ ] kill switch (3 níveis) interrompe execução corretamente
[ ] logs não contêm secrets em nenhuma circunstância (scan automático)
[ ] nenhum agente consegue apagar/alterar system_events ou agent_runs
[ ] configuração inválida (schema incorreto) é rejeitada no load, não em runtime
[ ] tentativa de agente exceder sua permissão é negada e registrada como evento
[ ] regressão de Broker Risk (PASS→FAIL) suspende DEMO em uso automaticamente
```

Nenhuma release avança para o Kiro Crew sem 100% destes testes passando —
é um gate de CI, não uma checagem manual pontual.

---

## 8. Segurança operacional pré-REAL (seção 65)

Antes de qualquer integração REAL (fora de escopo até Fase 10), checklist
sequencial — falha em qualquer item bloqueia (`BLOCK`):

```text
1. verificar ambiente (mode == REAL confirmado explicitamente)
2. verificar credenciais (REAL_* presentes e isoladas de DEMO_*)
3. verificar modo (execution.enabled ainda false até revisão final)
4. verificar estratégia (validada, todos os gates do AGENT_CONTRACTS.md passados)
5. verificar limites de risco configurados
6. verificar kill switch testado e operante
7. verificar logs funcionando e sem secrets
8. verificar aprovação humana explícita registrada
```

---

## 9. Referências

- `MASTER_SPEC.md` seções 9, 16.1, 31–36, 46, 65–68.
- `docs/decisions/ADR-001, ADR-003, ADR-006`.
- `docs/ARCHITECTURE.md`, `docs/AGENT_CONTRACTS.md`, `docs/IMPLEMENTATION_PLAN.md`.
