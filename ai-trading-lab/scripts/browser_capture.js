/*
 * Capturador de frames de WebSocket — para você rodar no SEU navegador.
 *
 * O que faz: observa as mensagens que a página já está recebendo e guarda em
 * memória. Depois você baixa um arquivo .json para eu analisar o formato real.
 *
 * O que NÃO faz: não envia nada, não altera nada na página, não faz requisição
 * para servidor nenhum, não transmite dado para fora da sua máquina. É somente
 * leitura passiva do que a corretora já está mandando para o seu terminal.
 *
 * COMO USAR
 *   1. Abra o terminal da corretora logado, com o gráfico no ativo e timeframe
 *      que você quer estudar.
 *   2. Abra o DevTools (F12) e vá na aba Console.
 *   3. Cole este arquivo inteiro e aperte Enter.
 *   4. Deixe o gráfico rodando por alguns minutos. Quanto mais tempo, mais
 *      velas. Trocar o timeframe no gráfico costuma fazer a corretora reenviar
 *      o histórico inteiro, o que rende bastante dado de uma vez.
 *   5. Rode:  captura.resumo()     para ver o que foi coletado
 *   6. Rode:  captura.baixar()     para salvar o arquivo
 *
 * ANTES DE ME MANDAR O ARQUIVO
 *   Abra ele e dê uma olhada. O capturador já tenta remover campos com cara de
 *   credencial, mas a conferência final é sua. Se vir token, senha, cookie ou
 *   número de documento, apague antes de enviar. Eu só preciso de tempo e preço.
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
      return; // ignora binário: não dá para interpretar sem o protocolo
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
        console.log("nada capturado. Troque o timeframe do gráfico para forçar reenvio.");
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
      "Deixe o gráfico rodando, troque o timeframe para forçar o histórico, e use:\n" +
      "  captura.resumo()         ver o que foi coletado\n" +
      "  captura.baixarSoVelas()  baixar só o que parece vela\n" +
      "  captura.baixar()         baixar tudo\n" +
      "  captura.parar()          encerrar"
  );
})();
