import os
import sys
import json
import re
import asyncio
import platform
import shutil
import subprocess
import logging
from typing import Set, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WPP_Trader_Server")

app = FastAPI(title="WPP Trader Server", description="Servidor Cloud para o robô WhatsApp-to-MT5")

# Habilitar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Caminho para o diretório de dados do Web Server
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "web_config.json")
LOG_HISTORY = []

# Estado Global
class GlobalState:
    wpp_status: str = "disconnected"  # disconnected, connecting, connected
    qr_code_data: Optional[str] = None
    node_process: Optional[subprocess.Popen] = None
    
    # WebSocket Connections
    dashboards: Set[WebSocket] = set()
    agents: Set[WebSocket] = set()

state = GlobalState()

# Regex Parser de Sinais integrado para ser auto-suficiente na nuvem
class SignalParser:
    def __init__(self):
        self.re_codigo = re.compile(r"Código da Opção:\s*([A-Z0-9]+)", re.IGNORECASE)
        self.re_entrada = re.compile(r"Preço de Entrada:\s*([\d,]+)", re.IGNORECASE)
        self.re_tipo = re.compile(r"Tipo de Opção:\s*(PUT|CALL)", re.IGNORECASE)
        self.re_alvo1 = re.compile(r"Primeiro Alvo[^\d]*([\d,]+)", re.IGNORECASE)
        self.re_alvo2 = re.compile(r"Segundo Alvo[^\d]*([\d,]+)", re.IGNORECASE)
        self.re_alvo3 = re.compile(r"Terceiro Alvo[^\d]*([\d,]+)", re.IGNORECASE)
        self.re_stop = re.compile(r"Stop:\s*([\d,]+)", re.IGNORECASE)

    def _to_float(self, val_str):
        if not val_str:
            return None
        return float(val_str.replace(',', '.'))

    def parse(self, text):
        parsed = {}
        m_codigo = self.re_codigo.search(text)
        parsed['ativo'] = m_codigo.group(1).upper() if m_codigo else None
        
        m_entrada = self.re_entrada.search(text)
        parsed['entrada'] = self._to_float(m_entrada.group(1)) if m_entrada else None
        
        m_tipo = self.re_tipo.search(text)
        parsed['tipo'] = m_tipo.group(1).upper() if m_tipo else None
        
        parsed['alvos'] = []
        m_alvo1 = self.re_alvo1.search(text)
        if m_alvo1: parsed['alvos'].append(self._to_float(m_alvo1.group(1)))
        m_alvo2 = self.re_alvo2.search(text)
        if m_alvo2: parsed['alvos'].append(self._to_float(m_alvo2.group(1)))
        m_alvo3 = self.re_alvo3.search(text)
        if m_alvo3: parsed['alvos'].append(self._to_float(m_alvo3.group(1)))
        
        m_stop = self.re_stop.search(text)
        parsed['stop'] = self._to_float(m_stop.group(1)) if m_stop else None
        
        if parsed['ativo']:
            return parsed
        return None

parser = SignalParser()

# Helper para carregar/salvar configurações locais
def load_web_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler web_config.json: {e}")
    return {"wpp_group": "Grupo Sinais VIP"}

def save_web_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar web_config.json: {e}")

# Transmitir mensagem para todos os navegadores abertos no Dashboard
async def broadcast_to_dashboards(msg: dict):
    if not state.dashboards:
        return
    disconnected = set()
    for ws in state.dashboards:
        try:
            await ws.send_json(msg)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        state.dashboards.remove(ws)

# Enviar dados de logs e salvar no histórico
async def add_log(msg: str):
    logger.info(msg)
    LOG_HISTORY.append(msg)
    if len(LOG_HISTORY) > 500:
        LOG_HISTORY.pop(0)
    await broadcast_to_dashboards({"type": "log", "data": msg})

# ─── CONTROLE DO PROCESSO NODE.JS WHATSAPP ──────────────────────────────────
async def start_node_listener():
    if state.node_process is not None:
        logger.info("Processo WhatsApp já está rodando.")
        return

    # Procura a pasta wpp_listener
    # Tenta caminhos comuns relativos
    wpp_dir = os.path.join(os.path.dirname(BASE_DIR), "wpp_listener")
    if not os.path.exists(wpp_dir):
        wpp_dir = os.path.join(BASE_DIR, "wpp_listener")

    if not os.path.exists(wpp_dir):
        await add_log("[ERRO] Pasta 'wpp_listener' não encontrada no servidor!")
        return

    cfg = load_web_config()
    target_group = cfg.get("wpp_group", "Não configurado")

    await add_log(f"[SISTEMA] Iniciando listener do WhatsApp para o grupo '{target_group}'...")
    
    env = os.environ.copy()
    env["WPP_TARGET_GROUP"] = target_group

    try:
        # Configurar criação do processo para ignorar console caso esteja no Windows
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NO_WINDOW

        state.node_process = subprocess.Popen(
            ["node", "index.js"],
            cwd=wpp_dir,
            env=env,
            creationflags=creationflags
        )
        state.wpp_status = "connecting"
        await broadcast_to_dashboards({"type": "wpp_status", "data": "connecting"})
    except Exception as e:
        await add_log(f"[ERRO] Falha ao iniciar processo Node.js: {e}")

