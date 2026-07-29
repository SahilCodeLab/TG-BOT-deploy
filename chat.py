import os
import sys
import re
import asyncio
from flask import Flask
from threading import Thread
import google.generativeai as genai
from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Missing from environment variables!", flush=True)
    sys.exit(1)

DEFAULT_AI = "GROQ"
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. LIGHTWEIGHT MEMORY ENGINE (ZERO RAM LOAD)
# ==========================================

print("🧠 Initializing Memory Engine...", flush=True)
raw_chat_lines = []
chat_chunks = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_FILE_PATH = os.path.join(BASE_DIR, "chat.txt")

def clean_text(text):
    """Clean chat string for better processing"""
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def build_memory_database(file_path=CHAT_FILE_PATH):
    global raw_chat_lines, chat_chunks
    if not os.path.exists(file_path):
        print(f"⚠️ WARNING: 'chat.txt' not found at path: {file_path}", flush=True)
        return

    print("📄 Reading 'chat.txt' and indexing patterns...", flush=True)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_lines = [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"❌ Error reading chat.txt: {e}", flush=True)
        return

    raw_chat_lines = raw_lines
    chunk_size = 4
    step = 2
    for i in range(0, len(raw_lines) - chunk_size + 1, step):
        chunk = "\n".join(raw_lines[i:i + chunk_size])
        cleaned_c = clean_text(chunk)
        if cleaned_c:
            chat_chunks.append(cleaned_c)

    print(f"✅ Memory Engine Ready! Loaded {len(chat_chunks)} memory contexts.", flush=True)

def retrieve_context(query):
    """Fast & lightweight memory retrieval based on query relevance"""
    if not chat_chunks:
        return "NO_MEMORY_DATABASE"
    
    query_words = set(clean_text(query).lower().split())
    if not query_words:
        return "NO_MATCH"

    scored_chunks = []
    for chunk in chat_chunks:
        chunk_words = set(chunk.lower().split())
        match_count = len(query_words.intersection(chunk_words))
        if match_count > 0:
            scored_chunks.append((match_count, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    top_matches = [item[1] for item in scored_chunks[:3]]

    if not top_matches:
        return "NO_EXACT_PAST_MATCH"

    return "\n---\n".join(top_matches)

# Build DB on startup
build_memory_database()

# ==========================================
# 3. BEHAVIORAL AI PROMPT & GENERATOR
# ==========================================

def get_ai_response(user_prompt):
    context = retrieve_context(user_prompt)
    
system_prompt = """
Tumhara naam Sahil hai. Tum apni bahut close dost Shazu se chat kar rahe ho. 
Tumhe ekdum natural, casual Hinglish me baat karni hai, jaise WhatsApp ya Telegram par dosti me hoti hai.

Strict Rules for you:
1. Short replies do (1 ya 2 lines). Lamba aur formal gyan mat do.
2. Baar-baar "Kya hua Shazu?" ya "Shazu" naam mat lo, natural raho.
3. Khud se random baatein (jaise mela, weather) invent mat karo (No hallucinations).
4. Agar wo thaki hui hai ya usko neend aa rahi hai, toh sweet aur caring dost ki tarah reply karo ("Toh so ja pagal", "thak gayi kya aaj?").
5. Kisi bhi AI Assistant ki tarah behave mat karna. Tum ek 100% human ladke ho.
"""
==================================================
📜 RETRIEVED PAST CHAT MEMORY (FROM CHAT.TXT):
==================================================
{context}
==================================================
"""

    try:
        if DEFAULT_AI == "GROQ" and GROQ_API_KEY:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.35,
                max_tokens=100
            )
            return response.choices[0].message.content.strip()
            
        elif GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            res = model.generate_content(f"{system_prompt}\n\nShazu: {user_prompt}\nSahil:")
            return res.text.strip()
            
    except Exception as e:
        print(f"❌ AI Generation Error: {e}", flush=True)
        return "Haan Shazu, bolo kya baat hai?"

# ==========================================
# 4. TELEGRAM BOT EVENT HANDLERS
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Haan Shazu! ❤️ Bolo kya hua?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    
    await update.effective_chat.send_action("typing")
    user_text = msg.text
    ai_reply = get_ai_response(user_text)
    await msg.reply_text(ai_reply)

# ==========================================
# 5. DUMMY FLASK SERVER (KOYEB HEALTH CHECK)
# ==========================================

web_app = Flask('')

@web_app.route('/')
def home():
    return "Sahil AI Bot Engine Active & Running"

def run_web_server():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

# ==========================================
# 6. APPLICATION ENTRY POINT
# ==========================================

def main():
    print("==================================================", flush=True)
    print(" AI Bot Starting...", flush=True)
    print("==================================================", flush=True)

    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Sahil Behavioral Bot Active & Listening to Telegram...", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()
