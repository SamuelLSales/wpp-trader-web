// Variáveis de Conexão WebSocket
let socket;
let reconnectInterval = 5000;
let signalCounter = 0;

// Inicializa a aplicação ao carregar a página
document.addEventListener("DOMContentLoaded", () => {
    connectWebSocket();
    // Recupera dados iniciais de status via REST API para evitar tela preta
    fetchSystemStatus();
});

// Retorna a URL base correta para chamadas de API caso o arquivo seja aberto diretamente no browser
function getApiBase() {
    return (window.location.protocol === "file:" || !window.location.host) ? "http://localhost:5001" : "";
}

// Conecta ao WebSocket do servidor FastAPI
function connectWebSocket() {
    let host = window.location.host;
    let protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    
    if (!host || window.location.protocol === "file:") {
        host = "localhost:5001";
        protocol = "ws:";
    }
    const wsUrl = `${protocol}//${host}/ws/dashboard`;

    console.log(`[WS] Conectando ao servidor em: ${wsUrl}`);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("[WS] Conectado com sucesso!");
        document.getElementById("global-status-dot").className = "status-dot green pulse";
        document.getElementById("global-status-text").innerText = "Monitorando";
    };

    socket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleServerMessage(message);
        } catch (err) {
            console.error("[WS] Erro ao decodificar JSON:", err);
        }
    };

    socket.onclose = () => {
        console.warn("[WS] Conexão encerrada pelo servidor. Tentando reconectar...");
        document.getElementById("global-status-dot").className = "status-dot red";
        document.getElementById("global-status-text").innerText = "Desconectado";
        
        // Exibe estados offline nos cards
        updateWppUI("disconnected");
        updateAgentUI("disconnected");
        
        // Reconeção automática
        setTimeout(connectWebSocket, reconnectInterval);
    };

    socket.onerror = (error) => {
        console.error("[WS] Erro detectado:", error);
    };
}

// Busca o status inicial via API REST
async function fetchSystemStatus() {
    try {
        const response = await fetch(`${getApiBase()}/api/status`);
        if (response.ok) {
            const data = await response.json();
            updateWppUI(data.wpp_status);
            updateAgentUI(data.agent_status);
            if (data.qr_code_data) {
                renderQRCode(data.qr_code_data);
            }
            if (data.config) {
                if (data.config.wpp_group) document.getElementById("input-wpp-group").value = data.config.wpp_group;
                if (data.config.mt5_login) document.getElementById("input-mt5-login").value = data.config.mt5_login;
                if (data.config.mt5_password) document.getElementById("input-mt5-password").value = data.config.mt5_password;
                if (data.config.mt5_server) document.getElementById("input-mt5-server").value = data.config.mt5_server;
                if (data.config.mt5_path) document.getElementById("input-mt5-path").value = data.config.mt5_path;
                if (data.config.valor_operacao) document.getElementById("input-valor-op").value = data.config.valor_operacao;
            }
        }
    } catch (error) {
        console.error("Falha ao buscar status do sistema:", error);
    }
}

// Gerencia as mensagens recebidas via WebSocket
function handleServerMessage(message) {
    const type = message.type;
    const data = message.data;

    switch (type) {
        case "init":
            // Estado inicial completo enviado pelo backend
            updateWppUI(message.wpp_status);
            updateAgentUI(message.agent_status);
            if (message.qr_code_data) {
                renderQRCode(message.qr_code_data);
            }
            if (message.config) {
                if (message.config.wpp_group) document.getElementById("input-wpp-group").value = message.config.wpp_group;
                if (message.config.mt5_login) document.getElementById("input-mt5-login").value = message.config.mt5_login;
                if (message.config.mt5_password) document.getElementById("input-mt5-password").value = message.config.mt5_password;
                if (message.config.mt5_server) document.getElementById("input-mt5-server").value = message.config.mt5_server;
                if (message.config.mt5_path) document.getElementById("input-mt5-path").value = message.config.mt5_path;
                if (message.config.valor_operacao) document.getElementById("input-valor-op").value = message.config.valor_operacao;
            }
            // Carrega histórico de logs
            const consoleTerminal = document.getElementById("console-terminal");
            consoleTerminal.innerHTML = "";
            if (message.logs && message.logs.length > 0) {
                message.logs.forEach(log => appendLogLine(log));
            } else {
                appendLogLine("[SISTEMA] Aguardando novas atividades...");
            }
            break;

        case "wpp_status":
            updateWppUI(data);
            break;

        case "agent_status":
            updateAgentUI(data);
            break;

        case "qr":
            renderQRCode(data);
            break;

        case "log":
            appendLogLine(data);
            break;

        case "raw_signal":
            signalCounter++;
            document.getElementById("val-signals").innerText = signalCounter;
            break;
            
        default:
            console.log("[WS] Mensagem não tratada:", message);
    }
}

