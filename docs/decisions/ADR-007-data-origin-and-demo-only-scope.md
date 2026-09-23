# ADR-007 — Origem de dado isolada e escopo DEMO-only

**Status:** Aceito
**Substitui:** ADR-005 (coleta exclusiva da corretora como forma de reduzir basis risk)
**Ajusta:** ADR-002, ADR-003, ADR-006 (Broker Risk deixa de ser gate bloqueante)
**Decisão do usuário:** o projeto opera em DEMO, sem capital em risco. O objetivo
é encontrar estratégias que funcionem em opções binárias. Dados OTC devem ser
coletados e mantidos separados por fonte.

## Contexto

O ADR-005 assumia que coletar da própria corretora reduziria `basis_risk`.
Duas coisas mudaram:

1. As corretoras-alvo não expõem API oficial, então "coletar da corretora" não
   tem um caminho documentado.
2. O projeto permanece em DEMO. Sem depósito, não há risco de saque, de
   contraparte ou de perda de capital. O gate de risco de contraparte estava
   protegendo um ativo que não existe nesta fase.

## Decisão

### 1. Origem de dado é explícita e isolada

Todo ponto e toda versão de dataset carregam uma origem declarada:

```text
BROKER_OTC    — preço gerado pela própria corretora (sintético, por corretora)
MARKET_PROXY  — dado real de mercado usado como referência
```

Regras:

- Uma série nunca mistura origens. Ponto com origem divergente é rejeitado,
  igual ao que já ocorre com broker/asset/timeframe divergentes.
- Uma versão de dataset tem exatamente uma origem.
- Datasets de corretoras diferentes permanecem separados, mesmo para o mesmo
  ativo e timeframe. O preço OTC da corretora A não é comparável ao da B.

### 2. Broker Risk deixa de bloquear

O Broker Risk Agent continua existindo e continua registrando o que apurar, mas
passa a ser **informativo e configurável**, não eliminatório:

```yaml
broker_risk:
  blocking: false   # RESEARCH e DEMO
  blocking: true    # REAL (mantido, para quando/se essa fase existir)
```

Justificativa: o agente foi desenhado para proteger capital contra risco de
contraparte (recusa de saque, idoneidade). Em DEMO não há depósito, então o
risco que ele mede não se materializa. Manter um gate eliminatório aí só
impediria a pesquisa sem proteger nada.

Consequência: a regra "FAIL bloqueia entrada em DEMO" (MASTER_SPEC seção 16.1,
67) fica suspensa enquanto `broker_risk.blocking` for falso. Se o projeto algum
dia considerar REAL, o gate volta a valer e a avaliação precisa ser refeita.

### 3. `basis_risk` é informativo, não bloqueante

Datasets `BROKER_OTC` recebem `basis_risk` alto automaticamente e isso aparece
no relatório de estratégia. Não impede promoção. O papel dele é delimitar o
escopo da conclusão, não barrar o experimento.

## Escopo da conclusão (limitação registrada)

Uma estratégia validada sobre dados `BROKER_OTC` de uma corretora específica é
uma conclusão sobre **aquela** corretora, naquele período. Não é transferível
para outra corretora, nem automaticamente para a conta real da mesma corretora,
porque o preço é gerado pelo provedor e pode mudar.

Isso não é um risco financeiro nesta fase — é o limite do que o experimento
prova. Fica registrado para que nenhum relatório futuro sugira generalidade que
o dado não sustenta.

## Coleta de dados

Sem API oficial, a ingestão passa a ser feita a partir de arquivo exportado ou
capturado pelo usuário, através de um importador com formato validado. A
arquitetura expõe uma porta (`MarketDataSource`) para que um coletor ao vivo
possa ser acoplado depois sem alterar o pipeline.

O importador não afrouxa nenhuma validação: timestamp com timezone, ordem
cronológica, duplicatas, gaps e preço válido continuam obrigatórios, e tudo que
for rejeitado continua registrado.

## Consequências

- `data_models.py` ganha `DataOrigin`; `RawPricePoint` e `ValidatedPricePoint`
  passam a declarar origem; `DatasetVersion` registra a origem da versão.
- `validate_and_normalize` rejeita mistura de origens.
- `configuration.py` ganha `BrokerRiskConfig(blocking: bool)`.
- O Validator só exige `broker_risk_passed` quando o gate estiver ligado.
- Pesquisa de reputação de corretora sai do fluxo obrigatório.