async def stop_node_listener():
    if state.node_process is None:
        return

    await add_log("[SISTEMA] Parando listener do WhatsApp...")
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(state.node_process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Encerra o grupo de processos no Linux
            import signal
            os.kill(state.node_process.pid, signal.SIGTERM)
    except Exception as e:
        logger.error(f"Erro ao matar processo Node: {e}")
        try:
            state.node_process.terminate()
        except:
            pass

    state.node_process = None
    state.wpp_status = "disconnected"
    state.qr_code_data = None
    await broadcast_to_dashboards({"type": "wpp_status", "data": "disconnected"})
    await broadcast_to_dashboards({"type": "qr", "data": None})

async def delete_wpp_session():
    await stop_node_listener()
    
    # Determina o diretório de dados
    if platform.system() == "Windows":
        data_dir = os.path.join(os.environ.get('APPDATA', os.environ.get('LOCALAPPDATA', '')), 'WPP_Trader_Data')
    else:
        data_dir = os.path.join(os.environ.get('HOME', '/tmp'), '.wpp_trader_data')

    auth_dir = os.path.join(data_dir, ".wwebjs_auth")
    
    if os.path.exists(auth_dir):
        await add_log("[SISTEMA] Excluindo sessão salva do WhatsApp...")
        # Aguarda um momento para liberação dos arquivos
        await asyncio.sleep(2)
        try:
            await asyncio.get_running_loop().run_in_executor(None, shutil.rmtree, auth_dir, True)
            await add_log("[SISTEMA] ✅ Sessão excluída com sucesso!")
        except Exception as e:
            await add_log(f"[AVISO] Algum arquivo da sessão está travado. Tente reiniciar a VM: {e}")
    else:
        await add_log("[SISTEMA] Nenhuma sessão ativa encontrada.")

# ─── ROTAS DA API ───────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request):
    """
    Recebe os dados do script wpp_listener/index.js rodando localmente no servidor
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"status": "erro", "message": "JSON inválido"}, status_code=400)
    
    msg_type = data.get("type")
    
    if msg_type == "qr":
        qr_data = data.get("data")
        state.qr_code_data = qr_data
        state.wpp_status = "connecting"
        await broadcast_to_dashboards({"type": "qr", "data": qr_data})
        await broadcast_to_dashboards({"type": "wpp_status", "data": "connecting"})
        
    elif msg_type == "status":
        status_data = data.get("data")
        is_conn = (status_data == "connected")
        state.wpp_status = "connected" if is_conn else "disconnected"
        if is_conn:
            state.qr_code_data = None
            await broadcast_to_dashboards({"type": "qr", "data": None})
            await add_log("[WPP] ✅ WhatsApp conectado e pronto!")
        await broadcast_to_dashboards({"type": "wpp_status", "data": state.wpp_status})
        
    elif msg_type == "signal":
        signal_text = data.get("message")
        grupo = data.get("grupo")
        await add_log(f"[WPP] 📩 Novo sinal recebido do grupo '{grupo}'!")
        
        # Envia sinal de texto bruto para o log
        await broadcast_to_dashboards({"type": "raw_signal", "data": signal_text})
        
        # Processar o sinal
        parsed_signal = parser.parse(signal_text)
        if parsed_signal:
            await add_log(f"[PROCESSO] 📊 Sinal interpretado: {parsed_signal['ativo']} - Tipo: {parsed_signal['tipo']}")
            # Enviar para o agente Windows se estiver conectado
            if state.agents:
                await add_log(f"[CONEXÃO] 📡 Enviando ordem do ativo {parsed_signal['ativo']} para o Agente Windows...")
                # Broadcast do sinal para todos os agentes conectados (geralmente só 1)
                disconnected_agents = set()
                for ws in state.agents:
                    try:
                        await ws.send_json({"type": "execute_order", "data": parsed_signal})
                    except Exception:
                        disconnected_agents.add(ws)
                for ws in disconnected_agents:
                    state.agents.remove(ws)
            else:
                await add_log(f"[AVISO] ❌ Nenhuma corretora/Agente Windows conectado para executar a ordem de {parsed_signal['ativo']}!")
        else:
            await add_log("[PROCESSO] Mensagem recebida não condiz com as regras de sinal válidas.")

    return {"status": "ok"}

@app.get("/api/status")
def get_status():
    return {
        "wpp_status": state.wpp_status,
        "agent_status": "connected" if len(state.agents) > 0 else "disconnected",
        "qr_code_data": state.qr_code_data,
        "config": load_web_config()
    }

@app.post("/api/config")
async def save_config(request: Request):
    data = await request.json()
    wpp_group = data.get("wpp_group", "").strip()
    if not wpp_group:
        return JSONResponse({"status": "erro", "message": "Grupo inválido"}, status_code=400)
    
    cfg = load_web_config()
    cfg["wpp_group"] = wpp_group
    # Salvar dados do MT5 também no servidor na nuvem (opcional, mas bom pra recarregar a tela)
    cfg["mt5_login"] = data.get("mt5_login", "")
    cfg["mt5_password"] = data.get("mt5_password", "")
    cfg["mt5_server"] = data.get("mt5_server", "")
    cfg["mt5_path"] = data.get("mt5_path", "")
    cfg["valor_operacao"] = data.get("valor_operacao", "1000")
    save_web_config(cfg)
    
    await add_log(f"[SISTEMA] Configurações atualizadas. Grupo WPP: '{wpp_group}'")
    
    # Envia a nova configuração do MT5 para todos os agentes conectados (VM Windows)
    if state.agents:
        await add_log("[CONEXÃO] Enviando configurações do MT5 para a VM Windows...")
        for ws in list(state.agents):
            try:
                await ws.send_json({
                    "type": "update_mt5_config",
                    "data": {
                        "mt5_login": cfg["mt5_login"],
                        "mt5_password": cfg["mt5_password"],
                        "mt5_server": cfg["mt5_server"],
                        "mt5_path": cfg["mt5_path"],
                        "valor_operacao": cfg["valor_operacao"]
                    }
                })
            except Exception:
                pass
    
    # Se o WhatsApp já estiver conectado ou tentando conectar, reinicia o listener para aplicar novas configurações
    if state.node_process is not None:
        await add_log("[SISTEMA] Reiniciando listener do WhatsApp para aplicar novas configurações...")
        await stop_node_listener()
        await asyncio.sleep(1.5)
        await start_node_listener()
        
    return {"status": "ok"}

@app.post("/api/connect_wpp")
async def connect_wpp():
    await start_node_listener()
    return {"status": "ok"}

@app.post("/api/logout_wpp")
async def logout_wpp():
    asyncio.create_task(delete_wpp_session())
    return {"status": "ok"}

@app.post("/api/clear_logs")
def clear_logs():
    global LOG_HISTORY
    LOG_HISTORY = []
    return {"status": "ok"}

# ─── WEBSOCKETS ─────────────────────────────────────────────────────────────

@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    state.dashboards.add(websocket)
    
    # Enviar estado inicial para o dashboard que acabou de conectar
    initial_state = {
        "type": "init",
        "wpp_status": state.wpp_status,
        "agent_status": "connected" if len(state.agents) > 0 else "disconnected",
        "qr_code_data": state.qr_code_data,
        "logs": LOG_HISTORY,
        "config": load_web_config()
    }
    await websocket.send_json(initial_state)
    
    try:
        while True:
            # Apenas mantém o socket aberto e escuta pings/comandos
            data = await websocket.receive_text()
            # Tratar comandos extras se necessário
    except WebSocketDisconnect:
        state.dashboards.remove(websocket)
    except Exception as e:
        logger.error(f"Erro no socket do dashboard: {e}")
        if websocket in state.dashboards:
            state.dashboards.remove(websocket)

@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    await websocket.accept()
    state.agents.add(websocket)
    await add_log("[CONEXÃO] 🔌 Agente Windows conectado com sucesso!")
    await broadcast_to_dashboards({"type": "agent_status", "data": "connected"})
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "order_result":
                success = data.get("success")
                msg = data.get("message")
                status_color = "🟢" if success else "🔴"
                await add_log(f"[AGENTE] {status_color} Retorno da Execução: {msg}")
                
            elif msg_type == "mt5_status":
                mt5_connected = data.get("connected")
                status_str = "Conectado" if mt5_connected else "Desconectado"
                await add_log(f"[AGENTE] Status do MT5: {status_str}")
                
    except WebSocketDisconnect:
        state.agents.remove(websocket)
        await add_log("[CONEXÃO] ⚠️ Agente Windows desconectado!")
        await broadcast_to_dashboards({"type": "agent_status", "data": "disconnected"})
    except Exception as e:
        logger.error(f"Erro no socket do agente: {e}")
        if websocket in state.agents:
            state.agents.remove(websocket)
        await broadcast_to_dashboards({"type": "agent_status", "data": "disconnected"})

# ─── SERVIR FRONTEND ─────────────────────────────────────────────────────────

# Cria pasta static se não existir
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)

# Mount files estáticos
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# Eventos de Ciclo de Vida do FastAPI
@app.on_event("startup")
async def startup_event():
    logger.info("Servidor iniciado. Agendando início do WhatsApp...")
    async def delayed_start():
        await asyncio.sleep(2)
        await start_node_listener()
    asyncio.create_task(delayed_start())

# Execução do Servidor
if __name__ == "__main__":
    logger.info("Iniciando servidor web na porta 5001...")
    uvicorn.run(app, host="0.0.0.0", port=5001)
