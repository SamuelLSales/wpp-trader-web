import MetaTrader5 as mt5
import json
import os
import math

class MT5Executor:
    def __init__(self, log_callback=None):
        self.config = {}
        self.log = log_callback if log_callback else print
        self._load_config()

    def _load_config(self):
        import sys
        base_dir = os.path.join(os.environ.get('APPDATA', os.environ.get('LOCALAPPDATA', '')), 'WPP_Trader_Data')
        config_path = os.path.join(base_dir, 'config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                self.log(f"[MT5] Erro ao carregar config.json: {e}")

    def connect(self):
        self._load_config()
        login_str = self.config.get('mt5_login', '').strip()
        password = self.config.get('mt5_password', '').strip()
        server = self.config.get('mt5_server', '').strip()
        mt5_path = self.config.get('mt5_path', '').strip()

        if not login_str or not password or not server:
            self.log("[MT5] ❌ Dados de login do MT5 incompletos. Preencha na aba Configuração.")
            return False

        try:
            login = int(login_str)
        except ValueError:
            self.log("[MT5] ❌ O Login do MT5 deve ser apenas numérico.")
            return False

        self.log(f"[MT5] Iniciando MetaTrader 5 (Servidor: {server})...")
        
        # Inicializa e passa credenciais, usando o caminho do executável se fornecido
        init_args = {"login": login, "server": server, "password": password}
        if mt5_path:
            init_args["path"] = mt5_path

        if not mt5.initialize(**init_args):
            self.log(f"[MT5] ❌ Falha ao iniciar: erro {mt5.last_error()}")
            mt5.shutdown()
            return False
            
        self.log("[MT5] ✅ MetaTrader 5 aberto e conectado com sucesso!")
        return True

    def send_order(self, signal):
        """
        Envia a ordem para o MT5 com base no sinal.
        """
        if not signal or not signal.get('ativo'):
            self.log("[MT5] ❌ Sinal inválido, ignorando execução.")
            return False

        symbol = signal['ativo']

        if not mt5.symbol_select(symbol, True):
            self.log(f"[MT5] ❌ Ativo {symbol} não encontrado no MT5.")
            return False

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            self.log(f"[MT5] ❌ Não foi possível obter informações do ativo {symbol}.")
            return False
            
        # Pega o preço atual (Ask, pois estamos comprando)
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask
        
        if price <= 0:
            self.log(f"[MT5] ❌ Preço inválido para {symbol}: {price}")
            return False

        # Calcula lotes com base no valor alvo configurado (arredonda para CIMA)
        valor_alvo = float(self.config.get('valor_operacao', '1000') or '1000')
        # Na B3, 1 lote = 100 unidades da opção
        custo_por_lote = price * 100.0
        lotes_necessarios = math.ceil(valor_alvo / custo_por_lote)
        lot = float(max(lotes_necessarios, 1))  # Mínimo 1 lote
        custo_real = lot * custo_por_lote
        
        self.log(f"[MT5] 💰 Alvo: R${valor_alvo:.0f} | Preço unitário: R${price:.4f} | Lotes: {int(lot)} | Custo estimado: R${custo_real:.2f}")

        sl = signal.get('stop')
        tp = None
        alvos = signal.get('alvos', [])
        if alvos and len(alvos) > 0:
            tp = alvos[0]  # Define o 1º alvo como TP principal no MT5

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": "WPP Bot",
            "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        
        if sl: request["sl"] = float(sl)
        if tp: request["tp"] = float(tp)

        self.log(f"[MT5] 📡 Enviando ordem {symbol}: Preço={price}, Lote={lot}, SL={sl}, TP={tp}")
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.log(f"[MT5] ❌ Falha ao enviar ordem: {result.retcode} - {mt5.last_error()}")
            
            # Tentar fallback de preenchimento (comum na B3 XP/Clear/Rico)
            if result.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
                self.log("[MT5] ⚠️ Tentando novamente com ORDER_FILLING_IOC...")
                request["type_filling"] = mt5.ORDER_FILLING_IOC
                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    self.log(f"[MT5] ❌ Falha novamente: {result.retcode}")
                    return False
            else:
                return False

        self.log(f"[MT5] ✅ Ordem executada! Ticket: {result.order}")
        return True
