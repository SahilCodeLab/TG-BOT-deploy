"""
Memo AI Telegram Bot - FastAPI + Production-Grade Version
A professional AI business assistant with persistent memory, SQLite database,
real-time Google Sheets logging, and FastAPI web server with interactive docs.
"""

import os
import sys
import json
import logging
import sqlite3
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from threading import Thread, Lock
from fastapi import FastAPI, BackgroundTasks, Request, Response
import uvicorn
import google.generativeai as genai
from groq import Groq
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ============================================================
# 1. CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "memo.db")
PORT = int(os.getenv("PORT", 8000))
ADMIN_USER_IDS = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 2))
MAX_MEMORY_ITEMS = int(os.getenv("MAX_MEMORY_ITEMS", 20))
ENABLE_GOOGLE_SHEETS = os.getenv("ENABLE_GOOGLE_SHEETS", "false").lower() == "true"
GOOGLE_SHEETS_RETRY = int(os.getenv("GOOGLE_SHEETS_RETRY", 3))
GOOGLE_SHEETS_TIMEOUT = int(os.getenv("GOOGLE_SHEETS_TIMEOUT", 10))

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Missing!", flush=True)
    sys.exit(1)

# Configure AI APIs
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# 2. GOOGLE SHEETS LOGGER - PRODUCTION GRADE
# ============================================================

