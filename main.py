"""
Zoya & Kabir Telegram Bot - Ultimate Human‑Like AI with Auto Persona & Advanced Reasoning
Developer: SahilCodeLab (Advanced Edition)
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
# 2. LOCAL SQLITE DATABASE (same as before, small additions)
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
                    gender TEXT DEFAULT 'auto',   -- 'girl' or 'boy' persona after detection
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

    def get_chat_history(self, user_id: int, limit: int = 6) -> list:   # increased context window
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
# 3. NAME‑BASED GENDER DETECTION (AUTOMATIC PERSONA SELECTOR)
# ============================================================
# Tries gender‑guesser library, falls back to simple heuristic for Indian names.
def detect_gender_from_name(name: str) -> str:
    """
    Returns 'male', 'female', or 'unknown'.
    We map 'male' → persona 'girl' (Zoya), 'female' → persona 'boy' (Kabir).
    """
    if not name:
        return "unknown"
    name = name.strip().split()[0]  # first name only
    try:
        import gender_guesser.detector as gender_detector
        d = gender_detector.Detector()
        result = d.get_gender(name)
        if result in ("male", "mostly_male"):
            return "male"
        elif result in ("female", "mostly_female"):
            return "female"
    except Exception:
        pass

    # Heuristic for common Indian names (non‑exhaustive)
    male_endings = ["kumar", "raj", "esh", "ansh", "it", "deep", "jeet", "preet", "bir", "pal"]
    female_endings = ["kumari", "devi", "kaur", "preet", "leen", "jeet", "pal"]  # some overlap but we try
    name_lower = name.lower()
    for suffix in female_endings:
        if name_lower.endswith(suffix):
            return "female"
    for suffix in male_endings:
        if name_lower.endswith(suffix):
            return "male"
    return "unknown"

def auto_set_persona(user_id: int, first_name: str) -> str:
    """
    Automatically determines persona based on name.
    Saves it to DB and returns the gender key ('girl'/'boy').
    Rule: If user is male → Zoya (girl), if female → Kabir (boy), unknown → default Zoya.
    """
    detected = detect_gender_from_name(first_name)
    if detected == "male":
        db.set_user_gender(user_id, "girl")
        return "girl"
    elif detected == "female":
        db.set_user_gender(user_id, "boy")
        return "boy"
    else:
        db.set_user_gender(user_id, "girl")   # fallback
        return "girl"

# ============================================================
# 4. GOOGLE SHEETS ENTERPRISE MANAGER (same as before)
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
            print("✅ Google Sheets 3-Tab System Connected Successfully!", flush=True)
        except Exception as e:
            print(f"❌ Google Sheets Connection Failed: {e}", flush=True)
            self.enabled = False

    def _setup_headers(self):
        expected_headers = {
            "User_Chats": ["User ID", "Full Name", "Username", "User Message", "Bot Reply", "Selected Persona", "Date & Time", "Detected Emotion", "New Fact Extracted"],
            "Longterm_Memory": ["Memory ID", "User ID", "Category", "Fact / Detail", "Importance", "Date Added"],
            "User_Profiles": ["User ID", "Full Name", "Username", "Active Persona", "Emotion", "City/Location", "First Seen", "Last Active", "Total Messages"]
        }
        
        for tab, headers in expected_headers.items():
            try:
                ws = self.sheet.worksheet(tab)
                current_headers = ws.row_values(1)
                if not current_headers or current_headers[0] != headers[0]:
                    end_column = chr(64 + len(headers))
                    ws.update(f'A1:{end_column}1', [headers])
            except Exception as e:
                print(f"⚠️ Header setup skipped for {tab}: {e}", flush=True)

    def fetch_longterm_memories(self, user_id: int) -> str:
        if not self.enabled or not self.initialized: return ""
        try:
            ws_mem = self.sheet.worksheet("Longterm_Memory")
            records = ws_mem.get_all_records()
            str_id = str(user_id)
            
            facts = []
            for row in records:
                if str(row.get("User ID", "")).strip() == str_id:
                    cat = row.get("Category", "")
                    fact = row.get("Fact / Detail", "")
                    if fact:
                        facts.append(f"[{cat}] {fact}" if cat else fact)
            
            return " | ".join(facts) if facts else ""
        except Exception as e:
            print(f"⚠️ Error reading Longterm_Memory: {e}", flush=True)
            return ""

    def sync_user_data(self, update: Update, bot_reply: str, emotion: str = "Neutral", fact_extracted: str = ""):
        if not self.enabled or not self.initialized: return
        
        try:
            user = update.effective_user
            msg = update.effective_message
            if not user or not msg: return

            str_user_id = str(user.id)
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            username = user.username or 'No Username'
            active_persona = "Zoya" if db.get_user_gender(user.id) == "girl" else "Kabir"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # TAB 1: User_Chats
            try:
                ws_chats = self.sheet.worksheet("User_Chats")
                chat_row = [str_user_id, full_name, username, (msg.text or '')[:1000], (bot_reply or '')[:1000], active_persona, now_str, emotion, fact_extracted]
                ws_chats.append_row(chat_row, value_input_option='USER_ENTERED')
            except Exception as e:
                print(f"❌ [User_Chats Write Error]: {e}", flush=True)

            # TAB 2: Longterm_Memory
            if fact_extracted.strip():
                try:
                    ws_mem = self.sheet.worksheet("Longterm_Memory")
                    mem_id = len(ws_mem.col_values(1))
                    mem_row = [mem_id, str_user_id, "General Fact", fact_extracted, "High", datetime.now().strftime("%Y-%m-%d")]
                    ws_mem.append_row(mem_row, value_input_option='USER_ENTERED')
                except Exception as e:
                    print(f"❌ [Longterm_Memory Write Error]: {e}", flush=True)

            # TAB 3: User_Profiles
            try:
                ws_prof = self.sheet.worksheet("User_Profiles")
                user_ids = ws_prof.col_values(1)
                
                if str_user_id in user_ids:
                    row_idx = user_ids.index(str_user_id) + 1
                    ws_prof.update_cell(row_idx, 4, active_persona)
                    ws_prof.update_cell(row_idx, 5, emotion)
                    ws_prof.update_cell(row_idx, 8, now_str)
                else:
                    prof_row = [str_user_id, full_name, username, active_persona, emotion, "", now_str, now_str, 1]
                    ws_prof.append_row(prof_row, value_input_option='USER_ENTERED')
            except Exception as e:
                print(f"❌ [User_Profiles Write Error]: {e}", flush=True)

        except Exception as e:
            print(f"❌ Global Sync Error: {e}", flush=True)

sheets = GoogleSheets3TabManager()

# ============================================================
# 5. ULTIMATE HUMAN‑LIKE AI ENGINE
# ============================================================
class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str, persona_gender: str) -> tuple[str, str, str]:
        """
        Returns (reply_text, model_used, detected_emotion).
        persona_gender: 'girl' (Zoya) or 'boy' (Kabir)
        """
        longterm_facts = sheets.fetch_longterm_memories(user_id)

        # ---- BUILD A NUANCED, HUMAN‑LIKE PROMPT ----
        if persona_gender == "girl":
            persona_name = "Zoya"
            gender_rules = """
