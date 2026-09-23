# ADR-004 — Critério de expectancy consistente entre folds

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 29 ("expectancy > 0 de forma consistente
entre folds do walk-forward, não apenas na média geral"). Ambiguidade original:
"consistente" não era quantificado.

## Decisão

Critério adotado: **100% dos folds do walk-forward devem ter `expectancy > 0`**
para a estratégia ser considerada candidata a avançar de `OUT_OF_SAMPLE` para
`MONTE_CARLO`/`DEMO_CANDIDATE`.

Não se usa média geral, nem "maioria dos folds" — um único fold com expectancy
negativo reprova a estratégia nesta etapa.

O valor é configurável via `configs/*.yaml`:

```yaml
validation:
  min_fold_pass_ratio: 1.0   # 1.0 = 100% dos folds; ajustável no futuro
```

## Justificativa

É a leitura mais rigorosa e mais segura da frase da spec ("não apenas na média
geral"). Como o projeto prioriza "mais validação" sobre "mais operações"
(seção 78), o critério mais estrito é o default seguro. Deixar configurável
permite relaxar essa régua no futuro com decisão explícita e documentada, nunca
por ajuste silencioso de agente.

## Consequências

- `core/engine/walk_forward.py` deve expor o resultado por fold individualmente,
  não apenas a agregação.
- O Validator Agent lê `min_fold_pass_ratio` da config ativa (nunca hardcoded)
  antes de decidir a transição de estado.
- Alterar este valor em produção exige revisão humana e nova versão de config,
  igual a qualquer outro threshold de validação (seção 29: "thresholds
  configuráveis e documentados").
