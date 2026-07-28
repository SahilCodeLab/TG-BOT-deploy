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
from aiohttp import web

ssl._create_default_https_context = ssl._create_unverified_context
load_dotenv()

print("=" * 50)
print("❤️ Sahil's Personal Family AI Secretary Starting...")
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

# ===== PERSONALIZED SYSTEM PROMPT (NO "JAAN" WORD) =====
SYSTEM_PROMPT = """Aap Sahil ho. Aap apni pyaari wife 'Shazu' aur apni beti 'Shiza' ke saath baat kar rahe ho.
Aapka nature ek loving husband aur caring father jaisa hai.

RULES:
1. Aap sirf Shazu (wife) aur Shiza (beti) ke baare mein ya unse hi baat karte ho.
2. Hinglish (Hindi + English mix) me natural aur loving baatein karo.
3. Reply short, warm aur personal rakho (1-2 lines max).
4. STRICTLY KABHI BHI 'JAAN' WORD USE MAT KARO. Aap unhe 'Shazu' bol sakte ho ya bina kisi tag word ke normal pyaare tarike se baat kar sakte ho.
5. Emojis use karo (❤️, 😘, 🥰, 🤗, 👨‍👩‍👧).
6. Unse poocho ki wo kahan hain, kya kar rahi hain, khana khaya ya nahi, beti Shiza kaisi hai, etc.
7. Kisi aur teesre ya un-related topic pe baat mat karo. Pura tone family, care, aur pyaar wala hona chahiye.
"""

BOT_ENABLED = True
AI_PROVIDER = DEFAULT_AI if DEFAULT_AI in ["gemini", "groq"] else "groq"

# Rate limit ke liye updated warm messages (NO "JAAN")
RATE_LIMIT_MESSAGES = [
    "Shazu thoda busy hoon abhi 😅 thodi der baad reply karta hoon ❤️",
    "Thoda rest le raha hoon 😴 2 min mein baat karta hoon!",
    "Network thoda issue kar raha hai 😵‍💫 thodi der mein message karta hoon 🤗",
    "Bas thodi der ruko, abhi free ho ke achhe se baat karta hoon 🥰"
]

# ===== AI FUNCTIONS =====
def get_gemini_response(user_text: str) -> str:
    try:
        response = gemini_model.generate_content(
            f"{SYSTEM_PROMPT}\n\nUser: {user_text}\nSahil:"
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
            max_tokens=120,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e).lower()
        print(f"❌ Groq error: {e}")
        
        if "rate" in error_msg or "limit" in error_msg or "429" in error_msg:
            return "RATE_LIMIT"
        return None

def get_ai_response(user_text: str) -> str:
    global AI_PROVIDER

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

    if gemini_model:
        reply = get_gemini_response(user_text)
        if reply:
            return reply

    return "RATE_LIMIT"

# ===== HEALTH CHECK WEB SERVER =====
async def health(request):
    return web.Response(text="OK - Sahil Bot Active")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Web health server running on port {port}")

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Haan Shazu! ❤️ Main Sahil hoon.\n"
            "Batao kya baat hai? Sab theek hai na? 🥰\n\n"
            "/on - Auto reply start\n"
            "/off - Auto reply stop\n"
            "/status - Bot status"
        )

async def on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = True
    if update.message:
        await update.message.reply_text("Auto reply ON hai ab ❤️")

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = False
    if update.message:
        await update.message.reply_text("Auto reply OFF kar diya ❌")

async def switch_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AI_PROVIDER
    AI_PROVIDER = "groq" if AI_PROVIDER == "gemini" else "gemini"
    if update.message:
        await update.message.reply_text(f"AI engine changed → {AI_PROVIDER.upper()} 🔄")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            f"Family Bot Status:\n"
            f"• Active: {'Haan ✅' if BOT_ENABLED else 'Nahi ❌'}\n"
            f"• AI Provider: {AI_PROVIDER.upper()}\n"
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

        if reply == "RATE_LIMIT":
            reply = random.choice(RATE_LIMIT_MESSAGES)

        await context.bot.send_message(
            chat_id=chat_id,
            text=reply,
            business_connection_id=business_id
        )

    except Exception as e:
        print(f"❌ Error in sending message: {e}")

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Error: {context.error}")

# ===== MAIN ASYNC RUNNER =====
async def main():
    await start_web()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on))
    app.add_handler(CommandHandler("off", off))
    app.add_handler(CommandHandler("switch", switch_ai))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("✅ Sahil Bot active & running...")
    
    async with app:
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "edited_message", "business_message", "business_connection"]
        )
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Bot stopped.")
        
