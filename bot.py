import os
import re
import random
import telebot
import time
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask
from pymongo import MongoClient, ASCENDING
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from ethiopian_date import EthiopianDateConverter

# =========================================================================
# 1. LOGGING & SERVER SETUP (KEEP ALIVE)
# =========================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask('')


@app.route('/')
def home():
    return "<b>Gett VIP Pro Bot is running smoothly!</b>"


def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def start_keep_alive():
    threading.Thread(target=run_web_server, daemon=True).start()


# =========================================================================
# 2. CONFIGURATION & DATABASE CONNECT
# =========================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
_admin_raw = os.getenv("ADMIN_ID")

if not BOT_TOKEN or not MONGO_URI or not _admin_raw or not _admin_raw.strip().lstrip("-").isdigit():
    raise SystemExit("Missing or invalid environment variables: BOT_TOKEN, MONGO_URI, ADMIN_ID (must be a number).")

ADMIN_ID = int(_admin_raw)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    db = client["gett_vip_ultimate_db"]
    users_col = db["users"]
    channels_col = db["channels"]
    settings_col = db["settings"]
    posters_col = db["posters"]
    posters_col.create_index([("channel_id", ASCENDING), ("message_id", ASCENDING)], unique=True)
    logger.info("Connected to MongoDB successfully!")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")
    raise SystemExit("Cannot start without database.")

PLANS = {
    "plan1": {"duration": 30, "price": 200, "name": "የ 1 ወር (200 ብር)", "days": 30},
    "plan2": {"duration": 60, "price": 380, "name": "የ 2 ወር (380 ብር)", "days": 60},
    "plan3": {"duration": 90, "price": 550, "name": "የ 3 ወር (550 ብር)", "days": 90},
    "plan5": {"duration": 150, "price": 1050, "name": "የ 5 ወር (1050 ብር)", "days": 150},
    "plan12": {"duration": 365, "price": 2000, "name": "የ 1 አመት (2000 ብር)", "days": 365}
}

REJECT_REASONS = {
    "receipt": "🚫 የላኩት ደረሰኝ ትክክል አይደለም። እባክዎ ትክክለኛውን ደረሰኝ ደግመው ይላኩ።",
    "amount": "📉 የከፈሉት ብር ከጥቅሉ ዋጋ ያነሰ ነው። እባክዎ ትክክለኛውን መጠን ከፍለው ደግመው ይላኩ።",
}


