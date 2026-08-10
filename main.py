"""
Zoya Bot - Tension Relief & Casual Companion (Verified & Fault-Tolerant)
Brand: SahilCodeLab (sahilcodelab.vercel.app)
Improved: Natural conversation + Proper per-user history
"""

import os
import sys
import logging
import sqlite3
import json
import time
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
# 2. GOOGLE SHEETS LOGGER
# ============================================================
# ============================================================
# 2. GOOGLE SHEETS LOGGER (Improved & Clean)
# ============================================================
class GoogleSheetsLogger:
    """Clean Google Sheets logger - one proper row per chat"""
   
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
           
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
           
            creds_dict = json.loads(self.credentials)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
           
            self._ensure_chat_sheet()
            self.initialized = True
            self.enabled = True
            logger.info("✅ Google Sheets logging enabled (Clean Mode)")
           
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False
            self.initialized = False

    def _ensure_chat_sheet(self):
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
                ws.append_row(headers)
                ws.freeze(rows=1)
                logger.info(f"📊 Created '{self.sheet_name}' worksheet")
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")

    def _get_next_serial(self, ws) -> int:
        """Safely get next serial number"""
        try:
            # Last non-empty row ka serial lo
            values = ws.col_values(1)  # Column A (S.No)
            if len(values) <= 1:
                return 1
            
            # Last valid number dhundo
            for val in reversed(values[1:]):
                if str(val).strip().isdigit():
                    return int(val) + 1
            return len(values)
        except Exception as e:
            logger.error(f"Serial error: {e}")
            return 1

    def _get_message_type(self, update: Update) -> str:
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
        else:
            return "Other"

    def _get_user_message_text(self, update: Update) -> str:
        message = update.effective_message
        if not message:
            return ""
       
        if message.text:
            return message.text[:1500]  # limit long messages
        elif message.caption:
            return message.caption[:1500]
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
        if not user:
            return "No Name"
       
        first_name = user.first_name or ''
        last_name = user.last_name or ''
        full_name = f"{first_name} {last_name}".strip()
       
        return full_name if full_name else (user.username or "No Name")

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
           
            # Message count from database
            message_count = 0
            try:
                user_data = db.get_user(user.id)
                if user_data:
                    message_count = user_data.get('total_interactions', 0) + 1
            except:
                pass
           
            row_data = [
                self._get_next_serial(ws),
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                now.isoformat(),
                str(user.id),
                user.username or "No Username",
                self._get_full_name(user),
                message_count,
                self._get_message_type(update),
                self._get_user_message_text(update),
                (bot_reply or "")[:2000]  # limit very long replies
            ]
           
            # Clean append
            for attempt in range(GOOGLE_SHEETS_RETRY):
                try:
                    ws.append_row(row_data, value_input_option='USER_ENTERED')
                    logger.info(f"📊 Logged chat for User {user.id}")
                    return True
                except Exception as e:
                    if attempt == GOOGLE_SHEETS_RETRY - 1:
                        raise
                    time.sleep(1.5 ** attempt)
           
            return False
           
        except Exception as e:
            logger.error(f"❌ Google Sheets log failed: {e}")
            return False

# ============================================================
# 3. DATABASE MANAGER
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
                # Index for faster per-user history fetch
                c.execute('''CREATE INDEX IF NOT EXISTS idx_chat_user_id 
                             ON chat_history(user_id)''')
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

    def get_chat_history(self, user_id: int, limit: int = 12) -> list:
        """Fetch last N messages ONLY for this user"""
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT user_message, bot_response 
                    FROM chat_history 
                    WHERE user_id = ? 
                    ORDER BY id DESC 
                    LIMIT ?
                """, (user_id, limit))
                rows = c.fetchall()
                
                history = []
                for user_msg, bot_resp in reversed(rows):
                    if user_msg:
                        history.append({"role": "user", "content": user_msg})
                    if bot_resp:
                        history.append({"role": "assistant", "content": bot_resp})
                return history
        except Exception as e:
            logger.error(f"Error fetching chat history: {e}")
            return []

    def clear_user_history(self, user_id: int):
        """Clear only this user's chat history (Fresh Chat)"""
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
                conn.commit()
                logger.info(f"🧹 Cleared history for user {user_id}")
        except Exception as e:
            logger.error(f"Clear History Error: {e}")

db = Database()

