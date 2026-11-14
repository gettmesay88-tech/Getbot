import os
import time
import html
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import telebot
from telebot import types
from flask import Flask
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError
from ethiopian_date import EthiopianDateConverter


# ============================================================
# 1. LOGGING, ENVIRONMENT, BOT AND DATABASE
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("gett-vip")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")
MONGO_URI = os.getenv("MONGO_URI")

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not ADMIN_ID_RAW:
    raise RuntimeError("Missing ADMIN_ID environment variable.")
if not MONGO_URI:
    raise RuntimeError("Missing MONGO_URI environment variable.")

ADMIN_ID = int(ADMIN_ID_RAW)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=20)

mongo_client = MongoClient(
    MONGO_URI,
    maxPoolSize=50,
    minPoolSize=5,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000,
    retryWrites=True,
)
db = mongo_client["gett_vip_ultimate_db"]
users_col = db["users"]
channels_col = db["channels"]
settings_col = db["settings"]

# Indexes reduce repeated scans and help MongoDB serve user/channel lookups.
try:
    mongo_client.admin.command("ping")
    users_col.create_index([("user_id", ASCENDING)], unique=True)
    users_col.create_index([("active", ASCENDING), ("expiry", ASCENDING)])
    channels_col.create_index([("id", ASCENDING)], unique=True)
    settings_col.create_index([("type", ASCENDING)], unique=True)
    logger.info("MongoDB connected and indexes checked.")
except Exception:
    logger.exception("MongoDB startup/index check failed.")
    raise


# ============================================================
# 2. WEB KEEP-ALIVE SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Gett VIP Bot is running.", 200


def run_web_server():
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def start_keep_alive():
    threading.Thread(target=run_web_server, daemon=True).start()


# ============================================================
# 3. CONFIGURATION
# ============================================================

PLANS = {
    "plan1": {"days": 30, "price": 200, "name": "የ 1 ወር (200 ብር)"},
    "plan2": {"days": 60, "price": 380, "name": "የ 2 ወር (380 ብር)"},
    "plan3": {"days": 90, "price": 550, "name": "የ 3 ወር (550 ብር)"},
    "plan5": {"days": 150, "price": 1050, "name": "የ 5 ወር (1050 ብር)"},
    "plan12": {"days": 365, "price": 2000, "name": "የ 1 ዓመት (2000 ብር)"},
}

CHANNELS_PER_PAGE = 10
POSTERS_TO_SHOW = 5
POSTER_HISTORY_LIMIT = 50
EXPIRY_CHECK_SECONDS = 300


# ============================================================
# 4. GENERAL HELPERS
# ============================================================

def safe_html(value) -> str:
    return html.escape(str(value or ""))


def is_admin(user_id: int) -> bool:
    return int(user_id) == ADMIN_ID


def is_restriction_on() -> bool:
    data = settings_col.find_one({"type": "config"})
    return bool(data.get("restriction", True)) if data else True


def to_eth_date(timestamp) -> str:
    try:
        dt = datetime.fromtimestamp(float(timestamp))
        converted = EthiopianDateConverter.to_ethiopian(dt.year, dt.month, dt.day)
        months = [
            "", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት",
            "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ",
        ]
        return f"{months[converted.month]} {converted.day}፣ {converted.year}"
    except Exception:
        logger.exception("Ethiopian date conversion failed.")
        return "ያልታወቀ ቀን"


def user_is_active(user_id: int) -> bool:
    user = users_col.find_one({"user_id": int(user_id), "active": True})
    return bool(user and float(user.get("expiry", 0)) > time.time())


def safe_answer_callback(call, text: str = "", show_alert: bool = False):
    try:
        bot.answer_callback_query(call.id, text=text, show_alert=show_alert)
    except Exception:
        logger.debug("Could not answer callback query.", exc_info=True)


def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💎 VIP ለመመዝገብ"),
        types.KeyboardButton("👤 የእኔ አገልግሎት"),
    )
    markup.add(
        types.KeyboardButton("🎬 አዳዲስ ፊልሞች"),
        types.KeyboardButton("📜 VIP Channel ዝርዝር"),
    )
    markup.add(types.KeyboardButton("🆘 እገዛ (Help)"))
    return markup


def admin_panel_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 የደንበኞች ዝርዝር", callback_data="adm_list"),
        types.InlineKeyboardButton("📢 ብሮድካስት", callback_data="adm_bc"),
    )
    markup.add(
        types.InlineKeyboardButton("➕ ቻናል ጨምር", callback_data="adm_add_ch"),
        types.InlineKeyboardButton("➖ ቻናል ቀንስ", callback_data="adm_rem_ch"),
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔄 የቻናል ስሞችን አድስ (Sync)",
            callback_data="adm_sync_names",
        )
    )
    restriction_text = "🚫 Restriction: ON" if is_restriction_on() else "🔓 Restriction: OFF"
    markup.add(types.InlineKeyboardButton(restriction_text, callback_data="adm_toggle_res"))
    markup.add(
        types.InlineKeyboardButton(
            "👤 ተጠቃሚ ማባረር (Manual)",
            callback_data="adm_manual_remove",
        )
    )
    return markup


