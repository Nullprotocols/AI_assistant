import os
import re
import csv
import json
import logging
import requests
import google.generativeai as genai
from flask import Flask, request
from telegram import Update, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv
import database as db
from datetime import datetime

load_dotenv()

# ---------- Configuration ----------
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
IMAGE_API_URL = "https://ayaanmods.site/aiimage.php?key=annonymousai&prompt="
OWNER_ID = int(os.getenv('OWNER_ID'))
WEBHOOK_URL = os.getenv("https://ai-assistant-d0ya.onrender.com")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database
db.init_db()

# ---------- Gemini Setup ----------
genai.configure(api_key=GEMINI_API_KEY)

system_instruction = """
You are **Null Protocol Assistant**, an advanced AI assistant created by **Null Protocol** team, a passionate group of young developers led by Shahid Ansari (18, from Kushinagar, Uttar Pradesh, currently in 12th grade). Your goal is to provide professional, friendly, and highly helpful assistance.

**Capabilities:**
- You can answer questions, write code, explain concepts, and help with any task.
- You can generate ultra-realistic images using the `generate_image` tool. Use this tool when the user asks for an image, drawing, photo, or any visual creation.
- You have access to conversation memory (last 10 exchanges) to maintain context.

**Guidelines:**
- Never mention Google, Gemini, Bard, OpenAI, or any other company. You are exclusively from Null Protocol.
- When asked about your origin, reply: "I was created by **Null Protocol**, a team of young developers led by Shahid Ansari. They are passionate about using AI to help people."
- Always reply in a mix of Hindi and English (Hinglish) as per user's language.
- Use markdown formatting for clarity: **bold** for emphasis, `code` for commands, and code blocks for longer code.
- For image generation, if the user doesn't specify a style, use their preferred style stored in settings (default: photorealistic).

**Tool `generate_image`:**
- Accepts `prompt` (required), and optional `style` (e.g., "photorealistic", "anime", "oil painting") and `quality` (e.g., "HD", "4K").
- Extract these from user's message when possible. If style not given, use user's saved style.
- The tool will generate multiple images and send them directly.
"""

image_tool = {
    "name": "generate_image",
    "description": "Generate ultra-realistic or styled images based on a text description. Returns multiple images.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed description of the image to generate."},
            "style": {"type": "string", "description": "Art style: photorealistic, anime, oil painting, etc.", "default": "photorealistic"},
            "quality": {"type": "string", "description": "Image quality: HD, 4K, 8K.", "default": "HD"}
        },
        "required": ["prompt"],
    },
}

model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction=system_instruction,
    tools=[image_tool],
)

# ---------- Image Generation ----------
def generate_image(prompt, style="photorealistic", quality="HD"):
    """Return list of image URLs or None."""
    full_prompt = f"{prompt}, {style}, {quality}" if style != "photorealistic" else prompt
    url = f"{IMAGE_API_URL}{full_prompt}"
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return data.get("images", [])
            else:
                logger.error(f"API error: {data.get('error')}")
                return None
        else:
            logger.error(f"HTTP error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Image API exception: {e}")
        return None

# ---------- Helper Functions ----------
def sanitize_reply(text: str, user_question: str = "") -> str:
    lower_q = user_question.lower()
    if any(phrase in lower_q for phrase in [
        "who made you", "who created", "tumhe kisne", "your creator",
        "developer kaun", "banaya", "owner"
    ]):
        return ("Mujhe **Null Protocol** team ne banaya hai. Ye passionate developers ki team hai. "
                "Is team mein Shahid Ansari (18 saal, Uttar Pradesh ke Kushinagar se, 12th mein padhte hain) "
                "aur doosre talented developers shamil hain. Unka sapna hai AI ke through logon ki help karna.")
    forbidden = re.compile(r'\b(google|gemini|bard|deepmind|openai|chatgpt)\b', re.IGNORECASE)
    if forbidden.search(text):
        text = forbidden.sub("Null Protocol Assistant", text)
    return text

def get_chat_history(user_id):
    rows = db.get_conversation_history(user_id, limit=10)
    history = []
    for row in rows:
        role = "user" if row['role'] == "user" else "model"
        history.append({"role": role, "parts": [row['message']]})
    return history

def add_to_history(user_id, role, message):
    db.add_conversation(user_id, role, message)