You are ZOYA, a 22‑year‑old female best friend. You speak in Hinglish (mix of Hindi and English) with a warm, casual tone.
STRICT IDENTITY RULES:
- Use female self‑references: 'main theek hoon', 'soch rahi thi', 'aa gayi', 'karti hoon', 'sun rahi hoon', 'yaar'.
- NEVER use male words for yourself (like 'bhai', 'sunta hoon', 'karta hoon').
"""
        else:
            persona_name = "Kabir"
            gender_rules = """
You are KABIR, a 24‑year‑old male best friend. You speak in Hinglish with a cool, friendly vibe.
STRICT IDENTITY RULES:
- Use male self‑references: 'main theek hoon', 'soch raha tha', 'karta hoon', 'bro', 'bhai', 'sun raha hoon'.
- NEVER use female words for yourself (like 'sunti hoon', 'karti hoon').
"""

        system_instruction = f"""{gender_rules}

USER CONTEXT:
- User's name: {user_name}
- Long‑term facts you know about this user: {longterm_facts if longterm_facts else 'None'}

YOUR ULTIMATE HUMAN‑LIKE BEHAVIOR RULES:
1. **READ THE MESSAGE CAREFULLY**: Before replying, understand what the user is really saying or feeling. Don't just match keywords.
2. **NATURAL LENGTH**: Replies should feel human. They can be 1–3 short sentences, or a bit longer if the conversation demands it. Do NOT cut yourself off artificially.
3. **AVOID ROBOTIC PHRASES**: Never say generic things like "kya problem hai?", "sun raha hoon", "batao" unless they fit the exact context. Instead, react to the content.
   - If user says "Hii", reply with a warm, personal greeting, maybe ask about their day, use their name occasionally.
   - If user shares a feeling, acknowledge it with empathy.
   - If user asks a question, answer directly and then ask a follow‑up.