// ─── ATUALIZAÇÕES DA INTERFACE GRÁFICA (UI) ----------------------------------

function updateWppUI(status) {
    const badge = document.getElementById("badge-wpp");
    const valText = document.getElementById("val-wpp");
    const btnConnect = document.getElementById("btn-connect-wpp");
    
    // Reseta classes do badge
    badge.className = "card-badge";
    
    if (status === "connected") {
        badge.classList.add("online");
        badge.innerText = "Online";
        valText.innerText = "Conectado";
        btnConnect.innerText = "📱 Reconfigurar";
        btnConnect.disabled = true; // Se está conectado, desativa botão de iniciar
        
        // Oculta QR Code e mostra tela de sucesso
        document.getElementById("qr-placeholder").classList.add("hidden");
        document.getElementById("qr-image").classList.add("hidden");
        document.getElementById("qr-success").classList.remove("hidden");
    } else if (status === "connecting") {
        badge.classList.add("connecting");
        badge.innerText = "Conectando";
        valText.innerText = "Gerando QR Code...";
        btnConnect.innerText = "📱 Conectando...";
        btnConnect.disabled = true;
    } else {
        badge.classList.add("offline");
        badge.innerText = "Offline";
        valText.innerText = "Desconectado";
        btnConnect.innerText = "📱 Iniciar Conexão";
        btnConnect.disabled = false;
        
        // Mostra placeholder inicial do QR
        document.getElementById("qr-placeholder").classList.remove("hidden");
        document.getElementById("qr-image").classList.add("hidden");
        document.getElementById("qr-success").classList.add("hidden");
        document.getElementById("qr-placeholder").innerHTML = `
            <div class="spinner hidden" id="qr-spinner"></div>
            <p id="qr-placeholder-text">WhatsApp desconectado. Clique em 'Iniciar Conexão' para obter o QR Code.</p>
        `;
    }
}

function updateAgentUI(status) {
    const badge = document.getElementById("badge-mt5");
    const valText = document.getElementById("val-mt5");
    
    badge.className = "card-badge";
    
    if (status === "connected") {
        badge.classList.add("online");
        badge.innerText = "Online";
        valText.innerText = "Conectado";
    } else {
        badge.classList.add("offline");
        badge.innerText = "Offline";
        valText.innerText = "Desconectado";
    }
}

