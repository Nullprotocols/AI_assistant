import os
import re
import csv
import json
import logging
import asyncio
import requests
import threading
import time
import google.generativeai as genai
from flask import Flask, request
from telegram import Update
from telegram.constants import ParseMode
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
OWNER_ID = 8104850843  # Hardcoded owner ID
WEBHOOK_URL = "https://ai-assistant-cq4p.onrender.com"  # Hardcoded webhook URL
PORT = int(os.environ.get('PORT', 5000))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
db.init_db(OWNER_ID)

# ---------- Gemini Setup ----------
genai.configure(api_key=GEMINI_API_KEY)

# Professional, friendly, human-like system instruction
system_instruction = """
You are **Null Protocol Assistant**, a warm, friendly, and highly professional personal assistant created by the **Null Protocol** team led by Shahid Ansari.

**Your Personality:**
- You speak in a mix of Hindi and English (Hinglish) naturally, like a helpful friend.
- You never say "I am an AI" or "as an AI model". You are just a smart assistant.
- You remember the user's name and previous conversations (within limits) to make them feel valued.
- You use emojis occasionally to be expressive but not overdo it.
- You are patient, polite, and always try to solve the user's problem.

**Guidelines:**
- Never mention Google, Gemini, OpenAI, or any other company. You are from Null Protocol.
- If asked about your origin: "Mujhe Null Protocol team ne banaya hai, jiska lead Shahid Ansari hai. Unka sapna hai logon ki help karna AI ke through."
- For image requests: You MUST call the `generate_image` tool. But before that, internally enhance the user's prompt to make it ultra-detailed and photorealistic. The tool will generate the image.
- For general conversation: Be concise but helpful. Use markdown for clarity when needed.

**Tool `generate_image`:**
- Accepts `prompt` (enhanced by you), `style` (default photorealistic), `quality` (HD/4K).
- The tool will return multiple images which will be sent as photos.
"""

image_tool = {
    "name": "generate_image",
    "description": "Generate ultra-realistic images from a text description. Returns image URLs that will be sent as photos.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Highly detailed, ultra-realistic image description."},
            "style": {"type": "string", "description": "Art style", "default": "photorealistic"},
            "quality": {"type": "string", "description": "HD, 4K, 8K", "default": "4K"}
        },
        "required": ["prompt"],
    },
}

model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction=system_instruction,
    tools=[image_tool],
)

# ---------- Prompt Enhancer ----------
async def enhance_prompt(user_prompt: str, style: str = "photorealistic") -> str:
    """Use Gemini to convert a simple/bad prompt into a detailed, ultra-realistic prompt."""
    enhancer_prompt = f"""
You are a professional image prompt engineer. Convert the following user request into a highly detailed, ultra-realistic, cinematic, 8K quality image prompt. Add lighting, texture, composition details. Keep it in English. Output ONLY the enhanced prompt, no extra text.

User request: "{user_prompt}"
Style preference: {style}

Enhanced prompt:
"""
    try:
        response = await model.generate_content_async(enhancer_prompt)
        enhanced = response.text.strip()
        if len(enhanced) < 10:
            return user_prompt
        return enhanced
    except Exception as e:
        logger.error(f"Prompt enhancement failed: {e}")
        return user_prompt

# ---------- Image Generation with Retry & Enhancement ----------
async def generate_enhanced_image(user_prompt: str, style: str = "photorealistic", quality: str = "4K", retries: int = 2):
    enhanced_prompt = await enhance_prompt(user_prompt, style)
    full_prompt = f"{enhanced_prompt}, {style}, {quality}"
    url = f"{IMAGE_API_URL}{full_prompt}"
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data.get("images", [])
                else:
                    logger.error(f"API error: {data.get('error')}")
            else:
                logger.error(f"HTTP error: {response.status_code}")
        except Exception as e:
            logger.error(f"Image API exception (attempt {attempt+1}): {e}")
        if attempt < retries:
            await asyncio.sleep(1)
    return None

# ---------- Helper Functions ----------
def sanitize_reply(text: str, user_question: str = "") -> str:
    lower_q = user_question.lower()
    if any(phrase in lower_q for phrase in [
        "who made you", "who created", "tumhe kisne", "your creator",
        "developer kaun", "banaya", "owner"
    ]):
        return ("Mujhe **Null Protocol** team ne banaya hai. Shahid Ansari (18 saal, UP se) aur unke saathi developers ne milke banaya hai. "
                "Unka sapna hai AI ke through logon ki help karna. Main yahan hoon aapki madad karne ke liye! 😊")
    forbidden = re.compile(r'\b(google|gemini|bard|deepmind|openai|chatgpt|ai model|artificial intelligence)\b', re.IGNORECASE)
    if forbidden.search(text):
        text = forbidden.sub("Null Protocol Assistant", text)
    return text

