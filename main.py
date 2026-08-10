"""
Zoya & Kabir Telegram Bot - Enterprise 3-Tab Google Sheets Architecture
Developer: codewithsahil / SahilCodeLab
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

# Fixed: Ensure it parses properly
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
                return row[0] if row and row[0] else "girl"
        except Exception as e:
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
# 3. GOOGLE SHEETS ENTERPRISE MANAGER (3 TABS)
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
            
            # AUTOMATIC HEADER SETUP TO PREVENT MISMATCH ERRORS
            self._setup_headers()
            
            print("✅ Google Sheets 3-Tab System Connected Successfully!", flush=True)
        except Exception as e:
            print(f"❌ Google Sheets Connection Failed: {e}", flush=True)
            self.enabled = False

    def _setup_headers(self):
        """Fixes Tab headers automatically so the logic never breaks."""
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
                    ws.update('A1:[{}1]'.format(chr(64+len(headers))), [headers])
                    print(f"🛠️ Headers auto-fixed for tab: {tab}", flush=True)
            except Exception as e:
                print(f"⚠️ Header setup skipped for {tab} (Tab might not exist): {e}", flush=True)

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
        if not self.enabled or not self.initialized: 
            print("⚠️ Google Sheets disabled ya initialized nahi hai!", flush=True)
            return
        
        try:
            user = update.effective_user
            msg = update.effective_message
            if not user or not msg: return

            str_user_id = str(user.id)
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            username = user.username or 'No Username'
            active_persona = "Zoya" if db.get_user_gender(user.id) == "girl" else "Kabir"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # --- TAB 1: User_Chats ---
            try:
                ws_chats = self.sheet.worksheet("User_Chats")
                chat_row = [str_user_id, full_name, username, (msg.text or '')[:1000], (bot_reply or '')[:1000], active_persona, now_str, emotion, fact_extracted]
                ws_chats.append_row(chat_row, value_input_option='USER_ENTERED')
                print(f"✅ [User_Chats] Data added for {full_name}", flush=True)
            except Exception as e:
                print(f"❌ [User_Chats Write Error]: {e}", flush=True)

            # --- TAB 2: Longterm_Memory ---
            if fact_extracted.strip():
                try:
                    ws_mem = self.sheet.worksheet("Longterm_Memory")
                    mem_id = len(ws_mem.col_values(1))
                    mem_row = [mem_id, str_user_id, "General Fact", fact_extracted, "High", datetime.now().strftime("%Y-%m-%d")]
                    ws_mem.append_row(mem_row, value_input_option='USER_ENTERED')
                    print(f"🧠 [Longterm_Memory] Fact added for {str_user_id}", flush=True)
                except Exception as e:
                    print(f"❌ [Longterm_Memory Write Error]: {e}", flush=True)

            # --- TAB 3: User_Profiles ---
            try:
                ws_prof = self.sheet.worksheet("User_Profiles")
                user_ids = ws_prof.col_values(1)
                
                if str_user_id in user_ids:
                    row_idx = user_ids.index(str_user_id) + 1
                    ws_prof.update_cell(row_idx, 4, active_persona)
                    ws_prof.update_cell(row_idx, 5, emotion)
                    ws_prof.update_cell(row_idx, 8, now_str)
                    print(f"👤 [User_Profiles] Profile updated for {str_user_id}", flush=True)
                else:
                    prof_row = [str_user_id, full_name, username, active_persona, emotion, "", now_str, now_str, 1]
                    ws_prof.append_row(prof_row, value_input_option='USER_ENTERED')
                    print(f"👤 [User_Profiles] New Profile Created for {str_user_id}", flush=True)
            except Exception as e:
                print(f"❌ [User_Profiles Write Error]: {e}", flush=True)

        except Exception as e:
            print(f"❌ Global Sync Error: {e}", flush=True)

sheets = GoogleSheets3TabManager()

# ============================================================
# 4. REALISTIC HUMAN AI ENGINE
# ============================================================
class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str, gender: str) -> tuple[str, str]:
        longterm_facts = sheets.fetch_longterm_memories(user_id)
        
        if gender == "girl":
            gender_rules = """
YOUR NAME: ZOYA (Female Best Friend)
STRICT GRAMMAR RULES:
- Use ONLY female self-referencing words: 'main theek hoon', 'soch rahi thi', 'aa gayi', 'karti hoon', 'sun rahi hoon', 'batao na'.
- NEVER use male words for yourself like 'sunta hoon', 'karta hoon', 'aaya tha', 'bhai'.
"""
        else:
            gender_rules = """
