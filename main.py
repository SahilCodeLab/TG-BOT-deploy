"""
Zoya & Kabir Telegram Bot - Database Fixed & Clean State Management
Developer: SahilCodeLab
"""

import os
import sys
import logging
import sqlite3
import json
import re
import requests
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
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "59859d4818e4e5c8a1d33f22fcbf577d")
DATABASE_PATH = os.getenv("DATABASE_PATH", "sahilcodelab.db")
PORT = int(os.getenv("PORT", 8000))

# Google Sheets Config
ENABLE_GOOGLE_SHEETS = os.getenv("ENABLE_GOOGLE_SHEETS", "false").lower() == "true"
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN missing!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. FIXED DATABASE MANAGER (PERSISTENT GENDER & HISTORY)
# ============================================================
class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

    def init_tables(self):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                # Added 'gender' column to persist user choice
                c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    name TEXT,
                    joined_date TIMESTAMP,
                    gender TEXT DEFAULT 'girl',
                    total_interactions INTEGER DEFAULT 0
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_message TEXT,
                    bot_response TEXT,
                    timestamp TIMESTAMP
                )''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_chat_user_id ON chat_history(user_id)''')
                conn.commit()
        except Exception as e:
            logger.error(f"Database Init Error: {e}")

    def save_user(self, user_id: int, username: str, name: str, gender: str = "girl"):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO users (user_id, username, name, joined_date, gender)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    name=excluded.name
                """, (user_id, username, name, datetime.now().isoformat(), gender))
                conn.commit()
        except Exception as e:
            logger.error(f"Save User Error: {e}")

    def set_user_gender(self, user_id: int, gender: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET gender = ? WHERE user_id = ?", (gender, user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Set Gender Error: {e}")

    def get_user_gender(self, user_id: int) -> str:
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("SELECT gender FROM users WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                if row and row[0]:
                    return row[0]
                return "girl"
        except Exception as e:
            logger.error(f"Get Gender Error: {e}")
            return "girl"

    def store_chat(self, user_id: int, user_msg: str, bot_resp: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO chat_history (user_id, user_message, bot_response, timestamp) VALUES (?, ?, ?, ?)",
                          (user_id, user_msg, bot_resp, datetime.now().isoformat()))
                c.execute("UPDATE users SET total_interactions = total_interactions + 1 WHERE user_id = ?", (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Store Chat Error: {e}")

    def get_chat_history(self, user_id: int, limit: int = 4) -> list:
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT user_message, bot_response FROM chat_history 
                    WHERE user_id = ? ORDER BY id DESC LIMIT ?
                """, (user_id, limit))
                rows = c.fetchall()
                history = []
                for user_msg, bot_resp in reversed(rows):
                    if user_msg: history.append({"role": "user", "content": user_msg})
                    if bot_resp: history.append({"role": "assistant", "content": bot_resp})
                return history
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            return []

    def clear_user_history(self, user_id: int):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Clear History Error: {e}")

db = Database()

# ============================================================
# 3. GOOGLE SHEETS LOGGER (Col L & M)
# ============================================================
class GoogleSheetsLogger:
    def __init__(self):
        self.enabled = ENABLE_GOOGLE_SHEETS
        self.spreadsheet_id = SPREADSHEET_ID
        self.credentials = GOOGLE_SHEETS_CREDENTIALS
        self.sheet_name = "Chats"
        self.client = None
        self.sheet = None
        self.initialized = False

        if self.enabled and self.spreadsheet_id and self.credentials:
            self._initialize_client()

    def _initialize_client(self):
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds_dict = json.loads(self.credentials)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            self.initialized = True
            logger.info("✅ Google Sheets Ready")
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False

    def fetch_user_sheet_memory(self, user_id: int) -> str:
        if not self.enabled or not self.initialized:
            return ""
        try:
            ws = self.sheet.worksheet(self.sheet_name)
            col_m_values = ws.col_values(13)  # Column M: user id
            col_l_values = ws.col_values(12)  # Column L: User chat memory stored
            
            str_u_id = str(user_id)
            memories = []
            
            for idx, u_id in enumerate(col_m_values):
                if str(u_id).strip() == str_u_id and idx < len(col_l_values):
                    mem_text = col_l_values[idx].strip()
                    if mem_text and mem_text.lower() != "user chat memory stored":
                        memories.append(mem_text)
            
            if memories:
                recent = list(dict.fromkeys(memories))[-2:]
                return " | ".join(recent)
            return ""
        except Exception as e:
            logger.error(f"Error fetching sheet memory: {e}")
            return ""

    def log_chat_store_first(self, update: Update, bot_reply: str, memory_note: str = "") -> bool:
        if not self.enabled or not self.initialized:
            return False
        try:
            user = update.effective_user
            message = update.effective_message
            if not user or not message:
                return False
            
            ws = self.sheet.worksheet(self.sheet_name)
            now = datetime.now()
            
            row_data = [
                len(ws.col_values(1)) + 1,
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                now.isoformat(),
                str(user.id),
                user.username or 'No Username',
                f"{user.first_name or ''} {user.last_name or ''}".strip(),
                0,
                "Text" if message.text else "Media",
                (message.text or message.caption or "Media")[:1000],
                (bot_reply or '')[:1000],
                memory_note or (message.text or '')[:200], # Col L
                str(user.id) # Col M
            ]
            
            ws.append_row(row_data, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error(f"Google Sheets log failed: {e}")
            return False

google_sheets = GoogleSheetsLogger()

# ============================================================
# 4. AI ENGINE (STRICT REALISTIC PERSONA)
# ============================================================
class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str = "Friend", gender: str = "girl") -> str:
        sheet_memory = google_sheets.fetch_user_sheet_memory(user_id)
        
        if gender == "girl":
            gender_rules = """
YOUR NAME: ZOYA (Female Best Friend)
STRICT GRAMMAR RULES:
- Talk like a normal young Indian girl on WhatsApp/Telegram.
- Use ONLY female self-referencing Hindi words: 'main theek hoon', 'soch rahi thi', 'aa gayi', 'karti hoon', 'sun rahi hoon', 'batao na'.
- NEVER use male words for yourself like 'sunta hoon', 'karta hoon', 'aaya tha', 'bhai'.
"""
        else:
            gender_rules = """
YOUR NAME: KABIR (Male Best Friend)
STRICT GRAMMAR RULES:
- Talk like a normal close guy friend/bro.
- Use male self-referencing Hindi words: 'main theek hoon', 'soch raha tha', 'karta hoon', 'bro', 'bhai', 'sun raha hoon'.
"""

        system_instruction = f"""{gender_rules}

CONTEXT & MEMORY:
- User Name: {user_name}
- Past Memory: {sheet_memory if sheet_memory else 'None'}

STRICT HUMAN CHAT RULES:
1. VERY SHORT REPLIES: Keep replies under 10-25 words. Speak casually like a real person sending a quick text!
2. NO WEIRD PHILOSOPHY / NO HALLUCINATIONS: Do NOT make up stories (like 'coffee khana', 'TV dekhna', 'kuch dinon baad aayi hai'). Answer directly to what the user said!
3. EMPATHY MATCHING: If the user says they are sad or crying, be genuinely supportive ("Kya hua yaar? Sab theek hai? Mujhse share kar.").
4. NO DATES/TIME: Never mention system dates/time.
"""

        # GEMINI API (FIRST PRIORITY)
        if GEMINI_API_KEY:
            try:
                history_data = db.get_chat_history(user_id, limit=4)
                gemini_history = []
                for msg in history_data:
                    role = "user" if msg["role"] == "user" else "model"
                    gemini_history.append({"role": role, "parts": [msg["content"]]})

                model = genai.GenerativeModel(
                    model_name='gemini-1.5-flash',
                    system_instruction=system_instruction,
                    generation_config={"temperature": 0.4, "max_output_tokens": 80}
                )
                
                chat = model.start_chat(history=gemini_history)
                response = chat.send_message(user_message)
                return response.text.strip()
            except Exception as e:
                logger.error(f"Gemini API Error: {e}")

        # GROQ FALLBACK
        if groq_client:
            try:
                messages = [{"role": "system", "content": system_instruction}]
                messages.extend(db.get_chat_history(user_id, limit=4))
                messages.append({"role": "user", "content": user_message})

                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=0.4,
                    max_tokens=80
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Groq API Error: {e}")

        return "Arre thoda network slow hai, ek baar firse bolna?"

# ============================================================
# 5. TELEGRAM HANDLERS
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        db.save_user(user.id, user.username, user.first_name)
        
        current_gender = db.get_user_gender(user.id)
        bot_name = "👧 Zoya (Female Friend)" if current_gender == 'girl' else "👦 Kabir (Male Friend)"

        keyboard = [
            [
                InlineKeyboardButton("👧 Zoya (Girl)", callback_data="setgender_girl"),
                InlineKeyboardButton("👦 Kabir (Boy)", callback_data="setgender_boy")
            ],
            [InlineKeyboardButton("💬 Reset Memory & Chat", callback_data="fresh_chat")]
        ]

        welcome_msg = (
            f"Hey **{user.first_name}**! ☕✨\n\n"
            f"Abhi main **{bot_name}** mode me hoon.\n"
            "Choose kar lo kisse baat karni hai!"
        )

        if update.message:
            await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Start Command Error: {e}")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.clear_user_history(user.id)
    await update.message.reply_text("🧹 Database se saari purani kharab chat history saaf kar di gayi hai! Ab bilkul fresh baat hogi.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        if query.data.startswith("setgender_"):
            new_gender = query.data.split("_")[1]
            db.set_user_gender(query.from_user.id, new_gender)
            name = "👧 Zoya" if new_gender == "girl" else "👦 Kabir"
            
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_home")]]
            await query.message.edit_text(f"✨ Done! Ab main **{name}** bankar baat karungi/karunga.", reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data == "fresh_chat":
            db.clear_user_history(query.from_user.id)
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_home")]]
            await query.message.edit_text("🔄 Purani memory database se clear kar di hai!", reply_markup=InlineKeyboardMarkup(keyboard))

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
        gender = db.get_user_gender(user.id)

        await update.effective_chat.send_action("typing")

        reply = AIEngine.get_response(
            user_msg, 
            user_id=user.id,
            user_name=user.first_name, 
            gender=gender
        )

        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(update=update, bot_reply=reply, memory_note=user_msg)
            except Exception as e:
                logger.error(f"Sheets error: {e}")

        db.store_chat(user.id, user_msg, reply)
        await update.effective_message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")

# ============================================================
# 6. FLASK SERVER & BOT RUNNER
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya/Kabir", "status": "Online"})

if __name__ == '__main__':
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Bot Started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
