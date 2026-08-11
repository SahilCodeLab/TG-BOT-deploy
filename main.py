"""
Zoya & Kabir Telegram Bot – Ultimate Human‑Like AI with Auto Persona
Developer: SahilCodeLab (Final Edition)
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
# 1. CONFIGURATION & ENVIRONMENT
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "sahilcodelab.db")
PORT = int(os.getenv("PORT", 8000))

ENABLE_GOOGLE_SHEETS = os.getenv("ENABLE_GOOGLE_SHEETS", "false").lower() == "true"
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN missing!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 2. LOCAL SQLITE DATABASE
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
                    gender TEXT DEFAULT 'auto',
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
                    INSERT INTO users (user_id, username, name) VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, name=excluded.name
                """, (user_id, username, name))
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
                return row[0] if row and row[0] else "auto"
        except Exception as e:
            return "auto"

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

    def get_chat_history(self, user_id: int, limit: int = 6) -> list:
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                c = conn.cursor()
                c.execute("SELECT user_message, bot_response FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
                rows = c.fetchall()
                history = []
                for user_msg, bot_resp in reversed(rows):
                    if user_msg: history.append({"role": "user", "content": user_msg})
                    if bot_resp: history.append({"role": "assistant", "content": bot_resp})
                return history
        except Exception as e:
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
# 3. AUTO PERSONA DETECTION (name‑based)
# ============================================================
def detect_gender_from_name(name: str) -> str:
    if not name:
        return "unknown"
    name = name.strip().split()[0]
    try:
        import gender_guesser.detector as gender_detector
        d = gender_detector.Detector()
        result = d.get_gender(name)
        if result in ("male", "mostly_male"):
            return "male"
        elif result in ("female", "mostly_female"):
            return "female"
    except:
        pass
    male_endings = ["kumar", "raj", "esh", "ansh", "it", "deep", "jeet", "preet", "bir", "pal"]
    female_endings = ["kumari", "devi", "kaur", "preet", "leen", "jeet", "pal"]
    name_lower = name.lower()
    for suffix in female_endings:
        if name_lower.endswith(suffix):
            return "female"
    for suffix in male_endings:
        if name_lower.endswith(suffix):
            return "male"
    return "unknown"

def auto_set_persona(user_id: int, first_name: str) -> str:
    detected = detect_gender_from_name(first_name)
    if detected == "male":
        db.set_user_gender(user_id, "girl")
        return "girl"
    elif detected == "female":
        db.set_user_gender(user_id, "boy")
        return "boy"
    else:
        db.set_user_gender(user_id, "girl")  # default Zoya
        return "girl"

# ============================================================
# 4. GOOGLE SHEETS 3‑TAB MANAGER (unchanged)
# ============================================================
class GoogleSheets3TabManager:
    def __init__(self):
        self.enabled = ENABLE_GOOGLE_SHEETS
        self.spreadsheet_id = SPREADSHEET_ID
        self.credentials = GOOGLE_SHEETS_CREDENTIALS
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
            client = gspread.authorize(creds)
            self.sheet = client.open_by_key(self.spreadsheet_id)
            self.initialized = True
            self._setup_headers()
            print("✅ Google Sheets connected", flush=True)
        except Exception as e:
            print(f"❌ Sheets error: {e}", flush=True)
            self.enabled = False

    def _setup_headers(self):
        expected = {
            "User_Chats": ["User ID", "Full Name", "Username", "User Message", "Bot Reply", "Selected Persona", "Date & Time", "Detected Emotion", "New Fact Extracted"],
            "Longterm_Memory": ["Memory ID", "User ID", "Category", "Fact / Detail", "Importance", "Date Added"],
            "User_Profiles": ["User ID", "Full Name", "Username", "Active Persona", "Emotion", "City/Location", "First Seen", "Last Active", "Total Messages"]
        }
        for tab, headers in expected.items():
            try:
                ws = self.sheet.worksheet(tab)
                if not ws.row_values(1) or ws.row_values(1)[0] != headers[0]:
                    ws.update(f'A1:{chr(64+len(headers))}1', [headers])
            except: pass

    def fetch_longterm_memories(self, user_id: int) -> str:
        if not self.enabled or not self.initialized: return ""
        try:
            ws = self.sheet.worksheet("Longterm_Memory")
            records = ws.get_all_records()
            facts = []
            for row in records:
                if str(row.get("User ID","")).strip() == str(user_id):
                    fact = row.get("Fact / Detail","")
                    if fact: facts.append(fact)
            return " | ".join(facts) if facts else ""
        except: return ""

    def sync_user_data(self, update: Update, bot_reply: str, emotion: str = "Neutral", fact_extracted: str = ""):
        if not self.enabled or not self.initialized: return
        try:
            user = update.effective_user
            msg = update.effective_message
            if not user or not msg: return
            uid = str(user.id)
            full = f"{user.first_name or ''} {user.last_name or ''}".strip()
            uname = user.username or 'No Username'
            persona = "Zoya" if db.get_user_gender(user.id) == "girl" else "Kabir"
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws_chats = self.sheet.worksheet("User_Chats")
            ws_chats.append_row([uid, full, uname, (msg.text or '')[:1000], (bot_reply or '')[:1000], persona, now, emotion, fact_extracted], value_input_option='USER_ENTERED')
            # Longterm Memory
            if fact_extracted.strip():
                ws_mem = self.sheet.worksheet("Longterm_Memory")
                mem_id = len(ws_mem.col_values(1))
                ws_mem.append_row([mem_id, uid, "General Fact", fact_extracted, "High", datetime.now().strftime("%Y-%m-%d")], value_input_option='USER_ENTERED')
            # Profiles
            ws_prof = self.sheet.worksheet("User_Profiles")
            col1 = ws_prof.col_values(1)
            if uid in col1:
                row = col1.index(uid)+1
                ws_prof.update_cell(row, 4, persona)
                ws_prof.update_cell(row, 5, emotion)
                ws_prof.update_cell(row, 8, now)
            else:
                ws_prof.append_row([uid, full, uname, persona, emotion, "", now, now, 1], value_input_option='USER_ENTERED')
        except: pass

sheets = GoogleSheets3TabManager()

# ============================================================
# 5. SAFE MATH EVALUATOR
# ============================================================
def safe_math_eval(expression: str) -> str:
    """If the message is a pure arithmetic expression, return the computed result as a string, else None."""
    clean = expression.replace(" ", "")
    if not clean:
        return None
    allowed = set("0123456789+-*/().")
    if all(ch in allowed for ch in clean):
        try:
            # Use a restricted eval
            result = eval(clean, {"__builtins__": None}, {})
            if isinstance(result, (int, float)):
                if isinstance(result, float) and result.is_integer():
                    result = int(result)
                return str(result)
        except:
            return None
    return None

# ============================================================
# 6. TRULY HUMAN AI ENGINE (NO ROBOTIC PHRASES)
# ============================================================
class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str, persona_gender: str) -> tuple[str, str, str]:
        longterm_facts = sheets.fetch_longterm_memories(user_id)

        # ---- Persona definitions ----
        if persona_gender == "girl":
            persona_name = "Zoya"
            identity = "You are ZOYA, a 22‑year‑old female best friend. You ALWAYS use female self‑references: 'main theek hoon', 'soch rahi thi', 'karti hoon'."
        else:
            persona_name = "Kabir"
            identity = "You are KABIR, a 24‑year‑old male best friend. You ALWAYS use male self‑references: 'main theek hoon', 'soch raha tha', 'karta hoon', 'bro'."

        # ---- Strict human behaviour rules ----
        system = f"""{identity}
User's name: {user_name}
Long‑term facts: {longterm_facts if longterm_facts else 'None'}

CRITICAL HUMAN BEHAVIOR RULES (follow exactly):
1. READ the user's message carefully. Understand what they want or feel before replying.
2. NEVER use robotic filler like "sun rahi hoon", "sun raha hoon", "batao", "problem hai kya" unless it naturally fits the EXACT situation. DO NOT start sentences with these.
3. If the user asks a simple math question like "2+6", you can answer casually (e.g., "8 😄"). For large/complex numbers, say "Arre yaar, itna bada math mere bas ka nahi 😅 Calculator use kar le".
4. Keep replies warm, short (1-2 sentences), and extremely natural. Use Hinglish, emojis (😄🤔🙌😅✨💬) casually, words like yaar, arre, accha, ohh, haan na.
5. DO NOT repeat the user's words back in a weird way. Don't ask "kaun saa din" unless you genuinely don't know. Just talk normally.
6. If the user thanks you, reply simply "Koi nahi yaar 😊" or "Happy to help! 😊".
7. Incorporate stored facts naturally if relevant, but don't force it.
8. Use emojis to make the conversation lively, but not every sentence. One or two is fine.
"""

        # ---- Try local math first (for safe expressions) ----
        math_result = safe_math_eval(user_message)
        if math_result:
            # Friendly math reply
            reply = f"{math_result} 😄"
            return reply, "MathEngine", "Neutral"

        # ---- AI model ----
        reply = None
        model_used = ""

        if GEMINI_API_KEY:
            try:
                history = db.get_chat_history(user_id, limit=6)
                gemini_hist = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in history]

                model = genai.GenerativeModel(
                    model_name='gemini-1.5-flash',
                    system_instruction=system,
                    generation_config={"temperature": 0.8, "max_output_tokens": 80}
                )
                chat = model.start_chat(history=gemini_hist)
                resp = chat.send_message(user_message)
                reply = resp.text.strip()
                model_used = "Gemini-1.5-Flash"
            except Exception as e:
                logger.error(f"Gemini Error: {e}")

        if not reply and groq_client:
            try:
                msgs = [{"role": "system", "content": system}]
                msgs.extend(db.get_chat_history(user_id, limit=6))
                msgs.append({"role": "user", "content": user_message})
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=msgs,
                    temperature=0.8,
                    max_tokens=80
                )
                reply = resp.choices[0].message.content.strip()
                model_used = "Groq-Llama3"
            except Exception as e:
                logger.error(f"Groq Error: {e}")

        if not reply:
            reply = "Arre yaar, network slow lag raha hai. Ek baar firse bol na? 🫤"
            model_used = "Fallback"

        # ---- Emotion detection ----
        emotion = AIEngine.detect_emotion(user_message)

        return reply, model_used, emotion

    @staticmethod
    def detect_emotion(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["haha","😂","lol","mast","badhiya","super","khush"]): return "Happy"
        if any(w in t for w in ["😢","udaas","sad","dukhi","rona"]): return "Sad"
        if any(w in t for w in ["😡","gussa","anger"]): return "Angry"
        return "Neutral"

