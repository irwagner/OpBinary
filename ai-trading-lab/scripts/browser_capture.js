/*
 * Capturador de frames de WebSocket — para você rodar no SEU navegador.
 *
 * O que faz: observa as mensagens que a página recebe e guarda em memória.
 * Depois você baixa um .json para eu analisar o formato real.
 *
 * O que NÃO faz: não envia nada, não altera a página, não faz requisição para
 * servidor nenhum, não transmite dado para fora da sua máquina. É leitura
 * passiva do que a corretora já está mandando para o seu terminal.
 *
 * ============================================================================
 * LIMITAÇÃO IMPORTANTE — leia antes
 * ============================================================================
 * Este script substitui `window.WebSocket`, então só enxerga conexões criadas
 * DEPOIS que ele roda. A traderoom conecta no carregamento da página, portanto
 * colar no console com a página já aberta captura ZERO mensagens.
 *
 * Duas formas de resolver:
 *
 *   FORMA 1 — Snippet + reload (funciona, exige um passo a mais)
 *     1. DevTools (F12) → aba Sources → painel Snippets → New snippet
 *     2. Cole este arquivo, salve (Ctrl+S) com o nome "captura"
 *     3. Recarregue a página (Ctrl+R)
 *     4. Assim que a página começar a carregar, rode o snippet (Ctrl+Enter)
 *        Se perdeu a janela e deu 0, tente de novo — o objetivo é rodar antes
 *        do app abrir o socket.
 *     5. Use captura.diagnostico() para confirmar que o hook pegou algo
 *
 *   FORMA 2 — Aba Network (mais confiável, sem script)
 *     Não precisa deste arquivo. Ver instruções em
 *     docs/OPERATIONS.md, seção "Capturar formato pela aba Network".
 *     Funciona na conexão já aberta e é o caminho recomendado só para
 *     identificar o formato das mensagens.
 *
 * Use a FORMA 2 para descobrir o formato. Use a FORMA 1 quando precisar
 * acumular volume de velas.
 * ============================================================================
 *
 * COMANDOS
 *   captura.diagnostico()    o hook está pegando? quantos sockets viu?
 *   captura.resumo()         o que foi coletado, com exemplo
 *   captura.baixarSoVelas()  baixa só o que parece vela
 *   captura.baixar()         baixa tudo
 *   captura.parar()          encerra e restaura o WebSocket original
 *
 * ANTES DE ME MANDAR O ARQUIVO
 *   Abra e confira. O capturador já mascara campos com cara de credencial, mas
 *   a revisão final é sua. Se vir token, senha, cookie ou documento, apague.
 *   Eu só preciso de tempo e preço.
 */

