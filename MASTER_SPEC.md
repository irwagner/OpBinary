# AI Trading Research Lab
## Especificação Mestre do Projeto — Kiro IDE + Kiro Crew

> **Status:** Especificação inicial  
> **Versão:** 1.0  
> **Idioma:** Português  
> **Objetivo:** construir um laboratório de pesquisa quantitativa assistido por múltiplos agentes de IA para estudar estratégias de operações binárias, validar hipóteses com dados e simulações e, somente após validação e aprovação humana explícita, permitir eventual integração com execução real.

---

# 1. Visão geral

O **AI Trading Research Lab** será um sistema de pesquisa quantitativa composto por múltiplos agentes de IA.

O sistema não deve ser construído com o objetivo simplista de "prever a próxima operação". O objetivo é criar um processo científico e reproduzível para:

1. coletar e validar dados;
2. gerar hipóteses;
3. transformar hipóteses em regras objetivas;
4. executar backtests;
5. separar desenvolvimento, validação e teste;
6. realizar walk-forward;
7. executar simulações Monte Carlo;
8. procurar overfitting;
9. tentar quebrar estratégias;
10. analisar risco;
11. validar estratégias em ambiente DEMO;
12. gerar relatórios;
13. manter auditoria completa;
14. permitir operação REAL somente mediante aprovação humana explícita.

**Importante:** resultados históricos ou de DEMO não garantem resultados futuros em conta real.

---

# 2. Princípios fundamentais

## 2.1 Separação entre pesquisa e execução

A IA deve ser principalmente uma ferramenta de pesquisa, análise, validação e automação controlada.

O sistema deve separar:

```text
RESEARCH
    ↓
BACKTEST
    ↓
VALIDATION
    ↓
OUT-OF-SAMPLE
    ↓
MONTE CARLO
    ↓
DEMO
    ↓
HUMAN REVIEW
    ↓
REAL
```

Nenhuma etapa deve ser pulada.

---

## 2.2 A IA não deve ser o motor matemático

LLMs podem:

- gerar hipóteses;
- escrever código de pesquisa;
- interpretar resultados;
- procurar inconsistências;
- propor novos experimentos;
- analisar relatórios.

Mas cálculos críticos devem ser executados por código determinístico e testado.

Exemplo:

```text
LLM
 ↓
define estratégia
 ↓
Backtest Engine
 ↓
calcula resultados
 ↓
Statistician Agent
 ↓
interpreta resultados
```

O LLM nunca deve inventar números de performance.

---

## 2.3 Nenhuma promoção automática para REAL

A transição:

```text
DEMO → REAL
```

deve exigir ação humana explícita.

O Crew pode gerar uma solicitação de promoção, mas não pode executá-la sozinho.

---

# 3. Modos do sistema

## 3.1 RESEARCH

Nenhuma operação é enviada.

Permissões:

- gerar hipóteses;
- criar experimentos;
- executar backtests;
- executar simulações;
- analisar dados;
- gerar relatórios.

---

## 3.2 DEMO

Permite testar a estratégia em ambiente demonstrativo, quando suportado pela integração utilizada.

Permissões:

- acompanhar mercado/dados;
- gerar sinais;
- executar operações DEMO;
- registrar resultados;
- avaliar comportamento operacional.

---

## 3.3 REAL

Bloqueado por padrão.

Acesso condicionado a:

- aprovação humana;
- estratégia validada;
- configuração específica;
- limites de risco;
- credenciais separadas;
- logs;
- kill switch.

---

# 4. Cenários de capital

O sistema deve suportar inicialmente os cenários:

```text
$100
$300
$500
$700
$1.000
```

Esses valores devem ser tratados como **cenários de análise e simulação**, não como recomendações de investimento.

Cada estratégia deve poder ser simulada em todos os cenários.

Exemplo:

```text
Strategy: HYP-000123

Capital:
    $100
    $300
    $500
    $700
    $1.000

Para cada cenário:
    - drawdown
    - sequência de perdas
    - exposição
    - risco de ruína
    - recuperação
    - distribuição dos resultados
```

---

# 5. Arquitetura geral

