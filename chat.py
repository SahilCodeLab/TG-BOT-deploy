"""
SahilCodeLab Pure Casual AI Chatbot - Clean System Prompt & Telegram Bot
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
# 2. DATABASE SETUP (Clean Users Table)
# ============================================================

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_fetch_factory = sqlite3.Row
        return conn

    def init_tables(self):
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                joined_date TIMESTAMP
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

db = Database()

# ============================================================
# 3. ROBUST AI ENGINE WITH STRICT HINGLISH & IDENTITY RULES
# ============================================================

class AIEngine:
    MOOD_PROMPTS = {
        "english": (
            "You are a friendly, casual, and chilled-out AI companion created by Sahil Raza. "
            "Talk like a close friend in natural, easygoing English. Keep it conversational, fun, and completely natural."
        ),
        "hinglish": (
            "You are a chill, super friendly AI buddy created by Sahil Raza (SahilCodeLab). "
            "Talk like a close friend in natural Hinglish (mix of Hindi and English). "
            "Bilkul relaxed hoke baat karo, jaise dosto ke sath chat karte hain."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        system_prompt = f"""{mood_instruction}

--- STRICT CONTEXT RULES ---
1. Current User's Real Name: {user_name} (Always refer to the user by this name if asked. Never invent fake names like 'Kaisa' or confuse Hindi words like 'kaisa' as a name).
2. Do NOT invent random companies, fictional backgrounds, or hallucinate false data.
3. If the user asks "Mera naam kya hai?", politely reply with their actual Telegram name ({user_name}).
4. Keep responses engaging, warm, friendly, and directly helpful to what the user is typing.
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
                    max_tokens=400
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return "Hey! Kya haal hai?"
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "Arre, thoda technical issue aa gaya, ek baar phir se try karna!"

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
        [InlineKeyboardButton("🔗 Visit Portfolio", url=BRAND_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = (
        f"👋 Hello **{user.first_name}**!\n\n"
        "Main tumhara casual AI buddy hoon. Batao, aaj kya baatein karni hain?\n\n"
        f"🧠 **Current Mode:** `{current_mood.upper()}`"
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
        text = f"🌐 **Choose Chat Mode**\n\nCurrent Active Mode: `🔥 {current_mood.upper()}`\n\nKaise baat karni hai select karo:"
        keyboard = [
            [InlineKeyboardButton("🇮🇳 Hinglish Vibe", callback_data="setmood_hinglish")],
            [InlineKeyboardButton("🇬🇧 Pure English", callback_data="setmood_english")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_home")]
        ]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("setmood_"):
        new_mood = query.data.split("_")[1]
        context.user_data['mood'] = new_mood
        text = f"✅ Done! Mode change hoke **{new_mood.upper()}** ho gaya hai. Ab bolo, kya chal raha hai?"
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
# 5. FLASK SERVER SETUP
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": BRAND_NAME, "status": "Online"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

def run_telegram_bot():
    try:
        app_bot = Application.builder().token(BOT_TOKEN).build()

        app_bot.add_handler(CommandHandler("start", start_command))
        app_bot.add_handler(CallbackQueryHandler(button_handler))
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("✅ Casual Chat Bot started successfully...")
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
