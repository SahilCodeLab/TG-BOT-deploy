"""
SahilCodeLab Pure AI Chatbot - Original DB Structure & 2-Moods (English/Hinglish)
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
# 2. DATABASE SETUP (Original Schema: users & leads)
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
                joined_date TIMESTAMP
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_requested TEXT,
                budget TEXT,
                timestamp TIMESTAMP
            )''')
            conn.commit()

    def save_user(self, user_id: int, username: str, name: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR IGNORE INTO users (user_id, username, name, joined_date)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, name, datetime.now().isoformat()))
            conn.commit()

    def log_lead(self, user_id: int, service: str, budget: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO leads (user_id, service_requested, budget, timestamp) VALUES (?,?,?,?)",
                      (user_id, service, budget, datetime.now().isoformat()))
            conn.commit()

db = Database()

# ============================================================
# 3. 2-MOOD AI ENGINE (English & Hinglish)
# ============================================================

class AIEngine:
    MOOD_PROMPTS = {
        "english": (
            "You are a professional, clear, and friendly AI assistant created by Sahil Raza (SahilCodeLab). "
            "Always respond strictly in clear, professional English."
        ),
        "hinglish": (
            "You are a chill, user-friendly AI buddy created by Sahil Raza (SahilCodeLab). "
            "Talk in natural Hinglish (mix of Hindi and English) like a relaxed developer friend."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        system_prompt = f"""{mood_instruction}

--- DEVELOPER INFO ---
Brand Name: {BRAND_NAME}
Creator & Developer: {FOUNDER_NAME}
Portfolio Website: {BRAND_URL}
Contact Email: {CONTACT_EMAIL}

Current User's Name: {user_name}
--- RULES ---
- DO NOT treat random text words as names or hallucinate false memory context.
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
    
    if 'mood' not in context.user_data:
        context.user_data['mood'] = 'hinglish'
    current_mood = context.user_data['mood']

    keyboard = [
        [InlineKeyboardButton("🌐 Switch Chat Mood", callback_data="menu_mood")],
        [InlineKeyboardButton("🔗 Visit Portfolio", url=BRAND_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = (
        f"👋 Hello **{user.first_name}**!\n\n"
        f"I am your AI companion powered by **{BRAND_NAME}** (Developer: {FOUNDER_NAME}).\n\n"
        f"🧠 **Current Mode:** `{current_mood.upper()}`\n\n"
        "Kuch bhi pucho ya chat shuru karo!"
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
        text = f"🌐 **Choose Language / Chat Mode**\n\nCurrent Active Mode: `🔥 {current_mood.upper()}`\n\nSelect how you want me to talk with you:"
        keyboard = [
            [InlineKeyboardButton("🇮🇳 Hinglish Vibe", callback_data="setmood_hinglish")],
            [InlineKeyboardButton("🇬🇧 Pure English", callback_data="setmood_english")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_home")]
        ]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("setmood_"):
        new_mood = query.data.split("_")[1]
        context.user_data['mood'] = new_mood
        text = f"✅ **Mode updated to `{new_mood.upper()}`!**\n\nAb batao, kya chal raha hai?"
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

    if 'mood' not in context.user_data:
        context.user_data['mood'] = 'hinglish'
    current_mood = context.user_data['mood']

    await update.effective_chat.send_action("typing")
    reply = AIEngine.get_response(user_msg, user_name=user.first_name, mood=current_mood)

    await update.effective_message.reply_text(reply)

# ============================================================
# 5. FASTAPI SERVER
# ============================================================

app = FastAPI(title=f"{BRAND_NAME} 2-Mood Chat API", version="5.2")

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

        logger.info(f"✅ {BRAND_NAME} Bot started successfully...")
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