class GoogleSheetsLogger:
    def __init__(self):
        self.enabled = ENABLE_GOOGLE_SHEETS
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self.credentials = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        self.sheet_name = "Chats"
        self.client = None
        self.sheet = None
        self.initialized = False
        self._serial_cache = None
        self._lock = Lock()
        self.max_retries = GOOGLE_SHEETS_RETRY
        self.timeout = GOOGLE_SHEETS_TIMEOUT

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
            self._refresh_serial_cache()
            
            self.initialized = True
            self.enabled = True
            logger.info("✅ Google Sheets production logger initialized")
            
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
                for col_idx, header in enumerate(headers, start=1):
                    ws.update_cell(1, col_idx, header)
                ws.freeze(rows=1)
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")
            raise

    def _refresh_serial_cache(self):
        try:
            ws = self.sheet.worksheet(self.sheet_name)
            last_row_data = ws.row_values(ws.row_count)
            if last_row_data and last_row_data[0] and str(last_row_data[0]).isdigit():
                self._serial_cache = int(last_row_data[0])
            else:
                self._serial_cache = ws.row_count - 1
        except Exception as e:
            logger.error(f"Error refreshing serial cache: {e}")
            self._serial_cache = 1

    def _get_next_serial(self, ws) -> int:
        with self._lock:
            if self._serial_cache is None:
                total_rows = ws.row_count
                if total_rows <= 1:
                    self._serial_cache = 1
                else:
                    try:
                        last_row = ws.row_values(total_rows)
                        if last_row and last_row[0] and str(last_row[0]).isdigit():
                            self._serial_cache = int(last_row[0]) + 1
                        else:
                            self._serial_cache = total_rows - 1
                    except:
                        self._serial_cache = total_rows - 1
            self._serial_cache += 1
            return self._serial_cache

    def _get_message_type(self, update: Update) -> str:
        message = update.effective_message
        if not message: return "Unknown"
        if message.text: return "Text"
        if message.photo: return "Photo"
        if message.video: return "Video"
        if message.voice: return "Voice"
        if message.document: return "Document"
        return "Other"

    def _get_user_message_text(self, update: Update) -> str:
        message = update.effective_message
        if not message: return ""
        if message.text: return message.text
        if message.caption: return message.caption
        if message.photo: return "📸 Photo"
        if message.voice: return f"🎤 Voice Message ({message.voice.duration}s)"
        if message.document: return f"📄 Document"
        return "📨 Media Message"

    def _get_full_name(self, user) -> str:
        if not user: return "No Name"
        full = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return full if full else (user.username or "No Name")

    def log_chat_store_first(self, update: Update, bot_reply: str) -> bool:
        if not self.enabled or not self.initialized: return False
        try:
            user = update.effective_user
            message = update.effective_message
            if not user or not message: return False
            
            ws = self.sheet.worksheet(self.sheet_name)
            now = datetime.now()
            serial_no = self._get_next_serial(ws)
            
            db_obj = Database(DATABASE_PATH)
            usr = db_obj.get_user(user.id)
            message_count = usr.get('total_interactions', 0) if usr else 0
            
            row_data = [
                serial_no, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                now.isoformat(), str(user.id), user.username or 'No Username',
                self._get_full_name(user), message_count, self._get_message_type(update),
                self._get_user_message_text(update), bot_reply or ''
            ]
            ws.append_row(row_data, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error(f"❌ Google Sheets log failed: {e}")
            return False

google_sheets = GoogleSheetsLogger()

# ============================================================
# 3. DATABASE CLASS
# ============================================================

class Database:
    def __init__(self, db_path: str = "memo.db"):
        self.db_path = db_path
        self._lock = Lock()
        self.init_tables()
        self.create_indexes()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_tables(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_username TEXT,
                name TEXT,
                preferred_language TEXT DEFAULT 'English',
                joined_date TIMESTAMP,
                last_active TIMESTAMP,
                total_interactions INTEGER DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                memory_key TEXT,
                memory_value TEXT,
                confidence REAL DEFAULT 0.0,
                updated_by_ai INTEGER DEFAULT 0,
                validated INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                UNIQUE(user_id, memory_key)
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS memory_schema (
                key_name TEXT PRIMARY KEY,
                description TEXT,
                data_type TEXT,
                max_length INTEGER,
                default_confidence REAL DEFAULT 0.7
            )''')
            c.execute("SELECT COUNT(*) FROM memory_schema")
            if c.fetchone()[0] == 0:
                default_schema = [
                    ('name', 'User full name', 'string', 100, 0.95),
                    ('company', 'Company name', 'string', 200, 0.9),
                    ('project', 'Current project name', 'string', 200, 0.9),
                    ('preferred_language', 'Preferred language', 'string', 20, 0.95),
                    ('goal', 'Primary goal', 'string', 500, 0.85),
                    ('profession', 'User profession', 'string', 100, 0.9)
                ]
                for key, desc, dtype, maxlen, conf in default_schema:
                    c.execute('''INSERT OR IGNORE INTO memory_schema
                        (key_name, description, data_type, max_length, default_confidence)
                        VALUES (?,?,?,?,?)''', (key, desc, dtype, maxlen, conf))
            c.execute('''CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_message TEXT,
                bot_reply TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER PRIMARY KEY,
                last_message_time TIMESTAMP,
                message_count INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )''')
            conn.commit()

    def create_indexes(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('CREATE INDEX IF NOT EXISTS idx_chat_user_id ON chat_logs(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_memory_user_key ON memory(user_id, memory_key)')
            conn.commit()

    def get_or_create_user(self, user_id: int, username: str = None, name: str = None) -> Dict:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO users (user_id, telegram_username, name, joined_date, last_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    telegram_username = COALESCE(excluded.telegram_username, telegram_username),
                    last_active = excluded.last_active
            """, (user_id, username, name, datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
            c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(c.fetchone())

    def update_user_name(self, user_id: int, name: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
            conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None

    def is_valid_memory_key(self, key: str) -> bool:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM memory_schema WHERE key_name = ?", (key,))
            return c.fetchone() is not None

    def get_allowed_keys(self) -> List[Dict]:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT key_name, default_confidence FROM memory_schema")
            return [dict(row) for row in c.fetchall()]

    def save_memory(self, user_id: int, key: str, value: str, confidence: float = 0.8) -> bool:
        if not self.is_valid_memory_key(key): return False
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO memory (user_id, memory_key, memory_value, confidence, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(user_id, memory_key) DO UPDATE SET
                    memory_value = excluded.memory_value,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at''',
                (user_id, key, value, confidence, datetime.now().isoformat()))
            conn.commit()
            return True

    def get_memory(self, user_id: int, min_confidence: float = 0.5) -> Dict[str, str]:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''SELECT memory_key, memory_value FROM memory
                WHERE user_id = ? AND confidence >= ?''', (user_id, min_confidence))
            return {row['memory_key']: row['memory_value'] for row in c.fetchall()}

    def log_chat(self, user_id: int, user_message: str, bot_reply: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO chat_logs (user_id, user_message, bot_reply, timestamp) VALUES (?,?,?,?)",
                      (user_id, user_message, bot_reply, datetime.now().isoformat()))
            c.execute("UPDATE users SET total_interactions = total_interactions + 1, last_active = ? WHERE user_id = ?",
                      (datetime.now().isoformat(), user_id))
            conn.commit()

    def get_stats(self) -> Dict:
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            u_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM chat_logs")
            m_count = c.fetchone()[0]
            return {"total_users": u_count, "total_messages": m_count}

db = Database(DATABASE_PATH)

# ============================================================
# 4. AI & HANDLERS
# ============================================================

class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int) -> str:
        memory = db.get_memory(user_id)
        user_data = db.get_user(user_id)
        name = memory.get('name', user_data.get('name') if user_data else None)
        
        prompt = f"You are Memo, a helpful AI business assistant. User name: {name or 'Friend'}."
        
        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_message}],
                    temperature=0.6, max_tokens=500
                )
                reply = resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=prompt)
                resp = model.generate_content(user_message)
                reply = resp.text.strip()
            else:
                reply = "⚠️ No AI API configured."
            
            db.log_chat(user_id, user_message, reply)
            return reply
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "Technical difficulties. Please try again."

# Telegram Bot Handlers
NAME, COMPANY, PROJECT, LANGUAGE = range(4)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_or_create_user(user.id, user.username)
    if user_data.get('name'):
        await update.message.reply_text(f"Welcome back, {user_data['name']}! How can I help you?")
        return ConversationHandler.END
    await update.message.reply_text("Welcome to Memo! What is your name?")
    return NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    db.update_user_name(user_id, name)
    db.save_memory(user_id, "name", name, 0.95)
    await update.message.reply_text(f"Nice to meet you, {name}! What project are you working on?")
    return PROJECT

async def handle_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project = update.message.text.strip()
    db.save_memory(user_id, "project", project, 0.9)
    await update.message.reply_text("All set! How can I help you today?")
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    user_id = update.effective_user.id
    await update.effective_chat.send_action("typing")
    reply = AIEngine.get_response(update.effective_message.text or "", user_id)
    
    if google_sheets.enabled:
        google_sheets.log_chat_store_first(update, reply)
        
    await update.effective_message.reply_text(reply)

# ============================================================
# 5. FASTAPI WEB SERVER
# ============================================================

app = FastAPI(title="Memo AI Bot API", version="3.0")

@app.get("/")
def home():
    return {"message": "Memo AI Assistant FastAPI Backend is running."}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "google_sheets": "enabled" if google_sheets.enabled else "disabled",
        "database": "connected"
    }

@app.get("/stats")
def stats():
    return db.get_stats()

def run_telegram_bot():
    """Run Telegram Bot in background thread"""
    try:
        app_bot = Application.builder().token(BOT_TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start_command)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
                PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project)],
            },
            fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        )
        app_bot.add_handler(conv_handler)
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("✅ Telegram Bot polling started...")
        app_bot.run_polling()
    except Exception as e:
        logger.error(f"Telegram Bot error: {e}")

# ============================================================
# 6. MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    # Start Telegram Bot in a separate daemon thread
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # Start FastAPI Uvicorn Server
    uvicorn.run(app, host="0.0.0.0", port=PORT)