```text
                         KIRO IDE
                            │
                    Desenvolvimento
                            │
                            ▼
                         Git
                            │
                     versão estável
                            │
                            ▼
                       KIRO CREW
                            │
                    ┌───────┴───────┐
                    │   SUPERVISOR  │
                    └───────┬───────┘
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
   RESEARCHER              DATA                 QUANT
       │                    │                    │
       └────────────────────┼────────────────────┘
                            ▼
                       BACKTESTER
                            │
                            ▼
                      STATISTICIAN
                            │
                            ▼
                       ADVERSARIAL
                            │
                            ▼
                         RISK
                            │
                            ▼
                     BROKER RISK
                            │
                            ▼
                       VALIDATOR
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
              REJECT                 DEMO
                                       │
                                       ▼
                                HUMAN REVIEW
                                       │
                                       ▼
                                     REAL
```

---

# 6. Kiro IDE

O Kiro IDE será o ambiente principal de desenvolvimento.

Responsabilidades:

- criar arquitetura;
- escrever código;
- criar testes;
- revisar agentes;
- criar documentação;
- corrigir bugs;
- evoluir o sistema;
- versionar mudanças.

O Kiro IDE não deve ser substituído pelo Crew.

---

# 7. Kiro Crew

O Kiro Crew será o ambiente operacional dos agentes.

Responsabilidades:

- executar ciclos de pesquisa;
- executar experimentos;
- coordenar agentes;
- executar scripts;
- processar resultados;
- gerar relatórios;
- monitorar DEMO;
- abrir solicitações de revisão;
- manter o ciclo de pesquisa.

O Crew deve trabalhar sobre versões estáveis do projeto.

---

# 8. Fluxo IDE → Crew

```text
Kiro IDE
   ↓
implementação
   ↓
testes
   ↓
revisão
   ↓
Git
   ↓
release
   ↓
Kiro Crew
   ↓
execução autônoma controlada
```

O Crew não deve modificar silenciosamente a arquitetura principal.

Caso encontre um problema estrutural:

```text
Crew
 ↓
gera issue/proposta
 ↓
Kiro IDE
 ↓
implementa correção
 ↓
testes
 ↓
nova versão
 ↓
Crew
```

---

# 9. Agentes

## 9.1 Supervisor Agent

Função: coordenador central.

Responsabilidades:

- controlar o workflow;
- distribuir tarefas;
- verificar pré-condições;
- impedir etapas inválidas;
- consolidar resultados;
- controlar estado dos experimentos;
- impedir promoção automática para REAL.

Não deve:

- inventar resultados;
- apagar logs;
- modificar limites de risco;
- acessar credenciais reais sem autorização do sistema;
- desativar o kill switch.

---

# 10. Research Agent

Função: gerar hipóteses.

Uma hipótese precisa ser formalizada.

Exemplo:

```yaml
strategy_id: HYP-000001

market:
  asset: EXAMPLE
  timeframe: EXAMPLE

entry:
  conditions:
    - condition_a
    - condition_b

exit:
  rule: EXAMPLE

filters:
  - filter_a

parameters:
  parameter_a: value
```

Cada hipótese recebe ID único.

Exemplo:

```text
HYP-000001
HYP-000002
HYP-000003
```

---

# 11. Quant Agent

Responsável por transformar ideias em regras matemáticas e computáveis.

Não aceitar regras vagas como:

```text
"quando o mercado estiver forte"
```

A regra precisa ser mensurável.

Exemplo conceitual:

```text
IF condition_A
AND condition_B
AND condition_C
THEN signal = TRUE
```

Toda estratégia deve ser reproduzível.

---

# 12. Data Agent

Responsável pelos dados.

Funções:

- ingestão;
- validação;
- normalização;
- deduplicação;
- detecção de gaps;
- timestamps;
- qualidade;
- versionamento;
- criação de datasets.

Estrutura:

```text
data/
├── raw/
├── validated/
├── processed/
├── train/
├── validation/
└── test/
```

---

# 13. Backtester Agent

O Backtester executa as estratégias.

Cada execução precisa registrar:

```text
experiment_id
strategy_id
dataset_id
asset
timeframe
period
parameters
trades
wins
losses
payout
profit
drawdown
max_loss_streak
expectancy
```

O Backtest Engine deve ser independente dos LLMs.

---

# 14. Statistician Agent

Responsável por verificar a robustez estatística.

Deve analisar:

- tamanho da amostra;
- estabilidade;
- distribuição dos resultados;
- variância;
- sequência de perdas;
- drawdown;
- sensibilidade;
- performance fora da amostra;
- Monte Carlo;
- estabilidade temporal.

Não deve considerar apenas taxa de acerto.

---

# 15. Adversarial Agent

Função: tentar quebrar a estratégia.

Deve procurar:

