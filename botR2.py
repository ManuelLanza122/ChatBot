import telebot
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from telebot import types

# --- CONFIGURACIÓN ---
TOKEN = 'TU_TOKEN_AQUI'
ADMIN_ID = 123456789 
GRUPO_ID = -1001234567890 
bot = telebot.TeleBot(TOKEN)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('comunidad.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                      (user_id INTEGER PRIMARY KEY, nombre TEXT, tipo TEXT, 
                       limite_multimedia INTEGER, hoy_enviado INTEGER, fecha_expiracion TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS videos 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- FUNCIONES AUXILIARES ---
def actualizar_usuario(user_id, tipo, limite, exp):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("UPDATE usuarios SET tipo = ?, limite_multimedia = ?, fecha_expiracion = ? WHERE user_id = ?", (tipo, limite, exp, user_id))
    conn.commit()
    conn.close()

# --- TAREAS AUTOMÁTICAS ---
def tareas_automaticas():
    while True:
        time.sleep(86400) # 24 horas
        conn = sqlite3.connect('comunidad.db')
        # Degradación si no cumplió cuota
        conn.execute("UPDATE usuarios SET tipo = 'PENDIENTE', limite_multimedia = 0 WHERE tipo = 'APT' AND hoy_enviado < limite_multimedia")
        # Reset diario
        conn.execute("UPDATE usuarios SET hoy_enviado = 0 WHERE tipo = 'APT'")
        conn.commit()
        conn.close()

threading.Thread(target=tareas_automaticas, daemon=True).start()

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def start(message):
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo FROM usuarios WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO usuarios (user_id, nombre, tipo, limite_multimedia, hoy_enviado) VALUES (?, ?, 'PENDIENTE', 0, 0)", 
                     (message.from_user.id, message.from_user.first_name))
        conn.commit()
        tipo = 'PENDIENTE'
    else:
        tipo = user[0]
    conn.close()

    if tipo == 'VIP':
        texto = f"👑 Bienvenido VIP. Tu ID: `{message.from_user.id}`."
    elif tipo == 'APT':
        texto = f"🛠 Bienvenido Aportador. Tu ID: `{message.from_user.id}`. Recuerda tu cuota diaria."
    else:
        texto = f"👋 Bienvenido. Tu ID: `{message.from_user.id}`. Contacta al admin."
    bot.reply_to(message, texto, parse_mode='Markdown')

@bot.message_handler(commands=['add_vip'])
def add_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        uid, dias = int(args[1]), int(args[2])
        exp = (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
        actualizar_usuario(uid, 'VIP', 0, exp)
        bot.send_message(uid, "🎉 ¡Acceso VIP activado!")
        bot.reply_to(message, f"✅ VIP asignado.")
    except: bot.reply_to(message, "Uso: /add_vip [ID] [DIAS]")

@bot.message_handler(commands=['add_apt'])
def add_apt(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        uid, limite = int(args[1]), int(args[2])
        actualizar_usuario(uid, 'APT', limite, None)
        bot.send_message(uid, f"✅ Acceso APT activado con cuota: {limite}.")
        bot.reply_to(message, "✅ APT asignado.")
    except: bot.reply_to(message, "Uso: /add_apt [ID] [LIMITE]")

@bot.message_handler(commands=['stats'])
def stats(message):
    if message.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect('comunidad.db')
    vips = conn.execute("SELECT count(*) FROM usuarios WHERE tipo = 'VIP'").fetchone()[0]
    apts = conn.execute("SELECT nombre, hoy_enviado, limite_multimedia FROM usuarios WHERE tipo = 'APT'").fetchall()
    conn.close()
    texto = f"📊 VIPs: {vips}\n📝 Aportadores:\n" + "\n".join([f"• {n}: {e}/{l}" for n, e, l in apts])
    bot.reply_to(message, texto)

# --- NAVEGACIÓN VIDEOS ---
@bot.message_handler(commands=['tik'])
def comando_tik(message):
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT id, file_id FROM videos").fetchall()
    conn.close()
    if not videos: return bot.reply_to(message, "No hay contenido.")
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️", callback_data="nav_0"), types.InlineKeyboardButton("➡️", callback_data="nav_1"))
    bot.send_video(message.chat.id, videos[0][1], reply_markup=markup, caption="1/{}".format(len(videos)))

@bot.callback_query_handler(func=lambda call: call.data.startswith('nav_'))
def navegacion(call):
    index = int(call.data.split('_')[1])
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT id, file_id FROM videos").fetchall()
    conn.close()
    if 0 <= index < len(videos):
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⬅️", callback_data=f"nav_{index-1}"), types.InlineKeyboardButton("➡️", callback_data=f"nav_{index+1}"))
        bot.edit_message_media(media=types.InputMediaVideo(videos[index][1]), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

# --- MANEJADOR MULTIMEDIA ---
@bot.message_handler(content_types=['video', 'photo', 'document', 'audio', 'voice'])
def manejar_todo(message):
    if message.chat.id == GRUPO_ID: return
    
    # Si es video, lo guardamos para el /tik
    if message.content_type == 'video':
        conn = sqlite3.connect('comunidad.db')
        conn.execute("INSERT INTO videos (file_id) VALUES (?)", (message.video.file_id,))
        conn.commit()
        conn.close()

    # Lógica de reenvío y cuotas
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo, limite_multimedia, hoy_enviado FROM usuarios WHERE user_id = ?", (message.from_user.id,)).fetchone()
    
    if message.from_user.id != ADMIN_ID:
        if not user or user[0] == 'PENDIENTE': 
            conn.close()
            return
        if user[0] == 'APT':
            if user[2] >= user[1]: return
            conn.execute("UPDATE usuarios SET hoy_enviado = hoy_enviado + 1 WHERE user_id = ?", (message.from_user.id,))
            conn.commit()
            
    usuarios = conn.execute("SELECT user_id FROM usuarios WHERE tipo IN ('VIP', 'APT')").fetchall()
    for u in usuarios:
        if u[0] != message.from_user.id:
            try: bot.copy_message(u[0], message.chat.id, message.message_id)
            except: pass
    conn.close()

bot.infinity_polling()