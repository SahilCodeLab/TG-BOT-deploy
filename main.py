"""
Zoya Bot - Tension Relief & Casual Companion (Short & Natural Responses)
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
# 2. TIME HELPER (Internal System Awareness Only)
# ============================================================

class TimeHelper:
    @staticmethod
    def get_current_time_info() -> dict:
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 12:
            period = "Subah (Morning)"
        elif 12 <= hour < 16:
            period = "Dopehar (Afternoon)"
        elif 16 <= hour < 20:
            period = "Shaam (Evening)"
        else:
            period = "Raat (Night)"

        return {
            "date": now.strftime("%d %B %Y"),
            "time_12h": now.strftime("%I:%M %p"),
            "day": now.strftime("%A"),
            "period": period
        }

# ============================================================
# 3. WEATHER SERVICE
# ============================================================

class WeatherService:
    @staticmethod
    def extract_city(text: str) -> str:
        text_clean = re.sub(r'[^\w\s]', '', text.lower())
        stop_words = {
            "weather", "mausam", "kaisa", "hai", "batao", "bata", "kya", "aaj",
            "in", "ka", "ki", "ko", "me", "main", "par", "today", "now", "tell",
            "me", "about", "the", "what", "is", "like", "temperature", "temp",
            "rain", "barish", "hogi", "hoga", "zoya", "check", "please"
        }
        words = text_clean.split()
        filtered = [w for w in words if w not in stop_words]
        return " ".join(filtered).title() if filtered else ""

    @classmethod
    def get_weather(cls, user_msg: str) -> str:
        if not WEATHER_API_KEY:
            return "Weather API Key missing hai."

        city_name = cls.extract_city(user_msg)
        if not city_name:
            return "Consi city ka weather poocha? Naam clearly batao."

        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                temp = round(data['main']['temp'])
                feels_like = round(data['main']['feels_like'])
                desc = data['weather'][0]['description']
                city = data['name']
                country = data['sys']['country']
                
                return f"EXACT LIVE DATA: {city}, {country}: {temp}°C (Feels like {feels_like}°C), {desc.title()}."
            elif res.status_code == 404:
                return f"'{city_name}' naam ki city nahi mili."
            else:
                return "Weather fetch nahi ho paya."
        except Exception as e:
            logger.error(f"Weather API Error: {e}")
            return "Weather service down hai."

# ============================================================
# 4. GOOGLE SHEETS LOGGER (Store-First)
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
        self._serial_cache = None

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
            self._refresh_serial_cache()
            self.initialized = True
            self.enabled = True
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False

    def _ensure_chat_sheet(self):
        try:
            existing = [ws.title for ws in self.sheet.worksheets()]
            if self.sheet_name not in existing:
                ws = self.sheet.add_worksheet(title=self.sheet_name, rows=100000, cols=11)
                headers = [
                    "S.No", "Date", "Time", "Timestamp", "User ID",
                    "Username", "Full Name", "Message Count",
                    "Message Type", "User Message", "Bot Reply"
                ]
                for col_idx, header in enumerate(headers, start=1):
                    ws.update_cell(1, col_idx, header)
                ws.freeze(rows=1)
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")

    def _refresh_serial_cache(self):
        try:
            ws = self.sheet.worksheet(self.sheet_name)
            total_rows = ws.row_count
            if total_rows <= 1:
                self._serial_cache = 1
            else:
                last_row = ws.row_values(total_rows)
                if last_row and last_row[0] and str(last_row[0]).isdigit():
                    self._serial_cache = int(last_row[0]) + 1
                else:
                    self._serial_cache = total_rows - 1
        except Exception as e:
            self._serial_cache = 1

    def _get_next_serial(self, ws) -> int:
        if self._serial_cache is None:
            self._refresh_serial_cache()
        self._serial_cache += 1
        return self._serial_cache

    def log_chat_store_first(self, update: Update, bot_reply: str) -> bool:
        if not self.enabled or not self.initialized:
            return False
        try:
            user = update.effective_user
            message = update.effective_message
            if not user or not message:
                return False
            
            ws = self.sheet.worksheet(self.sheet_name)
            now = datetime.now()
            serial_no = self._get_next_serial(ws)
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username or "No Name"
            
            row_data = [
                serial_no, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                now.isoformat(), str(user.id), user.username or 'No Username',
                full_name, 0, "Text" if message.text else "Media",
                message.text or message.caption or "Media Message", bot_reply or ''
            ]
            
            for attempt in range(GOOGLE_SHEETS_RETRY):
                try:
                    ws.append_row(row_data, value_input_option='USER_ENTERED')
                    return True
                except Exception:
                    if attempt == GOOGLE_SHEETS_RETRY - 1:
                        raise
                    time.sleep(2 ** attempt)
            return False
        except Exception as e:
            logger.error(f"❌ Google Sheets log failed: {e}")
            return False

google_sheets = GoogleSheetsLogger()

# ============================================================
# 5. DATABASE MANAGER
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
                    user_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
                    joined_date TIMESTAMP, total_interactions INTEGER DEFAULT 0
                )''')
                c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                    user_message TEXT, bot_response TEXT, timestamp TIMESTAMP
                )''')
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

db = Database()

# ============================================================
# 6. AI ENGINE (Short, Natural & Friendly Persona)
# ============================================================

class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish", weather_context: str = "") -> str:
        time_info = TimeHelper.get_current_time_info()
        
        system_prompt = f"""Tu Zoya hai, ek bohot hi pyari, casual aur friendly dost.