- períodos ruins;
- ativos problemáticos;
- horários problemáticos;
- mudanças de volatilidade;
- sensibilidade excessiva;
- dependência de parâmetros;
- overfitting;
- look-ahead bias;
- data leakage;
- degradação fora da amostra.

Resultado:

```text
PASS
WARN
FAIL
```

---

# 16. Risk Agent

Responsável exclusivamente por risco.

Analisar:

```text
maximum drawdown
maximum consecutive losses
risk of ruin
capital depletion
recovery time
exposure
```

Também deve executar cenários adversos.

O Risk Agent não deve ser otimizado para aumentar lucro.

---

# 16.1 Broker Risk Agent

Responsável por avaliar o risco de contraparte — separado do risco de mercado tratado pelo Risk Agent.

O Adversarial Agent (seção 15) testa se a *estratégia* quebra. O Broker Risk Agent testa se a *corretora* é confiável o suficiente pra sequer valer a pena testar a estratégia nela.

Analisar antes de liberar qualquer integração DEMO:

```text
status regulatório (CVM, jurisdição de origem)
tempo de mercado / idade do domínio
histórico de reclamações (volume e natureza)
padrão de recusa de saque
transparência sobre precificação OTC
disponibilidade de ambiente DEMO real
disponibilidade de histórico de dados oficial
```

Resultado:

```text
PASS
WARN
FAIL
```

FAIL bloqueia entrada em DEMO, independente do resultado da estratégia.

**Dado crítico:** em ativos OTC, quem gera o preço é a própria corretora, não um mercado público. Isso significa que os dados usados no backtest (seção 12, Data Agent) provavelmente vêm de uma fonte proxy — não da corretora-alvo. O Broker Risk Agent deve registrar essa diferença como `basis_risk` no relatório da estratégia, porque nenhum backtest, walk-forward ou Monte Carlo elimina o risco de o preço ao vivo divergir do preço histórico usado na validação.

Este agente deve ser reexecutado periodicamente — o perfil de risco de uma corretora muda (ex: piora repentina no histórico de saques) mesmo depois de uma estratégia já estar em DEMO.

---

# 17. Validator Agent

Controla a promoção entre fases.

Estados:

```text
IDEA
↓
BACKTEST
↓
VALIDATION
↓
OUT_OF_SAMPLE
↓
MONTE_CARLO
↓
DEMO_CANDIDATE
↓
DEMO
↓
HUMAN_REVIEW
↓
REAL
```

Uma falha em qualquer etapa pode retornar a estratégia para:

```text
REJECTED
```

ou:

```text
NEEDS_RESEARCH
```

---

# 18. Reporter Agent

Produz:

- relatório de experimento;
- relatório diário;
- relatório de estratégia;
- relatório de risco;
- relatório DEMO;
- relatório de falhas;
- relatório de promoção.

---

# 19. Estrutura de diretórios

```text
ai-trading-lab/

├── agents/
│   ├── supervisor/
│   ├── researcher/
│   ├── quant/
│   ├── data/
│   ├── backtester/
│   ├── statistician/
│   ├── adversarial/
│   ├── risk/
│   ├── broker_risk/
│   ├── validator/
│   └── reporter/
│
├── core/
│   ├── engine/
│   ├── models/
│   ├── events/
│   ├── state/
│   └── configuration/
│
├── data/
│   ├── raw/
│   ├── validated/
│   ├── processed/
│   └── datasets/
│
├── strategies/
│   ├── candidates/
│   ├── validated/
│   └── rejected/
│
├── backtests/
│   ├── runs/
│   └── reports/
│
├── simulations/
│   ├── monte_carlo/
│   └── scenarios/
│
├── demo/
│
├── execution/
│   ├── demo/
│   └── real/
│
├── risk/
│
├── broker_risk/
│
├── dashboard/
│
├── database/
│
├── logs/
│
├── tests/
│
├── configs/
│   ├── research.yaml
│   ├── demo.yaml
│   └── real.yaml
│
└── docs/
```

---

# 20. Banco de dados

Entidades principais:

```text
experiments
strategies
datasets
backtests
trades
simulations
risk_reports
broker_risk_reports
agent_runs
system_events
demo_sessions
promotion_requests
```

Cada registro precisa possuir identificador único.

---

# 21. Experimentos

Um experimento deve registrar:

```yaml
experiment_id: EXP-000001
strategy_id: HYP-000001
dataset_id: DATA-000001

created_at: timestamp

software_version: v0.1.0
agent_version: ...

parameters:
  ...

result:
  status: ...
```

