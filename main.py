import discord
from discord.ext import commands
from datetime import datetime
import sqlite3
import os
from pytz import timezone
import re
import unicodedata
import logging
import traceback

# IDs dos canais e cargo - VERIFIQUE SE ESTÃO CORRETOS
CANAL_PONTO = 1416969896687964190
CANAL_LOG = 1416970104507338842
CANAL_PRISOES = 1371206848622891129
ADMIN_ROLE_ID = 1416970979468640287

# --- CONFIGURAÇÕES GERAIS ---
fuso_horario = timezone('America/Sao_Paulo')
DB_FILE = "ponto.db"

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

entradas = {}


def setup_database():
    """Cria as tabelas do banco de dados se não existirem."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, username TEXT,
            entrada TEXT NOT NULL, saida TEXT NOT NULL, tempo_total TEXT
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS prisoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, policial_id INTEGER NOT NULL, policial_nome TEXT,
            mensagem_completa TEXT, data_hora TEXT NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS entradas_ativas (
            user_id INTEGER PRIMARY KEY, username TEXT, entrada TEXT NOT NULL
        )""")
    logging.info("Banco de dados verificado e pronto.")


def load_active_entries():
    """Carrega as entradas ativas do banco para a memória ao iniciar o bot."""
    global entradas
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, entrada FROM entradas_ativas")
            rows = cursor.fetchall()
            for row in rows:
                entradas[row['user_id']] = datetime.fromisoformat(
                    row['entrada']).astimezone(fuso_horario)
        if entradas:
            logging.info(
                f"Carregadas {len(entradas)} entradas ativas do banco de dados."
            )
    except Exception as e:
        logging.error(f"Falha ao carregar entradas ativas: {e}")


class PontoView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def normalize_to_ascii(s: str) -> str:
        s = unicodedata.normalize('NFKC', s)
        out = []
        for ch in s:
            code = ord(ch)
            if 0x1D400 <= code <= 0x1D419:
                out.append(chr(ord('A') + code - 0x1D400))
            elif 0x1D41A <= code <= 0x1D433:
                out.append(chr(ord('a') + code - 0x1D41A))
            elif 0x1D7CE <= code <= 0x1D7D7:
                out.append(chr(ord('0') + code - 0x1D7CE))
            elif 0xFF21 <= code <= 0xFF3A:
                out.append(chr(ord('A') + code - 0xFF21))
            elif 0xFF41 <= code <= 0xFF5A:
                out.append(chr(ord('a') + code - 0xFF41))
            elif 0xFF10 <= code <= 0xFF19:
                out.append(chr(ord('0') + code - 0xFF10))
            else:
                out.append(ch)
        return ''.join(out)

    @discord.ui.button(label="📥 Entrada",
                       style=discord.ButtonStyle.success,
                       custom_id="ponto_entrada_button")
    async def entrada(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        user = interaction.user
        try:
            if user.id in entradas:
                await interaction.response.send_message(
                    f"{user.mention}, você já tem um ponto em aberto!",
                    ephemeral=True)
                return

            agora = datetime.now(fuso_horario)
            entradas[user.id] = agora

            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO entradas_ativas (user_id, username, entrada) VALUES (?, ?, ?)",
                    (user.id, user.name, agora.isoformat()))

            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **entrada** às {agora.strftime('%H:%M:%S')}.",
                ephemeral=True)

            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"✅ Entrada registrada: {user.name} ({user.id}) às {agora.strftime('%d/%m %H:%M:%S')}"
                )

        except Exception:
            logging.error("Erro no botão de ENTRADA:")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Ocorreu um erro ao registrar sua entrada.",
                    ephemeral=True)

    @discord.ui.button(label="📤 Saída",
                       style=discord.ButtonStyle.danger,
                       custom_id="ponto_saida_button")
    async def saida(self, interaction: discord.Interaction,
                    button: discord.ui.Button):
        user = interaction.user
        try:
            if user.id not in entradas:
                await interaction.response.send_message(
                    f"{user.mention}, você não registrou entrada!",
                    ephemeral=True)
                return

            inicio = entradas.pop(user.id)
            fim = datetime.now(fuso_horario)
            duracao = (fim - inicio).total_seconds()
            horas, resto = divmod(duracao, 3600)
            minutos, _ = divmod(resto, 60)
            tempo_total = f"{int(horas)}h {int(minutos)}min"

            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO registros (user_id, username, entrada, saida, tempo_total) VALUES (?, ?, ?, ?, ?)",
                    (user.id, user.name, inicio.strftime("%Y-%m-%d %H:%M:%S"),
                     fim.strftime("%Y-%m-%d %H:%M:%S"), tempo_total))
                cursor.execute("DELETE FROM entradas_ativas WHERE user_id = ?",
                               (user.id, ))

            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **saída** às {fim.strftime('%H:%M:%S')}.\n"
                f"⏱️ Tempo de serviço: {tempo_total}",
                ephemeral=True)

            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"❌ Saída registrada: {user.name} ({user.id}) às {fim.strftime('%d/%m %H:%M:%S')} | Tempo: {tempo_total}"
                )

        except Exception:
            logging.error("Erro no botão de SAÍDA:")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Ocorreu um erro ao registrar sua saída.",
                    ephemeral=True)