--- INTERNAL CONTEXT (DO NOT SPAM USER WITH THIS) ---
• Time context for you: {time_info['period']} ({time_info['time_12h']}), {time_info['day']}, {time_info['date']}.
• User Name: {user_name}

--- STRICT CHAT RULES ---
1. SHORT & NATURAL REPLIES: Casual baaton me maximum 30-50 words me reply do. Bilkul human dost ki tarah natural baatein karo.
2. NO SPAMMING DATE/TIME: Bilkul zaroori na ho ya user ne na poocha ho tab tak "Aaj date ye hai, time ye hai" APNE MAN SE MAT BOLO. It is annoying.
3. EXCEPTIONS (SERIOUS QUESTIONS): Agar user koi serious, deep, problem-solving ya long topic par baat kare, tab detailed aur lamba reply do.
4. ACCURATE WEATHER: Agar weather data niche diya hai, toh exact temperature/condition natural tone me batao.
"""

        if weather_context:
            system_prompt += f"\n--- LIVE WEATHER DATA ---\n{weather_context}\n"

        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt}, 
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7, 
                    max_tokens=300
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return "Hey! Batao kya chal raha hai?"
        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return "Arre thoda network glitch aa gaya, phir se bolo?"

# ============================================================
# 7. TELEGRAM HANDLERS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        db.save_user(user.id, user.username, user.first_name)
        
        if 'mood' not in context.user_data:
            context.user_data['mood'] = 'hinglish'

        keyboard = [
            [InlineKeyboardButton("🌐 Switch Vibe", callback_data="menu_mood")],
            [InlineKeyboardButton("💬 Fresh Chat", callback_data="fresh_chat")]
        ]

        welcome_msg = (
            f"Hey **{user.first_name}**! ☕✨ Main Zoya hoon.\n\n"
            "Sab tension chhodo aur chill baatein karo. Weather poochna ho ya bas timepass karna ho, main yahin hoon!"
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

        if query.data == "menu_mood":
            keyboard = [
                [InlineKeyboardButton("🇮🇳 Hinglish Vibe", callback_data="setmood_hinglish")],
                [InlineKeyboardButton("🇬🇧 Pure English", callback_data="setmood_english")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_home")]
            ]
            await query.message.edit_text("🌐 **Choose Your Vibe:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("setmood_"):
            new_mood = query.data.split("_")[1]
            context.user_data['mood'] = new_mood
            await query.message.edit_text(f"✨ Vibe set to **{new_mood.upper()}**!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_home")]]))

        elif query.data == "fresh_chat":
            await query.message.edit_text("🔄 Naye siri se baat karte hain! Bolo kya scene hai?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_home")]]))

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
        
        weather_info = ""
        msg_lower = user_msg.lower()
        if any(w in msg_lower for w in ["weather", "mausam", "temperature", "temp", "barish", "rain"]):
            weather_info = WeatherService.get_weather(user_msg)

        reply = AIEngine.get_response(
            user_msg, 
            user_name=user.first_name, 
            mood=current_mood,
            weather_context=weather_info
        )

        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(update=update, bot_reply=reply)
            except Exception as e:
                logger.error(f"Google Sheets log error: {e}")

        db.store_chat(user.id, user_msg, reply)
        await update.effective_message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")

# ============================================================
# 8. FLASK & MAIN
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya", "status": "Online"})

if __name__ == '__main__':
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Zoya Bot started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
