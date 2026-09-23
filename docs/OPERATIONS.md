# AI Trading Research Lab — Manual de Operação

Estado: **ON, em RESEARCH.** Pipeline completo validado de ponta a ponta
(importação → backtest → walk-forward → Monte Carlo → risco → decisão).

```text
Mode:        RESEARCH
Execution:   DISABLED
REAL:        BLOCKED
```

---

## 1. Pré-requisitos

- Python 3.12 (validado em 3.12.10)
- PyYAML 6.0.3 (já presente no ambiente)
- Nenhuma credencial é necessária em RESEARCH. Nenhuma credencial existe no código.

Todos os comandos rodam a partir de `ai-trading-lab/`:

```powershell
cd c:\OpBinario\ai-trading-lab
$env:PYTHONPATH = 'src'
```

---

## 2. Comandos

| Comando | O que faz |
|---|---|
| `python -m ai_trading_lab.cli status --dataset-id <ID>` | Dashboard, health check e datasets |
| `python -m ai_trading_lab.cli agents` | Lista os 11 agentes registrados |
| `python -m ai_trading_lab.cli import ...` | Importa série de CSV/JSON (ver seção 2.1) |
| `python -m ai_trading_lab.cli cycle --dataset-id <ID> --payout <valor>` | Executa um ciclo de pesquisa |
| `python -m ai_trading_lab.cli stop` | Encerra o ciclo (RUNNING → STOPPED) |
| `python -m ai_trading_lab.cli reset --operator <nome>` | STOPPED → IDLE |
| `python -m ai_trading_lab.cli emergency-stop --operator <nome> --reason <texto>` | Kill switch de sistema |
| `python -m ai_trading_lab.cli clear-emergency --operator <nome>` | Libera o kill switch (→ STOPPED) |

`--mode` aceita `research` (padrão), `demo` ou `real`. O modo `real` carrega apenas
para inspeção: a configuração reprova execução por construção.

`--payout` é obrigatório em `cycle` e deve ser o payout **real** do ativo na
corretora. O sistema nunca inventa esse número.

---

## 2.1 Importar dados

```powershell
python -m ai_trading_lab.cli import `
  --file data/raw/minha_serie.csv `
  --dataset-id DATA-EURUSD-OTC `
  --broker Polarium `
  --asset EURUSD-OTC `
  --timeframe M1 `
  --origin BROKER_OTC
```

Formato aceito: CSV com cabeçalho ou JSON com lista de objetos. Colunas
obrigatórias: `timestamp` e `price`.

```csv
timestamp,price
2026-09-23T14:30:00-03:00,1.16542
2026-09-23T14:31:00-03:00,1.16551
```

Regras da importação:

- **Timezone é obrigatório.** `2026-09-23T14:30:00` sem offset é rejeitado.
  Use `-03:00` ou `Z`. Epoch em segundos também é aceito.
- `--origin` é declarado por você, nunca inferido do arquivo:
  - `BROKER_OTC` — preço gerado pela corretora. Marca `basis_risk` alto.
  - `MARKET_PROXY` — dado real de mercado usado como referência.
- **Origens nunca se misturam.** Cada corretora tem seu próprio dataset, mesmo
  para o mesmo ativo e timeframe. O preço OTC da corretora A não é comparável
  ao da B.
- Linha inválida é rejeitada e reportada, nunca corrigida por suposição.
- Cada importação cria uma **nova versão** do dataset com hash próprio. Versões
  anteriores nunca são sobrescritas.

---

## 3. Rodar os testes

```powershell
$env:PYTHONPATH = 'src;.'
python -m unittest discover -s tests -t .
```

Resultado esperado: **195 testes, OK**.

---

## 4. Máquina de estados do sistema

```text
IDLE ⇄ RUNNING → PAUSED/ERROR → STOPPED → IDLE
qualquer estado → EMERGENCY_STOPPED
EMERGENCY_STOPPED → STOPPED   (somente por ação humana explícita)
```

`EMERGENCY_STOPPED` é protegido em três camadas: allowlist em memória,
compare-and-swap na persistência e trigger SQLite. Sair dele exige
`clear-emergency` com um operador humano, e leva a `STOPPED` — nunca direto
para operação. Retomar exige um segundo passo deliberado (`reset`).

---

## 5. Barreiras de segurança ativas

- `real.enabled` é rejeitado se verdadeiro, em qualquer modo.
- Execução habilitada exige kill switch habilitado.
- RESEARCH não pode habilitar execução.
- Transição de estratégia para `REAL` exige aprovação humana persistida em
  `promotion_requests` (validada no manager, na store e em trigger SQLite).
- `audit_events`, `experiments`, `dataset_versions`, `dataset_points` e
  `quality_reports` são append-only.
- Segredos são mascarados antes de qualquer log ou gravação de auditoria.
- Broker Risk é **informativo** em RESEARCH e DEMO (ADR-007), porque não há
  capital em risco. Continua obrigatório em REAL: `real.yaml` é rejeitado se
  `broker_risk.blocking` for falso.

Os triggers de proteção são recriados a cada abertura do banco e a versão fica
registrada em `schema_meta.guard_schema_version`. Um banco antigo nunca continua
rodando com barreiras desatualizadas.

---

## 6. Readiness

| Estado | Significado |
|---|---|
| `READY` | Há dataset com versão registrada; o ciclo roda |
| `NO_DATA` | Infraestrutura pronta, sem dataset. `cycle` não roda e retorna sem falhar |
| `BLOCKED` | Emergency stop ativo ou alguma barreira de segurança reprovando |

Para sair de `NO_DATA`, importe uma série (seção 2.1).

---

## 7. Interpretando o resultado

O número que decide tudo é o **expectancy líquido de payout**:

```text
expectancy = (win_rate × payout) - (loss_rate × 1)
```

Com payout de 0.87, o ponto de equilíbrio é `1 / (1 + 0.87)` = **53,48% de
acerto**. Abaixo disso a estratégia perde dinheiro mesmo parecendo "quase
acertar metade". É por isso que taxa de acerto sozinha nunca valida nada.

Uma estratégia só avança se **todos** os folds do walk-forward tiverem
expectancy positivo (ADR-004, configurável em `validation.min_fold_pass_ratio`).

Se o sistema rejeitar quase tudo, isso normalmente é o comportamento correto —
principalmente em dado sem edge real. Uma validação que aprova estratégia em
série aleatória está quebrada, não generosa.

---

## 8. Arquivos gerados em runtime

```text
logs/state.db             estado global, estratégias, promoções, auditoria
data/datasets/datasets.db versões de dataset, pontos e relatórios de qualidade
```

Ambos são append-only nas tabelas de histórico. Não apague — resultados
negativos e rejeições são informação (MASTER_SPEC seção 56).