# ============================================================
# 4. AI ENGINE (Natural + Per-User History)
# ============================================================
class AIEngine:
    MOOD_PROMPTS = {
        "english": (
            "You are Zoya, a warm, caring, deeply supportive and close female friend. "
            "Your only goal is to help the user feel relaxed, relieve tension, and have light, comforting conversations. "
            "Talk like a real close friend — natural, empathetic, slightly playful when needed, and never robotic. "
            "Keep replies human, warm and engaging."
        ),
        "hinglish": (
            "Tu Zoya hai — ek bohot acchi, samajhdar, caring aur kareebi dost (ladki). "
            "Tera sirf ek kaam hai: user ka tension door karna, usko comfort dena aur dosto ki tarah natural Hinglish mein baat karna. "
            "Kabhi bhi robotic, formal ya AI jaisi baat mat karna. "
            "Bilkul real dost ki tarah baat kar — pyaar se, naturally, thoda mazaak-masti ke saath jab mood ho. "
            "User jo language use kare usi mein reply kar (mostly Hinglish)."
        )
    }

    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str = "User", mood: str = "hinglish") -> str:
        mood_instruction = AIEngine.MOOD_PROMPTS.get(mood, AIEngine.MOOD_PROMPTS["hinglish"])
        
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_vibe = "Subah ka time hai, fresh energy ke saath baat kar."
        elif 12 <= hour < 17:
            time_vibe = "Dopahar hai, thoda relaxed mood mein baat kar."
        elif 17 <= hour < 21:
            time_vibe = "Shaam ho gayi hai, thakaan door karte hue soft baat kar."
        else:
            time_vibe = "Raat ka time hai, soft, caring aur dil se baat kar."

        system_prompt = f"""{mood_instruction}

TIME CONTEXT: {time_vibe}

IMPORTANT RULES:
- User ka naam: {user_name}
- Kabhi bhi formal, robotic ya AI jaisi language mat use karna.
- Har reply natural aur human-like hona chahiye.
- Agar user tension mein hai to pehle usko suno aur comfort do.
- Short to medium length replies prefer karo.
- User Hinglish mein baat kare to Hinglish mein hi reply do.
"""

        # Sirf is user ka history lao
        history = db.get_chat_history(user_id, limit=12)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.85,
                    max_tokens=550,
                    top_p=0.9
                )
                return resp.choices[0].message.content.strip()

            elif GEMINI_API_KEY:
                model = genai.GenerativeModel(
                    'gemini-1.5-flash',
                    system_instruction=system_prompt
                )
                
                chat = model.start_chat(history=[])
                for msg in history:
                    if msg["role"] == "user":
                        chat.history.append({"role": "user", "parts": [msg["content"]]})
                    else:
                        chat.history.append({"role": "model", "parts": [msg["content"]]})
                
                resp = chat.send_message(user_message)
                return resp.text.strip()

            else:
                return "Hey! Batao kya chal raha hai, main sun rahi hoon."

        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return "Arre, thoda network issue ho gaya lagta hai. Ek baar phir se bolo na!"

# ============================================================
# 5. TELEGRAM HANDLERS
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
            # Sirf is user ka history clear karo
            user_id = query.from_user.id
            db.clear_user_history(user_id)
            
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
       
        # AI response with proper per-user history
        reply = AIEngine.get_response(
            user_message=user_msg,
            user_id=user.id,
            user_name=user.first_name,
            mood=current_mood
        )
       
        # STORE-FIRST: Google Sheets
        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(update=update, bot_reply=reply)
            except Exception as e:
                logger.error(f"Google Sheets log error: {e}")
       
        # Save to SQLite (yeh history bhi banata hai)
        db.store_chat(user.id, user_msg, reply)
       
        # Send reply
        await update.effective_message.reply_text(reply)
       
    except Exception as e:
        logger.error(f"Handle Message Error: {e}")
        if update.effective_message:
            await update.effective_message.reply_text("Arre, thoda sa glitch aa gaya tha! Dubara kehna kya bol rahe the?")

# ============================================================
# 6. FLASK WEB SERVER
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya", "status": "Online"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ============================================================
# 7. SECURE ENTRY POINT
# ============================================================
if __name__ == '__main__':
    flask_thread = Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    logger.info("🌐 Flask web server running in background thread.")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
   
    logger.info("✨ Zoya Bot polling starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