@bot.command(name="prisoes", help="Mostra o total de prisões por policial.")
@commands.has_role(ADMIN_ROLE_ID)
async def prisoes(ctx):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT T2.policial_nome, T1.total
                FROM (SELECT policial_id, COUNT(*) as total FROM prisoes GROUP BY policial_id) T1
                JOIN (SELECT policial_id, policial_nome FROM prisoes GROUP BY policial_id HAVING MAX(id)) T2 
                ON T1.policial_id = T2.policial_id
                ORDER BY T1.total DESC
            """)
            resultados = cursor.fetchall()

        if resultados:
            embed = discord.Embed(title="📊 Relatório de Prisões por Policial",
                                  color=discord.Color.blue())
            for nome, contagem in resultados:
                embed.add_field(name=f"👮‍♂️ {nome}",
                                value=f"**{contagem}** prisões",
                                inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("Nenhuma prisão registrada ainda.")
    except Exception as e:
        logging.error(f"Erro no comando prisoes_admin: {e}")
        await ctx.send("Ocorreu um erro ao buscar o relatório de prisões.")


@prisoes.error
async def prisoes_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("Você não tem permissão para usar este comando.",
                       ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Processa comandos primeiro para que o !prisoes ainda funcione
    await bot.process_commands(message)

    # Se a mensagem não for no canal de prisões, ignora o resto
    if message.channel.id != CANAL_PRISOES:
        return

    content = message.content or ""
    normalized = PontoView.normalize_to_ascii(content).upper()
    prisoes_na_mensagem = len(re.findall(r'FICHA\s*CRIMINAL', normalized))

    if prisoes_na_mensagem <= 0:
        return

    agora = datetime.now(fuso_horario)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            for _ in range(prisoes_na_mensagem):
                cursor.execute(
                    "INSERT INTO prisoes (policial_id, policial_nome, mensagem_completa, data_hora) VALUES (?, ?, ?, ?)",
                    (message.author.id, str(message.author), content,
                     agora.strftime("%Y-%m-%d %H:%M:%S")))

            cursor.execute(
                "SELECT COUNT(*) FROM prisoes WHERE policial_id = ?",
                (message.author.id, ))
            total_prisoes_policial = cursor.fetchone()[0]

        # --- MUDANÇA PRINCIPAL AQUI ---
        # 1. Tenta enviar uma Mensagem Direta (DM) para o autor
        try:
            mensagem_confirmacao = (
                f"Olá! Sua prisão registrada no canal #{message.channel.name} foi contabilizada com sucesso.\n"
                f"Você registrou: **{prisoes_na_mensagem}** prisão(ões).\n"
                f"Seu total agora é: **{total_prisoes_policial}** prisões.")
            await message.author.send(
                f"🚨 **Confirmação de Registro** 🚨\n{mensagem_confirmacao}")
        except discord.Forbidden:
            # Se o usuário bloqueia DMs, avisa no console
            logging.warning(
                f"Não foi possível enviar DM para {message.author.name}. O usuário pode ter DMs desabilitadas."
            )

        # 2. Adiciona uma reação na mensagem original como feedback visual no canal
        await message.add_reaction('✅')

    except Exception as e:
        # Se der erro no banco de dados, reage com ❌
        await message.add_reaction('❌')
        logging.error(f"Erro ao gravar prisões: {e}")
        traceback.print_exc()


# --- FUNÇÃO ON_READY ATUALIZADA ---
@bot.event
async def on_ready():
    # Funções essenciais do código novo
    setup_database()
    load_active_entries()
    bot.add_view(
        PontoView())  # Garante que botões de mensagens antigas funcionem

    logging.info(f"Bot conectado como {bot.user}")

    # Lógica simplificada, como no seu código antigo que funcionava
    # Isso envia uma nova mensagem a cada reinício para garantir que a view está 100% ativa.
    # Pode gerar algumas mensagens a mais no canal, mas aumenta a confiabilidade.
    canal = bot.get_channel(CANAL_PONTO)
    if canal:
        try:
            await canal.send("🕒 **Sistema de Ponto** — use os botões abaixo:",
                             view=PontoView())
            logging.info(
                "Nova mensagem de ponto enviada para garantir que a view está ativa."
            )
        except Exception as e:
            logging.error(f"Não foi possível enviar a mensagem de ponto: {e}")


if __name__ == "__main__":
    if os.path.exists("keep_alive.py"):
        from keep_alive import keep_alive
        keep_alive()
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print(
            "ERRO CRÍTICO: O token do bot não foi encontrado na aba 'Secrets' do Replit."
        )
    else:
        bot.run(TOKEN)
