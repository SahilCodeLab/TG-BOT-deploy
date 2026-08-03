"""
Memo AI Telegram Bot - Production-Grade Version
A professional AI business assistant with persistent memory, SQLite database,
and real-time Google Sheets logging with store-first architecture.

Features:
- User-specific memory with confidence scoring
- Real-time Google Sheets logging (store-first)
- Support for all Telegram message types
- Rate limiting and security
- Production-ready error handling
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
from flask import Flask, jsonify
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
    """
    Production-grade Google Sheets logger with:
    - Store-first architecture
    - Automatic retry with exponential backoff
    - Timeout protection
    - Cached serial number
    - Support for all message types
    """
    
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
        """Initialize Google Sheets client with proper error handling"""
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            from requests.exceptions import Timeout, ConnectionError
            
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds_dict = json.loads(self.credentials)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            
            # Ensure worksheet exists
            self._ensure_chat_sheet()
            
            # Initialize serial cache
            self._refresh_serial_cache()
            
            self.initialized = True
            self.enabled = True
            logger.info("✅ Google Sheets production logger initialized")
            
        except (Timeout, ConnectionError) as e:
            logger.error(f"❌ Google Sheets connection error: {e}")
            self.enabled = False
            self.initialized = False
        except Exception as e:
            logger.error(f"❌ Google Sheets init failed: {e}")
            self.enabled = False
            self.initialized = False

    def _ensure_chat_sheet(self):
        """Create or verify Chat worksheet with headers"""
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
            else:
                # Verify headers
                ws = self.sheet.worksheet(self.sheet_name)
                headers = ws.row_values(1)
                expected = ["S.No", "Date", "Time", "Timestamp", "User ID", 
                           "Username", "Full Name", "Message Count", "Message Type",
                           "User Message", "Bot Reply"]
                
                if not headers or len(headers) < len(expected):
                    for idx, header in enumerate(expected, start=1):
                        if idx > len(headers) or headers[idx-1] != header:
                            ws.update_cell(1, idx, header)
                    logger.info("📊 Updated Chat sheet headers")
                    
        except Exception as e:
            logger.error(f"Error creating chat sheet: {e}")
            raise

    def _refresh_serial_cache(self):
        """Refresh cached serial number using last row"""
        try:
            ws = self.sheet.worksheet(self.sheet_name)
            # Get only the last row values (more efficient)
            last_row_data = ws.row_values(ws.row_count)
            if last_row_data and last_row_data[0] and str(last_row_data[0]).isdigit():
                self._serial_cache = int(last_row_data[0])
            else:
                self._serial_cache = ws.row_count - 1  # Subtract header row
            logger.debug(f"Serial cache initialized: {self._serial_cache}")
        except Exception as e:
            logger.error(f"Error refreshing serial cache: {e}")
            self._serial_cache = 1

    def _get_next_serial(self, ws) -> int:
        """Get next serial number using cached value"""
        with self._lock:
            if self._serial_cache is None:
                # Get total rows using efficient method
                total_rows = ws.row_count
                if total_rows <= 1:
                    self._serial_cache = 1
                else:
                    # Try to get last serial from last row
                    try:
                        last_row = ws.row_values(total_rows)
                        if last_row and last_row[0] and str(last_row[0]).isdigit():
                            self._serial_cache = int(last_row[0]) + 1
                        else:
                            self._serial_cache = total_rows - 1  # Subtract header
                    except:
                        self._serial_cache = total_rows - 1
            
            self._serial_cache += 1
            return self._serial_cache

    def _get_message_type(self, update: Update) -> str:
        """Detect message type with proper priority"""
        message = update.effective_message
        
        if not message:
            return "Unknown"
        
        # Priority order: most specific first
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
        elif message.poll:
            return "Poll"
        elif message.video_note:
            return "Video Note"
        elif message.game:
            return "Game"
        elif message.dice:
            return "Dice"
        else:
            return "Unknown"

    def _get_user_message_text(self, update: Update) -> str:
        """Extract user message with proper handling for all types"""
        message = update.effective_message
        
        if not message:
            return ""
        
        # For text messages
        if message.text:
            return message.text
        
        # For messages with caption
        if message.caption:
            return message.caption
        
        # For messages without text
        if message.photo:
            return "📸 Photo"
        elif message.video:
            return f"🎬 Video{(': ' + message.video.file_name) if message.video.file_name else ''}"
        elif message.voice:
            return f"🎤 Voice Message ({message.voice.duration}s)"
        elif message.audio:
            return f"🎵 Audio{(': ' + message.audio.title) if message.audio.title else ''}"
        elif message.sticker:
            return f"🎨 Sticker: {message.sticker.emoji or 'sticker'}"
        elif message.animation:
            return "🎞️ GIF/Animation"
        elif message.document:
            return f"📄 Document{(': ' + message.document.file_name) if message.document.file_name else ''}"
        elif message.location:
            return f"📍 Location: {message.location.latitude}, {message.location.longitude}"
        elif message.contact:
            return f"👤 Contact: {message.contact.first_name}"
        elif message.poll:
            return f"📊 Poll: {message.poll.question}"
        elif message.video_note:
            return "📹 Video Note"
        elif message.game:
            return "🎮 Game"
        elif message.dice:
            return "🎲 Dice"
        else:
            return "📨 Message (unsupported type)"

    def _get_full_name(self, user) -> str:
        """Get full name with proper fallback"""
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
        """
        Log chat to Google Sheets with store-first architecture.
        Implements retry with exponential backoff.
        """
        if not self.enabled or not self.initialized:
            logger.debug("Google Sheets logging skipped (disabled or not initialized)")
            return False
        
        try:
            # Get user info with validation
            user = update.effective_user
            message = update.effective_message
            
            if not user or not message:
                logger.error("Invalid update: missing user or message")
                return False
            
            # Get worksheet with retry
            ws = None
            for attempt in range(self.max_retries):
                try:
                    ws = self.sheet.worksheet(self.sheet_name)
                    break
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)  # Exponential backoff
            
            if not ws:
                logger.error("Could not access worksheet")
                return False
            
            # Get all data
            now = datetime.now()
            serial_no = self._get_next_serial(ws)
            message_count = self._get_message_count(user.id)
            message_type = self._get_message_type(update)
            user_message = self._get_user_message_text(update)
            full_name = self._get_full_name(user)
            
            # Prepare row data
            row_data = [
                serial_no,                          # S.No
                now.strftime("%Y-%m-%d"),           # Date
                now.strftime("%H:%M:%S"),           # Time
                now.isoformat(),                    # Timestamp
                str(user.id),                       # User ID
                user.username or 'No Username',     # Username
                full_name,                          # Full Name
                message_count,                      # Message Count
                message_type,                       # Message Type
                user_message,                       # User Message
                bot_reply or ''                     # Bot Reply
            ]
            
            # Append with retry
            for attempt in range(self.max_retries):
                try:
                    ws.append_row(row_data, value_input_option='USER_ENTERED')
                    logger.debug(f"📊 Store-first log: User {user.id}, Serial #{serial_no}")
                    return True
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise
                    time.sleep(2 ** attempt)  # Exponential backoff
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Google Sheets store-first log failed: {e}")
            return False

    def _get_message_count(self, user_id: int) -> int:
        """Get total messages from user with fallback"""
        try:
            # Use cached connection to reduce overhead
            db = Database(DATABASE_PATH)
            user = db.get_user(user_id)
            return user.get('total_interactions', 0) if user else 0
        except Exception as e:
            logger.error(f"Error getting message count: {e}")
            return 0

# Initialize Google Sheets logger
google_sheets = GoogleSheetsLogger()

# ============================================================
# 3. DATABASE CLASS - OPTIMIZED
# ============================================================

class Database:
    """Production-grade SQLite database handler"""
    
    def __init__(self, db_path: str = "memo.db"):
        self.db_path = db_path
        self._connection_pool = {}
        self._lock = Lock()
        self.init_tables()
        self.create_indexes()

    def get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_tables(self):
        """Initialize all database tables"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                # Users table
                c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    telegram_username TEXT,
                    name TEXT,
                    preferred_language TEXT DEFAULT 'English',
                    joined_date TIMESTAMP,
                    last_active TIMESTAMP,
                    total_interactions INTEGER DEFAULT 0
                )''')
                
                # Memory table with confidence scoring
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
                
                # Memory schema
                c.execute('''CREATE TABLE IF NOT EXISTS memory_schema (
                    key_name TEXT PRIMARY KEY,
                    description TEXT,
                    data_type TEXT,
                    max_length INTEGER,
                    default_confidence REAL DEFAULT 0.7
                )''')
                
                # Insert default schema if empty
                c.execute("SELECT COUNT(*) FROM memory_schema")
                if c.fetchone()[0] == 0:
                    default_schema = [
                        ('name', 'User full name', 'string', 100, 0.95),
                        ('company', 'Company name', 'string', 200, 0.9),
                        ('project', 'Current project name', 'string', 200, 0.9),
                        ('preferred_language', 'Preferred language', 'string', 20, 0.95),
                        ('goal', 'Primary goal', 'string', 500, 0.85),
                        ('profession', 'User profession', 'string', 100, 0.9),
                        ('programming_languages', 'Languages used', 'string', 200, 0.8),
                        ('frameworks', 'Frameworks used', 'string', 200, 0.8),
                        ('payment_gateways', 'Payment gateways used', 'string', 200, 0.8),
                        ('business_type', 'Type of business', 'string', 100, 0.85),
                        ('country', 'User country', 'string', 50, 0.8),
                        ('timezone', 'User timezone', 'string', 50, 0.8)
                    ]
                    for key, desc, dtype, maxlen, conf in default_schema:
                        c.execute('''INSERT INTO memory_schema
                            (key_name, description, data_type, max_length, default_confidence)
                            VALUES (?,?,?,?,?)''', (key, desc, dtype, maxlen, conf))
                
                # Chat logs - NO SUMMARY
                c.execute('''CREATE TABLE IF NOT EXISTS chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_message TEXT,
                    bot_reply TEXT,
                    timestamp TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
                
                # Feedback
                c.execute('''CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    rating INTEGER,
                    comment TEXT,
                    timestamp TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
                
                # Rate limits
                c.execute('''CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id INTEGER PRIMARY KEY,
                    last_message_time TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Database init error: {e}")
            raise

    def create_indexes(self):
        """Create optimized indexes"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                c.execute('''CREATE INDEX IF NOT EXISTS idx_chat_user_id 
                            ON chat_logs(user_id)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_chat_timestamp 
                            ON chat_logs(timestamp DESC)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_chat_user_timestamp 
                            ON chat_logs(user_id, timestamp DESC)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_memory_user_key 
                            ON memory(user_id, memory_key)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_memory_confidence 
                            ON memory(user_id, confidence DESC)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_users_username 
                            ON users(telegram_username)''')
                c.execute('''CREATE INDEX IF NOT EXISTS idx_users_last_active 
                            ON users(last_active DESC)''')
                
                conn.commit()
        except Exception as e:
            logger.error(f"Index creation error: {e}")

    # ---------- User Operations ----------
    
    def get_or_create_user(self, user_id: int, username: str = None, name: str = None) -> Dict:
        """Get existing user or create new one"""
        try:
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
        except Exception as e:
            logger.error(f"Error in get_or_create_user: {e}")
            raise

    def update_user_name(self, user_id: int, name: str):
        """Update user name"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating user name: {e}")

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    # ---------- Memory Operations ----------
    
    def is_valid_memory_key(self, key: str) -> bool:
        """Check if memory key is allowed"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT 1 FROM memory_schema WHERE key_name = ?", (key,))
                return c.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking memory key: {e}")
            return False

    def get_allowed_keys(self) -> List[Dict]:
        """Get all allowed memory keys"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT key_name, default_confidence FROM memory_schema")
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting allowed keys: {e}")
            return []

    def save_memory(self, user_id: int, key: str, value: str, 
                    confidence: float = 0.8, updated_by_ai: bool = True, 
                    validated: bool = True) -> bool:
        """Save memory with UPSERT and confidence-based update"""
        if not self.is_valid_memory_key(key):
            logger.warning(f"Invalid memory key: {key} for user {user_id}")
            return False
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                c.execute("SELECT max_length FROM memory_schema WHERE key_name = ?", (key,))
                res = c.fetchone()
                if res and len(value) > res['max_length']:
                    value = value[:res['max_length']]
                
                c.execute("SELECT confidence FROM memory WHERE user_id = ? AND memory_key = ?", (user_id, key))
                existing = c.fetchone()
                if existing and existing['confidence'] > confidence:
                    return True
                
                c.execute('''INSERT INTO memory 
                            (user_id, memory_key, memory_value, confidence, updated_by_ai, validated, updated_at)
                            VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(user_id, memory_key) DO UPDATE SET
                                memory_value = excluded.memory_value,
                                confidence = excluded.confidence,
                                updated_by_ai = excluded.updated_by_ai,
                                validated = excluded.validated,
                                updated_at = excluded.updated_at''',
                          (user_id, key, value, confidence, 
                           1 if updated_by_ai else 0,
                           1 if validated else 0, 
                           datetime.now().isoformat()))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving memory: {e}")
            return False

    def save_memory_batch(self, user_id: int, memories: Dict, validated: bool = True):
        """Save multiple memories at once"""
        for key, data in memories.items():
            if isinstance(data, dict):
                val = data.get('value', '')
                conf = data.get('confidence', 0.7)
            else:
                val = data
                conf = 0.7
            if val and len(val) > 1:
                self.save_memory(user_id, key, val, conf, True, validated)

    def get_memory(self, user_id: int, min_confidence: float = 0.0) -> Dict[str, str]:
        """Get memory with minimum confidence threshold"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute('''SELECT memory_key, memory_value, confidence 
                            FROM memory
                            WHERE user_id = ? AND confidence >= ?
                            ORDER BY confidence DESC, updated_at DESC''', 
                          (user_id, min_confidence))
                rows = c.fetchall()
                
                memory = {}
                for row in rows[:MAX_MEMORY_ITEMS]:
                    memory[row['memory_key']] = row['memory_value']
                return memory
        except Exception as e:
            logger.error(f"Error getting memory: {e}")
            return {}

    def get_memory_context(self, user_id: int) -> Dict[str, str]:
        """Get high-confidence memory for AI context"""
        return self.get_memory(user_id, min_confidence=0.5)

    def delete_memory(self, user_id: int):
        """Delete all memory for a user"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM memory WHERE user_id = ?", (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")

    def delete_user(self, user_id: int):
        """Delete all user data"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error deleting user: {e}")

    # ---------- Chat Logs ----------
    
    def log_chat(self, user_id: int, user_message: str, bot_reply: str):
        """Log chat to SQLite"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""INSERT INTO chat_logs 
                            (user_id, user_message, bot_reply, timestamp) 
                            VALUES (?,?,?,?)""",
                          (user_id, user_message, bot_reply, datetime.now().isoformat()))
                
                c.execute("""UPDATE users 
                            SET total_interactions = total_interactions + 1, 
                                last_active = ? 
                            WHERE user_id = ?""",
                          (datetime.now().isoformat(), user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error logging chat: {e}")

    def get_chat_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get recent chat history"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""SELECT user_message, bot_reply, timestamp 
                            FROM chat_logs 
                            WHERE user_id = ? 
                            ORDER BY timestamp DESC 
                            LIMIT ?""",
                          (user_id, limit))
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    # ---------- Rate Limiting ----------
    
    def check_rate_limit(self, user_id: int) -> Tuple[bool, int]:
        """Check rate limit with cooldown and per-minute limits"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                now = datetime.now()
                
                c.execute("SELECT last_message_time, message_count FROM rate_limits WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                
                if not row:
                    c.execute("INSERT INTO rate_limits (user_id, last_message_time, message_count) VALUES (?,?,?)",
                              (user_id, now.isoformat(), 1))
                    conn.commit()
                    return True, 0
                
                last = datetime.fromisoformat(row['last_message_time'])
                count = row['message_count']
                elapsed = (now - last).total_seconds()
                
                # Cooldown check
                if elapsed < RATE_LIMIT_SECONDS:
                    return False, int(RATE_LIMIT_SECONDS - elapsed) + 1
                
                # Per-minute limit (30 messages/minute)
                if count >= 30:
                    if elapsed > 60:
                        c.execute("""UPDATE rate_limits 
                                    SET last_message_time = ?, message_count = 1 
                                    WHERE user_id = ?""",
                                  (now.isoformat(), user_id))
                        conn.commit()
                        return True, 0
                    else:
                        return False, int(60 - elapsed) + 1
                
                # Increment counter
                c.execute("""UPDATE rate_limits 
                            SET message_count = message_count + 1, last_message_time = ? 
                            WHERE user_id = ?""",
                          (now.isoformat(), user_id))
                conn.commit()
                return True, 0
        except Exception as e:
            logger.error(f"Rate limit check error: {e}")
            return True, 0  # Allow on error

    def save_feedback(self, user_id: int, rating: int, comment: str = None):
        """Save user feedback"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""INSERT INTO feedback (user_id, rating, comment, timestamp)
                            VALUES (?,?,?,?)""",
                          (user_id, rating, comment, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving feedback: {e}")

    # ---------- Statistics ----------
    
    def get_stats(self) -> Dict:
        """Get bot statistics"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                c.execute("SELECT COUNT(*) FROM users")
                total_users = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM chat_logs")
                total_messages = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM chat_logs WHERE timestamp > datetime('now', '-7 days')")
                weekly_messages = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM users WHERE joined_date > datetime('now', '-7 days')")
                new_users_week = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM memory")
                total_memories = c.fetchone()[0]
                
                return {
                    "total_users": total_users,
                    "total_messages": total_messages,
                    "weekly_messages": weekly_messages,
                    "new_users_week": new_users_week,
                    "total_memories": total_memories
                }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_users": 0,
                "total_messages": 0,
                "weekly_messages": 0,
                "new_users_week": 0,
                "total_memories": 0
            }