Experimentos antigos nunca devem ser sobrescritos.

---

# 22. Versionamento

Estratégias:

```text
HYP-001
HYP-001-v2
HYP-001-v3
```

Software:

```text
SYSTEM-v0.1
SYSTEM-v0.2
SYSTEM-v0.3
```

Nunca alterar silenciosamente o histórico.

---

# 23. Separação TRAIN / VALIDATION / TEST

O sistema deve separar os dados.

Exemplo inicial:

```text
TRAIN       60%
VALIDATION  20%
TEST        20%
```

Esses percentuais devem ser configuráveis.

O conjunto TEST não pode ser utilizado para ajustar parâmetros.

---

# 24. Data leakage

O sistema deve detectar e impedir:

- informações futuras;
- dados posteriores ao momento da decisão;
- indicadores calculados com futuro;
- labels vazando para entrada;
- mistura indevida de datasets;
- uso acidental do TEST durante desenvolvimento.

---

# 25. Look-ahead bias

Uma estratégia nunca pode utilizar informação que não estaria disponível no momento da operação.

Todo indicador e regra precisa possuir uma referência temporal explícita.

---

# 26. Walk-forward

O sistema deve permitir:

```text
TRAIN
 ↓
VALIDATE
 ↓
TEST
 ↓
avança janela
 ↓
TRAIN
 ↓
VALIDATE
 ↓
TEST
```

O objetivo é observar estabilidade ao longo do tempo.

---

# 27. Monte Carlo

O sistema deve executar múltiplas simulações sobre os resultados.

Objetivos:

- estudar distribuição possível;
- observar drawdowns;
- observar sequências de perdas;
- estudar cenários adversos;
- avaliar sensibilidade à ordem dos resultados.

O número de simulações deve ser configurável.

---

# 28. Controle de overfitting

O sistema deve procurar:

- excesso de parâmetros;
- regras excessivamente específicas;
- estratégias que funcionam apenas em uma janela;
- estratégias que funcionam apenas em um ativo;
- dependência excessiva de horário;
- degradação forte fora da amostra.

Uma estratégia com resultado histórico excepcional mas baixa robustez deve ser tratada como suspeita.

---

# 29. Critérios de validação

A promoção não deve depender de uma única métrica.

Checklist:

```text
[ ] amostra suficiente
[ ] dados validados
[ ] sem data leakage
[ ] sem look-ahead bias
[ ] resultado fora da amostra
[ ] walk-forward
[ ] Monte Carlo
[ ] estabilidade temporal
[ ] análise de drawdown
[ ] análise de sequência de perdas
[ ] adversarial testing
[ ] expectancy líquido de payout
[ ] risk review
[ ] broker risk review
[ ] documentação completa
```

Os thresholds devem ser configuráveis e documentados.

**Expectancy líquido de payout:** taxa de acerto sozinha não valida uma estratégia. O Validator deve calcular o expectancy usando o payout real do ativo/corretora registrado no dataset (seção 13):

```text
expectancy = (win_rate × payout) - (loss_rate × 1)
```

Uma estratégia só é candidata a DEMO se `expectancy > 0` de forma consistente entre folds do walk-forward, não apenas na média geral. Payout varia por ativo, horário e corretora — o valor usado no cálculo nunca deve ser hardcoded.

---

# 30. DEMO

Uma estratégia candidata pode entrar em DEMO somente depois de passar pelos testes definidos.

O ambiente DEMO deve registrar:

```text
timestamp
strategy_id
signal
operation
result
payout
capital_scenario
reason
system_version
```

---

# 31. REAL

O ambiente REAL deve ser isolado.

Credenciais DEMO:

```text
DEMO_API_KEY
DEMO_SECRET
```

Credenciais REAL:

```text
REAL_API_KEY
REAL_SECRET
```

O processo DEMO não deve possuir acesso às credenciais REAL.

---

# 32. Aprovação humana

Uma solicitação pode ter:

```text
promotion_request_id
strategy_id
demo_period
demo_results
risk_report
failure_report
software_version
dataset_version
```

Status:

```text
PENDING
APPROVED
REJECTED
EXPIRED
```

A aprovação precisa ser explícita.

---

# 33. Kill Switch

Três níveis.

## Estratégia

```text
disable_strategy()
```

## Agente

```text
disable_agent()
```

## Sistema

