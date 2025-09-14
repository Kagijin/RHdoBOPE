import discord
from discord.ext import commands
from datetime import datetime
import sqlite3
import os
from keep_alive import keep_alive

# IDs dos canais
CANAL_PONTO = 123456789012345678 # canal onde os usu�rios batem ponto
CANAL_LOG = 987654321098765432   # canal de logs

# ID da fun��o de administrador para o comando !prisoes_admin
# Substitua este ID pelo ID da sua fun��o de administrador no Discord
ADMIN_ROLE_ID = 111111111111111111

# Configura��o do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Criar e/ou conectar ao banco SQLite
conn = sqlite3.connect("ponto.db")
cursor = conn.cursor()

# Tabela para registros de ponto (j� existente)
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

# Tabela para registros de pris�es (NOVA)
cursor.execute("""
CREATE TABLE IF NOT EXISTS prisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policial_id INTEGER,
    policial_nome TEXT,
    preso_nome TEXT,
    motivo TEXT,
    data_hora TEXT
)
""")

conn.commit()
conn.close()

# Guardar entradas ativas (para n�o precisar consultar banco toda hora)
entradas = {}

class PontoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="?? Entrada", style=discord.ButtonStyle.success)
    async def entrada(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in entradas:
            await interaction.response.send_message(
                f"{user.mention}, voc� j� tem um ponto em aberto!", ephemeral=True
            )
        else:
            agora = datetime.now()
            entradas[user.id] = agora
            await interaction.response.send_message(
                f"{user.mention} bateu ponto de **entrada** �s {agora.strftime('%H:%M:%S')}.",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"? Entrada registrada: {user.name} ({user.id}) �s {agora.strftime('%d/%m %H:%M:%S')}"
                )

    @discord.ui.button(label="?? Sa�da", style=discord.ButtonStyle.danger)
    async def saida(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id not in entradas:
            await interaction.response.send_message(
                f"{user.mention}, voc� n�o registrou entrada!", ephemeral=True
            )
        else:
            inicio = entradas.pop(user.id)
            fim = datetime.now()
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
                f"{user.mention} bateu ponto de **sa�da** �s {fim.strftime('%H:%M:%S')}.\n"
                f"?? Tempo de servi�o: {tempo_total}",
                ephemeral=True
            )
            canal_log = bot.get_channel(CANAL_LOG)
            if canal_log:
                await canal_log.send(
                    f"? Sa�da registrada: {user.name} ({user.id}) �s {fim.strftime('%d/%m %H:%M:%S')} "
                    f"| Tempo: {tempo_total}"
                )

# Comando para registrar uma pris�o
# Uso: !prender <nome_do_preso> <motivo>
@bot.command(name="prender", help="Registra uma pris�o no banco de dados. Ex: !prender 'Fulano de Tal' 'Roubo a Loja'")
async def prender(ctx, preso_nome: str, *, motivo: str):
    policial = ctx.author
    agora = datetime.now()

    # Salvar a pris�o no banco
    conn = sqlite3.connect("ponto.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO prisoes (policial_id, policial_nome, preso_nome, motivo, data_hora)
        VALUES (?, ?, ?, ?, ?)
    """, (policial.id, policial.name, preso_nome, motivo, agora.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    # Enviar mensagem de confirma��o para o canal de onde o comando foi executado
    await ctx.send(f"?? Pris�o registrada com sucesso! \n"
                   f"**Policial:** {policial.mention} \n"
                   f"**Nome do Preso:** {preso_nome} \n"
                   f"**Motivo:** {motivo}")

    # Enviar log para o canal de logs
    canal_log = bot.get_channel(CANAL_LOG)
    if canal_log:
        await canal_log.send(f"?? Pris�o registrada: Policial {policial.name} ({policial.id}) prendeu '{preso_nome}' por '{motivo}' �s {agora.strftime('%d/%m %H:%M:%S')}")

# Comando para consultar o total de pris�es do usu�rio
@bot.command(name="prisoes_total", help="Mostra o total de pris�es registradas por voc�.")
async def prisoes_total(ctx):
    policial_id = ctx.author.id
    conn = sqlite3.connect("ponto.db")
    cursor = conn.cursor()

    # Contar as pris�es do usu�rio
    cursor.execute("SELECT COUNT(*) FROM prisoes WHERE policial_id = ?", (policial_id,))
    total_prisoes = cursor.fetchone()[0]

    conn.close()

    await ctx.send(f"?? **Relat�rio de Pris�es**\n"
                   f"O policial {ctx.author.mention} registrou um total de **{total_prisoes}** pris�es at� o momento.")

# NOVO COMANDO: Lista o total de pris�es por policial (apenas para administradores)
@bot.command(name="prisoes_admin", help="Mostra o total de pris�es registradas por todos os policiais. (Somente para administradores)")
async def prisoes_admin(ctx):
    # Verifica se o usu�rio tem a fun��o de administrador
    if any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
        conn = sqlite3.connect("ponto.db")
        cursor = conn.cursor()
        
        # Puxa a lista de todos os policiais e a contagem de suas pris�es
        cursor.execute("SELECT policial_nome, COUNT(*) FROM prisoes GROUP BY policial_nome ORDER BY COUNT(*) DESC")
        resultados = cursor.fetchall()
        
        conn.close()
        
        if resultados:
            embed = discord.Embed(
                title="?? Relat�rio de Pris�es por Policial",
                color=discord.Color.blue()
            )
            for nome, contagem in resultados:
                embed.add_field(name=f"????? {nome}", value=f"**{contagem}** pris�es", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("Nenhuma pris�o registrada ainda.")
    else:
        await ctx.send("Voc� n�o tem permiss�o para usar este comando.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    canal = bot.get_channel(CANAL_PONTO)
    if canal:
        await canal.send("?? **Sistema de Ponto** � use os bot�es abaixo:", view=PontoView())

keep_alive()
bot.run(os.getenv("TOKEN"))