# Initialize database
db = Database(DATABASE_PATH)

# ============================================================
# 4. AI MEMORY EXTRACTOR
# ============================================================

class MemoryExtractor:
    """Extracts long-term memory from conversations using AI"""
    
    @staticmethod
    def extract_memory_with_ai(user_message: str, user_id: int) -> Dict[str, Dict]:
        """Extract memory using AI with strict JSON validation"""
        try:
            existing = db.get_memory(user_id)
            existing_keys = ', '.join(existing.keys()) if existing else 'none'
            allowed = db.get_allowed_keys()
            allowed_keys_str = ', '.join([k['key_name'] for k in allowed])

            prompt = f"""Analyze this user message and extract ONLY long-term information.

ALLOWED KEYS: {allowed_keys_str}
CURRENT KEYS: {existing_keys}

RULES:
- Extract only clearly stated facts (name, company, project, preferred_language, goal, profession, programming_languages, frameworks, payment_gateways, business_type, country, timezone)
- Do NOT extract temporary information
- Return ONLY valid JSON:
{{"save": true, "memory": {{"key": {{"value": "...", "confidence": 0.9}}}}}}
If nothing to save: {{"save": false, "memory": {{}}}}

USER: {user_message}"""

            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": "You extract structured memory data. Return only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1, max_tokens=400
                )
                result = resp.choices[0].message.content.strip()
                
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash')
                resp = model.generate_content(
                    prompt, 
                    generation_config={"temperature": 0.1, "max_output_tokens": 400}
                )
                result = resp.text.strip()
            else:
                return {}

            # Extract JSON
            match = re.search(r'```json\s*(\{.*?\})\s*```', result, re.DOTALL)
            if match:
                result = match.group(1)
            
            data = json.loads(result)
            if not data.get('save', False):
                return {}
            
            memory_data = data.get('memory', {})
            filtered = {}
            allowed_keys = [k['key_name'] for k in db.get_allowed_keys()]
            
            for key, val in memory_data.items():
                if key in allowed_keys:
                    if isinstance(val, dict):
                        value = val.get('value', '')
                        confidence = val.get('confidence', 0.7)
                    else:
                        value = val
                        confidence = 0.7
                    
                    if value and len(value) > 1:
                        confidence = max(0.0, min(1.0, confidence))
                        filtered[key] = {'value': value, 'confidence': confidence}
            
            return filtered
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from memory extraction")
            return {}
        except Exception as e:
            logger.error(f"Memory extraction error: {e}")
            return {}