```text
EMERGENCY_STOP()
```

O sistema deve parar ações de execução quando o estado global for:

```text
EMERGENCY_STOPPED
```

---

# 34. Limites de autonomia

Agentes podem:

```text
✓ criar hipóteses
✓ executar backtests
✓ criar experimentos
✓ executar testes
✓ analisar resultados
✓ gerar relatórios
✓ operar ambiente DEMO autorizado
```

Agentes não podem:

```text
✗ promover DEMO → REAL
✗ apagar logs
✗ alterar kill switch
✗ remover limites de risco
✗ obter credenciais reais arbitrariamente
✗ ocultar resultados negativos
✗ integrar com corretora sem broker risk review = PASS
```

---

# 35. Auditoria

Registrar:

```text
timestamp
agent
experiment_id
input
output
model
model_version
software_version
dataset_version
decision
reason
```

O sistema deve permitir reconstruir a cadeia de decisão.

---

# 36. Segurança

Nunca armazenar segredos diretamente no código.

Usar:

- variáveis de ambiente;
- secret manager quando disponível;
- arquivos locais protegidos;
- permissões mínimas;
- credenciais separadas.

Nunca registrar secrets nos logs.

---

# 37. Dashboard

Tela principal:

```text
AI TRADING LAB

Mode: DEMO

Strategies tested: 1,284
Candidates: 42
Validated: 17
Rejected: 1,225

Current experiment:
EXP-009283

System:
ONLINE

Risk:
NORMAL
```

---

# 38. Dashboard de agentes

```text
Supervisor       ONLINE
Researcher       ONLINE
Quant            ONLINE
Data             ONLINE
Backtester       ONLINE
Statistician     ONLINE
Adversarial      ONLINE
Risk             ONLINE
Broker Risk      ONLINE
Validator        ONLINE
Reporter         ONLINE
```

---

# 39. Dashboard de experimentos

```text
Experiment
Strategy
Dataset
Status
Sample Size
Drawdown
OOS Result
Monte Carlo
Risk
Broker Risk
Decision
```

---

# 40. Ciclo autônomo do Crew

```text
START
 ↓
Health Check
 ↓
Data Check
 ↓
Load State
 ↓
Research
 ↓
Quantification
 ↓
Backtest
 ↓
Statistics
 ↓
Adversarial
 ↓
Risk
 ↓
Validation
 ↓
Report
 ↓
Save State
 ↓
Next Experiment
```

---

# 41. Controle de estado

Estados possíveis:

```text
IDLE
RUNNING
PAUSED
ERROR
STOPPED
EMERGENCY_STOPPED
```

O sistema deve sobreviver a reinicializações sem perder o estado.

---

# 42. Falhas

Se um agente falhar:

```text
Agent Error
 ↓
log
 ↓
retry policy
 ↓
if repeated:
    pause task
 ↓
notify/report
```

Não executar ações críticas com estado desconhecido.

---

# 43. Rollback

Toda release deve poder voltar para a versão anterior.

Exemplo:

```text
v0.5.0
 ↓
v0.6.0
 ↓
problema
 ↓
rollback
 ↓
v0.5.0
```

---

# 44. Testes

Criar:

```text
tests/
├── unit/
├── integration/
├── regression/
├── backtest/
├── risk/
├── security/
└── agents/
```

Nenhuma release deve ser considerada estável sem passar pelos testes críticos.

---

# 45. Testes do Backtest Engine

Testar:

- entradas;
- saídas;
- timestamps;
- payout;
- capital;
- drawdown;
- sequência de perdas;
- cálculo de resultados;
- dados ausentes;
- dados duplicados;
- timezone.

---

# 46. Testes de segurança

Testar:

```text
DEMO não acessa REAL
REAL exige aprovação
kill switch funciona
logs não contêm secrets
agente não consegue apagar auditoria
configuração inválida é rejeitada
```

---

# 47. Fases de implementação

## FASE 0 — Especificação

Criar documentação.

Status:

```text
[ ] arquitetura
[ ] agentes
[ ] dados
[ ] risco
[ ] execução
[ ] validação
```

---

## FASE 1 — Infraestrutura

Implementar:

- configuração;
- logging;
- eventos;
- banco;
- modelos;
- testes.

Não implementar execução REAL.

---

## FASE 2 — Data Engine

Implementar:

- ingestão;
- validação;
- datasets;
- versionamento.

---

## FASE 3 — Backtest Engine

Implementar:

