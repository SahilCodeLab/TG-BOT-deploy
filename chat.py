import os
import sys
import re
import random
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
    print("❌ ERROR: BOT_TOKEN Missing!", flush=True)
    sys.exit(1)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. FULL CHAT.TXT BEHAVIOR EXTRACTOR
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_FILE_PATH = os.path.join(BASE_DIR, "chat.txt")

sahil_messages = []

def load_chat_history():
    global sahil_messages
    if not os.path.exists(CHAT_FILE_PATH):
        print(f"⚠️ 'chat.txt' not found at {CHAT_FILE_PATH}", flush=True)
        return

    try:
        with open(CHAT_FILE_PATH, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        for line in lines:
            cleaned = re.sub(r'http\S+', '', line).strip()
            if cleaned:
                sahil_messages.append(cleaned)

        print(f"✅ Loaded {len(sahil_messages)} lines from chat.txt for style clone!", flush=True)
    except Exception as e:
        print(f"❌ Error reading chat.txt: {e}", flush=True)

load_chat_history()

def get_dynamic_chat_samples(user_query):
    """Retrieves relevant past conversations to match Sahil's style for current input"""
    if not sahil_messages:
        return "No past chat available."

    # Look for matching words in past chat
    words = set(re.findall(r'\w+', user_query.lower()))
    matched_lines = []

    for idx, line in enumerate(sahil_messages):
        line_words = set(re.findall(r'\w+', line.lower()))
        if len(words.intersection(line_words)) > 0:
            start_i = max(0, idx - 1)
            end_i = min(len(sahil_messages), idx + 3)
            snippet = "\n".join(sahil_messages[start_i:end_i])
            matched_lines.append(snippet)

    if matched_lines:
        # Pick 3 relevant matching snippets
        return "\n---\n".join(random.sample(matched_lines, min(3, len(matched_lines))))
    else:
        # Pick random recent samples if no direct word match
        return "\n---\n".join(random.sample(sahil_messages, min(5, len(sahil_messages))))

# ==========================================
# 3. 100% BEHAVIOR CLONE ENGINE
# ==========================================

def get_ai_response(user_prompt):
    past_samples = get_dynamic_chat_samples(user_prompt)

    system_prompt = f"""
YOU ARE SAHIL. YOU ARE NOT AN AI, BOT, OR ASSISTANT.
You are chatting with your wife/partner 'Shazu' on Telegram. Your task is to 100% copy Sahil's personality, vocabulary, and communication style.

==================================================
PAST CHAT HISTORY SAMPLES (HOW SAHIL TALKS):
==================================================
{past_samples}
==================================================

RULES FOR SAHIL'S RESPONSE:
1. Copy the exact Hinglish typing style, spelling short-forms, and slangs seen in chat.txt.
2. Keep replies short (1 to 2 lines max). Real people don't send long formal paragraphs.
3. If Shazu brings up past topics/arguments, handle it casually (don't over-explain or drag old drama), then bring up normal daily things (like khana, sleep, routine).
4. NEVER say things like "Main aapki kya madad karoon", "Kaise hain aap", or formal assistant lines.
5. Do not repeat the exact same phrase in every message. Keep the conversation natural.
"""

    try:
        if GROQ_API_KEY:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.35, # Low temperature ensures strict behavior matching
                max_tokens=60
            )
            return response.choices[0].message.content.strip()

        elif GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            res = model.generate_content(
                f"{system_prompt}\n\nShazu: {user_prompt}\nSahil:",
                generation_config={"temperature": 0.35, "max_output_tokens": 60}
            )
            return res.text.strip()

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        return "Haan bolo, kya hua?"

# ==========================================
# 4. TELEGRAM BOT HANDLERS
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Haan bolo! Kya hua?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    await update.effective_chat.send_action("typing")
    user_text = msg.text
    ai_reply = get_ai_response(user_text)
    await msg.reply_text(ai_reply)

# ==========================================
# 5. DUMMY FLASK SERVER (FOR KOYEB)
# ==========================================

web_app = Flask('')

@web_app.route('/')
def home():
    return "Sahil Behavior Engine Active"

def run_web_server():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

# ==========================================
# 6. MAIN EXECUTION
# ==========================================

def main():
    print("==========================================", flush=True)
    print(" Starting Sahil Behavior Engine...", flush=True)
    print("==========================================", flush=True)

    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Sahil Bot is Online & Ready!", flush=True)
    app.run_polling()

if __name__ == '__main__':
    main()
