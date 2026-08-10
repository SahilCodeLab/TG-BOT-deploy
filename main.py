"""
Zoya & Kabir Bot - Persona & Sheet Memory Enabled
Brand: SahilCodeLab (sahilcodelab.vercel.app)
"""

import os
import sys
import logging
import sqlite3
import json
import time
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
GOOGLE_SHEETS_RETRY = int(os.getenv("GOOGLE_SHEETS_RETRY", 3))

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN is missing in environment variables!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. DATABASE MANAGER
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
                    joined_date TIMESTAMP,
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

    def save_user(self, user_id: int, username: str, name: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, 0)", 
                          (user_id, username, name, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Save User Error: {e}")

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

    def get_chat_history(self, user_id: int, limit: int = 10) -> list:
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
            logger.error(f"Error fetching SQLite history: {e}")
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
# 3. GOOGLE SHEETS LOGGER & MEMORY FETCHER (Col L & M)
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
            self._ensure_chat_sheet()
            self.initialized = True
            logger.info("✅ Google Sheets initialized with Memory Support")
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False

    def _ensure_chat_sheet(self):
        try:
            existing = [ws.title for ws in self.sheet.worksheets()]
            if self.sheet_name not in existing:
                ws = self.sheet.add_worksheet(title=self.sheet_name, rows=100000, cols=15)
                headers = [
                    "S.No", "Date", "Time", "Timestamp", "User ID",
                    "Username", "Full Name", "Message Count",
                    "Message Type", "User Message", "Bot Reply",
                    "User chat memory stored", "user id"
                ]
                ws.append_row(headers)
                ws.freeze(rows=1)
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")

    def fetch_user_sheet_memory(self, user_id: int) -> str:
        """Fetch past stored memory for user from Column L (12) using User ID from Col M (13)"""
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
                # Get last 3 unique memories
                recent_memories = list(dict.fromkeys(memories))[-3:]
                return " | ".join(recent_memories)
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
            logger.error(f"❌ Google Sheets log failed: {e}")
            return False

google_sheets = GoogleSheetsLogger()

# ============================================================
# 4. WEATHER SERVICE
# ============================================================
class WeatherService:
    @staticmethod
    def extract_city(text: str) -> str:
        text_clean = re.sub(r'[^\w\s]', '', text.lower())
        stop_words = {"weather", "mausam", "kaisa", "hai", "batao", "bata", "kya", "aaj", "in", "ka", "ki", "ko", "me", "main", "par", "today", "now"}
        words = text_clean.split()
        filtered = [w for w in words if w not in stop_words]
        return " ".join(filtered).title() if filtered else ""

    @classmethod
    def get_weather(cls, user_msg: str) -> str:
        if not WEATHER_API_KEY: return ""
        city_name = cls.extract_city(user_msg)
        if not city_name: return "City name missing hai."

        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return f"LIVE WEATHER: {data['name']}: {round(data['main']['temp'])}°C, {data['weather'][0]['description'].title()}."
            return "Weather fetch nahi ho paya."
        except Exception:
            return ""

# ============================================================
# 5. AI ENGINE (Gemini 1st Priority + Boy/Girl Persona + Sheet Memory)
# ============================================================
class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str = "User", gender: str = "girl", weather_context: str = "") -> str:
        # Fetch Memory from Google Sheets (Col L & M)
        sheet_memory = google_sheets.fetch_user_sheet_memory(user_id)
        
        # Persona Config
        if gender == "girl":
            bot_identity = (
                "Tu ZOYA hai - ek bohot pyaari, caring, chill ladki dost. "
                "Tu ladkiyo waali language use karegi (jaise: 'mai soch rahi hoon', 'karungi', 'bol na', 'pagal hai kya', etc.)."
            )
        else:
            bot_identity = (
                "Tu KABIR hai - ek bohot cool, supportive aur mast ladka dost. "
                "Tu ladko waali language use karega (jaise: 'mai soch raha hoon', 'karunga', 'bhai', 'bolna bro', etc.)."
            )

        system_prompt = f"""{bot_identity}

--- MEMORY & CONTEXT ---
• User Name: {user_name}
• Past Sheet Memories (Jo is user ne pehle bataya tha): {sheet_memory or 'Nahi hai abhi tak'}

--- CHAT RULES ---
1. REALISTIC & NATURAL: Bilkul real human dost ki tarah baat kar. Har baat me "aaj ka date time ye hai" APNE MAN SE BILKUL MAT BOLO jab tak user khud na puche.
2. SHORT & CASUAL: Maximum 30-50 words me reply do. Formal ya AI jaisa jawab mat dena.
3. MEMORY RECALL: Agar past sheet memory relevant ho, toh casually use karo taaki user ko lage ki tujhe yaad hai.
4. Serious questions par thoda bada reply de sakti/sakta hai.
"""

        if weather_context:
            system_prompt += f"\n--- LIVE WEATHER DATA ---\n{weather_context}\n"

        # 1st Priority: GEMINI API
        if GEMINI_API_KEY:
            try:
                history_data = db.get_chat_history(user_id, limit=8)
                gemini_history = []
                for msg in history_data:
                    role = "user" if msg["role"] == "user" else "model"
                    gemini_history.append({"role": role, "parts": [msg["content"]]})

                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                chat = model.start_chat(history=gemini_history)
                resp = chat.send_message(user_message)
                return resp.text.strip()
            except Exception as e:
                logger.error(f"Gemini API Error, switching to Fallback Groq: {e}")

        # 2nd Priority: GROQ FALLBACK
        if GROQ_API_KEY:
            try:
                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(db.get_chat_history(user_id, limit=8))
                messages.append({"role": "user", "content": user_message})

                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=300
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Groq API Error: {e}")

        return "Arre thoda network glitch hai, fir se bol na!"