- execução;
- métricas;
- relatórios;
- testes.

---

## FASE 4 — Research Agents

Implementar:

- Researcher;
- Quant;
- Supervisor.

---

## FASE 5 — Validation

Implementar:

- Statistician;
- Adversarial;
- Risk;
- Validator.

---

## FASE 6 — Dashboard

Implementar:

- status;
- experimentos;
- estratégias;
- riscos;
- logs;
- DEMO.

---

## FASE 7 — Kiro Crew

Configurar:

- agentes;
- tarefas;
- workflows;
- permissões;
- execução;
- observabilidade.

---

## FASE 8 — DEMO

Executar somente ambiente demonstrativo.

---

## FASE 9 — Validação prolongada

Observar estabilidade.

Não alterar uma estratégia apenas para melhorar resultados históricos.

---

## FASE 10 — REAL

Somente após:

```text
[ ] validação técnica
[ ] validação estatística
[ ] DEMO
[ ] revisão de risco
[ ] revisão humana
[ ] aprovação explícita
```

---

# 48. Prompt inicial para o Kiro IDE

Use primeiro um prompt de análise, não de implementação:

```text
Leia o arquivo MASTER_SPEC.md e toda a documentação existente.

Não implemente código ainda.

Analise a especificação completa e produza:

1. arquitetura técnica;
2. dependências;
3. componentes;
4. interfaces;
5. banco de dados;
6. contratos entre agentes;
7. riscos técnicos;
8. pontos ambíguos;
9. plano de implementação por fases.

Não invente APIs de brokers.

Não crie integração REAL.

Não remova nenhuma camada de segurança definida na especificação.

Ao final, apresente um plano de implementação detalhado.
```

---

# 49. Prompt para infraestrutura

```text
Implemente somente a infraestrutura definida na MASTER_SPEC.md.

Crie:

- configuração;
- logging;
- event bus;
- modelos;
- persistência;
- state management;
- testes.

Não implemente execução de operações reais.

Não crie credenciais.

Execute os testes e corrija os erros encontrados.

Documente todas as decisões técnicas.
```

---

# 50. Prompt para Backtest Engine

```text
Implemente o Backtest Engine conforme MASTER_SPEC.md.

Requisitos:

- determinístico;
- reproduzível;
- independente de LLM;
- versionamento de datasets;
- registro completo dos experimentos;
- métricas;
- drawdown;
- sequência de perdas;
- cenários de capital;
- testes automatizados.

Impeça look-ahead bias e data leakage quando aplicável.

Não invente dados.

Não implemente execução REAL.
```

---

# 51. Prompt para agentes

```text
Implemente os agentes definidos na MASTER_SPEC.md.

Cada agente deve possuir:

- responsabilidade única;
- entrada definida;
- saída estruturada;
- logs;
- versionamento;
- tratamento de erro;
- testes.

Nenhum agente pode ultrapassar suas permissões.

O Supervisor deve apenas orquestrar o workflow definido.
```

---

# 52. Prompt para auditoria

```text
Audite o projeto inteiro contra MASTER_SPEC.md.

Procure:

- violações de arquitetura;
- data leakage;
- look-ahead bias;
- overfitting;
- acesso indevido a credenciais;
- possibilidade de DEMO acessar REAL;
- ausência de logs;
- ausência de testes;
- caminhos que permitam execução sem aprovação.

Não altere código.

Produza um relatório priorizado.
```

---

# 53. Prompt para o Crew

Depois que a versão estiver estável:

```text
Você é o Supervisor do AI Trading Research Lab.

Execute somente os workflows autorizados.

Prioridades:

1. integridade dos dados;
2. segurança;
3. reprodutibilidade;
4. validação estatística;
5. controle de risco;
6. pesquisa.

Nunca:

- acessar conta REAL sem autorização;
- alterar limites de segurança;
- apagar logs;
- ocultar resultados;
- pular etapas;
- considerar backtest como garantia de resultado futuro.

Quando encontrar um problema estrutural, gere um relatório/issue para revisão no Kiro IDE.
```

---

# 54. Protocolo de pesquisa

Cada ciclo:

```text
1. Selecionar hipótese
2. Formalizar hipótese
3. Selecionar dataset
4. Executar backtest
5. Registrar resultado
6. Estatística
7. Out-of-sample
8. Walk-forward
9. Monte Carlo
10. Adversarial
11. Risk
12. Decisão
13. Relatório
```

---

# 55. Protocolo de rejeição

