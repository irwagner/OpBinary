# ADR-003 — Comportamento na regressão de Broker Risk (PASS → FAIL)

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 16.1 ("este agente deve ser reexecutado
periodicamente"). Ambiguidade original: não estava definido o que ocorre com
estratégias já em DEMO quando a corretora piora de PASS para FAIL.

## Decisão

Adotada a regra mais conservadora, alinhada à seção 78 da spec
("mais controle" > "mais operações"):

Quando uma reavaliação periódica do Broker Risk Agent resultar em `FAIL` para
uma corretora que estava `PASS`:

1. Todas as estratégias em estado `DEMO` associadas a essa corretora são
   **suspensas automaticamente** (não paradas/deletadas). Suspender significa:
   nenhuma nova operação DEMO é enviada, mas todo histórico e estado são
   preservados intactos (coerente com a seção 56 — nunca destruir resultado).
2. Um `system_event` de severidade alta é registrado, e um item de
   **revisão humana obrigatória** é criado (reaproveitando a estrutura de
   `promotion_requests` ou uma entidade equivalente de "incidente").
3. Nenhuma estratégia suspensa por este motivo pode retomar DEMO automaticamente
   — requer decisão humana explícita, mesmo que a corretora volte a `PASS` depois.
4. O rebaixamento para `WARN` (não `FAIL`) não suspende automaticamente, mas
   gera alerta e reduz o intervalo até a próxima reavaliação.

## Justificativa

O risco de contraparte não é um risco de estratégia — é um risco de a própria
infraestrutura de execução deixar de ser confiável. Continuar operando (mesmo em
DEMO) contra uma corretora reprovada contamina os dados coletados (ver ADR-005)
e pode mascarar problemas reais de saque/idoneidade como se fossem resultado de
mercado.

## Consequências

- `broker_risk_reports` precisa de campo de histórico (não sobrescrever o último
  resultado — manter série temporal por corretora).
- `demo_sessions` precisa de um campo de status (`ACTIVE`/`SUSPENDED`) e motivo.
- O Supervisor deve consultar o status mais recente de Broker Risk antes de
  autorizar qualquer nova operação DEMO (gate de pré-condição, ver ADR-001).
