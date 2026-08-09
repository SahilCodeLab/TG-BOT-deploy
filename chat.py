"""
SahilCodeLab Pure AI Chatbot - Multi-Mood & Database Version
Brand: SahilCodeLab (sahilcodelab.vercel.app)
Contact Email: sahil.dev@gmail.com
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime
from threading import Thread
from fastapi import FastAPI
import uvicorn
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
# 2. DATABASE SETUP (Users, Moods & Chat Logs)
# ============================================================

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                mood TEXT DEFAULT 'casual',
                joined_date TIMESTAMP
            )''')
            c.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in c.fetchall()]
            if 'mood' not in columns:
                c.execute("ALTER TABLE users ADD COLUMN mood TEXT DEFAULT 'casual'")

            c.execute('''CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_message TEXT,
                bot_response TEXT,
                timestamp TIMESTAMP
            )''')
            conn.commit()

    def save_user(self, user_id: int, username: str, name: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR IGNORE INTO users (user_id, username, name, mood, joined_date)
                VALUES (?, ?, ?, 'casual', ?)
            """, (user_id, username, name, datetime.now().isoformat()))
            conn.commit()

    def get_user_mood(self, user_id: int) -> str:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT mood FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            return row["mood"] if row and row["mood"] else "casual"

    def set_user_mood(self, user_id: int, mood: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET mood = ? WHERE user_id = ?", (mood, user_id))
            conn.commit()

    def log_chat(self, user_id: int, user_msg: str, bot_resp: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO chat_logs (user_id, user_message, bot_response, timestamp) VALUES (?,?,?,?)",
                      (user_id, user_msg, bot_resp, datetime.now().isoformat()))
            conn.commit()

db = Database()

# ============================================================
# 3. MULTI-MOOD AI ENGINE
# ============================================================

class AIEngine:
    MOOD_PROMPTS = {
        "normal": (
            "You are a professional, direct, and efficient AI assistant created by Sahil Raza (SahilCodeLab). "
            "Keep responses clear, concise, and structured."
        ),
        "supportive": (
            "You are a warm, highly empathetic, encouraging, and supportive AI assistant created by Sahil Raza (SahilCodeLab). "
            "Validate user thoughts with genuine care, positivity, and warmth."
        ),
        "casual": (
            "You are a chill, super user-friendly AI buddy created by Sahil Raza (SahilCodeLab) chatting in natural Hinglish or English. "
            "Talk like a relaxed friend, without corporate robot talk."
        ),
        "geek": (
            "You are a hardcore tech expert and developer AI created by Sahil Raza (SahilCodeLab). "
            "Discuss software engineering, coding logic, and system architecture with precision."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "casual") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["casual"])
        
        system_prompt = f"""{mood_instruction}

--- DEVELOPER INFO ---
Brand Name: {BRAND_NAME}
Creator & Developer: {FOUNDER_NAME}
Portfolio Website: {BRAND_URL}
Contact Email: {CONTACT_EMAIL}

Current User's Name: {user_name}
--- RULES ---
- DO NOT treat random words as names or hallucinate false memory context.
- Keep responses conversational, natural, and directly helpful to what the user asks.
"""
        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt}, 
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7, 
                    max_tokens=500
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return f"Hello! I'm an AI assistant by {BRAND_NAME}."
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "Oops! Kuch technical issue hai, thodi der me try karo."

# ============================================================
# 4. TELEGRAM HANDLERS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)
    current_mood = db.get_user_mood(user.id)

    keyboard = [
        [InlineKeyboardButton("🎭 Change Chat Mood", callback_data="menu_mood")],
        [InlineKeyboardButton("🌐 Visit Portfolio", url=BRAND_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = (
        f"👋 Hello **{user.first_name}**!\n\n"
        f"I am your AI companion powered by **{BRAND_NAME}** (Developer: {FOUNDER_NAME}).\n\n"
        f"🧠 **Current Mood:** `{current_mood.upper()}`\n\n"
        "Kuch bhi pucho ya chat shuru karo!"
    )

    if update.message:
        await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "menu_mood":
        current_mood = db.get_user_mood(user_id)
        text = f"🎭 **Choose Chatbot Mood**\n\nCurrent Active Mood: `🔥 {current_mood.upper()}`\n\nSelect how you want me to chat with you:"
        keyboard = [
            [InlineKeyboardButton("💼 Normal / Professional", callback_data="setmood_normal")],
            [InlineKeyboardButton("🤗 Supportive & Empathetic", callback_data="setmood_supportive")],
            [InlineKeyboardButton("😎 Casual & Friendly", callback_data="setmood_casual")],
            [InlineKeyboardButton("⚡ Geek / Tech Expert", callback_data="setmood_geek")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_home")]
        ]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("setmood_"):
        new_mood = query.data.split("_")[1]
        db.set_user_mood(user_id, new_mood)
        text = f"✅ **Mood updated to `{new_mood.upper()}`!**\n\nAb batao, kya chal raha hai?"
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_home":
        await query.message.delete()
        await start_command(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    user = update.effective_user
    user_msg = update.effective_message.text

    current_mood = db.get_user_mood(user.id)

    await update.effective_chat.send_action("typing")
    reply = AIEngine.get_response(user_msg, user_name=user.first_name, mood=current_mood)

    # Save chat interaction in database
    db.log_chat(user.id, user_msg, reply)

    await update.effective_message.reply_text(reply)

# ============================================================
# 5. FASTAPI SERVER
# ============================================================

app = FastAPI(title=f"{BRAND_NAME} Pure Chat API", version="5.0")

@app.get("/")
def home():
    return {"brand": BRAND_NAME, "developer": FOUNDER_NAME, "status": "Online"}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def run_telegram_bot():
    try:
        app_bot = Application.builder().token(BOT_TOKEN).build()

        app_bot.add_handler(CommandHandler("start", start_command))
        app_bot.add_handler(CallbackQueryHandler(button_handler))
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info(f"✅ {BRAND_NAME} Pure Chat Bot started successfully...")
        app_bot.run_polling()
    except Exception as e:
        logger.error(f"Telegram Bot error: {e}")

# ============================================================
# 6. MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()

    uvicorn.run(app, host="0.0.0.0", port=PORT)