Uma estratégia pode ser rejeitada por:

```text
- amostra insuficiente
- resultado instável
- forte overfitting
- degradação OOS
- risco excessivo
- falha adversarial
- data leakage
- look-ahead bias
- inconsistência operacional
```

Rejeição deve ser registrada.

---

# 56. Não destruir resultados negativos

Resultados negativos são informação.

Nunca apagar:

```text
strategy rejected
```

Em vez disso:

```text
strategies/rejected/
```

com motivo.

Isso evita repetir experimentos inúteis.

---

# 57. Base de conhecimento

O Crew deve construir conhecimento estruturado a partir dos experimentos.

Exemplo:

```text
Knowledge Base

HYP-001
→ rejeitada
→ instável fora da amostra

HYP-002
→ rejeitada
→ excesso de parâmetros

HYP-003
→ candidata
→ DEMO
```

---

# 58. Evitar loops inúteis da IA

O Supervisor deve detectar quando agentes ficam repetindo pequenas alterações.

Exemplo:

```text
HYP-001
 ↓
HYP-001-v2
 ↓
HYP-001-v3
 ↓
HYP-001-v4
 ↓
...
```

Se a estratégia continuar falhando pelo mesmo motivo, o Supervisor deve encerrar a linha de pesquisa.

---

# 59. Limite de experimentos

Configurar:

```yaml
max_experiments_per_cycle: configurable
max_retries_per_agent: configurable
max_parameter_variations: configurable
```

Evitar exploração ilimitada.

---

# 60. Observabilidade

Registrar:

```text
CPU
RAM
tempo de execução
quantidade de experimentos
erros
agentes ativos
backtests executados
tempo médio
```

Isso será importante quando o Crew ficar funcionando por longos períodos.

---

# 61. Relatório diário

Formato:

```text
AI TRADING LAB — DAILY REPORT

Experiments:
...

New hypotheses:
...

Validated:
...

Rejected:
...

Reasons:
...

DEMO:
...

Risk:
...

System errors:
...

Pending human review:
...
```

---

# 62. Relatório de estratégia

```text
STRATEGY REPORT

ID:
Version:

Dataset:

Period:

Sample:

Backtest:

Out-of-sample:

Walk-forward:

Monte Carlo:

Risk:

Broker Risk:

Adversarial:

DEMO:

Decision:
```

---

# 63. Critérios para uma estratégia entrar em DEMO

A estratégia deve ter:

```text
[ ] definição formal
[ ] dataset validado
[ ] backtest reproduzível
[ ] validação
[ ] OOS
[ ] walk-forward
[ ] Monte Carlo
[ ] adversarial
[ ] risk review
[ ] broker risk review (PASS)
[ ] relatório
```

Os thresholds devem ser configurados pelo projeto e não pelo LLM durante o experimento.

---

# 64. Critérios para solicitar REAL

Além das etapas anteriores:

```text
[ ] DEMO concluído
[ ] resultados registrados
[ ] riscos documentados
[ ] ausência de incidentes críticos
[ ] revisão humana
[ ] aprovação explícita
```

A aprovação não significa que a estratégia tenha garantia de rentabilidade.

---

# 65. Segurança operacional

Antes de qualquer integração REAL:

```text
1. verificar ambiente;
2. verificar credenciais;
3. verificar modo;
4. verificar estratégia;
5. verificar limites;
6. verificar kill switch;
7. verificar logs;
8. verificar aprovação.
```

Se qualquer item falhar:

```text
BLOCK
```

---

# 66. Regras para credenciais

Nunca:

```text
hardcode
```

Nunca:

```text
commit secret
```

Nunca:

```text
print(secret)
```

Nunca:

```text
log(secret)
```

---

# 67. Regras para brokers

A integração deve utilizar somente:

- APIs oficiais;
- mecanismos oficialmente suportados;
- credenciais autorizadas;
- ambientes de teste quando disponíveis.

Não tentar contornar autenticação, controles, limites ou mecanismos de segurança do provedor.

Nenhuma corretora deve ser integrada, nem em DEMO, sem passar pelo Broker Risk Agent (seção 16.1) com resultado `PASS`. Corretoras com `FAIL` ficam registradas em `strategies/rejected/` junto com o motivo, para não serem reavaliadas sem justificativa nova.

**Corretoras-alvo:**

