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

# --- FUNCIONES ---
def es_autorizado(user_id):
    if user_id == ADMIN_ID: return True
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo, fecha_expiracion FROM usuarios WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not user: return False
    if user[0] == 'VIP' and user[1]:
        return datetime.now() <= datetime.strptime(user[1], '%Y-%m-%d')
    return user[0] == 'APT'

def actualizar_usuario(user_id, tipo, limite, exp):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("UPDATE usuarios SET tipo = ?, limite_multimedia = ?, fecha_expiracion = ? WHERE user_id = ?", (tipo, limite, exp, user_id))
    conn.commit()
    conn.close()

# --- TAREAS AUTOMÁTICAS (CASTIGO Y RESET) ---
def tareas_automaticas():
    while True:
        time.sleep(86400) # Ejecución cada 24 horas
        conn = sqlite3.connect('comunidad.db')
        cursor = conn.cursor()
        
        # 1. Identificar incumplidos y notificar
        cursor.execute("SELECT user_id FROM usuarios WHERE tipo = 'APT' AND hoy_enviado < limite_multimedia")
        incumplidos = cursor.fetchall()
        for u in incumplidos:
            try: bot.send_message(u[0], "⚠️ **Acceso Restringido:** No cumpliste con tu cuota diaria. Contacta al admin para reactivar tu cuenta.")
            except: pass
        
        # 2. Degradar y resetear contadores
        cursor.execute("UPDATE usuarios SET tipo = 'PENDIENTE', limite_multimedia = 0 WHERE tipo = 'APT' AND hoy_enviado < limite_multimedia")
        cursor.execute("UPDATE usuarios SET hoy_enviado = 0 WHERE tipo = 'APT'")
        conn.commit()
        conn.close()

threading.Thread(target=tareas_automaticas, daemon=True).start()

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def start(message):
    conn = sqlite3.connect('comunidad.db')
    conn.execute("INSERT OR IGNORE INTO usuarios (user_id, nombre, tipo, limite_multimedia, hoy_enviado) VALUES (?, ?, 'PENDIENTE', 0, 0)", 
                 (message.from_user.id, message.from_user.first_name))
    conn.commit()
    conn.close()
    bot.reply_to(message, "👋 Bienvenido. Usa /help para ver las funciones.")

@bot.message_handler(commands=['help'])
def help_command(message):
    texto = "🤖 **Manual:** /tik (catálogo), /mi_status (progreso)."
    if message.from_user.id == ADMIN_ID:
        texto += "\n🛠 **Admin:** /add_vip [ID] [DIAS], /add_apt [ID] [LIMITE]"
    bot.reply_to(message, texto, parse_mode='Markdown')

@bot.message_handler(commands=['mi_status'])
def mi_status(message):
    conn = sqlite3.connect('comunidad.db')
    user = conn.execute("SELECT tipo, limite_multimedia, hoy_enviado FROM usuarios WHERE user_id = ?", (message.from_user.id,)).fetchone()
    conn.close()
    if not user: return bot.reply_to(message, "⚠️ No registrado.")
    if user[0] == 'VIP': bot.reply_to(message, "👑 Eres VIP.")
    elif user[0] == 'APT': bot.reply_to(message, f"📊 **Progreso hoy:** {user[2]}/{user[1]} videos.")
    else: bot.reply_to(message, "👋 Contacta al admin para activar acceso.")

@bot.message_handler(commands=['add_vip', 'add_apt'])
def admin_commands(message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if message.text.startswith('/add_vip'):
        exp = (datetime.now() + timedelta(days=int(args[2]))).strftime('%Y-%m-%d')
        actualizar_usuario(int(args[1]), 'VIP', 0, exp)
        bot.reply_to(message, f"✅ VIP asignado hasta {exp}")
    else:
        actualizar_usuario(int(args[1]), 'APT', int(args[2]), None)
        bot.reply_to(message, f"✅ APT asignado con límite {args[2]}")

# --- NAVEGACIÓN VIDEOS ---
@bot.message_handler(commands=['tik'])
def comando_tik(message):
    if not es_autorizado(message.from_user.id): return
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT file_id FROM videos").fetchall()
    conn.close()
    if not videos: return bot.reply_to(message, "No hay contenido.")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➡️", callback_data="nav_0"))
    bot.send_video(message.chat.id, videos[0][0], reply_markup=markup, caption=f"1/{len(videos)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('nav_'))
def navegacion(call):
    index = int(call.data.split('_')[1])
    conn = sqlite3.connect('comunidad.db')
    videos = conn.execute("SELECT file_id FROM videos").fetchall()
    conn.close()
    
    if 0 <= index < len(videos):
        markup = types.InlineKeyboardMarkup()
        if index > 0: markup.add(types.InlineKeyboardButton("⬅️", callback_data=f"nav_{index-1}"))
        if index < len(videos) - 1: markup.add(types.InlineKeyboardButton("➡️", callback_data=f"nav_{index+1}"))
        
        bot.edit_message_media(media=types.InputMediaVideo(videos[index][0]), chat_id=call.message.chat.id, 
                               message_id=call.message.message_id, reply_markup=markup)

# --- MANEJADOR MULTIMEDIA ---
@bot.message_handler(content_types=['video'])
def recibir_multimedia(message):
    if message.chat.id == GRUPO_ID: return
    
    conn = sqlite3.connect('comunidad.db')
    # Verificar límite antes de guardar
    user = conn.execute("SELECT tipo, limite_multimedia, hoy_enviado FROM usuarios WHERE user_id = ?", (message.from_user.id,)).fetchone()
    
    if user and user[0] == 'APT':
        if user[2] >= user[1]:
            conn.close()
            return bot.reply_to(message, "❌ Límite diario alcanzado.")
        
        # Registrar aporte
        conn.execute("INSERT INTO videos (file_id) VALUES (?)", (message.video.file_id,))
        conn.execute("UPDATE usuarios SET hoy_enviado = hoy_enviado + 1 WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
    else:
        conn.execute("INSERT INTO videos (file_id) VALUES (?)", (message.video.file_id,))
        conn.commit()
    
    # Reenvío a comunidad
    usuarios = conn.execute("SELECT user_id FROM usuarios WHERE tipo IN ('VIP', 'APT')").fetchall()
    conn.close()
    for u in usuarios:
        if u[0] != message.from_user.id:
            try: bot.copy_message(u[0], message.chat.id, message.message_id)
            except: pass

if __name__ == "__main__":
    bot.remove_webhook()
    print("Bot activo y escuchando...")
    bot.infinity_polling(skip_pending=True)