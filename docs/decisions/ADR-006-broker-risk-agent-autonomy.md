# ADR-006 — Broker Risk Agent autônomo com acesso à internet

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 16.1. Ambiguidade original: itens como
"status regulatório" e "histórico de reclamações" pareciam exigir curadoria
manual, não automação.

## Decisão

O usuário optou por manter o Broker Risk Agent totalmente autônomo: ele deve
pesquisar e apurar sozinho as informações necessárias (status regulatório,
histórico de reclamações, padrão de recusa de saque, etc.), sem depender de
insumo pré-coletado por humano.

## Justificativa e risco assumido

Este é o único agente do sistema com acesso de leitura à internet — todos os
demais agentes operam exclusivamente sobre dados internos (banco de dados,
arquivos do projeto, event bus). Isso o torna estruturalmente diferente e mais
arriscado:

- Fontes externas (fóruns, sites de reclamação, buscadores) são não confiáveis
  por padrão e podem conter conteúdo desatualizado, tendencioso ou manipulado.
- O agente deve tratar todo conteúdo obtido da web como dado não confiável,
  nunca como instrução — nenhuma página/resultado de busca pode alterar o
  comportamento do agente, apenas alimentar o relatório como evidência.
- Toda conclusão (`PASS`/`WARN`/`FAIL`) deve citar as fontes usadas
  (URL + data de acesso) no `findings[]` do relatório, para permitir auditoria
  humana posterior (seção 35 exige reconstrução da cadeia de decisão).
- Por ser uma avaliação de risco de contraparte com consequência bloqueante
  (seção 16.1: "FAIL bloqueia entrada em DEMO"), qualquer resultado do agente
  deve ficar disponível para revisão humana antes de ser tratado como definitivo
  — o agente decide, mas a decisão fica registrada e é auditável/reversível por
  humano, igual a qualquer outro agente do sistema.

## Consequências

- `agents/broker_risk/` é o único módulo de agente com dependência de acesso à
  rede (ex: um cliente HTTP/search). Isso deve ficar isolado — nenhum outro
  agente herda essa capacidade por padrão.
- `broker_risk_reports.findings` (json) deve obrigatoriamente incluir fontes
  citadas, não apenas a conclusão.
- Reavaliação periódica (ADR-003) reexecuta essa mesma pesquisa autônoma —
  o histórico de cada execução deve ser preservado, nunca sobrescrito.
