# Relatório de defeito estrutural — envenenamento global do `tried_count`

**Autor:** Kiro (Kiro Crew — Supervisor do AI Trading Research Lab)
**Data:** 2026-09-23
**Severidade:** ALTA — bloqueia toda a pesquisa (varredura não avalia nenhuma hipótese)
**Estado do repo:** Fases 1–7, 273 testes OK. Descoberto durante a primeira
campanha em dado real coletado da Polarium.

---

## Resumo em uma linha

`run_cycle` grava o experimento e marca a hipótese como *testada* **antes** de
checar a permissão do Supervisor. Quando o sistema não está em `IDLE`/`RUNNING`,
a permissão é negada — mas o experimento já foi persistido. Como o `tried_count`
é reconstruído **globalmente** desses experimentos (sem escopo de dataset), uma
única campanha rodada em estado errado marca o espaço inteiro (1480 regras) como
"varrido" **para todos os ativos**, permanentemente.

---

## Como reproduzir

1. Deixar o sistema em `STOPPED` (ex.: após `cli stop`).
2. Rodar `python scripts/run_campaign.py --dataset-id <ID> --payout <p>`.
3. Observar: cada lote imprime `HYP-xxxxxx: status STOPPED não permite iniciar
   tarefas`, `avaliadas: 0`, mas `testadas` avança até `1480/1480`.
4. Rodar `cli reset --operator <nome>` (STOPPED → IDLE) e rodar a campanha de
   novo, em **qualquer** dataset (mesmo um recém-criado): `já testadas: 1480`,
   `espaço de busca varrido por completo`, `avaliadas: 0`.

Foi exatamente o observado em 2026-09-23:
- Campanha em `DATA-EURUSD-OTC-M1` com sistema em STOPPED → 1264 erros
  `status STOPPED não permite iniciar tarefas`, 1480/1480 "testadas", 0 avaliadas.
- Após `reset` para IDLE, campanhas em `DATA-EURUSD-OTC-M1`, `DATA-USDCHF-OTC-M1`
  e `DATA-USDXOF-OTC-M1` retornam todas `1480/1480 já testadas, 0 avaliadas`.

---

## Causa raiz

### 1. Ordem de operações em `_evaluate_hypothesis`

Arquivo: `src/ai_trading_lab/runtime.py`, método `_evaluate_hypothesis` (~linha 233).

Ordem atual:

```
self._tried_signatures.add(signature_of(dict(hypothesis.parameters)))   # marca testada
experiment_id = self._experiment_ids.next_id()
self._store.append_experiment(Experiment(...))                          # PERSISTE experimento
self._strategy_states.initialize(...)
permission = self._supervisor.request_permission(...)                   # SÓ AQUI checa status
```

O gate de status vive em `src/ai_trading_lab/agents/supervisor.py` (~linha 55):

```
if system_status not in {SystemStatus.IDLE, SystemStatus.RUNNING}:
    return self._deny(request, f"status {system_status.value} não permite iniciar tarefas", ...)
```

Quando esse `deny` dispara, a assinatura e o experimento **já foram gravados**.

### 2. `tried_count` é global (sem escopo de dataset)

Arquivo: `src/ai_trading_lab/runtime.py`, `_load_tried_signatures` (~linha 378):

```
def _load_tried_signatures(store):
    signatures = set()
    for parameters in store.load_experiment_parameters():   # <- SEM dataset_prefix
        signatures.add(signature_of(dict(parameters)))
    return signatures
```

`load_experiment_parameters(dataset_prefix=None)` existe em
`src/ai_trading_lab/persistence.py` (~linha 470) e **aceita** um filtro de
dataset, mas o runtime não o passa. A assinatura (`signature_of`) usa apenas os
parâmetros da regra — não inclui o dataset. Logo, experimentos de um ativo
contam como "testados" para todos os outros.

### 3. `experiments` é append-only (correto — não é o bug)

A tabela `experiments` é append-only por design (MASTER_SPEC seção 21), com
trigger de proteção. **Isso está certo** e não deve mudar. O bug não é a
imutabilidade; é gravar cedo demais e contar globalmente.

---

## Impacto

- `state.db` (`logs/state.db`) contém agora ~1264 experimentos que nunca foram
  avaliados. `tried_count` = 1480 (espaço inteiro).