def get_channel_status_markup(user_id: int, page: int = 0):
    """Shows only one page of channels; invite links are generated on demand."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    total = channels_col.count_documents({})
    if total == 0:
        markup.add(types.InlineKeyboardButton("ምንም ቻናል አልተጨመረም", callback_data="none"))
        return markup

    channels = list(
        channels_col.find({}, {"_id": 0, "id": 1, "name": 1})
        .sort("name", ASCENDING)
        .skip(page * CHANNELS_PER_PAGE)
        .limit(CHANNELS_PER_PAGE)
    )

    for channel in channels:
        channel_id = int(channel["id"])
        name = safe_html(channel.get("name", "Channel"))
        try:
            member = bot.get_chat_member(channel_id, user_id)
            joined = member.status in ("member", "administrator", "creator")
            icon = "✅" if joined else "☑️"
        except Exception:
            # Do not hide a channel if Telegram temporarily fails to return membership.
            icon = "❔"
        markup.add(
            types.InlineKeyboardButton(
                f"{icon} {channel.get('name', 'Channel')}",
                callback_data=f"join_ch_{channel_id}",
            )
        )

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"service_page_{page-1}"))
    if (page + 1) * CHANNELS_PER_PAGE < total:
        nav.append(types.InlineKeyboardButton("ቀጣይ ➡️", callback_data=f"service_page_{page+1}"))
    if nav:
        markup.row(*nav)
    markup.add(
        types.InlineKeyboardButton(
            "🔄 ሁኔታውን አድስ",
            callback_data=f"service_page_{page}",
        )
    )
    return markup


def send_channel_join_link(user_id: int, channel_id: int):
    if not user_is_active(user_id):
        bot.send_message(user_id, "ይህን አገልግሎት ለመጠቀም ንቁ VIP አባልነት ያስፈልጋል።")
        return

    try:
        member = bot.get_chat_member(channel_id, user_id)
        if member.status in ("member", "administrator", "creator"):
            bot.send_message(user_id, "✅ አስቀድመው ይህን ቻናል ተቀላቅለዋል።")
            return

        invite = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            name=f"VIP user {user_id}",
        ).invite_link

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔗 ቻናሉን ተቀላቀል", url=invite))
        bot.send_message(user_id, "👇 የቻናሉን ሊንክ ይጫኑ፦", reply_markup=markup)
    except Exception:
        logger.exception("Could not create channel invite link for user %s", user_id)
        bot.send_message(
            user_id,
            "❌ የቻናሉን ሊንክ ማዘጋጀት አልተቻለም። ቦቱ በቻናሉ ላይ Admin መሆኑን ያረጋግጡ።",
        )


# ============================================================
# 5. EXPIRY WORKER
# ============================================================

def remove_user_from_channels(user_id: int):
    for channel in channels_col.find({}, {"id": 1}):
        try:
            channel_id = int(channel["id"])
            bot.ban_chat_member(channel_id, user_id)
            bot.unban_chat_member(channel_id, user_id)
        except Exception:
            logger.warning(
                "Could not remove user %s from channel %s",
                user_id,
                channel.get("id"),
                exc_info=True,
            )


def auto_kick_worker():
    """Claims expired accounts once, then removes them from registered channels."""
    while True:
        try:
            now = time.time()
            expired_cursor = users_col.find(
                {"active": True, "expiry": {"$lte": now}},
                {"user_id": 1},
                no_cursor_timeout=True,
            ).batch_size(100)

            try:
                for record in expired_cursor:
                    user_id = int(record["user_id"])
                    # Atomic claim prevents duplicate processing by this worker.
                    claimed = users_col.update_one(
                        {"user_id": user_id, "active": True, "expiry": {"$lte": now}},
                        {"$set": {"active": False, "expired_processed_at": now}},
                    )
                    if claimed.modified_count == 0:
                        continue

                    logger.info("Expiring VIP user %s", user_id)
                    remove_user_from_channels(user_id)
                    try:
                        bot.send_message(
                            user_id,
                            "<b>⚠️ የአገልግሎት ጊዜዎ አብቅቷል!</b>\n\n"
                            "ከVIP ቻናሎች ተወግደዋል። አገልግሎቱን ለመቀጠል "
                            "እባክዎ አዲስ ጥቅል ይምረጡ።",
                        )
                    except Exception:
                        logger.info("Could not notify expired user %s", user_id)
            finally:
                expired_cursor.close()

        except Exception:
            logger.exception("Auto-expiry worker error.")

        time.sleep(EXPIRY_CHECK_SECONDS)


# ============================================================
# 6. USER MESSAGE HANDLERS
# ============================================================

@bot.message_handler(commands=["start"])
def handle_start(message):
    user_id = message.from_user.id
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "first_name": message.from_user.first_name or "",
                "username": message.from_user.username or "",
                "last_seen": time.time(),
            },
            "$setOnInsert": {"active": False, "created_at": time.time()},
        },
        upsert=True,
    )

    first_name = safe_html(message.from_user.first_name or "دوست")
    welcome = (
        f"<b>ሰላም {first_name}፣ እንኳን ወደ Gett VIP Bot በሰላም መጡ!</b>\n\n"
        "ይህ ቦት የVIP ቻናሎቻችንን በክፍያ ለመቀላቀል "
        "እና አገልግሎትዎን ለመቆጣጠር ይረዳዎታል። "
        "ለመጀመር ከታች ካሉት አማራጮች አንዱን ይምረጡ።"
    )
    bot.send_message(user_id, welcome, reply_markup=main_menu_keyboard())

    if is_admin(user_id):
        bot.send_message(
            ADMIN_ID,
            "<b>🛠 Master Admin Panel:</b>",
            reply_markup=admin_panel_keyboard(),
        )


@bot.message_handler(func=lambda m: m.text == "👤 የእኔ አገልግሎት")
def handle_my_service(message):
    user_id = message.from_user.id
    user = users_col.find_one({"user_id": user_id})

    if not user or not user.get("active") or float(user.get("expiry", 0)) <= time.time():
        bot.send_message(
            user_id,
            "<b>ሰላም፣ ንቁ የGett VIP አባልነት የለዎትም።</b>\n\n"
            "አባል ለመሆን '💎 VIP ለመመዝገብ' የሚለውን ይጫኑ።",
        )
        return

    expiry = to_eth_date(user.get("expiry", 0))
    plan_name = PLANS.get(user.get("plan"), {"name": "ያልታወቀ"})["name"]
    text = (
        f"<b>👤 ስም፦</b> {safe_html(message.from_user.first_name)}\n"
        f"<b>💎 የአባልነት አይነት፦</b> {safe_html(plan_name)}\n"
        f"<b>⏳ የሚያበቃው፦</b> {expiry}\n\n"
        "<b>ሁኔታዎች፦</b>\n"
        "✅ - ቻናሉ ውስጥ ገብተዋል\n"
        "☑️ - ቻናሉ ውስጥ አልገቡም\n"
        "❔ - ሁኔታውን ማረጋገጥ አልተቻለም\n\n"
        "ቻናሉን ለመቀላቀል የቻናሉን ቁልፍ ይጫኑ 👇"
    )
    bot.send_message(
        user_id,
        text,
        reply_markup=get_channel_status_markup(user_id, 0),
        protect_content=is_restriction_on(),
    )


@bot.message_handler(func=lambda m: m.text == "💎 VIP ለመመዝገብ")
def handle_registration(message):
    markup = types.InlineKeyboardMarkup()
    for plan_id, plan in PLANS.items():
        markup.add(
            types.InlineKeyboardButton(
                f"💳 {plan['name']}",
                callback_data=f"buy_{plan_id}",
            )
        )
    bot.send_message(
        message.chat.id,
        "<b>ለመመዝገብ የሚፈልጉትን ጥቅል ይምረጡ፦</b>",
        reply_markup=markup,
    )


@bot.message_handler(func=lambda m: m.text == "📜 VIP Channel ዝርዝር")
def handle_channel_list(message):
    channels = list(channels_col.find({}, {"name": 1}).sort("name", ASCENDING))
    if not channels:
        bot.send_message(message.chat.id, "<b>❌ ምንም ቻናል የለም።</b>")
        return

    markup = types.InlineKeyboardMarkup()
    for index, channel in enumerate(channels, start=1):
        markup.add(
            types.InlineKeyboardButton(
                f"🔹 {channel.get('name', 'Channel')} {index}",
                callback_data=f"view_ch_{channel['id']}",
            )
        )
    bot.send_message(
        message.chat.id,
        "<b>📜 የVIP ቻናሎች ዝርዝር፦</b>\nስለ ቻናሉ ለማወቅ ስሙን ይጫኑ 👇",
        reply_markup=markup,
    )


@bot.message_handler(func=lambda m: m.text == "🎬 አዳዲስ ፊልሞች")
def handle_new_movies(message):
    channels = list(channels_col.find({}, {"id": 1, "name": 1}).sort("name", ASCENDING))
    if not channels:
        bot.send_message(message.chat.id, "<b>❌ ምንም ቻናል አልተገኘም።</b>")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for channel in channels[:100]:
        clean_name = str(channel.get("name", "Channel")).split("-")[0].strip()
        clean_name = "".join(ch for ch in clean_name if not ch.isdigit()).strip() or "Channel"
        buttons.append(
            types.InlineKeyboardButton(
                f"🎬 {clean_name[:35]}",
                callback_data=f"get_last_5_{channel['id']}",
            )
        )
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "<b>🎬 የፊልም ፖስተሮች፦</b>\n\n"
        "የፊልም ፎቶዎችን ለማየት የቻናሉን ስም ይጫኑ 👇",
        reply_markup=markup,
    )


@bot.message_handler(func=lambda m: m.text == "🆘 እገዛ (Help)")
def handle_help(message):
    bot.send_message(
        message.chat.id,
        "<b>🆘 Gett VIP Help</b>\n\n"
        "💎 VIP ለመመዝገብ - ጥቅል ይምረጡ\n"
        "👤 የእኔ አገልግሎት - የአባልነት ሁኔታ ይመልከቱ\n"
        "📜 VIP Channel ዝርዝር - የቻናሎችን ስም ይመልከቱ\n\n"
        "ችግር ካጋጠመዎት አድሚኑን ያነጋግሩ።",
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
# 7. CHANNEL POST TRACKING FOR MOVIE POSTERS
# ============================================================

@bot.channel_post_handler(content_types=["photo"])
def track_channel_photo(message):
    """Telegram Bot API cannot read arbitrary channel history.
    Track new photo posts from the moment this version is deployed.
    """
    try:
        channels_col.update_one(
            {"id": message.chat.id},
            {
                "$set": {"name": message.chat.title or "Channel"},
                "$push": {
                    "poster_message_ids": {
                        "$each": [message.message_id],
                        "$slice": -POSTER_HISTORY_LIMIT,
                    }
                },
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Could not save channel poster message ID.")


# ============================================================
# 8. PAYMENT SUBMISSION STEPS
# ============================================================

def get_payment_screenshot(message):
    if message.text and message.text.strip().lower() == "/cancel":
        bot.send_message(
            message.chat.id,
            "ሂደቱ ተሰርዟል።",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not message.photo:
        bot.send_message(message.chat.id, "⚠️ እባክዎ የደረሰኙን ፎቶ (Screenshot) ብቻ ይላኩ። /cancel")
        bot.register_next_step_handler(message, get_payment_screenshot)
        return

    bot.send_message(
        message.chat.id,
        "<b>✅ ደረሰኙን ተቀብያለሁ!</b>\n"
        "አሁን የከፈሉበትን ሙሉ ስም ይላኩ፦",
    )
    bot.register_next_step_handler(message, collect_name_and_submit, message)


def collect_name_and_submit(message, photo_message):
    if not message.text:
        bot.send_message(message.chat.id, "እባክዎ ሙሉ ስምዎን በጽሑፍ ይላኩ። /cancel")
        bot.register_next_step_handler(message, collect_name_and_submit, photo_message)
        return

    if message.text.strip().lower() == "/cancel":
        bot.send_message(message.chat.id, "ሂደቱ ተሰርዟል።", reply_markup=main_menu_keyboard())
        return

    full_name = message.text.strip()[:100]
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("ሁሉንም ነገር ጨርሻለሁ ላክ"))
    bot.send_message(
        message.chat.id,
        f"ተቀብያለሁ <b>{safe_html(full_name)}</b>። ለመጨረስ ከታች ያለውን ቁልፍ ይጫኑ።",
        reply_markup=markup,
    )
    bot.register_next_step_handler(message, finalize_submission, photo_message, full_name)


def finalize_submission(message, photo_message, full_name):
    user_id = message.from_user.id
    if message.text != "ሁሉንም ነገር ጨርሻለሁ ላክ":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("ሁሉንም ነገር ጨርሻለሁ ላክ"))
        bot.send_message(
            user_id,
            "እባክዎ 'ሁሉንም ነገር ጨርሻለሁ ላክ' የሚለውን ይጫኑ።",
            reply_markup=markup,
        )
        bot.register_next_step_handler(message, finalize_submission, photo_message, full_name)
        return

    user_data = users_col.find_one({"user_id": user_id}) or {}
    plan_id = user_data.get("pending_plan", "plan1")
    if plan_id not in PLANS:
        plan_id = "plan1"

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "pending_receipt": True,
                "pending_full_name": full_name,
                "pending_receipt_message_id": photo_message.message_id,
                "pending_submitted_at": time.time(),
            }
        },
        upsert=True,
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "✅ Approve",
            callback_data=f"approve_{user_id}_{plan_id}",
        ),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}"),
    )

    admin_text = (
        "<b>💰 አዲስ የክፍያ ጥያቄ!</b>\n\n"
        f"👤 <b>ስም፦</b> {safe_html(full_name)}\n"
        f"🆔 <b>ID፦</b> <code>{user_id}</code>\n"
        f"💎 <b>ጥቅል፦</b> {safe_html(PLANS[plan_id]['name'])}"
    )
    bot.send_message(ADMIN_ID, admin_text)
    bot.forward_message(ADMIN_ID, user_id, photo_message.message_id)
    bot.send_message(ADMIN_ID, "ደረሰኙን ያረጋግጡ፦", reply_markup=markup)

    bot.send_message(
        user_id,
        "<b>✅ በስኬት ተልኳል!</b>\nአድሚኑ ደረሰኙን አይቶ በቅርቡ ያረጋግጥልዎታል።",
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
# 9. ADMIN NEXT-STEP PROCESSES
# ============================================================

def process_add_channel(message):
    if not is_admin(message.from_user.id):
        return

    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል።", reply_markup=admin_panel_keyboard())
        return

    if message.text == "✅ ሁሉንም ጨርሻለሁ":
        bot.send_message(ADMIN_ID, "<b>ስራው ተጠናቋል!</b>", reply_markup=main_menu_keyboard())
        bot.send_message(ADMIN_ID, "<b>🛠 Master Admin Panel:</b>", reply_markup=admin_panel_keyboard())
        return

    forwarded_chat = getattr(message, "forward_from_chat", None)
    if not forwarded_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ እባክዎ ከቻናሉ የተላከ መልዕክት Forward ያድርጉ። /cancel",
        )
        bot.register_next_step_handler(message, process_add_channel)
        return

    channel_id = forwarded_chat.id
    channel_name = forwarded_chat.title or "Channel"
    try:
        bot.get_chat(channel_id)
        channels_col.update_one(
            {"id": channel_id},
            {
                "$set": {"id": channel_id, "name": channel_name},
                "$setOnInsert": {"poster_message_ids": []},
            },
            upsert=True,
        )
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
        bot.send_message(
            ADMIN_ID,
            f"✅ ቻናል <b>{safe_html(channel_name)}</b> ተጨምሯል!\n"
            "ሌላ ቻናል Forward ያድርጉ ወይም ሲጨርሱ ቁልፉን ይጫኑ።",
            reply_markup=markup,
        )
    except Exception:
        logger.exception("Adding channel failed.")
        bot.send_message(
            ADMIN_ID,
            "❌ ቻናሉን መጨመር አልተቻለም። ቦቱ በቻናሉ ላይ Admin መሆኑን ያረጋግጡ።",
        )

    bot.register_next_step_handler(message, process_add_channel)


def process_manual_remove(message):
    if not is_admin(message.from_user.id):
        return

    raw = (message.text or "").strip()
    if raw == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል።", reply_markup=admin_panel_keyboard())
        return
    if not raw.isdigit():
        bot.send_message(ADMIN_ID, "❌ ትክክለኛ የቁጥር User ID ያስገቡ። /cancel")
        bot.register_next_step_handler(message, process_manual_remove)
        return

    target_id = int(raw)
    users_col.update_one(
        {"user_id": target_id},
        {"$set": {"active": False, "expiry": 0, "manually_removed_at": time.time()}},
    )
    remove_user_from_channels(target_id)
    bot.send_message(
        ADMIN_ID,
        f"✅ ተጠቃሚ <code>{target_id}</code> ከቻናሎች እንዲወገድ ተሞክሯል፤ አገልግሎቱም ተዘግቷል።",
        reply_markup=admin_panel_keyboard(),
    )


def process_broadcast(message):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip().lower() == "/cancel":
        bot.send_message(ADMIN_ID, "ብሮድካስቱ ተሰርዟል።", reply_markup=admin_panel_keyboard())
        return

    recipients = users_col.find({}, {"user_id": 1})
    sent = failed = 0
    for record in recipients:
        try:
            bot.copy_message(
                int(record["user_id"]),
                message.chat.id,
                message.message_id,
            )
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.04)

    bot.send_message(
        ADMIN_ID,
        f"📢 ብሮድካስት ተጠናቋል።\n✅ የተላከ: {sent}\n❌ ያልተሳካ: {failed}",
        reply_markup=admin_panel_keyboard(),
    )


def process_custom_rejection(message, target_id):
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        bot.send_message(ADMIN_ID, "እባክዎ የውድቅ ምክንያቱን በጽሑፍ ይላኩ።")
        bot.register_next_step_handler(message, process_custom_rejection, target_id)
        return
    try:
        bot.send_message(
            target_id,
            f"<b>❌ የክፍያ ጥያቄዎ አልጸደቀም።</b>\n\nምክንያት፦ {safe_html(message.text[:500])}",
        )
    except Exception:
        pass
    users_col.update_one({"user_id": target_id}, {"$set": {"pending_receipt": False}})
    bot.send_message(ADMIN_ID, "ለተጠቃሚው ምላሽ ተልኳል።", reply_markup=admin_panel_keyboard())


# ============================================================
# 10. CALLBACK HANDLER
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    user_id = call.from_user.id
    data = call.data or ""
    message_id = call.message.message_id if call.message else None
    chat_id = call.message.chat.id if call.message else user_id

    # Every admin action is checked before executing it.
    admin_actions = (
        data.startswith("adm_")
        or data.startswith("approve_")
        or data.startswith("reject_")
        or data.startswith("rj_")
    )
    if admin_actions and not is_admin(user_id):
        safe_answer_callback(call, "ይህን እርምጃ ማድረግ የሚችሉት Admin ብቻ ናቸው።", True)
        return

    try:
        if data.startswith("buy_"):
            plan_id = data.split("_", 1)[1]
            if plan_id not in PLANS:
                safe_answer_callback(call, "የተሳሳተ ጥቅል ነው።", True)
                return
            users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "pending_plan": plan_id,
                        "pending_started_at": time.time(),
                    },
                    "$setOnInsert": {"active": False, "created_at": time.time()},
                },
                upsert=True,
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🏦 CBE (ንግድ ባንክ)", callback_data="pay_cbe"),
                types.InlineKeyboardButton("🏦 Abyssinia (አቢሲኒያ)", callback_data="pay_aby"),
            )
            markup.add(types.InlineKeyboardButton("📱 Telebirr (ቴሌብር)", callback_data="pay_tele"))
            bot.edit_message_text(
                "<b>ለመክፈል የሚፈልጉትን የክፍያ አይነት ይምረጡ፦</b>",
                chat_id,
                message_id,
                reply_markup=markup,
            )

        elif data.startswith("pay_"):
            method = data.split("_", 1)[1]
            user = users_col.find_one({"user_id": user_id}) or {}
            if user.get("pending_plan") not in PLANS:
                safe_answer_callback(call, "መጀመሪያ ጥቅል ይምረጡ።", True)
                return

            if method == "cbe":
                account_info = (
                    "<b>🏦 የኢትዮጵያ ንግድ ባንክ (CBE)</b>\n"
                    "👤 ስም: Getamesay Fikru\n"
                    "🔢 Acc: <code>1000355140206</code>"
                )
            elif method == "aby":
                account_info = (
                    "<b>🏦 አቢሲኒያ ባንክ (Abyssinia)</b>\n"
                    "👤 ስም: Getamesay Fikru\n"
                    "🔢 Acc: <code>167829104</code>"
                )
            elif method == "tele":
                account_info = (
                    "<b>📱 ቴሌብር (Telebirr)</b>\n"
                    "👤 ስም: Getamesay Fikru\n"
                    "🔢 ስልክ: <code>0965979124</code>"
                )
            else:
                safe_answer_callback(call, "የክፍያ አይነቱ አልታወቀም።", True)
                return

            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"pending_payment_method": method}},
            )
            instruction = (
                f"{account_info}\n\n"
                "<b>📸 ክፍያውን ከፈጸሙ በኋላ የደረሰኙን Screenshot እዚህ ይላኩ።</b>\n\n"
                "ለመሰረዝ /cancel ይበሉ።"
            )
            bot.edit_message_text(instruction, chat_id, message_id)
            bot.register_next_step_handler(call.message, get_payment_screenshot)

        elif data in ("adm_users", "adm_list"):
            active_users = users_col.find(
                {"active": True, "expiry": {"$gt": time.time()}}
            ).sort("expiry", ASCENDING).limit(100)
            users = list(active_users)
            if not users:
                bot.send_message(ADMIN_ID, "ምንም ገባሪ ደንበኛ የለም።")
                safe_answer_callback(call)
                return

            bot.send_message(ADMIN_ID, f"<b>📋 የደንበኞች ዝርዝር (እስከ 100): {len(users)}</b>")
            for item in users:
                target_id = int(item["user_id"])
                plan_name = PLANS.get(item.get("plan"), {"name": "N/A"})["name"]
                expiry = to_eth_date(item.get("expiry", 0))
                markup = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(
                        "❌ አስወግድ (Remove)",
                        callback_data=f"adm_kick_{target_id}",
                    )
                )
                detail = (
                    f"👤 <a href='tg://user?id={target_id}'>ተጠቃሚውን እዚህ ይጫኑ</a>\n"
                    f"🆔 <code>{target_id}</code>\n"
                    f"💰 {safe_html(plan_name)}\n"
                    f"⏳ {expiry}"
                )
                bot.send_message(ADMIN_ID, detail, reply_markup=markup)
            safe_answer_callback(call)

        elif data.startswith("adm_kick_"):
            target_id = int(data.rsplit("_", 1)[1])
            users_col.update_one(
                {"user_id": target_id},
                {"$set": {"active": False, "expiry": 0, "manually_removed_at": time.time()}},
            )
            remove_user_from_channels(target_id)
            safe_answer_callback(call, "ተጠቃሚው ተወግዷል።")
            bot.edit_message_text(
                f"✅ ተጠቃሚ <code>{target_id}</code> ከአገልግሎት ተወግዷል።",
                chat_id,
                message_id,
            )

        elif data == "adm_add_ch":
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(types.KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
            prompt = bot.send_message(
                ADMIN_ID,
                "ከመጨመር የሚፈልጉት ቻናል አንድ መልዕክት Forward ያድርጉ።\n"
                "ሲጨርሱ '✅ ሁሉንም ጨርሻለሁ' ይጫኑ።",
                reply_markup=markup,
            )
            bot.register_next_step_handler(prompt, process_add_channel)
            safe_answer_callback(call)

        elif data == "adm_rem_ch":
            channels = list(channels_col.find({}, {"id": 1, "name": 1}).sort("name", ASCENDING))
            markup = types.InlineKeyboardMarkup()
            for channel in channels:
                markup.add(
                    types.InlineKeyboardButton(
                        f"❌ {channel.get('name', 'Channel')}",
                        callback_data=f"adm_confirm_del_{channel['id']}",
                    )
                )
            markup.add(
                types.InlineKeyboardButton(
                    "🔥 ሁሉንም ቻናል አስወግድ",
                    callback_data="adm_del_all_confirm",
                )
            )
            bot.edit_message_text(
                "መሰረዝ የሚፈልጉትን ቻናል ይምረጡ፦",
                chat_id,
                message_id,
                reply_markup=markup,
            )

        elif data == "adm_del_all_confirm":
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("✅ አዎ! ሁሉንም ሰርዝ", callback_data="adm_do_del_all_final"),
                types.InlineKeyboardButton("❌ አይ ተመለስ", callback_data="adm_rem_ch"),
            )
            bot.edit_message_text(
                "⚠️ <b>እርግጠኛ ነዎት?</b> ሁሉንም ቻናሎች ከዳታቤዝ ያጠፋል።",
                chat_id,
                message_id,
                reply_markup=markup,
            )

        elif data == "adm_do_del_all_final":
            channels_col.delete_many({})
            safe_answer_callback(call, "ሁሉም ቻናሎች ተሰርዘዋል!")
            bot.edit_message_text(
                "✅ ሁሉም የVIP ቻናሎች ተሰርዘዋል።",
                chat_id,
                message_id,
            )

        elif data.startswith("adm_confirm_del_"):
            channel_id = int(data.rsplit("_", 1)[1])
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("አዎ ሰርዝ", callback_data=f"adm_do_del_{channel_id}"),
                types.InlineKeyboardButton("አይ ተመለስ", callback_data="adm_rem_ch"),
            )
            bot.edit_message_text(
                "<b>እርግጠኛ ነዎት ይህ ቻናል ይጥፋ?</b>",
                chat_id,
                message_id,
                reply_markup=markup,
            )

        elif data.startswith("adm_do_del_"):
            channel_id = int(data.rsplit("_", 1)[1])
            channels_col.delete_one({"id": channel_id})
            safe_answer_callback(call, "ቻናሉ ተሰርዟል!")
            bot.edit_message_text("✅ ቻናሉ ተሰርዟል።", chat_id, message_id)

        elif data == "adm_toggle_res":
            current = is_restriction_on()
            settings_col.update_one(
                {"type": "config"},
                {"$set": {"restriction": not current}},
                upsert=True,
            )
            safe_answer_callback(call, "Restriction Status Updated!")
            bot.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup=admin_panel_keyboard(),
            )

        elif data == "adm_manual_remove":
            prompt = bot.send_message(
                ADMIN_ID,
                "ማስወገድ የሚፈልጉትን User ID ይላኩ። /cancel",
            )
            bot.register_next_step_handler(prompt, process_manual_remove)
            safe_answer_callback(call)

        elif data == "adm_bc":
            prompt = bot.send_message(
                ADMIN_ID,
                "ለሁሉም ተጠቃሚዎች የሚላከውን መልዕክት ወይም ፎቶ ይላኩ። /cancel",
            )
            bot.register_next_step_handler(prompt, process_broadcast)
            safe_answer_callback(call)

        elif data == "adm_sync_names":
            safe_answer_callback(call, "የቻናል ስሞች እየታደሱ ነው...")
            updated = 0
            for channel in channels_col.find({}, {"id": 1}):
                try:
                    info = bot.get_chat(int(channel["id"]))
                    channels_col.update_one(
                        {"id": channel["id"]},
                        {"$set": {"name": info.title or "Channel"}},
                    )
                    updated += 1
                    time.sleep(0.05)
                except Exception:
                    logger.warning("Channel name sync failed for %s", channel.get("id"))
            bot.send_message(ADMIN_ID, f"✅ የ{updated} ቻናሎች ስም ታድሷል።")

        elif data.startswith("approve_"):
            _, target_text, plan_id = data.split("_", 2)
            target_id = int(target_text)
            if plan_id not in PLANS:
                safe_answer_callback(call, "የጥቅሉ መረጃ ትክክል አይደለም።", True)
                return

            pending = users_col.find_one({"user_id": target_id}) or {}
            if not pending.get("pending_receipt"):
                safe_answer_callback(call, "ይህ የክፍያ ጥያቄ አስቀድሞ ተ处理 ሊሆን ይችላል።", True)
                return

            expiry_ts = (datetime.now() + timedelta(days=PLANS[plan_id]["days"])).timestamp()
            joined_at = time.time()
            users_col.update_one(
                {"user_id": target_id},
                {
                    "$set": {
                        "active": True,
                        "expiry": expiry_ts,
                        "plan": plan_id,
                        "joined_at": joined_at,
                        "pending_receipt": False,
                        "approved_at": joined_at,
                    },
                    "$unset": {
                        "pending_plan": "",
                        "pending_full_name": "",
                        "pending_receipt_message_id": "",
                    },
                },
                upsert=True,
            )
            user_name = safe_html(pending.get("pending_full_name", "VIP Member"))
            approval_text = (
                "<b>✅ እንኳን ደስ አለዎት! ክፍያዎ ተረጋግጧል።</b>\n\n"
                f"👤 ስም: {user_name}\n"
                f"📅 የገቡበት: {to_eth_date(joined_at)}\n"
                f"⏳ የሚያበቃው: {to_eth_date(expiry_ts)}\n\n"
                "☑️ - ቻናል ውስጥ አልገቡም\n"
                "✅ - ቻናል ውስጥ ገብተዋል\n\n"
                "የቻናሎችን ሊንክ ከታች ይጫኑ።"
            )
            bot.send_message(
                target_id,
                approval_text,
                reply_markup=get_channel_status_markup(target_id, 0),
                protect_content=is_restriction_on(),
            )
            safe_answer_callback(call, "ክፍያው ጸድቋል።")
            bot.edit_message_text(
                f"✅ ተጠቃሚ <code>{target_id}</code> ጸድቋል!",
                chat_id,
                message_id,
            )

        elif data.startswith("reject_"):
            target_id = int(data.split("_", 1)[1])
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "🚫 የደረሰኝ ስህተት",
                    callback_data=f"rj_msg_{target_id}_receipt",
                ),
                types.InlineKeyboardButton(
                    "📉 ብር አነስተኛ ነው",
                    callback_data=f"rj_msg_{target_id}_amount",
                ),
            )
            markup.add(
                types.InlineKeyboardButton(
                    "✍️ የራስህን መልዕክት ጻፍ",
                    callback_data=f"rj_custom_{target_id}",
                )
            )
            bot.edit_message_text(
                "ውድቅ የተደረገበትን ምክንያት ይምረጡ፦",
                chat_id,
                message_id,
                reply_markup=markup,
            )

        elif data.startswith("rj_msg_"):
            parts = data.split("_")
            target_id = int(parts[2])
            reason = (
                "የላኩት ደረሰኝ ትክክል አይደለም።"
                if parts[3] == "receipt"
                else "የተከፈለው መጠን ከተመረጠው ጥቅል ዋጋ ያነሰ ነው።"
            )
            bot.send_message(
                target_id,
                f"<b>❌ የክፍያ ጥያቄዎ አልጸደቀም።</b>\n\n{reason}",
            )
            users_col.update_one(
                {"user_id": target_id},
                {"$set": {"pending_receipt": False}},
            )
            safe_answer_callback(call, "ምክንያቱ ተልኳል።")
            bot.edit_message_text("የውድቅ ምክንያቱ ተልኳል።", chat_id, message_id)

        elif data.startswith("rj_custom_"):
            target_id = int(data.rsplit("_", 1)[1])
            prompt = bot.send_message(ADMIN_ID, "ለተጠቃሚው የሚላከውን ምክንያት ይጻፉ፦")
            bot.register_next_step_handler(prompt, process_custom_rejection, target_id)
            safe_answer_callback(call)

        elif data.startswith("view_ch_"):
            channel_id = int(data.rsplit("_", 1)[1])
            info = bot.get_chat(channel_id)
            description = info.description or "ለዚህ ቻናል ምንም መግለጫ አልተጻፈም።"
            safe_answer_callback(call, f"📝 የቻናሉ መግለጫ፦\n\n{description[:1800]}", True)

        elif data.startswith("service_page_"):
            if not user_is_active(user_id):
                safe_answer_callback(call, "ንቁ VIP አባልነት ያስፈልጋል።", True)
                return
            page = max(0, int(data.rsplit("_", 1)[1]))
            bot.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup=get_channel_status_markup(user_id, page),
            )
            safe_answer_callback(call)

        elif data.startswith("join_ch_"):
            channel_id = int(data.rsplit("_", 1)[1])
            safe_answer_callback(call)
            send_channel_join_link(user_id, channel_id)

        elif data.startswith("get_last_5_"):
            channel_id = int(data.rsplit("_", 1)[1])
            channel = channels_col.find_one({"id": channel_id}) or {}
            poster_ids = channel.get("poster_message_ids", [])
            if not poster_ids:
                bot.send_message(
                    user_id,
                    "❌ ከዚህ ቻናል አዲስ የፎቶ ፖስቶች ገና አልተመዘገቡም። "
                    "ቦቱን ከጨመሩ በኋላ የሚለቀቁ ፎቶዎች ይታያሉ።",
                )
                safe_answer_callback(call)
                return

            latest_ids = poster_ids[-POSTERS_TO_SHOW:]
            try:
                bot.send_message(
                    user_id,
                    f"<b>🎬 ከ {safe_html(channel.get('name', 'Channel'))} "
                    "የተመረጡ አዳዲስ የፊልም ፖስተሮች፦</b>",
                )
                bot.forward_messages(user_id, channel_id, latest_ids)
                bot.send_message(
                    user_id,
                    "<b>✅ ሁሉንም ፊልሞች ለማግኘት VIP አባል ይሁኑ!</b>",
                )
            except Exception:
                logger.exception("Poster forwarding failed.")
                bot.send_message(user_id, "❌ ፖስተሮቹን ማምጣት አልተቻለም።")
            safe_answer_callback(call)

        elif data == "none":
            safe_answer_callback(call, "ምንም ቻናል የለም።", True)

        else:
            safe_answer_callback(call, "ይህ ቁልፍ አይሰራም ወይም ጊዜው አልፏል።", True)

    except Exception:
        logger.exception("Callback processing failed: %s", data)
        safe_answer_callback(call, "ስህተት ተፈጥሯል። እንደገና ይሞክሩ።", True)


# ============================================================
# 11. STARTUP
# ============================================================

if __name__ == "__main__":
    logger.info("Starting Gett VIP Pro Bot...")
    start_keep_alive()

    threading.Thread(
        target=auto_kick_worker,
        daemon=True,
        name="vip-expiry-worker",
    ).start()

    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=False,
                allowed_updates=["message", "callback_query", "channel_post"],
            )
        except Exception:
            logger.exception("Polling stopped; retrying in 10 seconds.")
            time.sleep(10)
