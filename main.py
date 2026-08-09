"""
Zoya Bot - Tension Relief & Casual Companion (Verified & Fault-Tolerant)
Brand: SahilCodeLab (sahilcodelab.vercel.app)
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
# 1. CONFIGURATION & ENVIRONMENT CHECK
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "sahilcodelab.db")
PORT = int(os.getenv("PORT", 8000))

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN is missing in environment variables!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 2. BULLETPROOF DATABASE MANAGER
# ============================================================

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

    def init_tables(self):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    name TEXT,
                    joined_date TIMESTAMP
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_message TEXT,
                    bot_response TEXT,
                    timestamp TIMESTAMP
                )''')
                conn.commit()
        except Exception as e:
            logger.error(f"Database Init Error: {e}")

    def save_user(self, user_id: int, username: str, name: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT OR IGNORE INTO users (user_id, username, name, joined_date)
                    VALUES (?, ?, ?, ?)
                """, (user_id, username, name, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Save User Error: {e}")

    def store_chat(self, user_id: int, user_msg: str, bot_resp: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO chat_history (user_id, user_message, bot_response, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (user_id, user_msg, bot_resp, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Store Chat Error: {e}")

db = Database()

# ============================================================
# 3. ROBUST AI ENGINE (Zoya Persona)
# ============================================================

class AIEngine:
    MOOD_PROMPTS = {
        "english": (
            "You are Zoya, a warm, caring, and deeply supportive close friend. Your sole purpose is to help the user "
            "relieve tension, destress, pass time comfortably, and talk about anything they feel like—movies, life, "
            "hobbies, or just random casual thoughts. Be extremely friendly, empathetic, and comforting."
        ),
        "hinglish": (
            "Tu Zoya hai, ek bohot hi accha, samajhdar aur kareebi dost. Tera maqsad user ka stress aur tension door karna, "
            "unke sath time spend karna aur chill baatein karna hai. Koi kaam, project ya corporate baatein mat karna. "
            "Bas dosto ki tarah pyaar se, mazaak-masti me, aur comforting Hinglish me baat karna."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        system_prompt = f"""{mood_instruction}

--- STRICT RULES ---
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
                    max_tokens=400
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return "Hey! Batao kya chal raha hai, main sun raha hoon."
        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return "Arre, thoda network issue ho gaya lagta hai. Ek baar phir se bolo na!"

# ============================================================
# 4. TELEGRAM HANDLERS & CALLBACKS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        db.save_user(user.id, user.username, user.first_name)
        
        if 'mood' not in context.user_data:
            context.user_data['mood'] = 'hinglish'
        current_mood = context.user_data['mood']

        keyboard = [
            [InlineKeyboardButton("🌐 Switch Language / Vibe", callback_data="menu_mood")],
            [InlineKeyboardButton("💬 Fresh Chat", callback_data="fresh_chat")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_msg = (
            f"Hey **{user.first_name}**! ☕✨ Main Zoya hoon.\n\n"
            "Yahan sab tension bhool jao. Chahe din kaisa bhi raha ho, aram se baitho aur jo dil me aaye woh baatein karo. "
            "Main yahin hoon sunne ke liye!\n\n"
            f"🧠 **Current Vibe:** `{current_mood.upper()}`"
        )

        if update.message:
            await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Start Command Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Button Handler Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_message or not update.effective_message.text:
            return
        user = update.effective_user
        user_msg = update.effective_message.text

        if 'mood' not in context.user_data:
            context.user_data['mood'] = 'hinglish'
        current_mood = context.user_data['mood']

        await update.effective_chat.send_action("typing")
        reply = AIEngine.get_response(user_msg, user_name=user.first_name, mood=current_mood)

        db.store_chat(user.id, user_msg, reply)
        await update.effective_message.reply_text(reply)
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")
        if update.effective_message:
            await update.effective_message.reply_text("Arre, thoda sa glitch aa gaya tha! Dubara kehna kya bol rahe the?")

# ============================================================
# 5. FLASK WEB SERVER (Health Check for Cloud Hosting)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya", "status": "Online"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ============================================================
# 6. SECURE ENTRY POINT
# ============================================================

if __name__ == '__main__':
    # 1. Start Flask in a background daemon thread
    flask_thread = Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    logger.info("🌐 Flask web server running in background thread.")

    # 2. Build Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Zoya Bot polling starting in main thread...")
    
    # 3. Run Telegram Polling in the main thread (owns event loop cleanly)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
