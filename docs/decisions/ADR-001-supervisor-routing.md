# ADR-001 — Roteamento de tarefas via Supervisor

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 9, seção 40. Ambiguidade original: não estava
definido se agentes se comunicam diretamente entre si ou sempre via Supervisor.

## Decisão

Todo agente que deseja executar uma ação (iniciar uma tarefa, consumir output de
outro agente, avançar um experimento) deve solicitar autorização ao Supervisor
antes de agir. O Supervisor não microgerencia a execução interna do agente — ele
apenas concede ou nega a permissão de iniciar a tarefa (gate de entrada), verifica
pré-condições (seção 9: "verificar pré-condições; impedir etapas inválidas") e
registra o evento em auditoria.

Nenhum agente chama outro agente diretamente. A comunicação ocorre via:

```text
Agente A → Supervisor.request_permission(task) → [PASS/DENY]
Agente A → executa (se PASS)
Agente A → Supervisor.publish(output) → Event Bus
Agente B → Supervisor.request_permission(task, depende_de=output) → [PASS/DENY]
```

## Justificativa

- Mantém a regra da seção 34 ("agentes não podem ultrapassar suas permissões")
  enforçável em um único ponto central, não espalhada por cada agente.
- Evita "bagunça" (palavra do usuário) de chamadas cruzadas sem controle,
  mas sem burocracia excessiva: é uma autorização de entrada, não um workflow
  passo a passo supervisionado durante a execução da tarefa.
- Facilita auditoria (seção 35): toda transição de trabalho entre agentes passa
  por um ponto só, logável.

## Consequências

- `agents/base/agent.py` deve expor um método padrão de solicitação ao Supervisor
  antes de qualquer ação com efeito (leitura simples de dados já publicados não
  precisa de permissão, apenas ações que mudam estado ou iniciam trabalho).
- O Supervisor precisa de uma tabela/estrutura de regras de pré-condição por tipo
  de tarefa (ex: Backtester só pode iniciar se `FormalStrategy` existe e está em
  estado `IDEA`).
- Comunicação é assíncrona via Event Bus (`core/events`), não chamada de função
  direta entre módulos de agente.