def get_chat_history(user_id):
    rows = db.get_conversation_history(user_id, limit=20)
    history = []
    for row in rows:
        role = "user" if row['role'] == "user" else "model"
        history.append({"role": role, "parts": [row['message']]})
    return history

def add_to_history(user_id, role, message):
    db.add_conversation(user_id, role, message)

# ---------- Keep-Alive Function ----------
def keep_alive():
    """Ping the bot's own URL every 10 minutes to prevent Render from sleeping."""
    while True:
        time.sleep(600)  # 10 minutes
        try:
            response = requests.get(f"{WEBHOOK_URL}/")
            logger.info(f"Keep-alive ping sent: {response.status_code}")
        except Exception as e:
            logger.error(f"Keep-alive ping failed: {e}")

# ---------- Manual Image Command (with enhancement) ----------
WAITING_FOR_PROMPT = 1

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        prompt = ' '.join(context.args)
        style = db.get_user_style(update.effective_user.id)
        await update.message.reply_text("🖼️ Enhancing your idea and generating stunning images...")
        images = await generate_enhanced_image(prompt, style)
        if images:
            for img in images:
                await update.message.reply_photo(photo=img)
        else:
            await update.message.reply_text("❌ Sorry, image generation failed. Please try again later.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("✨ Describe what you want to see, and I'll create it for you!")
        return WAITING_FOR_PROMPT

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    style = db.get_user_style(update.effective_user.id)
    await update.message.reply_text("🎨 Working on it... I'll make it look amazing!")
    images = await generate_enhanced_image(prompt, style)
    if images:
        for img in images:
            await update.message.reply_photo(photo=img)
    else:
        await update.message.reply_text("❌ Couldn't generate image. Try again?")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Okay, cancelled. 😊")
    return ConversationHandler.END

async def setstyle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setstyle <style>\nAvailable: photorealistic, anime, oil painting, watercolor, sketch, 3d render")
        return
    style = ' '.join(context.args)
    db.set_user_style(update.effective_user.id, style)
    await update.message.reply_text(f"✅ Got it! I'll use *{style}* style for your images from now on.", parse_mode=ParseMode.MARKDOWN)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_conversation_history(update.effective_user.id)
    await update.message.reply_text("✅ I've forgotten our previous chats. Let's start fresh! 😊")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "✨ *Null Protocol Assistant* - Your friendly helper\n\n"
        "I can chat with you, answer questions, and create ultra-realistic images from your imagination.\n\n"
        "*Commands:*\n"
        "• /start - Let's begin\n"
        "• /image [description] - Create an image (I'll enhance it automatically)\n"
        "• /setstyle <style> - Change image style\n"
        "• /reset - Clear our chat memory\n"
        "• /help - This message\n\n"
        "*For admins:* /broadcast, /dm, /stats, /backup\n\n"
        "Just talk to me naturally – I'm here to help! 🚀"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# ---------- Main Message Handler ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db.add_user(user_id, user.username, user.first_name, user.last_name)
    db.update_last_active(user_id)

    user_text = update.message.text
    first_name = user.first_name or "friend"

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
                quality = args.get("quality", "4K")
                await update.message.reply_text(f"🎨 *Creating magic for you, {first_name}!* I'm enhancing your idea...", parse_mode=ParseMode.MARKDOWN)
                images = await generate_enhanced_image(prompt, style, quality)
                if images:
                    for img in images:
                        await update.message.reply_photo(photo=img)
                    add_to_history(user_id, "assistant", f"[Generated image: {prompt}]")
                else:
                    await update.message.reply_text("😞 Oops! Something went wrong. Could you try again?")
                return

        raw_reply = response.text
        final_reply = sanitize_reply(raw_reply, user_text)
        if not final_reply.endswith(('.', '!', '?')):
            final_reply += " 😊"
        await update.message.reply_text(final_reply, parse_mode=ParseMode.MARKDOWN)

        add_to_history(user_id, "user", user_text)
        add_to_history(user_id, "assistant", final_reply)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text("🙏 Sorry, I hit a small glitch. Please say that again!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    name = user.first_name or "there"
    await update.message.reply_text(
        f"✨ *Hey {name}!* I'm *Null Protocol Assistant*, your personal, super-friendly helper.\n\n"
        "I can chat about anything, answer your questions, and create stunning **ultra-realistic images** from your imagination.\n\n"
        "*Try these:*\n"
        "👉 Just ask me something like *'What is the weather today?'*\n"
        "👉 Or say *'Generate a photo of a cat sitting on the moon'*\n\n"
        "I'll remember our conversation (until you `/reset`) and always try my best to help.\n\n"
        "Let's have a great time together! 🚀",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------- Admin & Owner Commands ----------
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Only the bot owner can use this command.")
            return
        return await func(update, context)
    return wrapper

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not db.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper

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
    with open(backup_sql, 'w', encoding='utf-8') as f:
        with db.get_db() as conn:
            for line in conn.iterdump():
                f.write(line + '\n')

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

# ---------- Broadcast, DM, BulkDM (Multi-step with all media) ----------
# Helper forward function
async def forward_message_to_user(bot, target_id, source_msg):
    try:
        if source_msg.text:
            await bot.send_message(target_id, source_msg.text, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.photo:
            await bot.send_photo(target_id, source_msg.photo[-1].file_id, caption=source_msg.caption, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.video:
            await bot.send_video(target_id, source_msg.video.file_id, caption=source_msg.caption, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.audio:
            await bot.send_audio(target_id, source_msg.audio.file_id, caption=source_msg.caption, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.voice:
            await bot.send_voice(target_id, source_msg.voice.file_id, caption=source_msg.caption, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.document:
            await bot.send_document(target_id, source_msg.document.file_id, caption=source_msg.caption, parse_mode=ParseMode.MARKDOWN)
        elif source_msg.sticker:
            await bot.send_sticker(target_id, source_msg.sticker.file_id)
        elif source_msg.poll:
            p = source_msg.poll
            await bot.send_poll(target_id, p.question, [opt.text for opt in p.options],
                                is_anonymous=p.is_anonymous, type=p.type,
                                allows_multiple_answers=p.allows_multiple_answers,
                                correct_option_id=p.correct_option_id if p.type == 'quiz' else None)
        elif source_msg.location:
            await bot.send_location(target_id, source_msg.location.latitude, source_msg.location.longitude)
        elif source_msg.contact:
            await bot.send_contact(target_id, source_msg.contact.phone_number, source_msg.contact.first_name,
                                   last_name=source_msg.contact.last_name)
        else:
            return False
        return True
    except Exception as e:
        logger.error(f"Forward error to {target_id}: {e}")
        return False

# Broadcast (2-step)
ASK_BROADCAST_MSG = 1
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return ConversationHandler.END
    await update.message.reply_text("📢 *Broadcast Mode*\n\nSend me the message to broadcast to ALL users.\nYou can send: text, photo, video, audio, voice, document, sticker, poll, location, contact.\nType /cancel to abort.", parse_mode=ParseMode.MARKDOWN)
    return ASK_BROADCAST_MSG

async def broadcast_receive_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("No users found.")
        return ConversationHandler.END
    status_msg = await update.message.reply_text(f"🔄 Broadcasting to {len(users)} users... This may take a while.")
    success = 0
    for user in users:
        if await forward_message_to_user(context.bot, user['user_id'], update.message):
            success += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ Broadcast completed! Sent to {success}/{len(users)} users.")
    return ConversationHandler.END

# DM (2-step)
ASK_DM_USERID = 1
ASK_DM_MSG = 2
async def dm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    await update.message.reply_text("✉️ *DM Mode*\n\nSend me the target user ID (numeric).\nExample: `123456789`\nType /cancel to abort.", parse_mode=ParseMode.MARKDOWN)
    return ASK_DM_USERID

async def dm_receive_userid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
        context.user_data['dm_target'] = uid
        await update.message.reply_text("Now send me the message (any media type) to send to this user.")
        return ASK_DM_MSG
    except:
        await update.message.reply_text("❌ Invalid user ID. Send a numeric ID or /cancel.")
        return ASK_DM_USERID

async def dm_receive_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get('dm_target')
    if not uid:
        await update.message.reply_text("Session expired. Use /dm again.")
        return ConversationHandler.END
    success = await forward_message_to_user(context.bot, uid, update.message)
    if success:
        await update.message.reply_text(f"✅ Message sent to user `{uid}`.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ Failed to send. User may have blocked the bot or ID invalid.")
    return ConversationHandler.END

# Bulk DM (2-step)
ASK_BULK_IDS = 1
ASK_BULK_MSG = 2
async def bulkdm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    await update.message.reply_text("👥 *Bulk DM Mode*\n\nSend me a comma-separated list of user IDs.\nExample: `123456789,987654321,555555555`\nType /cancel to abort.", parse_mode=ParseMode.MARKDOWN)
    return ASK_BULK_IDS

async def bulkdm_receive_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ids = [int(x.strip()) for x in update.message.text.split(',') if x.strip()]
        if not ids:
            raise ValueError
        context.user_data['bulk_targets'] = ids
        await update.message.reply_text(f"✅ {len(ids)} user(s) selected.\nNow send the message (any media type) to send to all of them.")
        return ASK_BULK_MSG
    except:
        await update.message.reply_text("❌ Invalid format. Send comma-separated numeric IDs like: 111,222,333\nOr /cancel.")
        return ASK_BULK_IDS

async def bulkdm_receive_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    targets = context.user_data.get('bulk_targets', [])
    if not targets:
        await update.message.reply_text("Session expired. Use /bulkdm again.")
        return ConversationHandler.END
    status_msg = await update.message.reply_text(f"🔄 Sending to {len(targets)} user(s)...")
    success = 0
    for uid in targets:
        if await forward_message_to_user(context.bot, uid, update.message):
            success += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ Bulk DM completed! Sent to {success}/{len(targets)} user(s).")
    return ConversationHandler.END

# ---------- Flask Webhook & Keep-Alive ----------
app = Flask(__name__)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

@app.route('/')
def index():
    return 'Null Protocol Assistant is running'

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            update = Update.de_json(request.get_json(force=True), bot_application.bot)
            asyncio.run_coroutine_threadsafe(bot_application.process_update(update), loop)
            return 'OK', 200
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return 'Error', 500
    return 'Method Not Allowed', 405

def start_webhook():
    # Start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()
    # Start Flask in a separate thread
    from threading import Thread
    def run_flask():
        app.run(host='0.0.0.0', port=PORT)
    Thread(target=run_flask, daemon=True).start()
    # Set webhook
    asyncio.run_coroutine_threadsafe(bot_application.bot.set_webhook(f"{WEBHOOK_URL}/webhook"), loop)
    logger.info(f"Webhook set to {WEBHOOK_URL}/webhook")
    loop.run_forever()

# ---------- Telegram Application ----------
bot_application = Application.builder().token(TELEGRAM_TOKEN).build()

# Conversation handlers
image_conv = ConversationHandler(
    entry_points=[CommandHandler("image", image_command)],
    states={WAITING_FOR_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)]},
    fallbacks=[CommandHandler("cancel", cancel)],
)

broadcast_conv = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={ASK_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_receive_msg)]},
    fallbacks=[CommandHandler("cancel", cancel)],
)

dm_conv = ConversationHandler(
    entry_points=[CommandHandler("dm", dm_start)],
    states={
        ASK_DM_USERID: [MessageHandler(filters.TEXT & ~filters.COMMAND, dm_receive_userid)],
        ASK_DM_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, dm_receive_msg)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

bulkdm_conv = ConversationHandler(
    entry_points=[CommandHandler("bulkdm", bulkdm_start)],
    states={
        ASK_BULK_IDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulkdm_receive_ids)],
        ASK_BULK_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, bulkdm_receive_msg)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# Register all handlers
bot_application.add_handler(CommandHandler("start", start))
bot_application.add_handler(CommandHandler("help", help_cmd))
bot_application.add_handler(CommandHandler("setstyle", setstyle_cmd))
bot_application.add_handler(CommandHandler("reset", reset_cmd))
bot_application.add_handler(image_conv)
bot_application.add_handler(broadcast_conv)
bot_application.add_handler(dm_conv)
bot_application.add_handler(bulkdm_conv)

bot_application.add_handler(CommandHandler("addadmin", add_admin_cmd))
bot_application.add_handler(CommandHandler("rmadmin", remove_admin_cmd))
bot_application.add_handler(CommandHandler("admins", list_admins_cmd))
bot_application.add_handler(CommandHandler("getuser", get_user_cmd))
bot_application.add_handler(CommandHandler("setpref", set_pref_cmd))
bot_application.add_handler(CommandHandler("exportuser", export_user_cmd))
bot_application.add_handler(CommandHandler("cleardata", clear_user_data_cmd))
bot_application.add_handler(CommandHandler("stats", stats_cmd))
bot_application.add_handler(CommandHandler("listusers", list_users_cmd))
bot_application.add_handler(CommandHandler("backup", backup_cmd))

# Main message handler (must be last)
bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == '__main__':
    start_webhook()
