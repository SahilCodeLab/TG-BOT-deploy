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

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN Missing!")
    sys.exit(1)

DEFAULT_AI = "GROQ"
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. RAG ENGINE (STRICT VECTOR MEMORY SEARCH)
# ==========================================

print("🧠 Loading Sentence Transformer...", flush=True)
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

    print("📄 Memory Indexing active for chat.txt...", flush=True)
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 3-line chunks for maximum similarity match
    chunk_size = 3
    for i in range(0, len(lines), chunk_size):
        chunk = "".join(lines[i:i + chunk_size]).strip()
        if chunk:
            chat_chunks.append(chunk)

    if not chat_chunks:
        return

    embeddings = embedding_model.encode(chat_chunks, batch_size=32, show_progress_bar=False)
    
    # Cosine Normalization
    faiss.normalize_L2(embeddings)
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(embeddings).astype('float32'))
    print(f"✅ Loaded {len(chat_chunks)} memory chunks.", flush=True)

def retrieve_context(query, k=3, score_threshold=0.40):
    if index is None or len(chat_chunks) == 0:
        return "NO_MEMORY_FOUND"
    
    query_vector = embedding_model.encode([query])
    faiss.normalize_L2(query_vector)
    
    scores, indices = index.search(np.array(query_vector).astype('float32'), k)
    
    matched_chunks = []
    for score, idx in zip(scores[0], indices[0]):
        if score >= score_threshold and idx < len(chat_chunks):
            matched_chunks.append(chat_chunks[idx])
            
    if not matched_chunks:
        return "NO_MEMORY_FOUND"
        
    return "\n---\n".join(matched_chunks)

build_rag_database()

# ==========================================
# 3. AI GENERATOR (PURE MEMORY & SHORT REPLIES)
# ==========================================

def get_ai_response(user_prompt):
    context = retrieve_context(user_prompt)
    
    system_prompt = f"""
Aap SAHIL hain aur aap apni wife 'Shazu' se baat kar rahe hain.

RULES:
1. Aapka naam Sahil hai. Aap Shazu se conversational Hinglish me baat kar rahe hain.
2. STRICTLY KABHI BHI 'JAAN' WORD USE MAT KARO.
3. Kisi teesre ka zikr mat karo jab tak user khud na pooche. Sirf Shazu aur aapki baat honi chahiye.
4. AGAR MEMORY ME ANSWER HAIN (niche Chat Memory dekho), toh wahi exact jawab do.
5. AGAR MEMORY ME DATA NAHI HAI, toh koi bhi fake dates/facts mat banao. Direct bolo: "Mujhe yaad nahi aa raha Shazu, tum batao" ya 1 line me short response do.
6. Max 1-2 short lines me reply do. Extra kahani mat banao.

=== PAST CHAT MEMORY ===
{context}
========================
"""

    try:
        if DEFAULT_AI == "GROQ" and GROQ_API_KEY:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2, # Extremely low temperature = zero hallucination
                max_tokens=60
            )
            return response.choices[0].message.content.strip()
        elif GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            res = model.generate_content(f"{system_prompt}\n\nUser: {user_prompt}\nSahil:")
            return res.text.strip()
    except Exception as e:
        print(f"❌ AI Error: {e}", flush=True)
        return "Haan Shazu, bolo ❤️"

# ==========================================
# 4. TELEGRAM BOT HANDLERS
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Haan Shazu! ❤️ Bolo kya baat hai?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    
    ai_reply = get_ai_response(msg.text)
    await msg.reply_text(ai_reply)

# ==========================================
# 5. WEB SERVER (FOR KOYEB)
# ==========================================

web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot Online"

def run_web_server():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

# ==========================================
# 6. MAIN EXECUTION
# ==========================================

def main():
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Pure RAG Sahil Bot Active...", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()