```text
Polarium Broker  — status: PENDENTE (Broker Risk Agent ainda não executado)
                    sinais conhecidos: reputação suspensa, histórico de recusa de saque PIX
DayProfit        — status: PENDENTE (Broker Risk Agent ainda não executado)
                    sinais conhecidos: reclamações recentes de indisponibilidade e saldo não devolvido
```

Estar listada aqui não equivale a `PASS`. A entrada em DEMO continua condicionada ao resultado real do Broker Risk Agent no momento da integração — os sinais acima devem ser reavaliados, não descartados, quando o agente rodar.

---

# 68. Estado global

Exemplo:

```yaml
system:
  mode: DEMO
  status: RUNNING

risk:
  status: NORMAL

execution:
  enabled: true

real:
  enabled: false
```

O modo REAL deve possuir uma barreira adicional além de `mode`.

---

# 69. Configuração dos cinco capitais

Exemplo:

```yaml
capital_scenarios:
  - 100
  - 300
  - 500
  - 700
  - 1000
```

Esses valores são utilizados pelo simulador e pelos relatórios.

---

# 70. Arquivo de configuração RESEARCH

Exemplo:

```yaml
mode: RESEARCH

execution:
  enabled: false

real:
  enabled: false

capital_scenarios:
  - 100
  - 300
  - 500
  - 700
  - 1000
```

---

# 71. Arquivo DEMO

Exemplo:

```yaml
mode: DEMO

execution:
  enabled: true

real:
  enabled: false

capital_scenarios:
  - 100
  - 300
  - 500
  - 700
  - 1000
```

---

# 72. Arquivo REAL

O arquivo REAL deve ser altamente protegido.

Exemplo conceitual:

```yaml
mode: REAL

execution:
  enabled: false

human_approval:
  required: true

kill_switch:
  enabled: true
```

O valor de `execution.enabled` não deve ser alterado automaticamente por agentes.

---

# 73. Checklist antes do Crew

```text
[ ] MASTER_SPEC.md
[ ] arquitetura revisada
[ ] testes passando
[ ] Backtest Engine funcionando
[ ] banco funcionando
[ ] logging funcionando
[ ] agentes funcionando
[ ] dashboard funcionando
[ ] DEMO separado
[ ] REAL bloqueado
[ ] kill switch testado
[ ] credenciais protegidas
[ ] Git configurado
```

---

# 74. Checklist antes do DEMO

```text
[ ] dados validados
[ ] backtest reproduzível
[ ] OOS
[ ] walk-forward
[ ] Monte Carlo
[ ] adversarial
[ ] risk
[ ] auditoria
[ ] integração DEMO testada
```

---

# 75. Checklist antes do REAL

```text
[ ] estratégia validada
[ ] DEMO concluído
[ ] revisão humana
[ ] credenciais REAL separadas
[ ] limites configurados
[ ] kill switch testado
[ ] logs testados
[ ] rollback testado
[ ] aprovação explícita
```

---

# 76. Roadmap resumido

```text
FASE 0
Especificação

FASE 1
Infraestrutura

FASE 2
Dados

FASE 3
Backtest

FASE 4
Agentes

FASE 5
Validação

FASE 6
Dashboard

FASE 7
Crew

FASE 8
DEMO

FASE 9
Validação prolongada

FASE 10
REAL mediante aprovação humana
```

---

# 77. Definição de pronto

O projeto não será considerado pronto apenas porque:

```text
"o bot funciona"
```

Ele será considerado pronto quando:

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

# 78. Regra final

O sistema deve sempre preferir:

```text
menos operações
+
mais validação
+
mais transparência
+
mais controle
```

em vez de:

```text
mais operações
+
mais parâmetros
+
mais complexidade
+
resultado histórico artificialmente otimizado
```

A finalidade do projeto é construir um **laboratório quantitativo robusto e auditável**, e não uma máquina que prometa lucro.

---

# 79. Próximo passo de implementação

Depois de salvar este arquivo como:

```text
MASTER_SPEC.md
```

a sequência recomendada é:

```text
1. Abrir projeto no Kiro IDE
2. Criar MASTER_SPEC.md
3. Criar estrutura /docs
4. Pedir análise da especificação
5. Implementar infraestrutura
6. Implementar Data Engine
7. Implementar Backtest Engine
8. Implementar agentes
9. Implementar validação
10. Implementar dashboard
11. Testar tudo
12. Versionar
13. Configurar Kiro Crew
14. Executar RESEARCH
15. Executar DEMO
16. Somente depois avaliar eventual REAL
```

**Fim da especificação.**
