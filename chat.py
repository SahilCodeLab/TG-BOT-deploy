import os
import sys
import asyncio
from flask import Flask
from threading import Thread
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Environment Variable Missing!")
    sys.exit(1)

# API Setup
DEFAULT_AI = "GROQ"
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Gemini ready", flush=True)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
    print("✅ Groq ready", flush=True)

# ==========================================
# 2. RAG ENGINE (FAISS + EMBEDDINGS)
# ==========================================

print("🧠 Initializing Sentence Transformer Model...", flush=True)
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

index = None
chat_chunks = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_FILE_PATH = os.path.join(BASE_DIR, "chat.txt")

def build_rag_database(file_path=CHAT_FILE_PATH):
    global index, chat_chunks
    if not os.path.exists(file_path):
        print(f"⚠️ File nahi mili: {file_path}", flush=True)
        return

    print("📄 Reading 'chat.txt' and creating vector embeddings...", flush=True)
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 8 lines per chunk to save RAM on Koyeb
    chunk_size = 8
    for i in range(0, len(lines), chunk_size):
        chunk = "".join(lines[i:i + chunk_size]).strip()
        if chunk:
            chat_chunks.append(chunk)

    if not chat_chunks:
        print("⚠️ 'chat.txt' khaali hai.", flush=True)
        return

    print(f"🔄 Encoding {len(chat_chunks)} chunks into FAISS vector space...", flush=True)
    
    # Low RAM batch processing
    embeddings = embedding_model.encode(chat_chunks, batch_size=32, show_progress_bar=False)
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatL2(dimension)
    index.add(np.array(embeddings).astype('float32'))
    print(f"✅ RAG Memory Ready! Loaded {len(chat_chunks)} memory chunks into FAISS.", flush=True)

def retrieve_context(query, k=4):
    if index is None or len(chat_chunks) == 0:
        return ""
    
    query_vector = embedding_model.encode([query])
    distances, indices = index.search(np.array(query_vector).astype('float32'), k)
    
    context_chunks = []
    for idx in indices[0]:
        if idx < len(chat_chunks):
            context_chunks.append(chat_chunks[idx])
            
    return "\n---\n".join(context_chunks)

# Build RAG Memory on startup
build_rag_database()

# ==========================================
# 3. AI RESPONSE GENERATOR
# ==========================================

def get_ai_response(user_prompt):
    context = retrieve_context(user_prompt)
    
    system_prompt = f"""
Aap Sahil hain. Aap niche di gayi past chat memory ka use karke bilkul Sahil ke style, tone, wording aur personality me short aur accurate reply denge.

STRICT RULES:
1. Upar di gayi past chats ko dekho aur HUBEHU Sahil ka bolne ka tarika, short words, emojis, aur style copy karo.
2. STRICTLY KABHI BHI 'JAAN' WORD USE MAT KARO.
3. Chat history context se matching jawab do agar relevant ho.
4. Jawab bilkul natural aur short rakho (1-2 lines maximum).

Past Chat Memory Context:
{context}
"""

    full_user_input = f"User: {user_prompt}"

    try:
        if DEFAULT_AI == "GROQ" and GROQ_API_KEY:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_user_input}
                ],
                temperature=0.7,
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        elif GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            res = model.generate_content(f"{system_prompt}\n\n{full_user_input}")
            return res.text.strip()
    except Exception as e:
        print(f"❌ AI Error: {e}", flush=True)
        return "Haan bolo, kya hua?"

# ==========================================
# 4. TELEGRAM BOT HANDLERS
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Haan bhai, bol kya baat hai?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    
    user_text = msg.text
    ai_reply = get_ai_response(user_text)
    
    await msg.reply_text(ai_reply)

# ==========================================
# 5. DUMMY WEB SERVER (FOR KOYEB HEALTH CHECK)
# ==========================================

web_app = Flask('')

@web_app.route('/')
def home():
    return "Sahil AI Bot is Online & Running!"

def run_web_server():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

# ==========================================
# 6. MAIN EXECUTION
# ==========================================

def main():
    # Start web server in background thread for Koyeb health checks
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()
    print("✅ Web health server running on port 8000", flush=True)

    # Start Telegram Bot Application
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Sahil Bot active & running...", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()
