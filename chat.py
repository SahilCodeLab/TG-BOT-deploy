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

# RAG Libraries
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

ssl._create_default_https_context = ssl._create_unverified_context
load_dotenv()

print("=" * 50)
print("❤️ Sahil's Personal Family AI Secretary (RAG Powered) Starting...")
print("=" * 50)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEFAULT_AI = os.getenv("DEFAULT_AI", "groq")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN missing in .env")

# ===== RAG MEMORY ENGINE SETUP =====
print("🧠 Initializing RAG Memory Engine...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
chat_chunks = []
index = None

def build_rag_database(file_path="chat.txt"):
    global index, chat_chunks
    if not os.path.exists(file_path):
        print("⚠️ 'chat.txt' file nahi mili! Bot bina RAG memory ke chalega.")
        return

    print("📄 Reading 'chat.txt' and creating vector embeddings...")
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Chat ko 4-4 lines ke chunks me divide kar rahe hain taaki context bana rahe
    chunk_size = 4
    for i in range(0, len(lines), chunk_size):
        chunk = "".join(lines[i:i + chunk_size]).strip()
        if chunk:
            chat_chunks.append(chunk)

    if not chat_chunks:
        print("⚠️ 'chat.txt' khaali hai.")
        return

    # Embeddings Generate karna
    embeddings = embedding_model.encode(chat_chunks)
    dimension = embeddings.shape[1]

    # FAISS Index create karna
    index = faiss.IndexFlatL2(dimension)
    index.add(np.array(embeddings).astype('float32'))
    print(f"✅ RAG Memory Ready! Loaded {len(chat_chunks)} memory chunks into FAISS.")

# Build Database on startup
build_rag_database("chat.txt")

def get_relevant_memories(query, top_k=3):
    """Message ke aaspas ki relevant purani memories dhoondhta hai"""
    if index is None or len(chat_chunks) == 0:
        return "No past memory file available."
    
    query_vector = embedding_model.encode([query])
    distances, indices = index.search(np.array(query_vector).astype('float32'), top_k)
    
    retrieved = []
    for idx in indices[0]:
        if idx < len(chat_chunks):
            retrieved.append(chat_chunks[idx])
            
    return "\n---\n".join(retrieved)

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

BOT_ENABLED = True
AI_PROVIDER = DEFAULT_AI if DEFAULT_AI in ["gemini", "groq"] else "groq"

RATE_LIMIT_MESSAGES = [
    "Shazu thoda busy hoon abhi 😅 thodi der baad reply karta hoon ❤️",
    "Thoda rest le raha hoon 😴 2 min mein baat karta hoon!",
    "Network thoda issue kar raha hai 😵‍💫 thodi der mein message karta hoon 🤗",
    "Bas thodi der ruko, abhi free ho ke achhe se baat karta hoon 🥰"
]

# ===== DYNAMIC SYSTEM PROMPT BUILDER =====
def build_system_prompt(retrieved_memories: str) -> str:
    return f"""Aap Sahil ho. Aap apni pyaari wife 'Shazu' aur apni beti 'Shiza' ke saath baat kar rahe ho.
Aapka nature ek loving husband aur caring father jaisa hai.

=== RELEVANT PAST CHATS & MEMORY (FROM CHAT.TXT) ===
{retrieved_memories}
====================================================

RULES:
1. Upar di gayi past chats ko dekho aur HUBEHU Sahil ka bolne ka tarika, short words, emojis, aur style copy karo.
2. Agar message me koi purani baat poochi jaye, toh upar di gayi memory ka reference lekar exact jawab do.
3. Hinglish (Hindi + English mix) me natural aur loving baatein karo (1-2 lines max).
4. STRICTLY KABHI BHI 'JAAN' WORD USE MAT KARO. Aap unhe 'Shazu' bol sakte ho.
5. Emojis use karo (❤️, 😘, 🥰, 🤗, 👨‍👩‍👧).
6. Tone bilkul asli Sahil jaisa hona chahiye, kisi AI jaisa nahi.
"""

# ===== AI FUNCTIONS =====
def get_gemini_response(user_text: str, memories: str) -> str:
    try:
        prompt = f"{build_system_prompt(memories)}\n\nUser: {user_text}\nSahil:"
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return None

def get_groq_response(user_text: str, memories: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": build_system_prompt(memories)},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
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

    # Step 1: Retrieve Relevant Memories using RAG
    memories = get_relevant_memories(user_text, top_k=3)

    # Step 2: Pass Memories to AI Models
    if AI_PROVIDER == "gemini" and gemini_model:
        reply = get_gemini_response(user_text, memories)
        if reply:
            return reply
        AI_PROVIDER = "groq"

    if AI_PROVIDER == "groq" and groq_client:
        reply = get_groq_response(user_text, memories)
        if reply == "RATE_LIMIT":
            return "RATE_LIMIT"
        if reply:
            return reply
        AI_PROVIDER = "gemini"

    if gemini_model:
        reply = get_gemini_response(user_text, memories)
        if reply:
            return reply

    return "RATE_LIMIT"

# ===== HEALTH CHECK WEB SERVER =====
async def health(request):
    return web.Response(text="OK - Sahil RAG Bot Active")

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
            f"Family Bot Status (RAG Enabled):\n"
            f"• Active: {'Haan ✅' if BOT_ENABLED else 'Nahi ❌'}\n"
            f"• AI Provider: {AI_PROVIDER.upper()}\n"
            f"• RAG Chunks Loaded: {len(chat_chunks)}\n"
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

    print("✅ Sahil RAG Bot active & running...")
    
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