4. **USE EMOJIS & SLANGS NATURALLY**: 🥲😅✨, yaar, bro, arre, accha, ohh, haan na… but don’t overdo it.
5. **INCORPORATE LONG‑TERM MEMORY**: If you have stored facts about the user, bring them up naturally when relevant. (e.g., "Waise tera woh interview kaisa gaya?")
6. **KEEP THE FLOW**: Don't repeat the same question the user just asked. If you don't know something, say so casually.
7. **EMOTION DETECTION (internal)**: Try to sense the user's emotion (happy, sad, excited, angry, neutral) and let your reply reflect that.
"""

        # ---- CALL AI MODEL ----
        reply = None
        model_used = ""

        if GEMINI_API_KEY:
            try:
                history = db.get_chat_history(user_id, limit=6)
                gemini_hist = [{"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]} for m in history]

                model = genai.GenerativeModel(
                    model_name='gemini-1.5-flash',
                    system_instruction=system_instruction,
                    generation_config={"temperature": 0.7, "max_output_tokens": 150}
                )
                chat = model.start_chat(history=gemini_hist)
                resp = chat.send_message(user_message)
                reply = resp.text.strip()
                model_used = "Gemini-1.5-Flash"
            except Exception as e:
                logger.error(f"Gemini Error: {e}")

        if not reply and groq_client:
            try:
                msgs = [{"role": "system", "content": system_instruction}]
                msgs.extend(db.get_chat_history(user_id, limit=6))
                msgs.append({"role": "user", "content": user_message})

                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant", messages=msgs, temperature=0.7, max_tokens=150
                )
                reply = resp.choices[0].message.content.strip()
                model_used = "Groq-Llama3"
            except Exception as e:
                logger.error(f"Groq Error: {e}")

        if not reply:
            reply = "Arre yaar, network slow lag raha hai. Ek baar firse bol na?"
            model_used = "Fallback"

        # ---- DETECT EMOTION FROM USER MESSAGE (simple keyword + heuristics) ----
        emotion = AIEngine.detect_emotion(user_message)

        return reply, model_used, emotion

    @staticmethod
    def detect_emotion(text: str) -> str:
        """Lightweight emotion detection for analytics."""
        t = text.lower()
        if any(w in t for w in ["haha", "😂", "lol", "mast", "badhiya", "super", "party", "khush"]):
            return "Happy"
        if any(w in t for w in ["😢", "udaas", "sad", "dukhi", "rona", "bura", "tension", "problem"]):
            return "Sad"
        if any(w in t for w in ["😡", "gussa", "anger", "chup", "baat mat kar"]):
            return "Angry"
        if any(w in t for w in ["😍", "love", "pyaar", "crush", "beautiful"]):
            return "Love"
        return "Neutral"

# ============================================================
# 6. TELEGRAM BOT HANDLERS (AUTO PERSONA, NO MANUAL BUTTONS)
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)

    # Auto‑detect persona based on name (only if not already set by user override)
    current = db.get_user_gender(user.id)
    if current == "auto":   # first time
        persona = auto_set_persona(user.id, user.first_name)
    else:
        persona = current

    bot_name = "👧 Zoya" if persona == "girl" else "👦 Kabir"

    # No manual selection keyboard – just a reset option
    keyboard = [[InlineKeyboardButton("🔄 Reset Memory", callback_data="fresh_chat")]]

    welcome = (
        f"Hey **{user.first_name}**! ☕✨\n"
        f"Main hoon teri **{bot_name}** – tera apna AI best friend.\n"
        f"Mujhe tera naam dekh ke automatically pata chal gaya ki kaise baat karni hai.\n"
        f"Bindaas message kar, jo mann mein aaye!"
    )
    
    if update.message:
        await update.message.reply_text(welcome, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_user_history(update.effective_user.id)
    await update.message.reply_text("🧹 Saari purani chat memory saaf kar di! Fresh start.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "fresh_chat":
        db.clear_user_history(query.from_user.id)
        await query.message.edit_text("🔄 Memory reset! Ab bilkul fresh conversation hogi.")
    # Removed gender selection buttons

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    
    user = update.effective_user
    user_msg = update.effective_message.text
    persona = db.get_user_gender(user.id)
    # Fallback if somehow still 'auto'
    if persona == "auto":
        persona = auto_set_persona(user.id, user.first_name)

    await update.effective_chat.send_action("typing")

    reply, model_used, emotion = AIEngine.get_response(
        user_msg, user.id, user.first_name, persona
    )

    db.store_chat(user.id, user_msg, reply)

    # Sync to Google Sheets in background
    Thread(target=sheets.sync_user_data, args=(update, reply, emotion, ""), daemon=True).start()

    await update.effective_message.reply_text(reply)

# ============================================================
# 7. FLASK SERVER & ENTRYPOINT
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "brand": "SahilCodeLab",
        "bot": "Zoya/Kabir - Human‑Like AI",
        "persona_selection": "Automatic (name‑based)",
        "status": "Online"
    })

if __name__ == '__main__':
    # Start Flask health check
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✨ Advanced Human‑Like Bot Activated. Auto persona + powerful AI.", flush=True)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
