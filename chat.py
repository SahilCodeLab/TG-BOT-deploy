import os
import sys
import re
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
# 2. ADVANCED RAG MEMORY ENGINE
# ==========================================

print("🧠 Initializing Deep RAG Vector Engine...", flush=True)
# Light-weight model optimized for low memory usage on cloud servers
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

index = None
chat_chunks = []
raw_chat_lines = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_FILE_PATH = os.path.join(BASE_DIR, "chat.txt")

def clean_text(text):
    """Clean chat string for better embedding accuracy"""
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def build_rag_database(file_path=CHAT_FILE_PATH):
    global index, chat_chunks, raw_chat_lines
    if not os.path.exists(file_path):
        print(f"⚠️ WARNING: 'chat.txt' not found at path: {file_path}", flush=True)
        return

    print("📄 Reading 'chat.txt' and indexing Sahil's behavior patterns...", flush=True)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_lines = [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"❌ Error reading chat.txt: {e}", flush=True)
        return

    raw_chat_lines = raw_lines
    
    # 4-line sliding window chunks for high context precision
    chunk_size = 4
    step = 2
    for i in range(0, len(raw_lines) - chunk_size + 1, step):
        chunk = "\n".join(raw_lines[i:i + chunk_size])
        cleaned_c = clean_text(chunk)
        if cleaned_c:
            chat_chunks.append(cleaned_c)

    if not chat_chunks:
        print("⚠️ 'chat.txt' is empty or has no readable text.", flush=True)
        return

    print(f"🔄 Creating embeddings for {len(chat_chunks)} chunks...", flush=True)
    embeddings = embedding_model.encode(chat_chunks, batch_size=32, show_progress_bar=False)
    
    # Normalizing vectors for Cosine Similarity search
    faiss.normalize_L2(embeddings)
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(embeddings).astype('float32'))
    print(f"✅ RAG Memory Engine Ready! Loaded {len(chat_chunks)} memory contexts into FAISS.", flush=True)

def retrieve_context(query, k=5, score_threshold=0.22):
    """Retrieve top-k relevant memory chunks matching Sahil's style and past facts"""
    if index is None or len(chat_chunks) == 0:
        return "NO_MEMORY_DATABASE"
    
    cleaned_query = clean_text(query)
    query_vector = embedding_model.encode([cleaned_query])
    faiss.normalize_L2(query_vector)
    
    scores, indices = index.search(np.array(query_vector).astype('float32'), k)
    
    matched_chunks = []
    for score, idx in zip(scores[0], indices[0]):
        if score >= score_threshold and idx < len(chat_chunks):
            matched_chunks.append(chat_chunks[idx])
            
    if not matched_chunks:
        return "NO_EXACT_PAST_MATCH"
        
    return "\n---\n".join(matched_chunks)

# Build DB on startup
build_rag_database()

# ==========================================
# 3. BEHAVIORAL AI PROMPT & GENERATOR
# ==========================================

def get_ai_response(user_prompt):
    context = retrieve_context(user_prompt)
    
    system_prompt = f"""
YOU ARE SAHIL. YOU ARE NOT AN AI, ASSISTANT, OR BOT.
You are talking to your wife 'Shazu' on Telegram. Your task is to act, speak, and react EXACTLY like Sahil based on the provided chat history.

==================================================
🎯 SAHIL'S BEHAVIOR & STYLE GUIDELINES (STRICT):
==================================================
1. TONE & LANGUAGE:
   - Speak in natural, real Indian Hinglish.
   - Keep answers concise, short, direct, and conversational (1-2 sentences usually, max 3).
   - Use casual spelling habits if present in memory (e.g., "haa", "kyu", "kya hua", "batao", "naa", "acha").
   - DO NOT sound like a polite assistant. Never say "Mai aapki kya madad kar sakta hoon", "Kaise hain aap", etc.

2. FORBIDDEN WORDS & PATTERNS:
   - STRICTLY NEVER USE THE WORD 'JAAN' (Use 'Shazu' or speak directly without formal labels).
   - Never use robotic artificial warmers or over-explanation.
   - Do not mention third persons unless Shazu explicitly names them first.

3. PAST CHAT & MEMORY HANDLING (VERY IMPORTANT):
   - Analyze the provided PAST CHAT MEMORY carefully.
   - If Shazu asks "Hum pehle kya baat karte the?", "Tujhe yaad hai?", or refers to a past plan/event:
     a) IF MATCHED IN MEMORY: Say "Haan Shazu, mujhe yaad hai..." and mention the exact detail/topic naturally.
     b) IF NOT IN MEMORY: Reply naturally in Sahil's style like "Mujhe toh yaad nahi aa raha Shazu, kab ki baat hai?" or "Konsi baat? Mujhe yaad dila." DO NOT invent fake stories, dates, or details.

4. EMOTIONAL & REACTION ALIGNMENT:
   - Match the emotional tone of the past chats (caring, teasing, calm, or playful depending on context).

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
                temperature=0.35, # Low temperature to prevent hallucination while maintaining natural style
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
    """Handler for /start command"""
    await update.message.reply_text("Haan Shazu! ❤️ Bolo kya hua?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for text messages"""
    msg = update.effective_message
    if not msg or not msg.text:
        return
    
    # Send typing action to make response feel human
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

    # Start health-check server thread for cloud platform deployment
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    # Build Telegram Bot Application
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Sahil Behavioral Bot Active & Listening to Telegram...", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()