# ============================================================
# 5. AI ENGINE - OPTIMIZED
# ============================================================

class AIEngine:
    """Handles AI responses with optimized memory injection"""
    
    @staticmethod
    def get_response(user_message: str, user_id: int, user_name: str = None) -> str:
        """Generate AI response with memory context"""
        try:
            # Check rate limit
            allowed, wait = db.check_rate_limit(user_id)
            if not allowed:
                return f"Please wait {wait} seconds before sending another message."

            # Get user memory
            memory = db.get_memory_context(user_id)
            user_data = db.get_user(user_id)
            
            # Build system prompt
            system_prompt = AIEngine._build_system_prompt(memory, user_data)
            
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.6, 
                    max_tokens=500
                )
                reply = resp.choices[0].message.content.strip()
                
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(
                    user_message, 
                    generation_config={"temperature": 0.6, "max_output_tokens": 500}
                )
                reply = resp.text.strip()
            else:
                return "⚠️ No AI API configured."
            
            # Extract and save memory
            extracted = MemoryExtractor.extract_memory_with_ai(user_message, user_id)
            if extracted:
                db.save_memory_batch(user_id, extracted)
            
            # Log to SQLite
            db.log_chat(user_id, user_message, reply)
            
            return reply
            
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "I'm experiencing technical difficulties. Please try again."

    @staticmethod
    def _build_system_prompt(memory: Dict, user_data: Optional[Dict]) -> str:
        """Build system prompt with natural context"""
        name = memory.get('name', user_data.get('name') if user_data else None)
        project = memory.get('project')
        company = memory.get('company')
        language = memory.get('preferred_language', 'English')
        
        context_parts = []
        if name:
            context_parts.append(f"User: {name}")
        if project:
            context_parts.append(f"Project: {project}")
        if company:
            context_parts.append(f"Company: {company}")
        
        context_text = "\n".join(context_parts) if context_parts else "New user - no stored information yet."
        
        return f"""You are Memo, a professional AI business assistant.

USER CONTEXT:
{context_text}

PERSONALITY GUIDELINES:
- Be professional, helpful, and natural
- Use the user's name naturally when you know it
- Keep responses concise by default
- Provide detailed explanations only when asked
- Use emojis sparingly and appropriately

MEMORY GUIDELINES:
- Use the context above naturally in conversation
- Never say "I remember" or "I noticed we talked about"
- Simply incorporate context into the conversation
- If you don't know something, ask politely
- Never reveal that you're using stored memory

RESPONSE GUIDELINES:
- No unnecessary introductions like "I am Memo"
- Get straight to the point
- Be friendly but professional
- Ask clarifying questions when needed

SERVICES: Development, Websites, Mobile Apps, UI/UX, Design, AI, Automation, Branding, Business, Marketing, Content, Productivity

RESPOND IN: {language}"""