(() => {
  "use strict";

  if (window.captura) {
    console.warn("Capturador já está ativo. Use captura.resumo() ou captura.baixar().");
    return;
  }

  const LIMITE_MENSAGENS = 20000;
  const CAMPOS_SENSIVEIS = /(token|senha|password|secret|auth|cookie|session|cpf|email|ssid)/i;

  const coletadas = [];
  let descartadasPorLimite = 0;
  let socketsVistos = 0;
  let framesBinarios = 0;
  const urlsVistas = new Set();
  const instaladoEm = new Date();

  // Remove campos com cara de credencial antes de guardar.
  const limpar = (valor, profundidade = 0) => {
    if (profundidade > 8 || valor === null || typeof valor !== "object") {
      return valor;
    }
    if (Array.isArray(valor)) {
      return valor.map((item) => limpar(item, profundidade + 1));
    }
    const saida = {};
    for (const [chave, item] of Object.entries(valor)) {
      saida[chave] = CAMPOS_SENSIVEIS.test(chave)
        ? "***REMOVIDO***"
        : limpar(item, profundidade + 1);
    }
    return saida;
  };

  const guardar = (origem, dados) => {
    if (coletadas.length >= LIMITE_MENSAGENS) {
      descartadasPorLimite += 1;
      return;
    }
    if (typeof dados !== "string") {
      // Binário (ArrayBuffer/Blob) não dá para interpretar sem conhecer o
      // protocolo. Conta para o diagnóstico poder avisar.
      framesBinarios += 1;
      return;
    }
    let conteudo;
    try {
      conteudo = limpar(JSON.parse(dados));
    } catch {
      if (dados.length > 4000) return;
      conteudo = dados;
    }
    coletadas.push({ origem, recebido_em: new Date().toISOString(), conteudo });
  };

  // Intercepta apenas a LEITURA de mensagens. O envio segue intacto.
  const WebSocketOriginal = window.WebSocket;
  function WebSocketObservado(...argumentos) {
    const socket = new WebSocketOriginal(...argumentos);
    socketsVistos += 1;
    urlsVistas.add(String(argumentos[0] ?? "(sem url)"));
    socket.addEventListener("message", (evento) => {
      try {
        guardar(String(argumentos[0] ?? "ws"), evento.data);
      } catch {
        /* nunca interromper a página por causa da captura */
      }
    });
    return socket;
  }
  WebSocketObservado.prototype = WebSocketOriginal.prototype;
  WebSocketObservado.CONNECTING = WebSocketOriginal.CONNECTING;
  WebSocketObservado.OPEN = WebSocketOriginal.OPEN;
  WebSocketObservado.CLOSING = WebSocketOriginal.CLOSING;
  WebSocketObservado.CLOSED = WebSocketOriginal.CLOSED;
  window.WebSocket = WebSocketObservado;

  // Heurística leve só para o resumo: procura mensagens que parecem candle.
  const parecemVelas = () =>
    coletadas.filter((item) => {
      const texto = JSON.stringify(item.conteudo);
      return /"(open|close|high|low|o|c|h|l)"\s*:/.test(texto);
    });

  window.captura = {
    diagnostico() {
      console.log(`hook instalado em: ${instaladoEm.toISOString()}`);
      console.log(`sockets criados depois do hook: ${socketsVistos}`);
      console.log(`frames de texto capturados:     ${coletadas.length}`);
      console.log(`frames binários (ignorados):    ${framesBinarios}`);
      if (urlsVistas.size) {
        console.log("URLs de socket vistas:");
        for (const url of urlsVistas) console.log(`  ${url}`);
      }
      if (socketsVistos === 0) {
        console.warn(
          "Nenhum socket foi criado depois do hook.\n" +
          "A conexão da página já existia. Use a FORMA 1 (Snippet + reload) " +
          "ou a FORMA 2 (aba Network) descritas no topo deste arquivo."
        );
      } else if (coletadas.length === 0 && framesBinarios > 0) {
        console.warn(
          "O socket foi capturado, mas os frames são binários. Vou precisar " +
          "que você olhe a aba Network para eu entender o protocolo."
        );
      }
      return {
        sockets: socketsVistos,
        texto: coletadas.length,
        binarios: framesBinarios,
      };
    },

    resumo() {
      const candidatas = parecemVelas();
      console.log(`mensagens capturadas: ${coletadas.length}`);
      console.log(`parecem conter velas: ${candidatas.length}`);
      if (descartadasPorLimite) {
        console.log(`descartadas por limite: ${descartadasPorLimite}`);
      }
      if (candidatas.length) {
        console.log("exemplo do que parece vela:");
        console.log(JSON.stringify(candidatas[candidatas.length - 1], null, 2).slice(0, 1200));
      } else if (coletadas.length) {
        console.log("nenhuma mensagem com cara de vela ainda; exemplo qualquer:");
        console.log(JSON.stringify(coletadas[coletadas.length - 1], null, 2).slice(0, 800));
      } else {
        console.log("nada capturado. Rode captura.diagnostico() para saber por quê.");
      }
      return { total: coletadas.length, velas: candidatas.length };
    },

    baixar(nomeArquivo = "captura_corretora.json") {
      if (!coletadas.length) {
        console.warn("Nada capturado ainda.");
        return;
      }
      const blob = new Blob([JSON.stringify(coletadas, null, 2)], {
        type: "application/json",
      });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = nomeArquivo;
      link.click();
      URL.revokeObjectURL(link.href);
      console.log(`${coletadas.length} mensagem(ns) salva(s) em ${nomeArquivo}`);
    },

    // Só as que parecem vela, arquivo bem menor e mais fácil de revisar.
    baixarSoVelas(nomeArquivo = "captura_velas.json") {
      const candidatas = parecemVelas();
      if (!candidatas.length) {
        console.warn("Nenhuma mensagem com cara de vela. Rode captura.resumo().");
        return;
      }
      const blob = new Blob([JSON.stringify(candidatas, null, 2)], {
        type: "application/json",
      });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = nomeArquivo;
      link.click();
      URL.revokeObjectURL(link.href);
      console.log(`${candidatas.length} mensagem(ns) salva(s) em ${nomeArquivo}`);
    },

    limpar() {
      coletadas.length = 0;
      descartadasPorLimite = 0;
      console.log("coleta zerada");
    },

    parar() {
      window.WebSocket = WebSocketOriginal;
      console.log("captura encerrada; WebSocket original restaurado");
    },
  };

  console.log(
    "Capturador ativo (somente leitura).\n" +
    "ATENÇÃO: só enxerga conexões abertas DEPOIS deste momento.\n" +
    "Se a página já estava carregada, o resultado será 0 — veja o cabeçalho\n" +
    "do arquivo para as duas formas de contornar.\n\n" +
    "  captura.diagnostico()    o hook está pegando algo?\n" +
    "  captura.resumo()         ver o que foi coletado\n" +
    "  captura.baixarSoVelas()  baixar só o que parece vela\n" +
    "  captura.baixar()         baixar tudo\n" +
    "  captura.parar()          encerrar"
  );
})();
