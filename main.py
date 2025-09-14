import discord
from discord.ext import commands
from datetime import datetime
import sqlite3
import os
from pytz import timezone

# Nota: Você precisa instalar a biblioteca 'pytz'.
# Adicione a linha 'pytz' ao seu arquivo requirements.txt no Replit.

# IDs dos canais
CANAL_PONTO = 1416923344074444921 # canal onde os usuários batem ponto
CANAL_LOG = 987654321098765432   # canal de logs
CANAL_PRISOES = 1416923369714094160 # NOVO: canal onde as prisões serão registradas (substitua o ID)

# ID da função de administrador para o comando !prisoes_admin
# Substitua este ID pelo ID da sua função de administrador no Discord
ADMIN_ROLE_ID = 1416928088842960986

# Configuração do fuso horário de Brasília
fuso_horario = timezone('America/Sao_Paulo')

# Configuração do bot
intents = discord.Intents.default()
intents.message_content = True # É necessário para o bot ler as mensagens
bot = commands.Bot(command_prefix="!", intents=intents)

# Criar e/ou conectar ao banco SQLite
conn = sqlite3.connect("ponto.db")
cursor = conn.cursor()

# Tabela para registros de ponto (já existente)
cursor.execute("""
CREATE TABLE IF NOT EXISTS registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    entrada TEXT,
    saida TEXT,
    tempo_total TEXT
)
""")

# Tabela para registros de prisões (ATUALIZADA)
cursor.execute("""
CREATE TABLE IF NOT EXISTS prisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policial_id INTEGER,
    policial_nome TEXT,
    mensagem_completa TEXT,
    data_hora TEXT
)
""")

conn.commit()
conn.close()

# Guardar entradas ativas (para não precisar consultar banco toda hora)
entradas = {}

class PontoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📥 Entrada", style=discord.ButtonStyle.success)
    async def entrada(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in entradas:
            await interaction.response.send_message(
                f"{user.mention}, você já tem um ponto em aberto!", ephemeral=True
            )
        else:
            agora = datetime.now(fuso_horario)
            entradas[user.id] = agora
            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **entrada** às {agora.strftime('%H:%M:%S')}.",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"✅ Entrada registrada: {user.name} ({user.id}) às {agora.strftime('%d/%m %H:%M:%S')}"
                )

    @discord.ui.button(label="📤 Saída", style=discord.ButtonStyle.danger)
    async def saida(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id not in entradas:
            await interaction.response.send_message(
                f"{user.mention}, você não registrou entrada!", ephemeral=True
            )
        else:
            inicio = entradas.pop(user.id)
            fim = datetime.now(fuso_horario)
            duracao = fim - inicio
            horas = duracao.seconds // 3600
            minutos = (duracao.seconds % 3600) // 60
            tempo_total = f"{horas}h {minutos}min"

            # Salvar no banco
            conn = sqlite3.connect("ponto.db")
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO registros (user_id, username, entrada, saida, tempo_total)
                VALUES (?, ?, ?, ?, ?)
            """, (user.id, user.name, inicio.strftime("%Y-%m-%d %H:%M:%S"),
                  fim.strftime("%Y-%m-%d %H:%M:%S"), tempo_total))
            conn.commit()
            conn.close()

            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **saída** às {fim.strftime('%H:%M:%S')}.\n"
                f"⏱️ Tempo de serviço: {tempo_total}",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"❌ Saída registrada: {user.name} ({user.id}) às {fim.strftime('%d/%m %H:%M:%S')} "
                    f"| Tempo: {tempo_total}"
                )

# NOVO: O bot ouve todas as mensagens para registrar as prisões
@bot.event
async def on_message(message):
    # Ignora mensagens de outros bots
    if message.author.bot:
        return
    
    # Verifica se a mensagem foi enviada no canal de prisões
    if message.channel.id == CANAL_PRISOES:
        policial = message.author
        agora = datetime.now(fuso_horario)

        # Salva a prisão no banco de dados com a mensagem completa
        conn = sqlite3.connect("ponto.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO prisoes (policial_id, policial_nome, mensagem_completa, data_hora)
            VALUES (?, ?, ?, ?)
        """, (policial.id, policial.name, message.content, agora.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

        # Envia uma mensagem epêmera de confirmação para o policial
        # A mensagem aparecerá no mesmo chat, mas será visível apenas para ele.
        await message.channel.send(f"🚨 Sua prisão foi registrada com sucesso!", ephemeral=True)


    # Processa comandos para que eles ainda funcionem
    await bot.process_commands(message)

# Comando para listar o total de prisões por policial (somente para administradores)
@bot.command(name="prisoes_admin", help="Mostra o total de prisões registradas por todos os policiais. (Somente para administradores)")
async def prisoes_admin(ctx):
    # Verifica se o usuário tem a função de administrador
    if any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
        conn = sqlite3.connect("ponto.db")
        cursor = conn.cursor()
        
        # Puxa a lista de todos os policiais e a contagem de suas prisões
        cursor.execute("SELECT policial_nome, COUNT(*) FROM prisoes GROUP BY policial_nome ORDER BY COUNT(*) DESC")
        resultados = cursor.fetchall()
        
        conn.close()
        
        if resultados:
            embed = discord.Embed(
                title="📊 Relatório de Prisões por Policial",
                color=discord.Color.blue()
            )
            for nome, contagem in resultados:
                embed.add_field(name=f"👮‍♂️ {nome}", value=f"**{contagem}** prisões", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("Nenhuma prisão registrada ainda.")
    else:
        await ctx.send("Você não tem permissão para usar este comando.")


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    canal = bot.get_channel(CANAL_PONTO)
    if canal:
        await canal.send("🕒 **Sistema de Ponto** — use os botões abaixo:", view=PontoView())

bot.run(os.getenv("TOKEN"))

# Configuração do fuso horário de Brasília
fuso_horario = timezone('America/Sao_Paulo')

# Configuração do bot
intents = discord.Intents.default()
intents.message_content = True # É necessário para o bot ler as mensagens
bot = commands.Bot(command_prefix="!", intents=intents)

# Criar e/ou conectar ao banco SQLite
conn = sqlite3.connect("ponto.db")
cursor = conn.cursor()

# Tabela para registros de ponto (já existente)
cursor.execute("""
CREATE TABLE IF NOT EXISTS registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    entrada TEXT,
    saida TEXT,
    tempo_total TEXT
)
""")

# Tabela para registros de prisões (ATUALIZADA)
cursor.execute("""
CREATE TABLE IF NOT EXISTS prisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policial_id INTEGER,
    policial_nome TEXT,
    mensagem_completa TEXT,
    data_hora TEXT
)
""")

conn.commit()
conn.close()

# Guardar entradas ativas (para não precisar consultar banco toda hora)
entradas = {}

class PontoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📥 Entrada", style=discord.ButtonStyle.success)
    async def entrada(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in entradas:
            await interaction.response.send_message(
                f"{user.mention}, você já tem um ponto em aberto!", ephemeral=True
            )
        else:
            agora = datetime.now(fuso_horario)
            entradas[user.id] = agora
            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **entrada** às {agora.strftime('%H:%M:%S')}.",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"✅ Entrada registrada: {user.name} ({user.id}) às {agora.strftime('%d/%m %H:%M:%S')}"
                )

    @discord.ui.button(label="📤 Saída", style=discord.ButtonStyle.danger)
    async def saida(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id not in entradas:
            await interaction.response.send_message(
                f"{user.mention}, você não registrou entrada!", ephemeral=True
            )
        else:
            inicio = entradas.pop(user.id)
            fim = datetime.now(fuso_horario)
            duracao = fim - inicio
            horas = duracao.seconds // 3600
            minutos = (duracao.seconds % 3600) // 60
            tempo_total = f"{horas}h {minutos}min"

            # Salvar no banco
            conn = sqlite3.connect("ponto.db")
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO registros (user_id, username, entrada, saida, tempo_total)
                VALUES (?, ?, ?, ?, ?)
            """, (user.id, user.name, inicio.strftime("%Y-%m-%d %H:%M:%S"),
                  fim.strftime("%Y-%m-%d %H:%M:%S"), tempo_total))
            conn.commit()
            conn.close()

            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **saída** às {fim.strftime('%H:%M:%S')}.\n"
                f"⏱️ Tempo de serviço: {tempo_total}",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"❌ Saída registrada: {user.name} ({user.id}) às {fim.strftime('%d/%m %H:%M:%S')} "
                    f"| Tempo: {tempo_total}"
                )

# NOVO: O bot ouve todas as mensagens para registrar as prisões
@bot.event
async def on_message(message):
    # Ignora mensagens de outros bots
    if message.author.bot:
        return
    
    # Verifica se a mensagem foi enviada no canal de prisões
    if message.channel.id == CANAL_PRISOES:
        policial = message.author
        agora = datetime.now(fuso_horario)

        # Salva a prisão no banco de dados com a mensagem completa
        conn = sqlite3.connect("ponto.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO prisoes (policial_id, policial_nome, mensagem_completa, data_hora)
            VALUES (?, ?, ?, ?)
        """, (policial.id, policial.name, message.content, agora.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

        # Envia uma mensagem privada de confirmação para o policial
        try:
            await policial.send(f"🚨 Sua prisão foi registrada com sucesso!")
        except discord.Forbidden:
            print(f"Não foi possível enviar DM para {policial.name}. Verifique as permissões de privacidade.")

    # Processa comandos para que eles ainda funcionem
    await bot.process_commands(message)

# Comando para listar o total de prisões por policial (somente para administradores)
@bot.command(name="prisoes_admin", help="Mostra o total de prisões registradas por todos os policiais. (Somente para administradores)")
async def prisoes_admin(ctx):
    # Verifica se o usuário tem a função de administrador
    if any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
        conn = sqlite3.connect("ponto.db")
        cursor = conn.cursor()
        
        # Puxa a lista de todos os policiais e a contagem de suas prisões
        cursor.execute("SELECT policial_nome, COUNT(*) FROM prisoes GROUP BY policial_nome ORDER BY COUNT(*) DESC")
        resultados = cursor.fetchall()
        
        conn.close()
        
        if resultados:
            embed = discord.Embed(
                title="📊 Relatório de Prisões por Policial",
                color=discord.Color.blue()
            )
            for nome, contagem in resultados:
                embed.add_field(name=f"👮‍♂️ {nome}", value=f"**{contagem}** prisões", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("Nenhuma prisão registrada ainda.")
    else:
        await ctx.send("Você não tem permissão para usar este comando.")


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    canal = bot.get_channel(CANAL_PONTO)
    if canal:
        await canal.send("🕒 **Sistema de Ponto** — use os botões abaixo:", view=PontoView())

bot.run(os.getenv("TOKEN"))