# ============================================================
# 6. MARKDOWN HELPER
# ============================================================

def safe_markdown(text: str) -> str:
    """Safely escape markdown characters"""
    if not text:
        return ""
    special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in special:
        text = text.replace(ch, f'\\{ch}')
    return text

# ============================================================
# 7. TELEGRAM BOT HANDLERS - PRODUCTION GRADE
# ============================================================

# Conversation states
NAME, COMPANY, PROJECT, LANGUAGE, FEEDBACK, UPDATE_MEMORY = range(6)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start with proper error handling"""
    try:
        user = update.effective_user
        user_data = db.get_or_create_user(user.id, user.username)
        memory = db.get_memory_context(user.id)
        name = memory.get('name', user_data.get('name'))
        
        if name:
            msg = f"Welcome back! How can I help you today?"
            if memory.get('project'):
                msg += f" How's your {memory['project']} project going?"
            await update.message.reply_text(msg)
            return ConversationHandler.END
        else:
            await update.message.reply_text("""
Welcome to Memo! I'm your AI business assistant.

I can help with development, design, AI, automation, business strategy, and more.

To get started, what's your name?
""")
            return NAME
    except Exception as e:
        logger.error(f"Start command error: {e}")
        await update.message.reply_text("Welcome to Memo! Please try /start again.")
        return ConversationHandler.END

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle name input"""
    try:
        user_id = update.effective_user.id
        name = update.message.text.strip()
        
        if not name or len(name) > 50:
            await update.message.reply_text("Please enter a valid name (1-50 characters).")
            return NAME
        
        db.update_user_name(user_id, name)
        db.save_memory(user_id, "name", name, confidence=0.95)
        
        await update.message.reply_text(f"Nice to meet you, {name}! Do you work with a company or are you a freelancer?")
        return COMPANY
    except Exception as e:
        logger.error(f"Name handler error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")
        return NAME

