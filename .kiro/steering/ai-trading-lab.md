# AI Trading Research Lab — regras permanentes

Contexto sempre válido para qualquer trabalho neste repositório, em qualquer
cliente (IDE ou Crew).

## O que este projeto é

Laboratório de pesquisa quantitativa para opções binárias. O objetivo é
descobrir se existe estratégia com vantagem real e, quando existir, prová-la de
forma auditável. **Não** é um robô de execução.

Estado atual: Fases 1 a 7 implementadas, 273 testes passando, rodando em modo
RESEARCH com dado real coletado da plataforma.

## Regras não negociáveis

1. **Nunca receber, armazenar ou logar credencial.** O SSID vem de variável de
   ambiente (`BROKER_SSID`), nunca de arquivo, nunca de argumento de linha de
   comando. `logging.sanitize` mascara `ssid`, `session_id`, `token`, `password`
   e variantes antes de qualquer escrita.
2. **Nenhuma ordem de compra ou venda.** Os coletores são somente leitura. Existe
   teste que falha se alguém adicionar `buy`, `sell`, `place_order`, `withdraw`
   ou similares ao módulo de coletor.
3. **REAL permanece bloqueado.** `configs/real.yaml` é rejeitado se
   `execution.enabled` for verdadeiro. Transição de estratégia para `REAL` exige
   aprovação humana persistida em `promotion_requests`, validada em três camadas.
4. **Nunca apagar log, auditoria ou resultado negativo.** Resultado negativo é
   informação: evita repetir experimento inútil. As tabelas de auditoria,
   experimentos e datasets são append-only, com triggers no banco.
5. **Payout nunca é hardcoded.** É lido da plataforma
   (`scripts/list_actives.py`) porque varia por ativo, grupo e expiração, e
   define o limiar de acerto necessário.
6. **LLM não produz número.** Métricas, backtest, walk-forward e Monte Carlo são
   código determinístico e testado. O papel do LLM é gerar hipótese, interpretar
   e procurar inconsistência.
7. **Não pular etapa de validação.** Uma estratégia só avança se passar por
   walk-forward com todos os folds positivos, out-of-sample, Monte Carlo,
   adversarial e revisão de risco.

## Aritmética que decide tudo

```text
expectancy = (acerto × payout) - (erro × 1)
acerto para empatar = 1 / (1 + payout)
```

Com payout 0,89 o empate exige **52,91%** de acerto. Taxa de acerto sozinha nunca
valida nada. E margem sobre o empate precisa ser comparada ao **erro padrão**:
com n operações, o erro padrão do acerto é aproximadamente `0,5/√n`. Margem
menor que um erro padrão é ruído, não vantagem.

## Interpretação de resultados

Rejeitar quase tudo é o comportamento correto. Em teste com caminhada aleatória
sintética, 17 de 100 regras mostraram lucro por puro acaso — e o sistema rejeitou
todas. Uma validação que aprova estratégia em ruído está quebrada, não generosa.

Quanto mais regras testadas no mesmo dado, mais falsos vencedores aparecem. Por
isso existe margem que cresce com o tamanho da varredura
(`required_expectancy_margin`).

## Dado OTC

Em OTC quem gera o preço é a própria corretora, que é a contraparte e lucra
quando o cliente perde. Consequências registradas em ADR-007:

- `origin` é declarada explicitamente: `BROKER_OTC` ou `MARKET_PROXY`;
- origens nunca se misturam em um dataset;
- `BROKER_OTC` recebe `basis_risk` alto, informativo;
- conclusão obtida em OTC de uma corretora vale para **aquela** corretora.

## Comandos principais

```powershell
$env:PYTHONPATH = "src"

python -m ai_trading_lab.cli status --dataset-id <ID>
python -m ai_trading_lab.cli agents
python scripts/list_actives.py --filter EUR
python scripts/collect_candles.py --active-id 76 --asset EURUSD-OTC ...
python scripts/collector_loop.py ...        # coleta acumulativa
python scripts/run_campaign.py ...          # varredura longa, retomável
python scripts/ranking.py --dataset-id <ID> --payout <p>
python scripts/why_rejected.py <HYP-ID>
```

Testes: `$env:PYTHONPATH='src;.'; python -m unittest discover -s tests -t .`

## Documentação

- `MASTER_SPEC.md` — especificação original
- `docs/ARCHITECTURE.md`, `docs/AGENT_CONTRACTS.md`, `docs/SECURITY_MODEL.md`
- `docs/OPERATIONS.md` — manual de operação
- `docs/decisions/ADR-001..007` — decisões e por quê
- `docs/RESEARCH-broker-automation-landscape.md` — protocolo da plataforma
- `docs/RESULTS-first-real-campaign.md` — primeiro resultado em dado real