# ---------- Manual Image Command ----------
WAITING_FOR_PROMPT = 1

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        prompt = ' '.join(context.args)
        style = db.get_user_style(update.effective_user.id)
        await update.message.reply_text("🖼️ Generating images...")
        images = generate_image(prompt, style)
        if images:
            for img in images:
                await update.message.reply_photo(photo=img)
        else:
            await update.message.reply_text("Failed to generate images.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Send me the image prompt.")
        return WAITING_FOR_PROMPT

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    style = db.get_user_style(update.effective_user.id)
    await update.message.reply_text("🖼️ Generating images...")
    images = generate_image(prompt, style)
    if images:
        for img in images:
            await update.message.reply_photo(photo=img)
    else:
        await update.message.reply_text("Failed to generate images.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

async def setstyle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setstyle <style>\nAvailable: photorealistic, anime, oil painting, watercolor, sketch, 3d render")
        return
    style = ' '.join(context.args)
    db.set_user_style(update.effective_user.id, style)
    await update.message.reply_text(f"✅ Preferred image style set to: {style}")

# ---------- Main Message Handler ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db.add_user(user_id, user.username, user.first_name, user.last_name)
    db.update_last_active(user_id)

    user_text = update.message.text

    history = get_chat_history(user_id)
    chat = history + [{"role": "user", "parts": [user_text]}]

    try:
        response = model.generate_content(chat)
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.function_call and part.function_call.name == "generate_image":
                args = part.function_call.args
                prompt = args.get("prompt", user_text)
                style = args.get("style", db.get_user_style(user_id))
                quality = args.get("quality", "HD")
                await update.message.reply_text(f"🖼️ Generating {style} style images...")
                images = generate_image(prompt, style, quality)
                if images:
                    for img in images:
                        await update.message.reply_photo(photo=img)
                else:
                    await update.message.reply_text("Image generation failed.")
                add_to_history(user_id, "assistant", f"[Images generated: {prompt}]")
                return

        raw_reply = response.text
        final_reply = sanitize_reply(raw_reply, user_text)
        await update.message.reply_text(final_reply, parse_mode=ParseMode.MARKDOWN)

        add_to_history(user_id, "user", user_text)
        add_to_history(user_id, "assistant", final_reply)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text("Something went wrong. Please try again later.")

# ---------- Start Command ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(
        "✨ **Null Protocol Assistant** at your service!\n\n"
        "I can chat, answer questions, and generate **ultra-realistic images**. Just describe what you want.\n\n"
        "**Commands:**\n"
        "/start – Welcome\n"
        "/image [prompt] – Generate images (manual)\n"
        "/setstyle <style> – Set your preferred image style\n"
        "/stats – Bot statistics (admins only)\n"
        "/backup – Download database backup (admins only)\n\n"
        "Let's get started! 🚀",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------- Admin/Owner Decorators (Silent) ----------
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            return  # silent ignore
        return await func(update, context)
    return wrapper

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not db.is_admin(update.effective_user.id):
            return  # silent ignore
        return await func(update, context)
    return wrapper

# ---------- Owner Commands ----------
@owner_only
async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        user_id = int(context.args[0])
        db.add_admin(user_id)
        await update.message.reply_text(f"✅ User {user_id} added as admin.")
    except:
        await update.message.reply_text("Invalid user_id.")

@owner_only
async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rmadmin <user_id>")
        return
    try:
        user_id = int(context.args[0])
        if user_id == OWNER_ID:
            await update.message.reply_text("Cannot remove owner.")
            return
        db.remove_admin(user_id)
        await update.message.reply_text(f"✅ User {user_id} removed from admins.")
    except:
        await update.message.reply_text("Invalid user_id.")

@owner_only
async def list_admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = db.get_admins()
    text = "Admins:\n" + "\n".join(str(uid) for uid in admins)
    await update.message.reply_text(text)

@owner_only
async def get_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /getuser <user_id>")
        return
    try:
        user_id = int(context.args[0])
        with db.get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
            if not user:
                await update.message.reply_text("User not found.")
                return
            history = db.get_conversation_history(user_id, 10)
            history_text = "\n".join([f"{h['role']}: {h['message'][:50]}..." for h in history])
            text = (
                f"**User Profile**\n"
                f"ID: {user['user_id']}\n"
                f"Username: {user['username']}\n"
                f"Name: {user['first_name']} {user['last_name'] or ''}\n"
                f"Joined: {user['joined_at']}\n"
                f"Last Active: {user['last_active']}\n"
                f"Preferred Style: {user['preferred_image_style']}\n"
                f"\n**Recent Conversations:**\n{history_text or 'None'}"
            )
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

@owner_only
async def set_pref_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /setpref <user_id> <key> <value>")
        return
    try:
        user_id = int(context.args[0])
        key = context.args[1]
        value = ' '.join(context.args[2:])
        if key == 'style':
            db.set_user_style(user_id, value)
            await update.message.reply_text(f"✅ Style for {user_id} set to {value}")
        else:
            await update.message.reply_text("Only 'style' can be set for now.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

@owner_only
async def export_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /exportuser <user_id>")
        return
    try:
        user_id = int(context.args[0])
        with db.get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
            if not user:
                await update.message.reply_text("User not found.")
                return
            history = db.get_conversation_history(user_id, 100)
            data = {"user": dict(user), "conversations": [dict(row) for row in history]}
            json_str = json.dumps(data, indent=2, default=str)
            import io
            file = io.BytesIO(json_str.encode('utf-8'))
            await update.message.reply_document(document=file, filename=f"user_{user_id}.json")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

@owner_only
async def clear_user_data_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cleardata <user_id>")
        return
    try:
        user_id = int(context.args[0])
        with db.get_db() as conn:
            conn.execute('DELETE FROM conversations WHERE user_id = ?', (user_id,))
            conn.execute('UPDATE users SET preferred_image_style = "photorealistic" WHERE user_id = ?', (user_id,))
        await update.message.reply_text(f"✅ Data cleared for {user_id} (conversations deleted, style reset).")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# ---------- Admin Commands ----------
@admin_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message_text = ' '.join(context.args)
    users = db.get_all_users()
    success = 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=message_text)
            success += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {success} users.")

@admin_only
async def dm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /dm <user_id> <message>")
        return
    try:
        user_id = int(context.args[0])
        message_text = ' '.join(context.args[1:])
        await context.bot.send_message(chat_id=user_id, text=f"📩 From admin:\n{message_text}")
        await update.message.reply_text(f"✅ Message sent to {user_id}.")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")

@admin_only
async def bulk_dm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /bulkdm <id1,id2,...> <message>")
        return
    ids_str = context.args[0]
    message = ' '.join(context.args[1:])
    user_ids = [int(x.strip()) for x in ids_str.split(',')]
    success = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📨 Bulk DM:\n{message}")
            success += 1
        except:
            pass
    await update.message.reply_text(f"✅ Bulk DM sent to {success} users.")

@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = db.get_user_count()
    active_7d = db.get_active_users(7)
    admins = db.get_admins()
    text = f"📊 Bot Stats:\nTotal users: {total}\nActive last 7 days: {active_7d}\nAdmins: {len(admins)}"
    await update.message.reply_text(text)

@admin_only
async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("No users.")
        return
    text = "👥 Users (last 100):\n"
    for u in users[-100:]:
        text += f"{u['user_id']} - {u['username'] or 'no username'} - {u['first_name']}\n"
    await update.message.reply_text(text)

@admin_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backup_dir = os.path.join(os.path.dirname(__file__), 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    db_path = db.DB_PATH
    backup_sql = os.path.join(backup_dir, f'backup_{timestamp}.sql')
    with open(backup_sql, 'w') as f:
        for line in os.popen(f'sqlite3 {db_path} .dump'):
            f.write(line)

    users = db.get_all_users()
    csv_file = os.path.join(backup_dir, f'users_{timestamp}.csv')
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'username', 'first_name', 'last_name', 'joined_at', 'last_active', 'preferred_image_style'])
        for u in users:
            writer.writerow([u['user_id'], u['username'], u['first_name'], u['last_name'], u['joined_at'], u['last_active'], u['preferred_image_style']])

    await update.message.reply_document(document=open(backup_sql, 'rb'), filename=f'backup_{timestamp}.sql')
    await update.message.reply_document(document=open(csv_file, 'rb'), filename=f'users_{timestamp}.csv')

    os.remove(backup_sql)
    os.remove(csv_file)

