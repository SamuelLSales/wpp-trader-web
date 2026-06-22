import os
import sys
import json
import asyncio
import threading
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WPP_Trader_Agent")

# Verifica dependências necessárias
try:
    import websockets
except ImportError:
    print("\n[ERRO] A biblioteca 'websockets' não está instalada.")
    print("Por favor, instale executando o comando no console:")
    print("pip install websockets\n")
    input("Pressione Enter para sair...")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("\n[ERRO] A biblioteca 'MetaTrader5' não está instalada.")
    print("Este agente deve ser executado em um ambiente Windows onde o MetaTrader 5 esteja instalado.")
    print("pip install MetaTrader5\n")
    input("Pressione Enter para sair...")
    sys.exit(1)

# Adiciona o diretório atual ao path para importar os módulos da pasta core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.mt5_executor import MT5Executor

CONFIG_FILE = "agent_config.json"
executor = None
mt5_connected = False

# Carrega a URL do servidor Ubuntu
def load_agent_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler {CONFIG_FILE}: {e}")
    
    # Configuração padrão local para testes
    default_config = {"server_url": "ws://localhost:5001/ws/agent"}
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar configuração padrão: {e}")
    return default_config

config = load_agent_config()
SERVER_URL = config.get("server_url", "ws://localhost:5001/ws/agent")

# Callback de logs do MT5 para enviar para o console local do Agente
def agent_log(msg):
    logger.info(msg)

# Função síncrona de execução de ordens (executada em Thread separada para não travar o socket)
def execute_order_sync(signal, ws_connection, loop):
    global executor, mt5_connected
    if not executor:
        executor = MT5Executor(log_callback=agent_log)
    
    # Garante a conexão antes de mandar a ordem
    if not mt5_connected:
        agent_log("[MT5] Tentando reconectar ao terminal MT5...")
        mt5_connected = executor.connect()
        # Envia status atualizado de conexão
        asyncio.run_coroutine_threadsafe(
            ws_connection.send(json.dumps({"type": "mt5_status", "connected": mt5_connected})),
            loop
        )

    if not mt5_connected:
        result_msg = "Falha ao conectar no MetaTrader 5 local."
        agent_log(f"[EXECUÇÃO] ❌ {result_msg}")
        asyncio.run_coroutine_threadsafe(
            ws_connection.send(json.dumps({
                "type": "order_result",
                "success": False,
                "message": result_msg
            })),
            loop
        )
        return

    # Executa a ordem
    agent_log(f"[EXECUÇÃO] Executando sinal de {signal.get('ativo')}...")
    try:
        success = executor.send_order(signal)
        status_msg = f"Ordem executada com sucesso para o ativo {signal.get('ativo')}!" if success else f"Falha ao executar ordem para {signal.get('ativo')}."
        
        # Envia retorno para o servidor Ubuntu
        asyncio.run_coroutine_threadsafe(
            ws_connection.send(json.dumps({
                "type": "order_result",
                "success": success,
                "message": status_msg
            })),
            loop
        )
    except Exception as e:
        error_msg = f"Erro interno na execução do MT5: {e}"
        agent_log(f"[EXECUÇÃO] ❌ {error_msg}")
        asyncio.run_coroutine_threadsafe(
            ws_connection.send(json.dumps({
                "type": "order_result",
                "success": False,
                "message": error_msg
            })),
            loop
        )

# Loop principal de conexão WebSocket do Agente
async def run_agent():
    global executor, mt5_connected
    
    print("=" * 60)
    print("             WPP TRADER - AGENTE DE EXECUÇÃO LOCAL            ")
    print("=" * 60)
    print(f"Alvo do Servidor Cloud: {SERVER_URL}")
    print("Iniciando conexão local com MetaTrader 5...")
    
    executor = MT5Executor(log_callback=agent_log)
    mt5_connected = executor.connect()
    
    if mt5_connected:
        print("[MT5] [OK] MetaTrader 5 conectado com sucesso.")
    else:
        print("[MT5] [AVISO] Não foi possível conectar ao MetaTrader 5. O robô tentará conectar ao receber uma ordem.")
        
    print("\nConectando ao servidor Cloud Ubuntu...")

    loop = asyncio.get_running_loop()

    while True:
        try:
            async with websockets.connect(SERVER_URL) as ws:
                print("[NUVEM] [CONECTADO] Conectado ao servidor Cloud!")
                
                # Envia status do MT5 após conectar
                await ws.send(json.dumps({"type": "mt5_status", "connected": mt5_connected}))
                
                # Fica ouvindo novas ordens do servidor
                async for message_str in ws:
                    try:
                        message = json.loads(message_str)
                        msg_type = message.get("type")
                        
                        if msg_type == "execute_order":
                            signal_data = message.get("data")
                            agent_log(f"[NUVEM] 📥 Nova ordem recebida do WhatsApp: {signal_data['ativo']}")
                            
                            # Dispara a execução em uma thread secundária para não bloquear o recebimento de dados no socket
                            threading.Thread(
                                target=execute_order_sync, 
                                args=(signal_data, ws, loop), 
                                daemon=True
                            ).start()
                            
                        elif msg_type == "update_mt5_config":
                            mt5_config = message.get("data", {})
                            agent_log("[NUVEM] 📥 Nova configuração do MT5 recebida do painel web!")
                            
                            base_dir = os.path.join(os.environ.get('APPDATA', os.environ.get('LOCALAPPDATA', '')), 'WPP_Trader_Data')
                            os.makedirs(base_dir, exist_ok=True)
                            config_path = os.path.join(base_dir, 'config.json')
                            
                            current_config = {}
                            if os.path.exists(config_path):
                                try:
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        current_config = json.load(f)
                                except: pass
                                    
                            current_config['mt5_login'] = mt5_config.get('mt5_login', '')
                            current_config['mt5_password'] = mt5_config.get('mt5_password', '')
                            current_config['mt5_server'] = mt5_config.get('mt5_server', '')
                            current_config['mt5_path'] = mt5_config.get('mt5_path', '')
                            current_config['valor_operacao'] = mt5_config.get('valor_operacao', '1000')
                            
                            try:
                                with open(config_path, 'w', encoding='utf-8') as f:
                                    json.dump(current_config, f, indent=4)
                            except Exception as e:
                                agent_log(f"[ERRO] Falha ao salvar config do MT5: {e}")
                                
                            agent_log("[CONFIG] Configurações salvas. Tentando reconectar no MetaTrader 5...")
                            
                            def reconnect_mt5(ws_conn, main_loop):
                                global mt5_connected, executor
                                if mt5_connected:
                                    import MetaTrader5 as mt5
                                    mt5.shutdown() # Desconecta conta atual
                                mt5_connected = executor.connect()
                                asyncio.run_coroutine_threadsafe(
                                    ws_conn.send(json.dumps({"type": "mt5_status", "connected": mt5_connected})),
                                    main_loop
                                )
                                
                            threading.Thread(
                                target=reconnect_mt5,
                                args=(ws, loop),
                                daemon=True
                            ).start()
                            
                    except Exception as e:
                        logger.error(f"Erro ao processar mensagem do servidor: {e}")
                        
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError, OSError) as e:
            logger.warning(f"Erro de conexão com o servidor Cloud. Tentando novamente em 5 segundos... ({e})")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Erro inesperado no loop do agente: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\nAgente encerrado pelo usuário.")
        sys.exit(0)
