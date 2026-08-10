"""
Zoya Bot - Tension Relief & Casual Companion (Verified & Fault-Tolerant + Weather Support)
Brand: SahilCodeLab (sahilcodelab.vercel.app)

Features:
- Live Weather Integration (OpenWeatherMap)
- Google Sheets real-time logging (Store-First)
- SQLite backup
- Multi-language support (Hinglish/English)
- Interactive inline buttons
- Production-grade error handling
"""

import os
import sys
import logging
import sqlite3
import json
import time
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

# Google Sheets Configuration
ENABLE_GOOGLE_SHEETS = os.getenv("ENABLE_GOOGLE_SHEETS", "false").lower() == "true"
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEETS_RETRY = int(os.getenv("GOOGLE_SHEETS_RETRY", 3))

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN is missing in environment variables!", flush=True)
    sys.exit(1)

# Configure AI APIs
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
# 2. WEATHER SERVICE (OpenWeatherMap)
# ============================================================

class WeatherService:
    @staticmethod
    def get_weather(city_name: str) -> str:
        """Fetch current weather data for a given city"""
        if not WEATHER_API_KEY:
            return "Mujhe weather check karne ke liye API key nahi mili."
        
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                temp = data['main']['temp']
                feels_like = data['main']['feels_like']
                desc = data['weather'][0]['description']
                city = data['name']
                humidity = data['main']['humidity']
                
                return (
                    f"🌤 **Weather in {city}:**\n"
                    f"• Temperature: {temp}°C (Feels like {feels_like}°C)\n"
                    f"• Condition: {desc.capitalize()}\n"
                    f"• Humidity: {humidity}%"
                )
            elif res.status_code == 404:
                return f"Mujhe '{city_name}' naam ki koi city nahi mili. Ek baar spelling check karlo na!"
            else:
                return "Abhi weather data lane me thodi problem ho rahi hai."
        except Exception as e:
            logger.error(f"Weather API Error: {e}")
            return "Weather fetch karne me error aa gaya."

# ============================================================
# 3. GOOGLE SHEETS LOGGER (Store-First)
# ============================================================

class GoogleSheetsLogger:
    """Real-time Google Sheets logger with store-first architecture"""
    
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
        """Initialize Google Sheets client"""
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds_dict = json.loads(self.credentials)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            
            self._ensure_chat_sheet()
            self._refresh_serial_cache()
            
            self.initialized = True
            self.enabled = True
            logger.info("✅ Google Sheets logging enabled for Zoya Bot")
            
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False
            self.initialized = False

    def _ensure_chat_sheet(self):
        """Create Chats worksheet with headers if missing"""
        try:
            existing = [ws.title for ws in self.sheet.worksheets()]
            
            if self.sheet_name not in existing:
                ws = self.sheet.add_worksheet(title=self.sheet_name, rows=100000, cols=11)
                headers = [
                    "S.No", "Date", "Time", "Timestamp",
                    "User ID", "Username", "Full Name",
                    "Message Count", "Message Type",
                    "User Message", "Bot Reply"
                ]
                for col_idx, header in enumerate(headers, start=1):
                    ws.update_cell(1, col_idx, header)
                ws.freeze(rows=1)
                logger.info(f"📊 Created '{self.sheet_name}' worksheet")
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")

    def _refresh_serial_cache(self):
        """Refresh cached serial number"""
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
            logger.error(f"Error refreshing serial cache: {e}")
            self._serial_cache = 1

    def _get_next_serial(self, ws) -> int:
        """Get next serial number using cache"""
        if self._serial_cache is None:
            self._refresh_serial_cache()
        
        self._serial_cache += 1
        return self._serial_cache

    def _get_message_type(self, update: Update) -> str:
        """Detect message type"""
        message = update.effective_message
        if not message:
            return "Unknown"
        
        if message.text:
            return "Text"
        elif message.photo:
            return "Photo"
        elif message.video:
            return "Video"
        elif message.voice:
            return "Voice"
        elif message.audio:
            return "Audio"
        elif message.sticker:
            return "Sticker"
        elif message.animation:
            return "GIF"
        elif message.document:
            return "Document"
        elif message.location:
            return "Location"
        elif message.contact:
            return "Contact"
        else:
            return "Unknown"

    def _get_user_message_text(self, update: Update) -> str:
        """Extract user message text"""
        message = update.effective_message
        if not message:
            return ""
        
        if message.text:
            return message.text
        elif message.caption:
            return message.caption
        elif message.photo:
            return "📸 Photo"
        elif message.video:
            return "🎬 Video"
        elif message.voice:
            return "🎤 Voice Message"
        elif message.sticker:
            return "🎨 Sticker"
        else:
            return "📨 Media Message"

    def _get_full_name(self, user) -> str:
        """Get full name from user"""
        if not user:
            return "No Name"
        
        first_name = user.first_name or ''
        last_name = user.last_name or ''
        full_name = f"{first_name} {last_name}".strip()
        
        if full_name:
            return full_name
        elif user.username:
            return user.username
        else:
            return "No Name"

    def log_chat_store_first(self, update: Update, bot_reply: str) -> bool:
        """Log chat to Google Sheets (Store-First)"""
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
            
            message_count = 0
            try:
                db = Database()
                user_data = db.get_user(user.id)
                if user_data:
                    message_count = user_data.get('total_interactions', 0)
            except:
                pass
            
            row_data = [
                serial_no,
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                now.isoformat(),
                str(user.id),
                user.username or 'No Username',
                self._get_full_name(user),
                message_count,
                self._get_message_type(update),
                self._get_user_message_text(update),
                bot_reply or ''
            ]
            
            for attempt in range(GOOGLE_SHEETS_RETRY):
                try:
                    ws.append_row(row_data, value_input_option='USER_ENTERED')
                    logger.debug(f"📊 Google Sheets log: User {user.id}, Serial #{serial_no}")
                    return True
                except Exception as e:
                    if attempt == GOOGLE_SHEETS_RETRY - 1:
                        raise
                    time.sleep(2 ** attempt)
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Google Sheets log failed: {e}")
            return False

