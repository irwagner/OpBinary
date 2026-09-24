# Levantamento: automação de plataformas de opções binárias

Pesquisa do cenário de projetos open source que interfaceiam com corretoras de
opções binárias, para decidir a forma de coletar dados e, eventualmente,
automatizar execução.

*Conteúdo reformulado a partir das fontes para respeitar restrições de
licenciamento. Todos os links são das páginas públicas dos projetos.*

---

## 1. O que existe

O ecossistema é maduro para **quatro** plataformas, e inexistente para a nossa.

### IQ Option — ecossistema mais antigo e mais copiado

O projeto de referência é `iqoptionapi`, com muitos forks. A arquitetura é
consistente e informativa:

```text
http/   → login e chamadas REST
ws/
  chanels/  → ações enviadas pelo WebSocket
  objects/  → dados recebidos de volta
```

Referências: [guilhersantos/iqoptionapi](https://github.com/guilhersantos/iqoptionapi),
[betinhochagas/iqoption_api](https://github.com/betinhochagas/iqoption_api) (fachada
alto nível sobre `requests` + `websocket-client`),
[harwee/IQOption-Api](https://github.com/harwee/IQOption-Api) (sem manutenção),
[MongkonEiadon/IqOption.Net](https://github.com/MongkonEiadon/IqOption.Net) (.NET).

### Quotex — ecossistema mais ativo hoje

- [cleitonleonel/pyquotex](https://github.com/cleitonleonel/pyquotex) — biblioteca
  não oficial com atividade recente e histórico longo de commits.
- [A11ksa/API-Quotex](https://github.com/A11ksa/API-Quotex) — **o mais relevante
  arquiteturalmente**: descreve login via Playwright para obter SSID, e ciclo de
  vida completo de operação.
- [usmanch96/quotex-historical-data](https://github.com/usmanch96/quotex-historical-data)
  — projeto dedicado a contornar um **limite de 199 velas** por requisição de
  WebSocket.
- [usmanch96/quotex-api-fastapi-247](https://github.com/usmanch96/quotex-api-fastapi-247)
  — wrapper que grava **histórico de 8 dias de velas M1**, com suporte a pares OTC.
- [carlosrod723/Quotex-Trading-Bot](https://github.com/carlosrod723/Quotex-Trading-Bot)
  — abordagem alternativa: automação de navegador com Selenium em vez de falar o
  protocolo direto.

### Pocket Option

[A11ksa/API-Pocket-Option](https://github.com/A11ksa/API-Pocket-Option) — cliente
WebSocket assíncrono.

### Polarium — **identificada: plataforma Quadcode, protocolo família IQ Option**

Não existe projeto open source com o nome Polarium. Mas a plataforma foi
identificada a partir do log do console do próprio terminal, e o resultado torna
o ecossistema acima diretamente aplicável.

**Evidência 1 — o front de WebSocket:**

```text
WS front: ws06.ws.prod.sc-ams-1b.quadcode.tech
```

A [Quadcode](https://quadcode.com/white-label-binary-options) é fornecedora de
plataforma white-label de opções binárias. A Polarium é uma marca rodando sobre
essa plataforma, não um sistema proprietário.

**Evidência 2 — os nomes das requisições são do protocolo IQ Option:**

```text
get-first-candles          get-traders-mood
get-leaderboard-position   get-option-insurance
get-profitable-countries   get-currency-list
get-user-settings          get-alerts
```

`get-first-candles` e `traders-mood` são métodos conhecidos das bibliotecas de
IQ Option. `get-first-candles` é exatamente a requisição de velas.

**Evidência 3 — o envelope de resposta tem o formato da família:**

```json
{"name":"leaderboard-position","msName":"","request_id":"","status":-6,"msg":}
```

**Evidência 4 — versão e engine:**

```text
Version: PolariumBroker 4060.1.3791.release
glengine13edbdd2.wasm    ← engine de gráfico em WASM (Emscripten/C++)
```

O gráfico roda em WASM, o que explica por que ele é um canvas e por que o dado
não está no DOM. Também explica os frames de stack com namespace `F2::core::http`.

### Consequência

O ecossistema de `iqoptionapi` passa a servir como **mapa do protocolo**. A
diferença em relação ao IQ Option é o endpoint e o tenant, não a gramática das
mensagens. Isso elimina a necessidade de engenharia reversa às cegas.

Padrão de autenticação confirmado pela biblioteca
[MVH-Co/iqoption-api](https://github.com/MVH-Co/iqoption-api): é necessária uma
conexão HTTP para obter o token de WebSocket, e o token é o que autentica o
socket. É o mesmo padrão SSID descrito na seção 2 — nenhuma senha armazenada.

---

## 2. O achado que resolve o problema de credencial

O padrão usado pelo `API-Quotex` é o caminho certo, e vale adotar
independentemente da corretora:

```text
1. Playwright abre o navegador
2. O humano (ou a sessão já logada) autentica
3. Extrai-se o SSID / token de sessão
4. O cliente usa o SSID para autenticar o WebSocket
5. A senha nunca é armazenada em lugar algum
```

Isso encaixa exatamente no que o Kiro Crew oferece: o motor de navegador dele
**é** Playwright. E resolve a objeção de segurança — o bot opera com um token
revogável, não com a senha.

> **Alerta relevante da própria comunidade:** o repositório
> [kurtdennis/iqoptionapi](https://github.com/kurtdennis/iqoptionapi) recomenda
> explicitamente não inserir sua senha em executáveis ou sites de robô
> desconhecidos, porque muitos roubaram senhas de usuários. Isso confirma o risco
> dos serviços pagos que pedem credencial para "espelhar saldo".

---

## 3. Dois limites técnicos que mudam o plano de coleta

Descobertos nos projetos de Quotex, e provavelmente comuns ao tipo de plataforma:

**Limite de ~199 velas por requisição.** Existe um projeto inteiro dedicado a
contornar isso. Significa que puxar histórico longo requer paginação em múltiplas
requisições, não uma chamada só.

**Histórico de aproximadamente 8 dias em M1.** Esse é o limite prático. Em M1,
8 dias dão cerca de 11.500 velas.

### Consequência direta para o laboratório

Com ~11.500 velas por par:

- dá para rodar walk-forward de 5 folds com ~2.300 velas por fold — viável;
- **não** dá para estudo de horizonte longo a partir de um único download;
- portanto o coletor precisa **rodar continuamente e acumular**, porque a
  corretora só expõe uma janela curta.

Isso valida a decisão de arquitetura que já está implementada: `dataset_versions`
é append-only e versionado por snapshot, exatamente para acumular coleta ao longo
do tempo sem sobrescrever histórico (ADR-005/ADR-007).

---

## 4. Opções, com custo realista

### Opção A — Identificar a plataforma da Polarium primeiro

Teste barato: capturar alguns frames de WebSocket do terminal
(`scripts/browser_capture.js`) e comparar a estrutura das mensagens com os
formatos documentados nos projetos acima. Se bater com IQ Option, Quotex ou
Pocket Option, uma biblioteca madura passa a servir de mapa e o esforço cai
drasticamente.

Custo: minutos. Deveria ser o próximo passo independentemente de tudo.

### Opção B — Escrever o cliente da Polarium do zero

Se a plataforma for proprietária, é engenharia reversa completa: descobrir
handshake, formato de autenticação, canais de subscrição, formato de vela,
paginação de histórico. Iterativo, precisa de observação ao vivo, e quebra quando
a corretora mudar o protocolo.

Custo: alto e recorrente. Só se justifica se houver razão forte para ficar
especificamente nessa corretora.

### Opção C — Usar uma plataforma com biblioteca mantida

Trocar para Quotex, Pocket Option ou IQ Option, onde existe cliente ativo que já
resolve autenticação por SSID, streaming de velas e paginação de histórico.

Custo: baixo no código, exige abrir conta em outra plataforma. É a opção com
melhor relação esforço/resultado se o objetivo é **pesquisar estratégia**, e não
operar especificamente na Polarium.

### Opção D — Dado real de mercado como proxy

Para pares normais em horário de mercado, dado real legítimo (Dukascopy, MT5)
serve bem e não depende de corretora alguma. Não serve para OTC de fim de semana,
que é sintético por definição.

---

## 5. Recomendação (atualizada após identificar a plataforma)

A Opção A foi executada e retornou resultado: **Polarium é Quadcode, protocolo
família IQ Option.** Isso descarta a Opção B (engenharia reversa às cegas) e
torna a Opção C desnecessária para efeito de protocolo.

Plano revisado:

1. **Usar o protocolo IQ Option como especificação.** As bibliotecas da seção 1
   documentam handshake, formato de mensagem e canais. A adaptação é de endpoint
   e tenant, não de gramática.
2. **Autenticar por token obtido via HTTP**, extraído de um login feito por
   humano ou pelo navegador já logado. Nenhuma senha em código, config ou log.
3. **`get-first-candles` é a requisição de velas.** É o alvo da coleta.
4. **Coletor acumulativo**, dado o limite de janela curta de histórico.
5. **Execução automática segue fora de escopo** até existir estratégia validada.

### Protocolo confirmado em execução

Coleta real executada com sucesso. Detalhes verificados:

```text
endpoint:     wss://ws.trade.polariumbroker.com/echo/websocket
autenticação: {"name":"authenticate","msg":{"ssid":...,"protocol":3,...}}
              → a plataforma responde {"name":"authenticated","msg":true}
              → requisição enviada ANTES dessa confirmação é descartada
requisição:   {"name":"sendMessage","msg":{"name":"get-candles","version":"2.0",
               "body":{"active_id":N,"size":SEGUNDOS,"to":EPOCH,"count":N}}}
resposta:     {"name":"candles","msg":{"candles":[...]}}
```

Formato da vela:

```json
{"id": 3322821, "from": 1790207520, "at": 1790207580000000000,
 "to": 1790207580, "open": 1.13825, "close": 1.138235,
 "min": 1.138225, "max": 1.138255, "volume": 27}
```

- `from` e `to` em **segundos**; `at` em **nanossegundos**
- alta e baixa vêm como `max` e `min`, não `high`/`low`
- **1000 velas por requisição funcionam** — o limite de 199 observado em outras
  plataformas não se aplica aqui
- `get-first-candles` existe e retorna `candles_by_size`: a vela mais antiga
  disponível por timeframe. Útil para saber a profundidade real de histórico,
  que **varia por timeframe** (quanto maior a vela, mais fundo o histórico)

### Payout real, lido da plataforma

`get-initialization-data` versão 4.0 retorna `option.profit.commission` por
ativo, e o payout é `(100 - commission) / 100`. Para EURUSD-OTC:

| Grupo | Expiração | Payout | Acerto p/ empate |
|---|---|---|---|
| turbo | 60s | 89% | 52,91% |
| blitz | 5–15s | 88% | 53,19% |
| binary | 900s | 84% | 54,35% |

O payout varia por grupo e por expiração, confirmando que hardcodar esse valor
seria um erro grave. `scripts/list_actives.py` lê isso da plataforma.

### Distinção OTC versus mercado real, observada empiricamente

- `active_id 1` devolve EURUSD **real**: a série tem um gap de ~48h entre sexta
  20:59 e domingo 21:01 — o fechamento de fim de semana do forex.
- `active_id 76` devolve EURUSD-**OTC**: sem gap de fim de semana, roda 24/7,
  com gaps diários de exatamente 6 minutos às 08:04 (janela de manutenção).

Isso confirma na prática que OTC é série sintética gerada pela corretora. Os
dois devem ser mantidos em datasets separados, com `origin` distinta (ADR-007).

### Observação do log capturado

Várias requisições apareceram com timeout, incluindo `get-first-candles`:

```text
Request 'get-first-candles' (89) timed out after 3.7516 sec. (Attempt: 0)
Retries limit (0) reached on request 'get-traders-mood'
```

A sessão estava degradada no momento da coleta. O bloqueio de
`ingest.apptelemetry.xyz` por adblock é só telemetria Sentry e não deveria
afetar o WebSocket, mas vale repetir a observação com a sessão saudável antes de
concluir qualquer coisa sobre limites da plataforma.

---

## 6. Observação sobre qualidade dos projetos levantados

Vários desses repositórios são clientes não oficiais que dependem de protocolo
interno da corretora. Implicações práticas: quebram sem aviso quando a plataforma
muda, raramente têm testes, e alguns estão sem manutenção. Servem muito bem como
**mapa do protocolo**; usar como dependência de produção exige avaliar manutenção
e ler o código antes.
