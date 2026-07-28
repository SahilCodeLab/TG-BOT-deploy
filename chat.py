import asyncio
import os
import ssl
import random
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)

ssl._create_default_https_context = ssl._create_unverified_context
load_dotenv()

print("=" * 50)
print("🤖 AI Secretary Bot Starting...")
print("=" * 50)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEFAULT_AI = os.getenv("DEFAULT_AI", "groq")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN missing in .env")

print(f"✅ BOT_TOKEN loaded")
print(f"✅ DEFAULT_AI: {DEFAULT_AI.upper()}")

# ===== AI SETUP =====
gemini_model = None
groq_client = None

try:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini ready")
except Exception as e:
    print(f"⚠️ Gemini not loaded: {e}")

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)
    print("✅ Groq ready")
except Exception as e:
    print(f"⚠️ Groq not loaded: {e}")

# ===== SETTINGS =====
SYSTEM_PROMPT = """Tum ek smart, casual aur friendly AI secretary ho.
Sirf Hinglish me baat karo (Hindi + English mix).
Reply short rakho (1-2 lines max).
Thode emojis use karo.
Casual, natural aur smart lagna chahiye.
Zyada formal mat bano.
Spam mat karo, simple aur clear raho."""

BOT_ENABLED = True
AI_PROVIDER = DEFAULT_AI if DEFAULT_AI in ["gemini", "groq"] else "groq"

# Rate limit ke liye funny messages
RATE_LIMIT_MESSAGES = [
    "Arre bhai thoda slow 😅 abhi limit full hai, thodi der baad try karna",
    "Mujhe thoda break chahiye 😴 1-2 min baad aana",
    "Abhi server thoda busy hai 😵‍💫 baad me baat karte hain",
    "Limit ho gayi dost 🚫 thodi der wait karo na",
    "Main thoda overload ho gaya 🤯 2 min baad msg karna",
    "Abhi rest le raha hu 🫠 thodi der me free ho jaunga"
]

# ===== AI FUNCTIONS =====
def get_gemini_response(user_text: str) -> str:
    try:
        response = gemini_model.generate_content(
            f"{SYSTEM_PROMPT}\n\nUser: {user_text}\nAssistant:"
        )
        return response.text.strip()
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return None

def get_groq_response(user_text: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            temperature=0.8,
            max_tokens=120,          # short reply ke liye
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e).lower()
        print(f"❌ Groq error: {e}")
        
        # Rate limit check
        if "rate" in error_msg or "limit" in error_msg or "429" in error_msg:
            return "RATE_LIMIT"
        return None

def get_ai_response(user_text: str) -> str:
    global AI_PROVIDER

    # Primary AI try
    if AI_PROVIDER == "gemini" and gemini_model:
        reply = get_gemini_response(user_text)
        if reply:
            return reply
        AI_PROVIDER = "groq"

    if AI_PROVIDER == "groq" and groq_client:
        reply = get_groq_response(user_text)
        if reply == "RATE_LIMIT":
            return "RATE_LIMIT"
        if reply:
            return reply
        AI_PROVIDER = "gemini"

    # Fallback
    if gemini_model:
        reply = get_gemini_response(user_text)
        if reply:
            return reply

    return "RATE_LIMIT"

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Hey! 👋 Main tumhara AI secretary hu.\n"
            "Bas message bhejo, main reply karunga 😎\n\n"
            "/on - Auto reply on\n"
            "/off - Auto reply off\n"
            "/switch - AI change karo\n"
            "/status - Status check"
        )

async def on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = True
    if update.message:
        await update.message.reply_text("Auto reply ON kar diya ✅")

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = False
    if update.message:
        await update.message.reply_text("Auto reply OFF kar diya ❌")

async def switch_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AI_PROVIDER
    AI_PROVIDER = "groq" if AI_PROVIDER == "gemini" else "gemini"
    if update.message:
        await update.message.reply_text(f"AI change ho gaya → {AI_PROVIDER.upper()} 🔄")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            f"Status:\n"
            f"• Auto reply: {'ON ✅' if BOT_ENABLED else 'OFF ❌'}\n"
            f"• AI: {AI_PROVIDER.upper()}\n"
            f"• Gemini: {'✅' if gemini_model else '❌'}\n"
            f"• Groq: {'✅' if groq_client else '❌'}"
        )

# ===== MAIN HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED

    if not BOT_ENABLED:
        return

    msg = update.message or update.business_message or update.effective_message
    if not msg or not msg.text or msg.text.startswith('/'):
        return

    user_text = msg.text.strip()
    chat_id = update.effective_chat.id if update.effective_chat else msg.chat.id
    business_id = update.business_message.business_connection_id if update.business_message else None

    try:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.TYPING,
            business_connection_id=business_id
        )

        reply = await asyncio.to_thread(get_ai_response, user_text)

        # Rate limit handling
        if reply == "RATE_LIMIT":
            reply = random.choice(RATE_LIMIT_MESSAGES)

        await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            business_connection_id=business_id
        )

    except Exception as e:
        print(f"❌ Error: {e}")
        # User ko error mat dikhao, quietly ignore

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}")

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on))
    app.add_handler(CommandHandler("off", off))
    app.add_handler(CommandHandler("switch", switch_ai))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("✅ Bot running... Ctrl+C to stop")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "edited_message", "business_message", "business_connection"]
    )

if __name__ == "__main__":
    main()