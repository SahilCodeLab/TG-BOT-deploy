"""
SahilCodeLab AI Business Assistant - Production-Grade Bot & API
Brand: SahilCodeLab (sahilcodelab.vercel.app)
Contact Email: sahil.dev@gmail.com
Features: Persistent Memory, SQLite, Professional Pricing Engine (USD),
          Visual Project Showcase, Native Chat-Based Contact Form, and FastAPI Server.
"""

import os
import sys
import json
import logging
import sqlite3
from datetime import datetime
from threading import Thread
from fastapi import FastAPI
import uvicorn
import google.generativeai as genai
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# ============================================================
# 1. CONFIGURATION & BRAND IDENTITY
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "sahilcodelab.db")
PORT = int(os.getenv("PORT", 8000))

BRAND_NAME = "SahilCodeLab"
BRAND_URL = "https://sahilcodelab.vercel.app"
CONTACT_EMAIL = "sahil.dev@gmail.com"

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Missing!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 2. PRICING & SHOWCASE CATALOGUE (USD $ Engine)
# ============================================================

SERVICES_CATALOGUE = {
    "web": {
        "title": "💻 Custom Website & Web App",
        "price": "$299 - $899+",
        "desc": "High-performance React/Next.js/Node web apps with stunning UI/UX, SEO optimization, and fast speed.",
        "image": "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=800"
    },
    "mobile": {
        "title": "📱 Mobile App Development (iOS & Android)",
        "price": "$499 - $1,499+",
        "desc": "Cross-platform Flutter apps with native performance, secure local database, and smooth animations.",
        "image": "https://images.unsplash.com/photo-1512941937669-90a1b58e7e9c?w=800"
    },
    "saas": {
        "title": "🚀 SaaS Product Architecture",
        "price": "$999 - $2,500+",
        "desc": "End-to-end MVP development, user authentication, dashboard UI, and scalable backend infrastructure.",
        "image": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800"
    },
    "payment": {
        "title": "💳 Payment Gateway Integration",
        "price": "$150 - $350",
        "desc": "Seamless integration of Stripe, Razorpay, or PayPal with secure webhooks and subscription billing.",
        "image": "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"
    },
    "ai": {
        "title": "🤖 AI Bots & Automation",
        "price": "$399 - $999+",
        "desc": "Custom Telegram/WhatsApp bots, LLM integrations (Groq/Gemini), and n8n workflow automations.",
        "image": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800"
    }
}

PROJECT_SHOWCASE = [
    {
        "name": "Aura Notes",
        "category": "Productivity App (10K+ Downloads)",
        "desc": "A secure offline notepad with sleek dark UI and high performance.",
        "image": "https://images.unsplash.com/photo-1517842645767-c639042777db?w=800"
    },
    {
        "name": "Wrapify",
        "category": "Chat Analytics Platform",
        "desc": "Parses offline logs to generate rich statistics and dynamic insight cards.",
        "image": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800"
    },
    {
        "name": "PocketID",
        "category": "Secure Document Vault",
        "desc": "Encrypted local digital vault with custom animations and subscription models.",
        "image": "https://images.unsplash.com/photo-1633167606207-d840b5070fc2?w=800"
    }
]

