const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

const WEBHOOK_URL = 'http://localhost:5001/webhook';

// Carrega o nome do grupo do config.json criado pelo Python
let targetGroup = process.env.WPP_TARGET_GROUP || "Não configurado";

// Caminho de persistência compatível com Windows e Linux
const dataDir = process.platform === 'win32'
    ? path.join(process.env.APPDATA || process.env.LOCALAPPDATA, 'WPP_Trader_Data')
    : path.join(process.env.HOME || '/tmp', '.wpp_trader_data');

if (!fs.existsSync(dataDir)) { fs.mkdirSync(dataDir, { recursive: true }); }

// Se não veio pela env, tenta ler do config.json local
if (targetGroup === "Não configurado") {
    try {
        const configPath = path.join(dataDir, 'config.json');
        if (fs.existsSync(configPath)) {
            const configData = JSON.parse(fs.readFileSync(configPath, 'utf8'));
            if (configData.wpp_group) {
                targetGroup = configData.wpp_group;
            }
        }
    } catch (err) {
        console.error("Erro ao ler config.json:", err.message);
    }
}

console.log(`[WPP Listener] Grupo alvo definido como: "${targetGroup}"`);

// Usar LocalAuth para salvar a sessão e não pedir o QR Code toda vez
const client = new Client({
    authStrategy: new LocalAuth({ dataPath: dataDir }),
    webVersionCache: {
        type: 'remote',
        remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.3000.1041799339-alpha.html'
    },
    puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', async (qr) => {
    console.log('👆 QR Code gerado, enviando para a interface Python...');
    try {
        await axios.post(WEBHOOK_URL, { type: 'qr', data: qr });
    } catch (error) {
        // Silencioso se o Python ainda não subiu
    }
});

client.on('ready', async () => {
    console.log('✅ Cliente do WhatsApp conectado e pronto!');
    try {
        await axios.post(WEBHOOK_URL, { type: 'status', data: 'connected' });
    } catch (error) {
        // Silencioso
    }
});

client.on('message', async msg => {
    const chat = await msg.getChat();

    const NOME_DO_GRUPO_ALVO = targetGroup;

    if (chat.isGroup && chat.name === NOME_DO_GRUPO_ALVO) {
        const textoMsg = msg.body.toUpperCase();
        
        const isSinal = textoMsg.includes('CÓDIGO DA OPÇÃO') || 
                        textoMsg.includes('PREÇO DE ENTRADA') || 
                        textoMsg.includes('ALERTA DE RECOMENDAÇÃO');

        if (!isSinal) {
            return;
        }

        console.log(`✅ Sinal VIP recebido de ${chat.name}`);

        try {
            await axios.post(WEBHOOK_URL, {
                type: 'signal',
                message: msg.body,
                grupo: chat.name
            });
            console.log('📡 Sinal encaminhado para o Python!');
        } catch (error) {
            console.error('❌ Erro ao enviar para o Python:', error.message);
        }
    }
});

client.initialize();