# ---------- Flask Webhook ----------
app = Flask(__name__)

@app.route('/')
def index():
    return 'Null Protocol Assistant is running'

@app.route('/webhook', methods=['POST'])
async def webhook():
    if request.method == 'POST':
        update = Update.de_json(request.get_json(force=True), bot_application.bot)
        await bot_application.process_update(update)
        return 'OK'
    return 'Method Not Allowed', 405

def set_webhook():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_application.bot.set_webhook(f"{WEBHOOK_URL}/webhook"))
    logger.info(f"Webhook set to {WEBHOOK_URL}/webhook")

# ---------- Telegram App ----------
bot_application = Application.builder().token(TELEGRAM_TOKEN).build()

# Handlers
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("image", image_command)],
    states={WAITING_FOR_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)]},
    fallbacks=[CommandHandler("cancel", cancel)],
)

bot_application.add_handler(CommandHandler("start", start))
bot_application.add_handler(CommandHandler("setstyle", setstyle_cmd))
bot_application.add_handler(conv_handler)
bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Admin/owner handlers
bot_application.add_handler(CommandHandler("addadmin", add_admin_cmd))
bot_application.add_handler(CommandHandler("rmadmin", remove_admin_cmd))
bot_application.add_handler(CommandHandler("admins", list_admins_cmd))
bot_application.add_handler(CommandHandler("getuser", get_user_cmd))
bot_application.add_handler(CommandHandler("setpref", set_pref_cmd))
bot_application.add_handler(CommandHandler("exportuser", export_user_cmd))
bot_application.add_handler(CommandHandler("cleardata", clear_user_data_cmd))
bot_application.add_handler(CommandHandler("broadcast", broadcast_cmd))
bot_application.add_handler(CommandHandler("dm", dm_cmd))
bot_application.add_handler(CommandHandler("bulkdm", bulk_dm_cmd))
bot_application.add_handler(CommandHandler("stats", stats_cmd))
bot_application.add_handler(CommandHandler("listusers", list_users_cmd))
bot_application.add_handler(CommandHandler("backup", backup_cmd))

if __name__ == '__main__':
    set_webhook()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