# =========================================================================
# 3. UTILITY FUNCTIONS
# =========================================================================
def to_eth_date(timestamp):
    """Converts Unix timestamp to Ethiopian Date String"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        conv = EthiopianDateConverter.to_ethiopian(dt.year, dt.month, dt.day)
        months = ["", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት", "መጋቢት",
                  "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"]
        return f"{months[conv.month]} {conv.day}፣ {conv.year}"
    except Exception as e:
        logger.error(f"Date conversion error: {e}")
        return "ያልታወቀ ቀን"


def is_restriction_on():
    data = settings_col.find_one({"type": "config"})
    return data.get("restriction", True) if data else True


def get_user_first_name(user_id):
    """Customer's name (not the admin's)."""
    u = users_col.find_one({"user_id": user_id}) or {}
    if u.get("first_name"):
        return u["first_name"]
    try:
        return bot.get_chat(user_id).first_name or "ደንበኛ"
    except Exception:
        return "ደንበኛ"


def get_channel_status_markup(user_id):
    """Channel list with join-status icons and a refresh button"""
    markup = InlineKeyboardMarkup()
    channels = list(channels_col.find())

    if not channels:
        markup.add(InlineKeyboardButton("ምንም ቻናል አልተጨመረም", callback_data="none"))
        return markup

    for index, ch in enumerate(channels, start=1):
        try:
            member = bot.get_chat_member(ch["id"], user_id)
            status_icon = "✅" if member.status in ['member', 'administrator', 'creator'] else "☑️"
            invite = bot.create_chat_invite_link(ch["id"], member_limit=1).invite_link
            markup.add(InlineKeyboardButton(f"{status_icon} {ch['name']} {index}", url=invite))
        except Exception as e:
            # Don't hide broken channels silently
            logger.error(f"Channel {ch.get('id')} status/invite error: {e}")
            markup.add(InlineKeyboardButton(f"⚠️ {ch['name']} {index}", callback_data="none"))

    markup.add(InlineKeyboardButton("🔄 ሁሉም ቻናል መግባቶን ያረጋግጡ (Refresh)", callback_data="refresh_service"))
    return markup


def kick_from_all_channels(user_id):
    ok = 0
    for ch in list(channels_col.find()):
        try:
            bot.ban_chat_member(ch["id"], user_id)
            bot.unban_chat_member(ch["id"], user_id)  # so they can rejoin later
            ok += 1
        except Exception as e:
            logger.error(f"Error kicking {user_id} from {ch['id']}: {e}")
    return ok


def is_admin(user_id):
    return user_id == ADMIN_ID


# =========================================================================
# 4. BACKGROUND WORKER (AUTO-KICK)
# =========================================================================
def auto_kick_worker():
    while True:
        try:
            now = datetime.now().timestamp()
            expired_users = list(users_col.find({"active": True, "expiry": {"$lt": now}}))

            for user in expired_users:
                uid = user["user_id"]
                logger.info(f"Expiring user: {uid}")
                kick_from_all_channels(uid)
                users_col.update_one({"user_id": uid}, {"$set": {"active": False}})
                try:
                    bot.send_message(
                        uid,
                        "<b>⚠️ የአገልግሎት ጊዜዎ አብቅቷል!</b>\n\nከVIP ቻናሎች በራስ-ሰር ተወግደዋል። "
                        "አገልግሎቱን ለመቀጠል እባክዎ ደግመው ይክፈሉ እና ደረሰኝ ይላኩ።"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Auto-kick worker error: {e}")

        time.sleep(60)


# =========================================================================
# 5. KEYBOARDS
# =========================================================================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💎 VIP ለመመዝገብ"), KeyboardButton("👤 የእኔ አገልግሎት"))
    markup.add(KeyboardButton("🎬 አዳዲስ ፊልሞች"), KeyboardButton("📜 VIP Channel ዝርዝር"))
    markup.add(KeyboardButton("🆘 እገዛ (Help)"))
    return markup


def admin_panel_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 የደንበኞች ዝርዝር", callback_data="adm_list"),
        InlineKeyboardButton("📢 ብሮድካስት", callback_data="adm_bc")
    )
    markup.add(
        InlineKeyboardButton("➕ ቻናል ጨምር", callback_data="adm_add_ch"),
        InlineKeyboardButton("➖ ቻናል ቀንስ", callback_data="adm_rem_ch")
    )
    markup.add(InlineKeyboardButton("🔄 የቻናል ስሞችን አድስ (Sync)", callback_data="adm_sync_names"))
    res_text = "🚫 Restriction: ON" if is_restriction_on() else "🔓 Restriction: OFF"
    markup.add(InlineKeyboardButton(res_text, callback_data="adm_toggle_res"))
    markup.add(InlineKeyboardButton("👤 ተጠቃሚ ማባረር (Manual)", callback_data="adm_manual_remove"))
    return markup


# =========================================================================
# 6. MESSAGE HANDLERS
# =========================================================================
@bot.message_handler(commands=['start'])
def handle_start(message):
    uid = message.chat.id
    first_name = message.from_user.first_name

    # Remember the customer's name for later (approval message etc.)
    users_col.update_one({"user_id": message.from_user.id},
                         {"$set": {"first_name": first_name}}, upsert=True)

    welcome_text = (
        f"<b>ሰላም {first_name}፣ እንኳን ወደ Gett VIP Bot በሰላም መጡ!</b>\n\n"
        "ይህ ቦት የVIP ቻናሎቻችንን በክፍያ ለመቀላቀል እና አገልግሎትዎን ለመቆጣጠር ይረዳዎታል። "
        "ለመጀመር ከታች ካሉት አማራጮች አንዱን ይምረጡ።"
    )
    bot.send_message(uid, welcome_text, reply_markup=main_menu_keyboard())

    if uid == ADMIN_ID:
        bot.send_message(ADMIN_ID, "<b>🛠 Master Admin Panel:</b>", reply_markup=admin_panel_keyboard())


@bot.message_handler(func=lambda m: m.text == "👤 የእኔ አገልግሎት")
def handle_my_service(message):
    uid = message.from_user.id
    user_data = users_col.find_one({"user_id": uid})

    if not user_data or not user_data.get("active"):
        bot.send_message(uid, "<b>ሰላም፣ እስካሁን የGett VIP አባል አልሆኑም ወይም ጊዜዎ አልቋል።</b>\n\nአባል ለመሆን '💎 VIP ለመመዝገብ' የሚለውን ይጫኑ።")
        return

    expiry_str = to_eth_date(user_data["expiry"])
    plan_name = PLANS.get(user_data.get("plan"), {"name": "ያልታወቀ"})["name"]

    status_text = (
        f"<b>👤 ስም፦</b> {message.from_user.first_name}\n"
        f"<b>💎 የአባልነት አይነት፦</b> {plan_name}\n"
        f"<b>⏳ የሚያበቃው፦</b> {expiry_str}\n\n"
        f"<b>ሁኔታዎች፦</b>\n✅ - ቻናሉ ውስጥ ገብተዋል\n☑️ - ቻናሉ ውስጥ አልገቡም\n\n"
        f"ሊንኮቹን በመጫን ይቀላቀሉ 👇"
    )
    bot.send_message(uid, status_text, reply_markup=get_channel_status_markup(uid),
                     protect_content=is_restriction_on())


@bot.message_handler(func=lambda m: m.text == "💎 VIP ለመመዝገብ")
def handle_registration(message):
    markup = InlineKeyboardMarkup()
    for key, val in PLANS.items():
        markup.add(InlineKeyboardButton(f"💳 {val['name']}", callback_data=f"buy_{key}"))
    bot.send_message(message.chat.id, "<b>ለመመዝገብ የሚፈልጉትን ጥቅል ይምረጡ፦</b>", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text == "📜 VIP Channel ዝርዝር")
def handle_channel_list(message):
    channels = list(channels_col.find())
    if not channels:
        bot.send_message(message.chat.id, "<b>❌ ምንም ቻናል የለም።</b>")
        return

    markup = InlineKeyboardMarkup()
    for index, ch in enumerate(channels, start=1):
        markup.add(InlineKeyboardButton(f"🔹 {ch['name']} {index}", callback_data=f"view_ch_{ch['id']}"))

    bot.send_message(message.chat.id, "<b>📜 የVIP ቻናሎች ዝርዝር፦</b>\nስለ ቻናሉ ለማወቅ ስሙን ይጫኑ 👇", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text == "🎬 አዳዲስ ፊልሞች")
def handle_new_movies(message):
    all_channels = list(channels_col.find())
    if not all_channels:
        bot.send_message(message.chat.id, "<b>❌ ምንም ቻናል አልተገኘም።</b>")
        return

    selected_channels = random.sample(all_channels, min(len(all_channels), 12))

    markup = InlineKeyboardMarkup(row_width=3)
    buttons = []
    for ch in selected_channels:
        clean_name = ch['name'].split('-')[0].strip()
        clean_name = ''.join(i for i in clean_name if not i.isdigit()).strip() or ch['name']
        buttons.append(InlineKeyboardButton(f"🎬 {clean_name}", callback_data=f"get_last_5_{ch['id']}"))

    markup.add(*buttons)
    bot.send_message(message.chat.id,
                     "<b>🎬 የፊልም ፖስተሮች፦</b>\n\nየፊልም ፎቶዎችን ለማየት የቻናሉን ስም ይጫኑ 👇",
                     reply_markup=markup)


@bot.message_handler(func=lambda m: m.text == "🆘 እገዛ (Help)")
def handle_help(message):
    bot.send_message(
        message.chat.id,
        "<b>🆘 እገዛ</b>\n\n1️⃣ '💎 VIP ለመመዝገብ' ን ይጫኑ\n2️⃣ ጥቅል እና የባንክ አይነት ይምረጡ\n"
        "3️⃣ ክፍያ ፈጽመው ደረሰኝ ይላኩ\n4️⃣ አድሚኑ ሲያረጋግጥ ሊንኮች ይላካሉ።"
    )


# --- Store poster file_ids as the bot sees new channel photo posts ---
@bot.channel_post_handler(content_types=['photo'])
def save_channel_poster(post):
    try:
        if not channels_col.find_one({"id": post.chat.id}):
            return
        posters_col.update_one(
            {"channel_id": post.chat.id, "message_id": post.message_id},
            {"$set": {"file_id": post.photo[-1].file_id, "date": post.date}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Poster save error: {e}")


# =========================================================================
# 7. CALLBACK QUERY HANDLER
# =========================================================================
ADMIN_PREFIXES = ("adm_", "approve_", "reject_", "rj_")
# callbacks that answer themselves with custom text
SELF_ANSWERED = ("adm_kick_", "adm_do_del_", "adm_toggle_res", "adm_sync_names", "view_ch_")


@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    uid, mid = call.from_user.id, call.message.message_id
    data = call.data

    # Admin-only actions
    if data.startswith(ADMIN_PREFIXES) and not is_admin(uid):
        bot.answer_callback_query(call.id, "⛔ ፈቃድ የለዎትም።", show_alert=True)
        return

    # Stop the loading spinner for everything that doesn't answer with custom text
    if not data.startswith(SELF_ANSWERED):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    if data == "none":
        return

    # ---- User: plan selection ----
    if data.startswith("buy_"):
        plan_id = data.split("_")[1]
        if plan_id not in PLANS:
            return
        users_col.update_one({"user_id": uid}, {"$set": {"pending_plan": plan_id}}, upsert=True)

        bank_markup = InlineKeyboardMarkup(row_width=2)
        bank_markup.add(
            InlineKeyboardButton("🏦 CBE (ንግድ ባንክ)", callback_data="pay_cbe"),
            InlineKeyboardButton("🏦 Abyssinia (አቢሲኒያ)", callback_data="pay_aby")
        )
        bank_markup.add(InlineKeyboardButton("📱 Telebirr (ቴሌብር)", callback_data="pay_tele"))
        bot.edit_message_text("<b>ለመክፈል የሚፈልጉትን የባንክ አይነት ይምረጡ፦</b>", uid, mid, reply_markup=bank_markup)

    # ---- User: payment method ----
    elif data.startswith("pay_"):
        method = data.split("_")[1]
        if method == "cbe":
            acc_info = "<b>🏦 የኢትዮጵያ ንግድ ባንክ (CBE)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>1000355140206</code>"
        elif method == "aby":
            acc_info = "<b>🏦 አቢሲኒያ ባንክ (Abyssinia)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>167829104</code>"
        else:
            acc_info = "<b>📱 ቴሌብር (Telebirr)</b>\n👤 ስም: Getamesay Fikru\n🔢 ስልክ: <code>0965979124</code>"

        instruction = (f"{acc_info}\n\n<b>📸 ክፍያውን ከፈጸሙ በኋላ የደረሰኙን ፎቶ (Screenshot) እዚህ ይላኩ።</b>"
                       f"\n\nለመሰረዝ /cancel ይበሉ።")
        bot.edit_message_text(instruction, uid, mid)
        bot.register_next_step_handler(call.message, get_payment_screenshot)

    elif data == "refresh_service":
        try:
            bot.edit_message_reply_markup(uid, mid, reply_markup=get_channel_status_markup(uid))
        except Exception:
            pass  # "message is not modified" when nothing changed

    # ---- Admin: list users ----
    elif data in ("adm_users", "adm_list"):
        active_users = list(users_col.find({"active": True}))
        if not active_users:
            bot.send_message(ADMIN_ID, "ምንም ገባሪ ደንበኛ የለም።")
            return

        bot.send_message(ADMIN_ID, f"<b>📋 የደንበኞች ዝርዝር ({len(active_users)}):</b>")
        for u in active_users:
            u_id = u["user_id"]
            plan = PLANS.get(u.get("plan"), {"name": "N/A"})["name"]
            exp = to_eth_date(u["expiry"])
            manage_markup = InlineKeyboardMarkup().add(
                InlineKeyboardButton("❌ አስወግድ (Remove)", callback_data=f"adm_kick_{u_id}")
            )
            detail = (
                f"👤 <b>ሊንክ፦</b> <a href='tg://user?id={u_id}'>ተጠቃሚውን እዚህ ይጫኑ</a>\n"
                f"🆔 <b>ID፦</b> <code>{u_id}</code>\n"
                f"💰 <b>ጥቅል፦</b> {plan}\n"
                f"⏳ <b>ማብቂያ፦</b> {exp}"
            )
            bot.send_message(ADMIN_ID, detail, reply_markup=manage_markup)

    elif data == "adm_bc":
        msg = bot.send_message(ADMIN_ID, "📢 ለሁሉም ደንበኞች የሚላከውን መልዕክት ይጻፉ፦\n(ለመሰረዝ /cancel)")
        bot.register_next_step_handler(msg, process_broadcast)

    # ---- Admin: remove user ----
    elif data.startswith("adm_kick_"):
        target_id = int(data.split("_")[2])
        users_col.update_one({"user_id": target_id}, {"$set": {"active": False, "expiry": 0}})
        kick_from_all_channels(target_id)
        bot.answer_callback_query(call.id, "ተጠቃሚው ተወግዷል።")
        bot.edit_message_text(f"✅ ተጠቃሚ {target_id} ከአገልግሎት ተወግዷል።", ADMIN_ID, mid)

    # ---- Admin: add channel ----
    elif data == "adm_add_ch":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
        msg = bot.send_message(
            ADMIN_ID,
            "እባክዎ መጨመር ከሚፈልጉት ቻናል አንድ መልዕክት <b>ፎርዋርድ</b> ያድርጉልኝ፦\n\nሲጨርሱ ቁልፉን ይጫኑ።",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_add_channel)

    # ---- Admin: remove channel list ----
    elif data == "adm_rem_ch":
        markup = InlineKeyboardMarkup()
        for index, ch in enumerate(list(channels_col.find()), start=1):
            markup.add(InlineKeyboardButton(f"❌ {ch['name']} {index}", callback_data=f"adm_confirm_del_{ch['id']}"))
        markup.add(InlineKeyboardButton("🔥 ሁሉንም ቻናል አስወግድ", callback_data="adm_del_all_confirm"))
        bot.edit_message_text("መሰረዝ የሚፈልጉትን ቻናል ይምረጡ፦", ADMIN_ID, mid, reply_markup=markup)

    elif data == "adm_del_all_confirm":
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ አዎ! ሁሉንም ሰርዝ", callback_data="adm_do_del_all_final"),
            InlineKeyboardButton("❌ አይ ተመለስ", callback_data="adm_rem_ch")
        )
        bot.edit_message_text("⚠️ <b>እርግጠኛ ነዎት?</b> ሁሉንም ቻናሎች ከዳታቤዝ ላይ ያጠፋቸዋል!", ADMIN_ID, mid, reply_markup=markup)

    elif data == "adm_do_del_all_final":
        channels_col.delete_many({})
        posters_col.delete_many({})
        bot.answer_callback_query(call.id, "ሁሉም ቻናሎች ተሰርዘዋል!")
        bot.edit_message_text("✅ ሁሉም የVIP ቻናሎች በስኬት ተሰርዘዋል።", ADMIN_ID, mid)

    elif data.startswith("adm_confirm_del_"):
        ch_id = data.split("_")[3]
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("አዎ ሰርዝ", callback_data=f"adm_do_del_{ch_id}"),
            InlineKeyboardButton("አይ ተመለስ", callback_data="adm_rem_ch")
        )
        bot.edit_message_text("<b>እርግጠኛ ነዎት ይህ ቻናል ይጥፋ?</b>", ADMIN_ID, mid, reply_markup=markup)

    elif data.startswith("adm_do_del_"):
        ch_id = int(data.split("_")[3])
        channels_col.delete_one({"id": ch_id})
        posters_col.delete_many({"channel_id": ch_id})
        bot.answer_callback_query(call.id, "ቻናሉ ተሰርዟል!")
        bot.edit_message_text("✅ ቻናሉ በስኬት ተሰርዟል።", ADMIN_ID, mid)

    elif data == "adm_toggle_res":
        current = is_restriction_on()
        settings_col.update_one({"type": "config"}, {"$set": {"restriction": not current}}, upsert=True)
        bot.answer_callback_query(call.id, "Restriction Status Updated!")
        bot.edit_message_reply_markup(ADMIN_ID, mid, reply_markup=admin_panel_keyboard())

    elif data == "adm_manual_remove":
        msg = bot.send_message(ADMIN_ID, "እባክዎ ማስወገድ የሚፈልጉትን ተጠቃሚ ID (User ID) ይላኩ፦\n(ለመሰረዝ /cancel ይበሉ)")
        bot.register_next_step_handler(msg, process_manual_remove)

    elif data == "adm_sync_names":
        bot.answer_callback_query(call.id, "የቻናል ስሞችን የማደስ ስራ እየተሰራ ነው...")
        updated_count = 0
        for ch in list(channels_col.find()):
            try:
                chat_info = bot.get_chat(ch["id"])
                channels_col.update_one({"id": ch["id"]}, {"$set": {"name": chat_info.title}})
                updated_count += 1
            except Exception:
                continue
        bot.send_message(ADMIN_ID, f"✅ የ {updated_count} ቻናሎች ስም በስኬት ታድሷል!\nአሁን ለሁሉም ተጠቃሚዎች አዲሱ ስም ይታያል።")

    # ---- Admin: approve payment ----
    elif data.startswith("approve_"):
        _, target_id, plan_id = data.split("_")
        target_id = int(target_id)
        if plan_id not in PLANS:
            return

        existing = users_col.find_one({"user_id": target_id}) or {}
        now_ts = time.time()
        days = PLANS[plan_id]["days"]

        # Extend instead of overwrite if still active
        if existing.get("active") and existing.get("expiry", 0) > now_ts:
            base = datetime.fromtimestamp(existing["expiry"])
            joined_at = existing.get("joined_at", now_ts)
        else:
            base = datetime.now()
            joined_at = now_ts

        expiry_ts = (base + timedelta(days=days)).timestamp()

        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"active": True, "expiry": expiry_ts, "plan": plan_id, "joined_at": joined_at}},
            upsert=True
        )

        customer_name = get_user_first_name(target_id)
        msg = (
            f"<b>✅ እንኳን ደስ አለዎት! ክፍያዎ ተረጋግጧል።</b>\n\n"
            f"👤 ስም: {customer_name}\n"
            f"📅 የገቡበት: {to_eth_date(joined_at)}\n"
            f"⏳ የሚያበቃው {to_eth_date(expiry_ts)}\n\n"
            f"☑️ - ቻናል ውስጥ አልገቡም\n"
            f"✅ - ቻናል ውስጥ ገብተዋል\n\n"
            f"የሁሉንም ቻናሎች ሊንኮች ከታች ይገናኛሉ🔻"
        )
        try:
            bot.send_message(target_id, msg, reply_markup=get_channel_status_markup(target_id))
        except Exception as e:
            bot.send_message(ADMIN_ID, f"⚠️ ለተጠቃሚ {target_id} መልዕክት መላክ አልተቻለም: {e}")
        bot.edit_message_text(f"✅ ተጠቃሚ {target_id} ጸድቋል!", ADMIN_ID, mid)

    # ---- Admin: reject payment ----
    elif data.startswith("reject_"):
        target_id = int(data.split("_")[1])
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🚫 የደረሰኝ ስህተት", callback_data=f"rj_msg_{target_id}_receipt"),
            InlineKeyboardButton("📉 ብር አነስተኛ ነው", callback_data=f"rj_msg_{target_id}_amount")
        )
        markup.add(InlineKeyboardButton("✍️ የራስህን መልዕክት ጻፍ", callback_data=f"rj_custom_{target_id}"))
        bot.edit_message_text("ውድቅ የተደረገበትን ምክንያት ይምረጡ፦", ADMIN_ID, mid, reply_markup=markup)

    elif data.startswith("rj_msg_"):
        parts = data.split("_")  # rj, msg, id, reason
        target_id, reason = int(parts[2]), parts[3]
        text = REJECT_REASONS.get(reason, "ክፍያዎ ውድቅ ተደርጓል።")
        try:
            bot.send_message(target_id, f"<b>❌ ክፍያዎ ውድቅ ተደርጓል</b>\n\n{text}", reply_markup=main_menu_keyboard())
            bot.edit_message_text(f"✅ ለተጠቃሚ {target_id} ውድቅ የተደረገበት ምክንያት ተልኳል።", ADMIN_ID, mid)
        except Exception as e:
            bot.edit_message_text(f"⚠️ መልዕክት መላክ አልተቻለም: {e}", ADMIN_ID, mid)

    elif data.startswith("rj_custom_"):
        target_id = int(data.split("_")[2])
        msg = bot.send_message(ADMIN_ID, f"✍️ ለተጠቃሚ {target_id} የሚላከውን መልዕክት ይጻፉ፦\n(ለመሰረዝ /cancel)")
        bot.register_next_step_handler(msg, lambda m: process_custom_reject(m, target_id))

    # ---- User: channel description ----
    elif data.startswith("view_ch_"):
        try:
            ch_id = int(data.split("_")[2])
            info = bot.get_chat(ch_id)
            description = info.description if info.description else "ለዚህ ቻናል ምንም መግለጫ አልተጻፈም።"
            bot.answer_callback_query(call.id, f"📝 የቻናሉ መግለጫ፦\n\n{description}"[:200], show_alert=True)
        except Exception:
            bot.answer_callback_query(call.id, "❌ መግለጫውን ማግኘት አልተቻለም።", show_alert=True)

    # ---- User: latest posters (served from stored file_ids) ----
    elif data.startswith("get_last_5_"):
        ch_id = int(data.split("_")[3])
        try:
            ch_title = (channels_col.find_one({"id": ch_id}) or {}).get("name", "ቻናል")
            posters = list(posters_col.find({"channel_id": ch_id}).sort("message_id", -1).limit(5))
            if not posters:
                bot.send_message(uid, "<b>❌ በዚህ ቻናል ላይ እስካሁን የተቀመጠ የፊልም ፖስተር የለም።</b>")
                return

            posters.reverse()  # oldest first, newest last
            bot.send_message(uid, f"<b>🎬 ከ {ch_title} የተመረጡ አዳዲስ የፊልም ፖስተሮች፦</b>")
            media = [InputMediaPhoto(p["file_id"]) for p in posters]
            if len(media) == 1:
                bot.send_photo(uid, media[0].media, protect_content=is_restriction_on())
            else:
                bot.send_media_group(uid, media, protect_content=is_restriction_on())
            bot.send_message(uid, "<b>✅ ሁሉንም ፊልሞች ለማግኘት VIP አባል ይሁኑ!</b>")
        except Exception as e:
            logger.error(f"Poster send error: {e}")
            bot.send_message(uid, "❌ ፊልሞቹን ማግኘት አልተቻለም።")


# =========================================================================
# 8. PAYMENT & ADMIN PROCESSES
# =========================================================================
def get_payment_screenshot(message):
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "ሂደቱ ተሰርዟል።", reply_markup=main_menu_keyboard())
        return

    if not message.photo:
        bot.send_message(message.chat.id, "⚠️ እባክዎ የደረሰኙን ፎቶ (Screenshot) ብቻ ይላኩ!")
        bot.register_next_step_handler(message, get_payment_screenshot)
        return

    bot.send_message(message.chat.id, "<b>✅ ደረሰኙን ተቀብያለሁ!</b>\nአሁን ደግሞ የከፈሉበትን ሙሉ ስም በ አማርኛ ወይም በእንግሊዝኛ ይላኩ፦")
    bot.register_next_step_handler(message, lambda m: collect_name_and_submit(m, message))


def collect_name_and_submit(message, photo_msg):
    uid = message.from_user.id

    if message.text == "/cancel":
        bot.send_message(uid, "ሂደቱ ተሰርዟል።", reply_markup=main_menu_keyboard())
        return

    if not message.text:
        bot.send_message(uid, "⚠️ እባክዎ ስምዎን በጽሁፍ ይላኩ።")
        bot.register_next_step_handler(message, lambda m: collect_name_and_submit(m, photo_msg))
        return

    name = message.text.strip()
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("ሁሉንም ነገር ጨርሻለሁ ላክ")
    bot.send_message(uid, f"ተቀብያለሁ <b>{telebot.util.escape(name)}</b>! ለመጨረስ ከታች ያለውን ቁልፍ ይጫኑ።", reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, name))


def finalize_submission(message, photo_msg, full_name):
    uid = message.from_user.id
    if message.text != "ሁሉንም ነገር ጨርሻለሁ ላክ":
        bot.send_message(uid, "እባክዎ 'ሁሉንም ነገር ጨርሻለሁ ላክ' የሚለውን ይጫኑ።",
                         reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("ሁሉንም ነገር ጨርሻለሁ ላክ"))
        bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, full_name))
        return

    user_data = users_col.find_one({"user_id": uid}) or {}
    plan_id = user_data.get("pending_plan", "plan1")
    if plan_id not in PLANS:
        plan_id = "plan1"
    plan_name = PLANS[plan_id]["name"]

    # keep the customer's name on file
    users_col.update_one({"user_id": uid}, {"$set": {"first_name": message.from_user.first_name}}, upsert=True)

    approve_markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}_{plan_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}")
    )

    admin_msg = (
        "<b>💰 አዲስ የክፍያ ጥያቄ!</b>\n\n"
        f"👤 <b>ስም፦</b> {telebot.util.escape(full_name)}\n"
        f"🆔 <b>ID፦</b> <a href='tg://user?id={uid}'>{uid}</a>\n"
        f"💎 <b>ጥቅል፦</b> {plan_name}"
    )

    bot.send_message(ADMIN_ID, admin_msg)
    bot.forward_message(ADMIN_ID, uid, photo_msg.message_id)
    bot.send_message(ADMIN_ID, "ያረጋግጡ፦", reply_markup=approve_markup)

    bot.send_message(uid, "<b>✅ በስኬት ተልኳል!</b>\nአድሚኑ ደረሰኙን አይቶ በቅርቡ ያረጋግጥልዎታል።", reply_markup=main_menu_keyboard())


def process_custom_reject(message, target_id):
    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return
    if not message.text:
        bot.send_message(ADMIN_ID, "⚠️ እባክዎ መልዕክቱን በጽሁፍ ይላኩ።")
        bot.register_next_step_handler(message, lambda m: process_custom_reject(m, target_id))
        return
    try:
        bot.send_message(target_id, f"<b>❌ ክፍያዎ ውድቅ ተደርጓል</b>\n\n{telebot.util.escape(message.text)}",
                         reply_markup=main_menu_keyboard())
        bot.send_message(ADMIN_ID, f"✅ መልዕክቱ ለ {target_id} ተልኳል።")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"⚠️ መላክ አልተቻለም: {e}")


def _forwarded_chat(message):
    """Works with old (forward_from_chat) and new (forward_origin) Telegram API."""
    chat = getattr(message, "forward_from_chat", None)
    if chat:
        return chat
    origin = getattr(message, "forward_origin", None)
    return getattr(origin, "chat", None) if origin else None


def process_add_channel(message):
    if message.text == "✅ ሁሉንም ጨርሻለሁ":
        bot.send_message(ADMIN_ID, "<b>ስራው ተጠናቋል!</b> ቻናሎቹ ገብተዋል።", reply_markup=main_menu_keyboard())
        bot.send_message(ADMIN_ID, "<b>🛠 Master Admin Panel:</b>", reply_markup=admin_panel_keyboard())
        return

    fchat = _forwarded_chat(message)
    if not fchat:
        bot.send_message(ADMIN_ID, "❌ ስህተት! እባክዎ መልዕክቱን ከቻናሉ ፎርዋርድ ያድርጉት።\n\nካበቁ <b>'✅ ሁሉንም ጨርሻለሁ'</b> የሚለውን ይጫኑ።")
        bot.register_next_step_handler(message, process_add_channel)
        return

    ch_id, ch_name = fchat.id, fchat.title

    try:
        bot.get_chat(ch_id)
        channels_col.update_one({"id": ch_id}, {"$set": {"name": ch_name, "id": ch_id}}, upsert=True)

        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
        bot.send_message(
            ADMIN_ID,
            f"✅ ቻናል <b>{ch_name}</b> ገብቷል!\n\nአሁንም ሌላ ቻናል <b>forward</b> ማድረግ ይችላሉ። ሲጨርሱ ቁልፉን ይጫኑ።",
            reply_markup=markup
        )
        bot.register_next_step_handler(message, process_add_channel)

    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ ስህተት፦ ቦቱ በቻናሉ ላይ አድሚን መሆኑን ያረጋግጡ።\nምክንያት፦ {e}")
        bot.register_next_step_handler(message, process_add_channel)


def process_manual_remove(message):
    uid_text = (message.text or "").strip()

    if uid_text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return

    if not uid_text.isdigit():
        bot.send_message(ADMIN_ID, "❌ ስህተት! እባክዎ ትክክለኛ የቁጥር ID ብቻ ያስገቡ።")
        bot.register_next_step_handler(message, process_manual_remove)
        return

    target_id = int(uid_text)
    users_col.update_one({"user_id": target_id}, {"$set": {"active": False, "expiry": 0}})
    success_count = kick_from_all_channels(target_id)

    bot.send_message(ADMIN_ID, f"✅ ተጠቃሚ {target_id} ከ {success_count} ቻናሎች ተወግዷል፤ በዳታቤዝም አገልግሎቱ ተዘግቷል።",
                     reply_markup=admin_panel_keyboard())


def process_broadcast(message):
    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return
    sent = failed = 0
    for u in users_col.find({"active": True}):
        try:
            bot.copy_message(u["user_id"], message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.05)  # stay under flood limits
    bot.send_message(ADMIN_ID, f"📢 ተልኳል: {sent} | አልተላከም: {failed}", reply_markup=admin_panel_keyboard())


# =========================================================================
# 9. RUN BOT
# =========================================================================
if __name__ == "__main__":
    logger.info("Starting Gett VIP Pro Bot...")
    start_keep_alive()
    threading.Thread(target=auto_kick_worker, daemon=True).start()

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling Error: {e}")
            time.sleep(15)