# ============================================================
# 3. DATABASE CLASS (Persistent Memory & Leads)
# ============================================================

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_tables()

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
                username TEXT,
                name TEXT,
                joined_date TIMESTAMP,
                last_active TIMESTAMP,
                total_interactions INTEGER DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_requested TEXT,
                budget TEXT,
                status TEXT DEFAULT 'New',
                timestamp TIMESTAMP
            )''')
            conn.commit()

    def save_user(self, user_id: int, username: str, name: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO users (user_id, username, name, joined_date, last_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_active = ?
            """, (user_id, username, name, datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()

    def log_lead(self, user_id: int, service: str, budget: str):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO leads (user_id, service_requested, budget, timestamp) VALUES (?,?,?,?)",
                      (user_id, service, budget, datetime.now().isoformat()))
            conn.commit()

db = Database()

# ============================================================
# 4. BRAND AI ENGINE (SahilCodeLab Persona)
# ============================================================

class AIEngine:
    @staticmethod
    def get_response(user_message: str, user_id: int) -> str:
        system_prompt = f"""You are the official AI Business Representative for {BRAND_NAME} (founded by Sahil Raza). 
Portfolio Studio: {BRAND_URL}
Direct Contact Email: {CONTACT_EMAIL}

Your Expertise:
- Custom Web Apps, Mobile Apps (Flutter/Android/iOS), Full SaaS Product Development.
- Payment Gateway Integrations (Stripe, Razorpay, PayPal).
- AI Bots, Workflow Automation, and UI/UX Design.

Tone & Style:
- Professional, premium, confident, tech-savvy, and concise.
- Direct-to-the-point answers.
- Always provide contact via email ({CONTACT_EMAIL}) or portfolio ({BRAND_URL}) when clients inquire about hiring or custom quotes.
"""
        try:
            if GROQ_API_KEY:
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                    temperature=0.5, max_tokens=400
                )
                return resp.choices[0].message.content.strip()
            elif GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
                resp = model.generate_content(user_message)
                return resp.text.strip()
            else:
                return f"Hello! Welcome to {BRAND_NAME}. Reach us directly at {CONTACT_EMAIL}."
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return f"Feel free to email us directly at {CONTACT_EMAIL} or visit {BRAND_URL}."

# ============================================================
# 5. TELEGRAM BOT HANDLERS & NATIVE CONTACT FORM
# ============================================================

# Conversation States for Contact Form
CONTACT_NAME, CONTACT_EMAIL_STATE, CONTACT_MESSAGE = range(3)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🚀 View Services & Pricing", callback_data="menu_services")],
        [InlineKeyboardButton("📂 Our App Showcase", callback_data="menu_showcase")],
        [InlineKeyboardButton("💼 Hire / Contact Us", callback_data="menu_hire")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = (
        f"👋 Welcome to **{BRAND_NAME}** Official Bot!\n\n"
        f"We build high-performance Web Apps, Mobile Applications, SaaS Products, and custom AI Solutions.\n\n"
        f"📧 Direct Email: `{CONTACT_EMAIL}`\n"
        f"🌐 Portfolio: {BRAND_URL}\n\n"
        "Explore our work or check pricing below:"
    )
    
    if update.message:
        await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "menu_services":
        text = "📋 **SahilCodeLab Services & Pricing (USD)**\n\nChoose a category to view details:"
        keyboard = [
            [InlineKeyboardButton("💻 Web Apps ($299+)", callback_data="srv_web")],
            [InlineKeyboardButton("📱 Mobile Apps ($499+)", callback_data="srv_mobile")],
            [InlineKeyboardButton("🚀 SaaS Products ($999+)", callback_data="srv_saas")],
            [InlineKeyboardButton("💳 Payments ($150+)", callback_data="srv_payment")],
            [InlineKeyboardButton("🤖 AI & Bots ($399+)", callback_data="srv_ai")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_home")]
        ]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif query.data.startswith("srv_"):
        key = query.data.split("_")[1]
        srv = SERVICES_CATALOGUE[key]
        text = f"*{srv['title']}*\n\n💰 **Estimated Price:** `{srv['price']}`\n\n📖 {srv['desc']}\n\n📧 To book: `{CONTACT_EMAIL}`"
        
        keyboard = [
            [InlineKeyboardButton("💼 Hire for this Project", callback_data=f"hire_{key}")],
            [InlineKeyboardButton("⬅️ Back to Services", callback_data="menu_services")]
        ]
        
        await query.message.delete()
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=srv['image'],
            caption=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "menu_showcase":
        await query.message.delete()
        for proj in PROJECT_SHOWCASE:
            caption = f"🏆 *{proj['name']}*\n🏷️ _{proj['category']}_\n\n📝 {proj['desc']}"
            keyboard = [[InlineKeyboardButton("🌐 Visit Portfolio", url=BRAND_URL)]]
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=proj['image'],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        back_kb = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_home")]]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Want us to build something custom for you?",
            reply_markup=InlineKeyboardMarkup(back_kb)
        )

    elif query.data == "menu_home":
        await query.message.delete()
        await start_command(update, context)

    elif query.data.startswith("hire_"):
        key = query.data.split("_")[1]
        srv = SERVICES_CATALOGUE[key]
        user = update.effective_user
        db.log_lead(user.id, srv['title'], srv['price'])
        
        text = f"✅ **Inquiry Logged!**\n\nWe received your request for *{srv['title']}* (`{srv['price']}`). You can also email us directly at `{CONTACT_EMAIL}` for faster communication."
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_home")]]
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Native Chat Contact Form Handlers ---
async def contact_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    await message.reply_text(
        "📝 **SahilCodeLab Contact Form**\n\n"
        "Please enter your **Full Name** (or send /cancel to exit):",
        parse_mode="Markdown"
    )
    return CONTACT_NAME

async def contact_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contact_name'] = update.message.text.strip()
    await update.message.reply_text("Thanks! Now, please enter your **Email Address**:")
    return CONTACT_EMAIL_STATE

async def contact_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contact_email'] = update.message.text.strip()
    await update.message.reply_text("Great! Now, please type your **Project Message or Requirements**:")
    return CONTACT_MESSAGE

async def contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = context.user_data.get('contact_name')
    email = context.user_data.get('contact_email')
    project_msg = update.message.text.strip()
    
    db.log_lead(user_id, f"Custom Inquiry (Email: {email})", project_msg)
    
    success_text = (
        f"✅ **Form Submitted Successfully!**\n\n"
        f"👤 Name: `{name}`\n"
        f"📧 Email: `{email}`\n"
        f"💬 Message: `{project_msg}`\n\n"
        f"SahilCodeLab team will contact you soon at `{CONTACT_EMAIL}`."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_home")]]
    await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def cancel_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Contact form cancelled.")
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    user_id = update.effective_user.id
    user_msg = update.effective_message.text
    
    await update.effective_chat.send_action("typing")
    reply = AIEngine.get_response(user_msg, user_id)
    
    keyboard = [[InlineKeyboardButton("🚀 Explore Services", callback_data="menu_services")]]
    await update.effective_message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard))

# ============================================================
# 6. FASTAPI WEB SERVER
# ============================================================

app = FastAPI(title=f"{BRAND_NAME} API", version="3.7")

@app.get("/")
def home():
    return {"brand": BRAND_NAME, "portfolio": BRAND_URL, "contact": CONTACT_EMAIL, "status": "Online"}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def run_telegram_bot():
    try:
        app_bot = Application.builder().token(BOT_TOKEN).build()
        
        # Native Contact Form Conversation Handler
        contact_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(contact_start, pattern="^menu_hire$"),
                CommandHandler("contact", contact_start)
            ],
            states={
                CONTACT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_name)],
                CONTACT_EMAIL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_email)],
                CONTACT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_message)],
            },
            fallbacks=[CommandHandler("cancel", cancel_contact)],
        )
        
        app_bot.add_handler(CommandHandler("start", start_command))
        app_bot.add_handler(contact_conv_handler)
        app_bot.add_handler(CallbackQueryHandler(button_handler))
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info(f"✅ {BRAND_NAME} Telegram Bot polling started...")
        app_bot.run_polling()
    except Exception as e:
        logger.error(f"Telegram Bot error: {e}")

# ============================================================
# 7. MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)
