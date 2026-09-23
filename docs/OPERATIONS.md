# AI Trading Research Lab — Manual de Operação

Estado atual do sistema: **ON, em RESEARCH, ocioso por falta de dados.**

```text
Mode:        RESEARCH
System:      IDLE
Readiness:   NO_DATA
Execution:   DISABLED
REAL:        BLOCKED
Datasets:    0
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
- Broker Risk sem fonte de evidência configurada retorna `FAIL`, bloqueando DEMO.

Os triggers de proteção são recriados a cada abertura do banco e a versão fica
registrada em `schema_meta.guard_schema_version`. Um banco antigo nunca continua
rodando com barreiras desatualizadas.

---

## 6. Por que o sistema está ocioso

`Readiness: NO_DATA` significa que a infraestrutura está pronta mas não existe
dataset coletado. Conforme ADR-005, a única fonte legítima de dados é a própria
corretora-alvo. Não há coletor implementado porque isso exige a API oficial da
corretora — e inventar uma API está fora de escopo.

Enquanto não houver dataset:

- `cycle` não roda e retorna `NO_DATA` sem falhar;
- nenhum backtest, walk-forward ou Monte Carlo produz resultado;
- nenhuma estratégia avança de estado.

---

## 7. Arquivos gerados em runtime

```text
logs/state.db             estado global, estratégias, promoções, auditoria
data/datasets/datasets.db versões de dataset, pontos e relatórios de qualidade
```

Ambos são append-only nas tabelas de histórico. Não apague — resultados
negativos e rejeições são informação (MASTER_SPEC seção 56).