YOUR NAME: KABIR (Male Best Friend)
STRICT GRAMMAR RULES:
- Use male self-referencing words: 'main theek hoon', 'soch raha tha', 'karta hoon', 'bro', 'bhai', 'sun raha hoon'.
"""

        system_instruction = f"""{gender_rules}

USER CONTEXT & MEMORY:
- User Name: {user_name}
- Saved Longterm Memory Facts: {longterm_facts if longterm_facts else 'None'}

STRICT HUMAN TELEGRAM CHAT RULES:
1. VERY SHORT REPLIES: Keep replies under 10-25 words. Talk naturally like a friend texting on WhatsApp/Telegram!
2. NO WEIRD STORIES / HALLUCINATIONS: Do NOT invent made-up events. Answer directly and relevantly.
3. EMPATHY: If user seems sad, be genuinely caring.
"""

        # GEMINI API
        if GEMINI_API_KEY:
            try:
                history = db.get_chat_history(user_id, limit=4)
                gemini_hist = [{"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]} for m in history]

                model = genai.GenerativeModel(
                    model_name='gemini-1.5-flash',
                    system_instruction=system_instruction,
                    generation_config={"temperature": 0.4, "max_output_tokens": 80}
                )
                chat = model.start_chat(history=gemini_hist)
                resp = chat.send_message(user_message)
                return resp.text.strip(), "Gemini-1.5-Flash"
            except Exception as e:
                logger.error(f"Gemini Error: {e}")

        # GROQ FALLBACK
        if groq_client:
            try:
                msgs = [{"role": "system", "content": system_instruction}]
                msgs.extend(db.get_chat_history(user_id, limit=4))
                msgs.append({"role": "user", "content": user_message})

                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant", messages=msgs, temperature=0.4, max_tokens=80
                )
                return resp.choices[0].message.content.strip(), "Groq-Llama3"
            except Exception as e:
                logger.error(f"Groq Error: {e}")

        return "Arre thoda network slow hai, ek baar firse bolna?", "Error"

# ============================================================
# 5. TELEGRAM BOT HANDLERS
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)
    current_gender = db.get_user_gender(user.id)
    bot_name = "👧 Zoya" if current_gender == 'girl' else "👦 Kabir"

    keyboard = [
        [
            InlineKeyboardButton("👧 Zoya (Girl)", callback_data="setgender_girl"),
            InlineKeyboardButton("👦 Kabir (Boy)", callback_data="setgender_boy")
        ],
        [InlineKeyboardButton("💬 Reset Memory", callback_data="fresh_chat")]
    ]

    msg = f"Hey **{user.first_name}**! ☕✨\n\nAbhi main **{bot_name}** mode me hoon. Choose kar lo kisse baat karni hai!"
    
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_user_history(update.effective_user.id)
    await update.message.reply_text("🧹 Local database se saari purani chat history saaf kar di gayi hai!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("setgender_"):
        g = query.data.split("_")[1]
        db.set_user_gender(query.from_user.id, g)
        name = "👧 Zoya" if g == "girl" else "👦 Kabir"
        await query.message.edit_text(f"✨ Done! Ab se main **{name}** bankar baat karungi/karunga.")
    elif query.data == "fresh_chat":
        db.clear_user_history(query.from_user.id)
        await query.message.edit_text("🔄 Purani memory clear kar di hai!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text: return
    
    user = update.effective_user
    user_msg = update.effective_message.text
    gender = db.get_user_gender(user.id)

    await update.effective_chat.send_action("typing")

    reply, model_used = AIEngine.get_response(user_msg, user.id, user.first_name, gender)

    db.store_chat(user.id, user_msg, reply)

    Thread(target=sheets.sync_user_data, args=(update, reply, "Neutral", ""), daemon=True).start()

    await update.effective_message.reply_text(reply)

# ============================================================
# 6. FLASK SERVER & ENTRYPOINT
# ============================================================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"brand": "SahilCodeLab", "bot": "Zoya/Kabir", "sheets_system": "3-Tab Active", "status": "Online"})

if __name__ == '__main__':
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✨ Bot Starting with 3-Tab Google Sheets Architecture...", flush=True)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
