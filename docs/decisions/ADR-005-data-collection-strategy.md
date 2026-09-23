# ADR-005 — Estratégia de coleta de dados (sem dataset histórico externo)

**Status:** Aceito
**Contexto:** MASTER_SPEC.md seção 12 (Data Agent), seção 16.1 ("dado crítico":
preço em ativos OTC é gerado pela própria corretora, não por mercado público).
Ambiguidade original: fonte de dados de mercado nunca era definida pela spec.

## Decisão

Não haverá importação de dataset histórico de terceiro. A única fonte de dados
legítima é a própria corretora-alvo, observada e registrada pelo sistema em
tempo real, construindo histórico próprio do zero.

Implicações diretas na arquitetura:

1. **Fase 2 (Data Engine) não é um "importador", é um coletor/gravador.**
   Enquanto o sistema está em modo `RESEARCH` ou `DEMO`, um processo de captura
   observa os preços/candles expostos pela corretora e grava em `data/raw/`
   com timestamp, fonte e versão — nunca sobrescreve, sempre acumula.
2. **Não existe Monte Carlo/walk-forward robusto no dia 1.** Backtest e validação
   estatística só se tornam estatisticamente úteis depois que exista volume
   mínimo de histórico coletado (o volume mínimo é um threshold de configuração
   a definir na Fase 2/3, análogo ao `min_fold_pass_ratio` do ADR-004).
3. **`basis_risk` (seção 16.1) fica estruturalmente reduzido, mas não eliminado**,
   porque agora o dado histórico vem da mesma fonte que o dado ao vivo (a própria
   corretora) — isso é uma vantagem em relação a usar proxy de terceiro, mas não
   remove o risco de a corretora alterar seu comportamento de precificação entre
   o momento da coleta e o momento da operação real.
4. **O sistema evolui de forma incremental/online**: hipóteses são testadas contra
   o histórico próprio que cresce a cada ciclo, e o Adversarial/Statistician
   precisam considerar o tamanho da amostra disponível no momento da avaliação
   (amostra insuficiente é motivo de rejeição explícito na seção 55).

## Justificativa

O usuário confirmou explicitamente esse modelo: "corretoras de opção binária
mudam dados e não são 100% do mercado", portanto qualquer dataset de terceiro
seria uma fonte inconsistente com o preço real de execução. Coletar diretamente
da corretora-alvo é a única forma de manter o dado de backtest e o dado de
execução na mesma origem, reduzindo (não eliminando) basis risk.

## Consequências

- `agents/data/` precisa de um módulo de captura contínua, não só validação/ETL
  de arquivo estático.
- `datasets` (entidade de banco) precisa de campo indicando a corretora de origem
  e o intervalo de tempo real coberto pela coleta (não um "dataset fixo" versionado
  de uma vez, mas um dataset que cresce e é versionado por snapshot/corte).
- É necessário um threshold mínimo de amostra antes de qualquer backtest ser
  considerado válido — a ser definido tecnicamente na Fase 2/3, e documentado
  como novo ADR quando o valor for escolhido.
- O mecanismo exato de captura (polling de preço via interface oficial da
  corretora, WebSocket oficial, etc.) depende da documentação/API oficial de
  cada corretora e será definido durante a implementação da Fase 2 — nunca por
  engenharia reversa ou automação não suportada oficialmente (seção 67).
