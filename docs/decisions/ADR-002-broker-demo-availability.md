# ADR-002 — Disponibilidade de ambiente DEMO nas corretoras-alvo

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 3.2, seção 67. Ambiguidade original: o que
fazer se uma corretora-alvo não tiver ambiente DEMO utilizável.

## Decisão

Não se aplica um fallback genérico. O usuário confirmou que as duas
corretoras-alvo definidas na seção 67 (Polarium Broker e DayProfit) possuem
modo DEMO nativo. Portanto:

- Não será implementado um mecanismo de "skip" ou bypass para corretora sem DEMO.
- O Broker Risk Agent (seção 16.1) continua sendo obrigatório e bloqueante antes
  de qualquer uso do DEMO dessas corretoras — a existência de um modo DEMO nativo
  não substitui a avaliação de risco de contraparte.
- Caso uma corretora futura seja adicionada sem DEMO nativo, este ADR deve ser
  revisado antes de qualquer integração (não avançar por analogia).

## Consequências

- `execution/demo/` assume que sempre existe um modo demo nativo na corretora
  integrada. Se isso mudar, revisar este documento primeiro.