function renderQRCode(qrData) {
    const imgEl = document.getElementById("qr-image");
    const placeholderEl = document.getElementById("qr-placeholder");
    const successEl = document.getElementById("qr-success");

    if (qrData) {
        // O node passa a string do QR pura. Usamos uma API pública segura para renderizar como imagem
        const qrImageUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(qrData)}`;
        imgEl.src = qrImageUrl;
        imgEl.classList.remove("hidden");
        placeholderEl.classList.add("hidden");
        successEl.classList.add("hidden");
    }
}

// Injeta e colore as linhas de logs no console terminal
function appendLogLine(logText) {
    const terminal = document.getElementById("console-terminal");
    const line = document.createElement("div");
    line.className = "log-line";
    
    // Identificar tipo de log para aplicar cores CSS
    if (logText.includes("[ERRO]")) {
        line.classList.add("error");
    } else if (logText.includes("[SISTEMA]") || logText.includes("[CONEXÃO]")) {
        line.classList.add("system");
    } else if (logText.includes("[WPP]")) {
        line.classList.add("wpp");
    } else if (logText.includes("[AGENTE]")) {
        line.classList.add("agent");
    } else if (logText.includes("[PROCESSO]")) {
        line.classList.add("process");
    }
    
    line.innerText = logText;
    terminal.appendChild(line);
    
    // Auto-scroll para a última linha
    terminal.scrollTop = terminal.scrollHeight;
}

// ─── OPERAÇÕES DA API REST (AÇÕES) -------------------------------------------

async function requestConnectWpp() {
    const placeholderText = document.getElementById("qr-placeholder-text");
    const spinner = document.getElementById("qr-spinner");
    
    if (placeholderText) placeholderText.innerText = "Iniciando Puppeteer, aguarde...";
    if (spinner) spinner.classList.remove("hidden");
    
    try {
        const response = await fetch(`${getApiBase()}/api/connect_wpp`, { method: "POST" });
        if (!response.ok) {
            alert("Falha ao iniciar conexão com o WhatsApp.");
        }
    } catch (err) {
        console.error(err);
    }
}

async function requestLogoutWpp() {
    if (confirm("Tem certeza que deseja desconectar o WhatsApp e apagar a sessão atual?")) {
        try {
            await fetch(`${getApiBase()}/api/logout_wpp`, { method: "POST" });
        } catch (err) {
            console.error(err);
        }
    }
}

async function requestClearLogs() {
    try {
        const response = await fetch(`${getApiBase()}/api/clear_logs`, { method: "POST" });
        if (response.ok) {
            document.getElementById("console-terminal").innerHTML = '<div class="log-line system">[SISTEMA] Logs limpos com sucesso.</div>';
        }
    } catch (err) {
        console.error(err);
    }
}

async function saveConfiguration(event) {
    event.preventDefault();
    const btnSave = document.getElementById("btn-save-config");
    const wppGroup = document.getElementById("input-wpp-group").value.trim();
    const mt5Login = document.getElementById("input-mt5-login").value.trim();
    const mt5Password = document.getElementById("input-mt5-password").value.trim();
    const mt5Server = document.getElementById("input-mt5-server").value.trim();
    const mt5Path = document.getElementById("input-mt5-path").value.trim();
    const valorOp = document.getElementById("input-valor-op").value.trim();
    
    if (!wppGroup) {
        alert("O nome do grupo do WhatsApp é obrigatório.");
        return;
    }

    btnSave.innerText = "💾 Salvando...";
    btnSave.disabled = true;

    const payload = {
        wpp_group: wppGroup,
        mt5_login: mt5Login,
        mt5_password: mt5Password,
        mt5_server: mt5Server,
        mt5_path: mt5Path,
        valor_operacao: valorOp
    };

    try {
        const response = await fetch(`${getApiBase()}/api/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            alert("Configurações salvas e aplicadas com sucesso!");
        } else {
            alert("Erro ao salvar configurações.");
        }
    } catch (err) {
        console.error(err);
        alert("Erro de conexão ao salvar.");
    } finally {
        btnSave.innerText = "💾 Salvar Configurações";
        btnSave.disabled = false;
    }
}

// Alternador de guias (Abas) da interface
function switchTab(tabId) {
    // Esconde todas as panes
    document.querySelectorAll(".tab-pane").forEach(pane => {
        pane.classList.remove("active");
    });
    
    // Tira active de todos os nav-items
    document.querySelectorAll(".nav-item").forEach(item => {
        item.classList.remove("active");
    });
    
    // Ativa a pane correta e o item da navbar correto
    document.getElementById(`tab-${tabId}`).classList.add("active");
    
    let activeNavBtn;
    let pageTitleText = "";
    let pageSubtitleText = "";
    
    if (tabId === "dashboard") {
        activeNavBtn = document.getElementById("nav-btn-dashboard");
        pageTitleText = "Dashboard";
        pageSubtitleText = "Visão geral e conexões em tempo real";
    } else if (tabId === "config") {
        activeNavBtn = document.getElementById("nav-btn-config");
        pageTitleText = "Configurações";
        pageSubtitleText = "Edite as regras do robô na nuvem";
    } else if (tabId === "logs") {
        activeNavBtn = document.getElementById("nav-btn-logs");
        pageTitleText = "Logs & Sinais";
        pageSubtitleText = "Histórico de mensagens do WhatsApp e execuções";
    }
    
    if (activeNavBtn) {
        activeNavBtn.classList.add("active");
    }
    
    document.getElementById("page-title").innerText = pageTitleText;
    document.getElementById("page-subtitle").innerText = pageSubtitleText;
}
