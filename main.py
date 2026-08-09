"""
SahilCodeLab Final Tension Relief & Casual Chat Bot - Flask + Telegram Bot
Brand: SahilCodeLab (sahilcodelab.vercel.app)
Contact Email: sahil.dev@gmail.com
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime
from threading import Thread
from flask import Flask, jsonify
import google.generativeai as genai
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# ============================================================
# 1. CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "sahilcodelab.db")
PORT = int(os.getenv("PORT", 8000))

BRAND_NAME = "SahilCodeLab"
BRAND_URL = "https://sahilcodelab.vercel.app"
CONTACT_EMAIL = "sahil.dev@gmail.com"
FOUNDER_NAME = "Sahil Raza"

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Missing!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 2. DATABASE SETUP (Users & Chat Logs Store Feature)
# ============================================================

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

    def init_tables(self):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            c = conn.cursor()
            # Users table
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                joined_date TIMESTAMP
            )''')
            # Chat history store table
            c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_message TEXT,
                bot_response TEXT,
                timestamp TIMESTAMP
            )''')
            conn.commit()

    def save_user(self, user_id: int, username: str, name: str):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR IGNORE INTO users (user_id, username, name, joined_date)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, name, datetime.now().isoformat()))
            conn.commit()

    def store_chat(self, user_id: int, user_msg: str, bot_resp: str):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO chat_history (user_id, user_message, bot_response, timestamp)
                VALUES (?, ?, ?, ?)
            """, (user_id, user_msg, bot_resp, datetime.now().isoformat()))
            conn.commit()

db = Database()

# ============================================================
# 3. PURE TENSION RELIEF & CASUAL AI ENGINE
# ============================================================

class AIEngine:
    MOOD_PROMPTS = {
        "english": (
            "You are a warm, caring, and deeply supportive close friend. Your sole purpose is to help the user "
            "relieve tension, destress, pass time comfortably, and talk about anything they feel like—movies, life, "
            "hobbies, or just random casual thoughts. Be extremely friendly, empathetic, and comforting."
        ),
        "hinglish": (
            "Tu ek bohot hi accha, samajhdar aur kareebi dost hai. Tera maqsad user ka stress aur tension door karna, "
            "unke sath time spend karna aur chill baatein karna hai. Koi kaam, project ya corporate baatein mat karna. "
            "Bas dosto ki tarah pyaar se, mazaak-masti me, aur comforting Hinglish me baat karna."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        system_prompt = f"""{mood_instruction}

--- RULES ---
1. User's Name: {user_name}
2. NEVER talk about work, projects, businesses, or coding unless the user explicitly brings it up for fun.
3. If the user is stressed or tired, comfort them, listen to them patiently, and cheer them up.
4. Keep conversations light, engaging, deeply human, and warm.
"""
        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt}, 
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.8, 
                    max_tokens=500
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return "Hey! Batao kya chal raha hai, main sun raha hoon."
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "Arre, thoda network issue ho gaya lagta hai. Ek baar phir se bolo na!"

# ============================================================
# 4. TELEGRAM HANDLERS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)
    
    if 'mood' not in context.user_data:
        context.user_data['mood'] = 'hinglish'
    current_mood = context.user_data['mood']

    keyboard = [
        [InlineKeyboardButton("🌐 Switch Language / Mode", callback_data="menu_mood")],
        [InlineKeyboardButton("💬 Clear Mind / Fresh Chat", callback_data="fresh_chat")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = (
        f"Hey **{user.first_name}**! ☕✨\n\n"
        "Yahan sab tension bhool jao. Chahe din kaisa bhi raha ho, aram se baitho aur jo dil me aaye woh baatein karo. "
        "Main yahin hoon sunne ke liye!\n\n"
        f"🧠 **Current Vibe:** `{current_mood.upper()}`"
    )

    if update.message:
        await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if 'mood' not in context.user_data:
        context.user_data['mood'] = 'hinglish'

    if query.data == "menu_mood":
        current_mood = context.user_data['mood']
        text = f"🌐 **Choose Your Vibe**\n\nCurrent Mode: `🔥 {current_mood.upper()}`\n\nKaise baat karni hai select karo:"
        keyboard = [
            [InlineKeyboardButton("🇮🇳 Hinglish Vibe (Chill)", callback_data="setmood_hinglish")],
            [InlineKeyboardButton("🇬🇧 Pure English (Warm)", callback_data="setmood_english")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_home")]
        ]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("setmood_"):
        new_mood = query.data.split("_")[1]
        context.user_data['mood'] = new_mood
        text = f"✨ Done! Vibe set ho gayi **{new_mood.upper()}** par. Ab batao, kya chal raha hai dimag me?"
        keyboard = [[InlineKeyboardButton("🔙 Back to Home", callback_data="menu_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "fresh_chat":
        text = "🔄 Fresh slate! Purani baatein gayab, ab bilkul naye siri se chill baatein karte hain. Bolo kya sunaaoge?"
        keyboard = [[InlineKeyboardButton("🔙 Back to Home", callback_data="menu_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_home":
        await query.message.delete()
        await start_command(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    user = update.effective_user
    user_msg = update.effective_message.text

    if 'mood' not in context.user_data:
        context.user_data['mood'] = 'hinglish'
    current_mood = context.user_data['mood']

    await update.effective_chat.send_action("typing")
    reply = AIEngine.get_response(user_msg, user_name=user.first_name, mood=current_mood)

    # Store chat history in database securely
    db.store_chat(user.id, user_msg, reply)

    await update.effective_message.reply_text(reply)

# ============================================================
# 5. FLASK SERVER SETUP
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": BRAND_NAME, "purpose": "Tension Relief & Casual Companion", "status": "Online"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

def run_telegram_bot():
    try:
        app_bot = Application.builder().token(BOT_TOKEN).build()

        app_bot.add_handler(CommandHandler("start", start_command))
        app_bot.add_handler(CallbackQueryHandler(button_handler))
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("✨ Tension Relief & Casual Buddy Bot started successfully...")
        app_bot.run_polling()
    except Exception as e:
        logger.error(f"Telegram Bot error: {e}")

# ============================================================
# 6. MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()

    app.run(host="0.0.0.0", port=PORT)
