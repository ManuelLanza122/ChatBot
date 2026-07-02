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

# --- FUNCIONES DE GESTIÓN ---
def es_autorizado(user_id):
    if user_id == ADMIN_ID: return True
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo, fecha_expiracion FROM usuarios WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not user: return False
    # Verificación VIP con fecha
    if user[0] == 'VIP' and user[1]:
        if datetime.now() > datetime.strptime(user[1], '%Y-%m-%d'):
            actualizar_usuario(user_id, 'PENDIENTE', 0, None)
            return False
        return True
    return user[0] == 'APT'

def actualizar_usuario(user_id, tipo, limite, exp):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("UPDATE usuarios SET tipo = ?, limite_multimedia = ?, fecha_expiracion = ? WHERE user_id = ?", (tipo, limite, exp, user_id))
    conn.commit()
    conn.close()

# --- TAREAS AUTOMÁTICAS ---
def tareas_automaticas():
    while True:
        time.sleep(86400) # Reset diario
        conn = sqlite3.connect('comunidad.db')
        conn.execute("UPDATE usuarios SET hoy_enviado = 0 WHERE tipo = 'APT'")
        conn.commit()
        conn.close()

def spam_recordatorio():
    while True:
        time.sleep(3600) # Cada hora
        try: bot.send_message(GRUPO_ID, "📢 ¡Suscríbete a nuestra comunidad para acceder a contenido exclusivo!")
        except: pass

threading.Thread(target=tareas_automaticas, daemon=True).start()
threading.Thread(target=spam_recordatorio, daemon=True).start()

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def start(message):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("INSERT OR IGNORE INTO usuarios (user_id, nombre, tipo, limite_multimedia, hoy_enviado) VALUES (?, ?, 'PENDIENTE', 0, 0)", 
                 (message.from_user.id, message.from_user.first_name))
    conn.commit()
    conn.close()
    bot.reply_to(message, "👋 Bienvenido. Contacta al admin para activar acceso VIP o APT.")

@bot.message_handler(commands=['add_vip'])
def add_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        exp = (datetime.now() + timedelta(days=int(args[2]))).strftime('%Y-%m-%d')
        actualizar_usuario(int(args[1]), 'VIP', 0, exp)
        bot.reply_to(message, f"✅ VIP asignado hasta {exp}")
    except: bot.reply_to(message, "Uso: /add_vip [ID] [DIAS]")

@bot.message_handler(commands=['add_apt'])
def add_apt(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        actualizar_usuario(int(args[1]), 'APT', int(args[2]), None)
        bot.reply_to(message, "✅ APT asignado.")
    except: bot.reply_to(message, "Uso: /add_apt [ID] [LIMITE]")

@bot.message_handler(commands=['tik'])
def comando_tik(message):
    if message.chat.id == GRUPO_ID or not es_autorizado(message.from_user.id): return
    
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT id, file_id FROM videos").fetchall()
    conn.close()
    if not videos:
        bot.reply_to(message, "No hay videos disponibles.")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️", callback_data="nav_-1"),
               types.InlineKeyboardButton("➡️", callback_data="nav_1"))
    bot.send_video(message.chat.id, videos[0][1], reply_markup=markup, caption=f"Video 1/{len(videos)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('nav_'))
def navegacion_callback(call):
    if not es_autorizado(call.from_user.id): return
    index = int(call.data.split('_')[1])
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT id, file_id FROM videos").fetchall()
    conn.close()
    if 0 <= index < len(videos):
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⬅️", callback_data=f"nav_{index-1}"),
                   types.InlineKeyboardButton("➡️", callback_data=f"nav_{index+1}"))
        bot.edit_message_media(media=types.InputMediaVideo(videos[index][1]), chat_id=call.message.chat.id, 
                               message_id=call.message.message_id, reply_markup=markup)

@bot.message_handler(content_types=['video'])
def recibir_video(message):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("INSERT INTO videos (file_id) VALUES (?)", (message.video.file_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, "💾 Video guardado.")

@bot.message_handler(func=lambda message: True)
def chat_flow(message):
    if message.chat.id == GRUPO_ID: return
    
    user_id = message.from_user.id
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo, limite_multimedia, hoy_enviado FROM usuarios WHERE user_id = ?", (user_id,)).fetchone()
    
    if user_id != ADMIN_ID:
        if not user or user[0] == 'PENDIENTE': return
        if user[0] == 'APT':
            if user[2] >= user[1]: return
            conn.execute("UPDATE usuarios SET hoy_enviado = hoy_enviado + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
    
    usuarios = conn.execute("SELECT user_id FROM usuarios WHERE tipo IN ('VIP', 'APT')").fetchall()
    for u in usuarios:
        if u[0] != user_id:
            try: bot.copy_message(u[0], message.chat.id, message.message_id)
            except: pass
    conn.close()

bot.infinity_polling()