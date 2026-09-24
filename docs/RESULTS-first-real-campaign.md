# Primeira campanha em dado real — resultado

Primeira execução do pipeline completo sobre dados coletados da plataforma, e
não sobre amostra sintética.

## Dados

| | |
|---|---|
| Dataset | `DATA-EURUSD-OTC-M1` v1 |
| Ativo | EURUSD-OTC (`active_id` 76) |
| Vela | M1 (60s) |
| Pontos | 8.000, todos com OHLC completo |
| Cobertura | 2026-09-18T10:25Z → 2026-09-24T00:09Z |
| Origem | `BROKER_OTC` (basis_risk alto) |
| Rejeitados na validação | 0 |
| Duplicatas | 0 |
| Gaps | 5, todos de 360s às 08:04 (manutenção diária) |
| Hash | `ccd02829415916047dceb05473a3dd8dc63eaf3453feb0eb6ad2d66b0aaa9da9` |
| Payout usado | 0,89 (lido da plataforma, turbo 60s) |
| Acerto para empatar | 52,91% |

## Resultado

**101 backtests, 1 com expectancy positivo, 0 aprovados.**

A melhor regra encontrada:

```text
HYP-000177
  operações:        1.259
  acerto:           53,22%
  expectancy:       +0,0058
  drawdown:         59,8%
  perdas seguidas:  10
  folds positivos:  40%  (exigido: 100%)
  degradação OOS:   -0,0308
  decisão:          IDEA -> REJECTED
  reprovou em:      walk_forward_passed, expectancy_positive_net_payout,
                    drawdown_reviewed, risk_reviewed
```

### Por que 53,22% de acerto não significa nada aqui

O acerto necessário para empatar com payout 0,89 é 52,91%. A regra ficou
**0,31 ponto percentual** acima disso.

Com 1.259 operações, o erro padrão da taxa de acerto é **1,41%**. Ou seja, a
margem observada equivale a **0,22 erro padrão** — estatisticamente
indistinguível de zero. Precisaria de aproximadamente 20 vezes mais operações
para que uma vantagem desse tamanho fosse detectável.

Somado a isso: ganhou em apenas 2 dos 5 folds, piorou fora da amostra, e teve
59,8% de drawdown. Qualquer um desses itens já reprovaria sozinho.

## A comparação que importa

| Dado | Regras com expectancy > 0 |
|---|---|
| Caminhada aleatória sintética | 17 de 100 |
| EURUSD-OTC real da corretora | 1 de 101 |

O dado OTC real é **mais difícil de bater do que ruído aleatório**.

Isso não é um bug nem má sorte: é consistente com o fato de que em OTC quem gera
o preço é a própria contraparte, que lucra quando o cliente perde. Um gerador
aleatório é neutro; um gerador com incentivo contrário, não.

## Interpretação honesta

Nenhuma conclusão sobre as 1.480 regras do espaço de busca — foram testadas 101,
em 6 dias de dado, em um ativo, em um timeframe. É amostra pequena.

O que **pode** ser afirmado:

1. O pipeline funciona de ponta a ponta com dado real, de forma auditável.
2. O payout real (89%) exige 52,91% de acerto só para empatar, e nenhuma das
   regras testadas superou isso de forma estatisticamente significativa.
3. As barreiras de validação estão fazendo o trabalho: rejeitaram tanto os 17
   falsos positivos do dado sintético quanto o único candidato do dado real.

O que **não** pode ser afirmado: que não existe estratégia viável. Só que
nenhuma das testadas até agora é, e que o limiar é alto.

## Próximos passos possíveis

- Acumular mais histórico. O coletor grava versões append-only, então rodar
  periodicamente aumenta a amostra sem sobrescrever nada.
- Varrer o espaço completo (1.480 regras) numa campanha longa. A ~5,7s por
  hipótese, é da ordem de 2h20 — perfil adequado para execução autônoma no Crew.
- Testar outros ativos e timeframes. `blitz` (5–15s) e `binary` (900s) têm
  payout e dinâmica diferentes.
- Comparar a série OTC com a série real do mesmo par para quantificar o
  `basis_risk` em número, em vez de apenas rotulá-lo.