# ============================================================
# 6. TELEGRAM HANDLERS & PERSONA SELECTION
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        db.save_user(user.id, user.username, user.first_name)
        
        if 'gender' not in context.user_data:
            context.user_data['gender'] = 'girl'

        current_gender = context.user_data['gender']
        bot_name = "👧 Zoya (Female Friend)" if current_gender == 'girl' else "👦 Kabir (Male Friend)"

        keyboard = [
            [
                InlineKeyboardButton("👧 Zoya (Girl)", callback_data="setgender_girl"),
                InlineKeyboardButton("👦 Kabir (Boy)", callback_data="setgender_boy")
            ],
            [InlineKeyboardButton("💬 Fresh Chat", callback_data="fresh_chat")]
        ]

        welcome_msg = (
            f"Hey **{user.first_name}**! ☕✨\n\n"
            f"Abhi main **{bot_name}** mood me hoon.\n"
            "Tum apne hisab se choose kar sakte ho ki **Zoya (Girl)** se baat karni hai ya **Kabir (Boy)** se!\n\n"
            "Batao kya chal raha hai?"
        )

        if update.message:
            await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Start Command Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        if query.data.startswith("setgender_"):
            new_gender = query.data.split("_")[1]
            context.user_data['gender'] = new_gender
            name = "👧 Zoya" if new_gender == "girl" else "👦 Kabir"
            
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_home")]]
            await query.message.edit_text(f"✨ Done! Ab se tum **{name}** se baat kar rahe ho.", reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data == "fresh_chat":
            db.clear_user_history(query.from_user.id)
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_home")]]
            await query.message.edit_text("🔄 Purani baatein clear! Naye siri se baat karte hain.", reply_markup=InlineKeyboardMarkup(keyboard))

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

        if 'gender' not in context.user_data:
            context.user_data['gender'] = 'girl'
        gender = context.user_data['gender']

        await update.effective_chat.send_action("typing")
        
        weather_info = ""
        if any(w in user_msg.lower() for w in ["weather", "mausam", "temperature", "temp", "barish", "rain"]):
            weather_info = WeatherService.get_weather(user_msg)

        reply = AIEngine.get_response(
            user_msg, 
            user_id=user.id,
            user_name=user.first_name, 
            gender=gender,
            weather_context=weather_info
        )

        # Store into Google Sheets (Writes user memory into Col L and user id into Col M)
        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(update=update, bot_reply=reply, memory_note=user_msg)
            except Exception as e:
                logger.error(f"Google Sheets log error: {e}")

        db.store_chat(user.id, user_msg, reply)
        await update.effective_message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")

# ============================================================
# 7. FLASK & MAIN ENTRY POINT
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya/Kabir", "status": "Online"})

if __name__ == '__main__':
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Bot Started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
