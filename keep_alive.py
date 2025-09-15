from flask import Flask
from threading import Thread

app = Flask('')


@app.route('/')
def home():
    return "Bot esta online, Bot criado por Discord: kagijin, Criado exclusivamente para https://discord.gg/vkcuSuCpbP"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()