google_sheets = GoogleSheetsLogger()

# ============================================================
# 4. BULLETPROOF DATABASE MANAGER
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

    def get_user(self, user_id: int):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                if row:
                    return {
                        'user_id': row[0],
                        'username': row[1],
                        'name': row[2],
                        'joined_date': row[3],
                        'total_interactions': row[4]
                    }
                return None
        except Exception as e:
            logger.error(f"Get User Error: {e}")
            return None

    def store_chat(self, user_id: int, user_msg: str, bot_resp: str):
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO chat_history (user_id, user_message, bot_response, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (user_id, user_msg, bot_resp, datetime.now().isoformat()))
                c.execute("""
                    UPDATE users SET total_interactions = total_interactions + 1
                    WHERE user_id = ?
                """, (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Store Chat Error: {e}")

db = Database()

# ============================================================
# 5. ROBUST AI ENGINE (Zoya Persona)
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
    def get_response(user_message: str, user_name: str = "User", mood: str = "hinglish", weather_context: str = "") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        system_prompt = f"""{mood_instruction}

--- STRICT RULES ---
1. User's Name: {user_name}
2. NEVER talk about work, projects, businesses, or coding unless the user explicitly brings it up for fun.
3. If the user is stressed or tired, comfort them, listen to them patiently, and cheer them up.
4. Keep conversations light, engaging, deeply human, and warm.
"""
        if weather_context:
            system_prompt += f"\n--- LIVE WEATHER CONTEXT ---\nUse this real-time weather information naturally in your reply:\n{weather_context}\n"

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
# 6. TELEGRAM HANDLERS & CALLBACKS
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
            "💡 *Tip:* Aap kisi bhi city ka mausam pooch sakte ho, jaise: `Kolkata ka weather kaisa hai?`\n\n"
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
        
        # Weather Keyword Detection
        weather_info = ""
        msg_lower = user_msg.lower()
        if "weather" in msg_lower or "mausam" in msg_lower or "temperature" in msg_lower:
            # Extract potential city name from message
            words = user_msg.split()
            # Simple heuristic: remove common trigger words to find city
            ignore_words = {"weather", "mausam", "kaisa", "hai", "in", "ka", "ki", "of", "tell", "me", "what", "is", "the", "today", "aaj"}
            city_words = [w.strip("?,.!") for w in words if w.lower() not in ignore_words]
            if city_words:
                city_name = " ".join(city_words)
                weather_info = WeatherService.get_weather(city_name)

        # Get AI response with weather context if present
        reply = AIEngine.get_response(
            user_msg, 
            user_name=user.first_name, 
            mood=current_mood,
            weather_context=weather_info
        )

        # STORE-FIRST: Save to Google Sheets BEFORE sending reply
        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(update=update, bot_reply=reply)
            except Exception as e:
                logger.error(f"Google Sheets log error: {e}")

        # Save to SQLite
        db.store_chat(user.id, user_msg, reply)
        
        # Send reply to user
        await update.effective_message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")
        if update.effective_message:
            await update.effective_message.reply_text("Arre, thoda sa glitch aa gaya tha! Dubara kehna kya bol rahe the?")

# ============================================================
# 7. FLASK WEB SERVER (Health Check for Cloud Hosting)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya", "status": "Online"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ============================================================
# 8. SECURE ENTRY POINT
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
    
    # 3. Run Telegram Polling in the main thread
    application.run_polling(allowed_updates=Update.ALL_TYPES)