# ============================================================
# 7. TELEGRAM HANDLERS
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)

    current = db.get_user_gender(user.id)
    if current == "auto":
        persona = auto_set_persona(user.id, user.first_name)
    else:
        persona = current

    if persona == "girl":
        bot_name = "Zoya"
        emoji = "👧"
        tagline = "teri nayi bestie"
    else:
        bot_name = "Kabir"
        emoji = "👦"
        tagline = "tera apna bhai"

    welcome_text = (
        f"Oye **{user.first_name}**! 🎉\n"
        f"Kya haal hai mere dost? 🌟\n"
        f"Main hoon {emoji} **{bot_name}** – {tagline}!\n"
        f"Tu bas message kar, jo mann mein aaye, bindaas! 💬😎\n"
        f"Masti karte hain, baatein karte hain, full dosti mode ON! 🥳✨"
    )

    keyboard = [[InlineKeyboardButton("🔄 Reset Memory", callback_data="fresh_chat")]]

    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.callback_query.message.edit_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_user_history(update.effective_user.id)
    await update.message.reply_text("🧹 Purani chat memory saaf! Fresh start. 😇")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "fresh_chat":
        db.clear_user_history(query.from_user.id)
        await query.message.edit_text("🔄 Memory reset! Ab bilkul fresh conversation hogi. 😎")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    user = update.effective_user
    user_msg = update.effective_message.text
    persona = db.get_user_gender(user.id)
    if persona == "auto":
        persona = auto_set_persona(user.id, user.first_name)

    await update.effective_chat.send_action("typing")

    reply, model_used, emotion = AIEngine.get_response(
        user_msg, user.id, user.first_name, persona
    )

    db.store_chat(user.id, user_msg, reply)
    Thread(target=sheets.sync_user_data, args=(update, reply, emotion, ""), daemon=True).start()

    await update.effective_message.reply_text(reply)

# ============================================================
# 8. FLASK SERVER & ENTRYPOINT
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "brand": "SahilCodeLab",
        "status": "Human‑Like AI Online",
        "persona_selection": "Auto (name‑based)",
        "features": "Warm welcome, anti‑robotic replies, safe math, long‑term memory"
    })

if __name__ == '__main__':
    # Start Flask in daemon thread for health checks
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    # Build Telegram bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✨ Human‑Like Bot Activated with Auto Persona, Warm Welcome & Safe Math.", flush=True)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