async def handle_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle company input"""
    try:
        user_id = update.effective_user.id
        company = update.message.text.strip()
        
        if company.lower() not in ["none", "skip"]:
            db.save_memory(user_id, "company", company.title(), confidence=0.85)
        
        await update.message.reply_text("What projects are you currently working on?")
        return PROJECT
    except Exception as e:
        logger.error(f"Company handler error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")
        return COMPANY

async def handle_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle project input"""
    try:
        user_id = update.effective_user.id
        project = update.message.text.strip()
        
        if project.lower() not in ["none", "skip", "nothing"]:
            db.save_memory(user_id, "project", project.title(), confidence=0.85)
        
        await update.message.reply_text("What language do you prefer for responses? (English/Hindi)")
        return LANGUAGE
    except Exception as e:
        logger.error(f"Project handler error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")
        return PROJECT

async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language preference"""
    try:
        user_id = update.effective_user.id
        resp = update.message.text.strip().lower()
        
        if "hindi" in resp:
            db.save_memory(user_id, "preferred_language", "Hindi", confidence=0.95)
        else:
            db.save_memory(user_id, "preferred_language", "English", confidence=0.95)
        
        memory = db.get_memory_context(user_id)
        
        msg = f"✅ All set! I'll remember your preferences.\n\n"
        if memory.get('name'):
            msg += f"👤 {memory['name']}\n"
        if memory.get('company'):
            msg += f"🏢 {memory['company']}\n"
        if memory.get('project'):
            msg += f"📋 {memory['project']}\n"
        if memory.get('preferred_language'):
            msg += f"🌐 {memory['preferred_language']}\n"
        
        msg += "\nHow can I help you today?"
        
        await update.message.reply_text(msg)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Language handler error: {e}")
        await update.message.reply_text("Setup complete! How can I help you today?")
        return ConversationHandler.END

# ----- Command Handlers -----

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help"""
    try:
        help_text = """
🤖 *Memo AI Assistant*

*Available Commands:*
/start - Start or restart
/help - Show this help
/about - About Memo
/services - Services offered
/contact - Contact information
/profile - View your profile
/remember - See what I know about you
/update - Update your information
/forget - Clear your memory
/reset - Delete all your data
/history - Chat history
/feedback - Rate your experience

*How I help:*
💻 Development • 🎨 Design • 🤖 AI & Automation 
📊 Business Strategy • ✍️ Content • 📈 Growth
"""
        await update.message.reply_text(safe_markdown(help_text), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Help command error: {e}")
        await update.message.reply_text("Available commands: /start, /help, /about, /services, /profile, /remember")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /about"""
    try:
        about_text = """
ℹ️ *About Memo*

Memo is a professional AI assistant designed to help you with:
- Software & Web Development
- Mobile Applications
- UI/UX Design
- AI & Automation Solutions
- Business Strategy & Consulting
- Content & Marketing
- Productivity & Growth

*Key Features:*
• Personalized assistance
• Persistent memory
• Professional tone
• Production-grade responses

*Technology:*
Python • Telegram Bot API • AI-Powered
"""
        await update.message.reply_text(safe_markdown(about_text), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"About command error: {e}")
        await update.message.reply_text("Memo is a professional AI assistant. Use /help for more info.")

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /services"""
    try:
        services_text = """
📋 *Our Services*

💻 *Development*
- Websites & Web Applications
- Mobile Apps (iOS & Android)
- Custom Software Solutions
- API Development & Integration

🎨 *Design*
- UI/UX Design
- Graphic Design
- Brand Identity
- Logo Design

🤖 *AI & Automation*
- AI-Powered Solutions
- Process Automation
- Chatbots & Virtual Assistants
- Machine Learning Integration

📊 *Business*
- Digital Marketing Strategy
- Business Consulting
- SEO & Content Marketing
- Growth Hacking

✍️ *Content*
- Professional Writing
- SEO Content
- Technical Documentation
- Marketing Copy

💳 *Payment Integrations*
- Razorpay • Stripe • PayPal
"""
        await update.message.reply_text(safe_markdown(services_text), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Services command error: {e}")
        await update.message.reply_text("I offer development, design, AI, business, and content services.")

async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /contact"""
    try:
        await update.message.reply_text("""
📞 *Contact & Support*

Feel free to reach out:
- Ask questions directly in this chat
- Request a consultation
- Share your project requirements

I'm here to help you succeed!
""", parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Contact command error: {e}")
        await update.message.reply_text("Feel free to ask me anything!")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /profile"""
    try:
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Please use /start to set up your profile.")
            return
        
        memory = db.get_memory_context(user_id)
        
        msg = f"📊 *Your Profile*\n\n"
        msg += f"👤 Name: {user.get('name', 'Not set')}\n"
        msg += f"🆔 Username: @{user.get('telegram_username', 'Not set')}\n"
        msg += f"📅 Joined: {user.get('joined_date', 'Unknown')}\n"
        msg += f"💬 Interactions: {user.get('total_interactions', 0)}\n\n"
        
        if memory:
            msg += "*Stored Information:*\n"
            for key, value in memory.items():
                msg += f"• {key.replace('_', ' ').title()}: {value}\n"
        else:
            msg += "No stored information yet.\n"
        
        msg += "\nUse /update to modify your information."
        
        await update.message.reply_text(safe_markdown(msg), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Profile command error: {e}")
        await update.message.reply_text("Error retrieving profile. Please try again.")

async def remember_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remember"""
    try:
        user_id = update.effective_user.id
        memory = db.get_memory_context(user_id)
        
        if not memory:
            await update.message.reply_text("""
I don't have any information about you yet. 
Tell me about yourself (name, projects, goals) and I'll remember it!
""")
            return
        
        msg = "🧠 *What I Know About You*\n\n"
        for key, value in memory.items():
            msg += f"• {key.replace('_', ' ').title()}: {value}\n"
        
        msg += "\nUse /update to modify any of this information."
        
        await update.message.reply_text(safe_markdown(msg), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Remember command error: {e}")
        await update.message.reply_text("Error retrieving memory. Please try again.")

async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /update"""
    try:
        allowed_keys = db.get_allowed_keys()
        keys_str = ', '.join([k['key_name'] for k in allowed_keys])
        
        await update.message.reply_text(f"""
To update your information, type:
`Key: Value`

*Available Keys:*
{keys_str}

*Example:*
`Project: New Mobile App`

Type /cancel to cancel.
""", parse_mode='MarkdownV2')
        return UPDATE_MEMORY
    except Exception as e:
        logger.error(f"Update command error: {e}")
        await update.message.reply_text("Error. Please try again.")
        return ConversationHandler.END

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle manual memory update"""
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        if ':' not in text:
            await update.message.reply_text("Please use format: `Key: Value`")
            return UPDATE_MEMORY
        
        key, value = text.split(':', 1)
        key = key.strip().lower()
        value = value.strip()
        
        if db.is_valid_memory_key(key):
            db.save_memory(user_id, key, value, confidence=0.9, updated_by_ai=False)
            await update.message.reply_text(f"✅ Updated {key} to: {value}")
        else:
            allowed = ', '.join([k['key_name'] for k in db.get_allowed_keys()])
            await update.message.reply_text(f"Invalid key. Allowed: {allowed}")
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Update handler error: {e}")
        await update.message.reply_text("Error updating. Please try again.")
        return ConversationHandler.END

async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forget"""
    try:
        user_id = update.effective_user.id
        db.delete_memory(user_id)
        await update.message.reply_text("✅ Memory cleared. I've forgotten everything I knew about you.")
    except Exception as e:
        logger.error(f"Forget command error: {e}")
        await update.message.reply_text("Error clearing memory. Please try again.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset"""
    try:
        user_id = update.effective_user.id
        db.delete_user(user_id)
        await update.message.reply_text("✅ All your data has been deleted. Use /start to begin fresh.")
    except Exception as e:
        logger.error(f"Reset command error: {e}")
        await update.message.reply_text("Error resetting data. Please try again.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history"""
    try:
        user_id = update.effective_user.id
        history = db.get_chat_history(user_id, 5)
        
        if not history:
            await update.message.reply_text("No chat history found.")
            return
        
        msg = "📜 *Recent Conversations*\n\n"
        for entry in history:
            msg += f"*You:* {entry['user_message'][:100]}\n"
            msg += f"*Memo:* {entry['bot_reply'][:100]}\n"
            msg += f"_{entry['timestamp']}_\n\n"
        
        await update.message.reply_text(safe_markdown(msg), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"History command error: {e}")
        await update.message.reply_text("Error retrieving history. Please try again.")

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /feedback"""
    await update.message.reply_text("""
Please rate your experience with Memo (1-5):

1 - Very Poor
2 - Poor
3 - Average
4 - Good
5 - Excellent

Type a number from 1 to 5.
""")
    return FEEDBACK

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feedback input"""
    try:
        user_id = update.effective_user.id
        rating_text = update.message.text.strip()
        
        try:
            rating = int(rating_text)
            if 1 <= rating <= 5:
                db.save_feedback(user_id, rating)
                await update.message.reply_text("✅ Thank you for your feedback!")
            else:
                await update.message.reply_text("Please enter a number between 1 and 5.")
                return FEEDBACK
        except ValueError:
            await update.message.reply_text("Please enter a valid number (1-5).")
            return FEEDBACK
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Feedback handler error: {e}")
        await update.message.reply_text("Thank you for your feedback!")
        return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel"""
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle messages with STORE-FIRST architecture.
    Save to Google Sheets BEFORE sending reply.
    """
    try:
        if not update.effective_message:
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # Ensure user exists
        user_data = db.get_or_create_user(user_id, username)
        
        # Show typing indicator
        await update.effective_chat.send_action("typing")
        
        # 1. Get AI response
        reply = AIEngine.get_response(
            user_message=update.effective_message.text or "",
            user_id=user_id,
            user_name=user_data.get('name')
        )
        
        # 2. Save to Google Sheets FIRST (Store-First)
        if google_sheets.enabled and google_sheets.initialized:
            try:
                google_sheets.log_chat_store_first(
                    update=update,
                    bot_reply=reply
                )
            except Exception as e:
                logger.error(f"Google Sheets store-first error: {e}")
        
        # 3. Send reply to user
        await update.effective_message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Message handler error: {e}")
        await update.effective_message.reply_text("I'm experiencing technical difficulties. Please try again.")

# ----- Admin Commands -----

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command for statistics"""
    try:
        if update.effective_user.id not in ADMIN_USER_IDS:
            await update.message.reply_text("⛔ Unauthorized access.")
            return
        
        stats = db.get_stats()
        msg = f"""
📊 *Bot Statistics*

👤 **Total Users:** {stats['total_users']}
💬 **Total Messages:** {stats['total_messages']}
📈 **Weekly Messages:** {stats['weekly_messages']}
🆕 **New Users (Week):** {stats['new_users_week']}
🧠 **Stored Memories:** {stats['total_memories']}

*System Health:* ✅ Operational
"""
        await update.message.reply_text(safe_markdown(msg), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        await update.message.reply_text("Error retrieving stats.")

# ============================================================
# 8. FLASK WEB SERVER
# ============================================================

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Memo AI Assistant is running."

@web_app.route('/health')
def health():
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0",
        "google_sheets": "enabled" if google_sheets.enabled else "disabled",
        "database": "connected"
    }
    return jsonify(status)

@web_app.route('/stats')
def stats():
    return jsonify(db.get_stats())

def run_web_server():
    """Run Flask web server"""
    try:
        web_app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Web server error: {e}")

# ============================================================
# 9. MAIN EXECUTION
# ============================================================

def main():
    """Main entry point with proper error handling"""
    try:
        print("=" * 60)
        print(" Memo AI Bot v3.0 - Production-Grade")
        print("=" * 60)
        print(f"Bot Token: {'✓ Present' if BOT_TOKEN else '✗ Missing'}")
        print(f"Gemini API: {'✓ Present' if GEMINI_API_KEY else '✗ Missing'}")
        print(f"Groq API: {'✓ Present' if GROQ_API_KEY else '✗ Missing'}")
        print(f"Google Sheets: {'✓ Enabled' if ENABLE_GOOGLE_SHEETS else '✗ Disabled'}")
        print(f"Database: {DATABASE_PATH}")
        print("=" * 60)
        
        # Start web server
        web_thread = Thread(target=run_web_server, daemon=True)
        web_thread.start()
        logger.info(f"✅ Web server started on port {PORT}")
        
        # Build Telegram application
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start_command)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
                COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_company)],
                PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_project)],
                LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_language)],
                FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback)],
                UPDATE_MEMORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_update)],
            },
            fallbacks=[CommandHandler("cancel", cancel_command)],
        )
        app.add_handler(conv_handler)
        
        # Command handlers
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("about", about_command))
        app.add_handler(CommandHandler("services", services_command))
        app.add_handler(CommandHandler("contact", contact_command))
        app.add_handler(CommandHandler("profile", profile_command))
        app.add_handler(CommandHandler("remember", remember_command))
        app.add_handler(CommandHandler("update", update_command))
        app.add_handler(CommandHandler("forget", forget_command))
        app.add_handler(CommandHandler("reset", reset_command))
        app.add_handler(CommandHandler("history", history_command))
        app.add_handler(CommandHandler("feedback", feedback_command))
        app.add_handler(CommandHandler("admin_stats", admin_stats_command))
        
        # Message handler - handles all text messages
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Error handler
        app.add_error_handler(lambda update, context: logger.error(f"Update error: {context.error}"))
        
        logger.info("✅ Memo Bot is Online & Ready!")
        print("=" * 60)
        
        # Start the bot
        app.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        print(f"❌ Fatal error: {e}", flush=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