- Toda campanha futura vê o espaço como completo e sai sem avaliar, em qualquer
  ativo/timeframe. A pesquisa está efetivamente bloqueada.
- Nenhum dado foi perdido; nenhum resultado negativo foi apagado. As velas
  coletadas (EURUSD/USDCHF/USDXOF, datasets versionados) estão intactas.

---

## Correção proposta (para o Kiro IDE)

**Fix primário — mover o gate de status para antes da gravação.** Em
`_evaluate_hypothesis`, checar a permissão do Supervisor **antes** de
`_tried_signatures.add` e `append_experiment`. Se negada por status, não contar
como testada nem gravar experimento. Melhor ainda: `run_cycle` deve checar o
status logo no início e devolver `CycleOutcome` sem iterar hipóteses quando o
sistema não estiver IDLE/RUNNING — e `run_campaign.py` deve abortar o loop no
primeiro `deny` por status, em vez de rodar 106 lotes gravando fantasmas.

**Fix secundário — escopar o `tried_count` por dataset.** Passar o
`dataset_prefix` em `_load_tried_signatures` (a assinatura ou o filtro deve
incluir o dataset), para que a varredura de um ativo não marque o espaço de
outro. Decidir no design se "já testado" é por ativo (provável intenção) ou
global.

**Teste de regressão a adicionar:** rodar `run_cycle` com o sistema em `STOPPED`
NÃO deve incrementar `tried_count` nem gravar em `experiments`.

## Limpeza do estado envenenado

Como `experiments` é append-only e protegido por trigger, a limpeza é uma
**decisão humana auditada**, não algo a fazer por fora:
- Opção A: após o fix, bumpar `software_version` e/ou escopar por dataset, de
  modo que a contagem recomece limpa (os fantasmas ficam no histórico, mas não
  contam mais).
- Opção B: migração auditada que marque os experimentos-fantasma (os sem
  resultado de backtest associado) como inválidos — registrada em auditoria,
  nunca um `DELETE` silencioso.

Recomendo a Opção A: preserva o append-only e é reversível por inspeção.

---

## RESOLUÇÃO (aplicada em 2026-09-23, verificada)

Ambos os fixes foram aplicados em `src/ai_trading_lab/runtime.py` e os 273
testes continuam passando.

**Fix 1 — gate antes da gravação.** Em `_evaluate_hypothesis`, o
`request_permission` do Supervisor (gate de status) foi movido para ANTES de
`_tried_signatures...add` e `append_experiment`. Uma hipótese negada por status
(ex.: STOPPED) agora retorna sem contar como testada nem gravar experimento.

**Fix 2 — tried_count escopado por dataset.** `_load_tried_signatures` passou a
aceitar `dataset_prefix`. O runtime substituiu o set global único por um cache
`dict[str, set]` por `dataset_id` (`_tried_signatures_for`), preenchido sob
demanda. `run_cycle` fixa `_active_dataset_id` e usa o set do dataset atual no
`exclude`; `tried_count` reflete o dataset ativo; a margem de expectancy
(`required_expectancy_margin`) usa a contagem do dataset atual.

**Verificação empírica.** Antes do fix, a varredura em `DATA-USDCHF-OTC-M1`
retornava `avaliadas: 0` (espaço "cheio" por contaminação global). Depois do
fix, a mesma varredura avaliou 48 hipóteses de verdade (45 rejeitadas, 3
needs-research, 0 avançaram, 0 erros). Os experimentos-fantasma estavam todos em
`DATA-EURUSD-OTC-M1@v1/v2` (1503) e `DATA-OHLC@v1` (60); USDCHF/USDXOF nunca
gravaram experimento — só apareciam cheios pela contagem global.

**Estado residual do EURUSD.** O dataset `DATA-EURUSD-OTC-M1` ainda carrega os
~1288 experimentos-fantasma (dos lotes negados por STOPPED, gravados ANTES do
Fix 1). Com o escopo por dataset, isso afeta só o EURUSD. Para varrer o EURUSD
limpo: coletar sob um novo `dataset_id` (ex.: `DATA-EURUSD-OTC-M1B`) OU aplicar
a migração auditada da Opção A. Os demais ativos já varrem normalmente.

**Regressão a adicionar (ainda pendente):** teste de que `run_cycle` com sistema
em STOPPED não incrementa `tried_count` nem grava em `experiments`.

