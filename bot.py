import os
import telebot
import time
import threading
import logging
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from flask import Flask
from pymongo import MongoClient
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
    return "<b>ET Movie zone Pro Bot is running smoothly!</b>"

def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def start_keep_alive():
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

# =========================================================================
# 2. CONFIGURATION & DATABASE CONNECT
# =========================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")

# Initialize Bot
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Initialize MongoDB
try:
    client = MongoClient(MONGO_URI)
    db = client["gett_vip_ultimate_db"]
    users_col = db["users"]
    channels_col = db["channels"]
    settings_col = db["settings"]
    logger.info("Connected to MongoDB successfully!")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")

# VIP Subscription Plans
PLANS = {
    "plan1": {"duration": 30, "price": 200, "name": "የ 1 ወር (200 ብር)", "name_en": "1 Month (200 Birr)", "days": 30},
    "plan2": {"duration": 60, "price": 380, "name": "የ 2 ወር (380 ብር)", "name_en": "2 Months (380 Birr)", "days": 60},
    "plan3": {"duration": 90, "price": 550, "name": "የ 3 ወር (550 ብር)", "name_en": "3 Months (550 Birr)", "days": 90},
    "plan5": {"duration": 150, "price": 1050, "name": "የ 5 ወር (1050 ብር)", "name_en": "5 Months (1050 Birr)", "days": 150},
    "plan12": {"duration": 365, "price": 2000, "name": "የ 1 አመት (2000 ብር)", "name_en": "1 Year (2000 Birr)", "days": 365}
}

# =========================================================================
# ← አዲስ: LANGUAGE SYSTEM (አማርኛ / English)
# =========================================================================
BTN_REGISTER = ("💎 VIP ለመመዝገብ", "💎 Join VIP")
BTN_MY = ("👤 የእኔ አገልግሎት", "👤 My Service")
BTN_MOVIES = ("🎬 አዳዲስ ፊልሞች", "🎬 New Movies")
BTN_LIST = ("📜 VIP Channel ዝርዝር", "📜 VIP Channel List")
BTN_HELP = ("🆘 እገዛ (Help)", "🆘 Help")
BTN_LANG = ("🇬🇧English", "አማርኛ")  # አማርኛ ሲሆን "English" ያሳያል፣ English ሲሆን "አማርኛ"

TXT = {
    "am": {
        "welcome": "<b>ሰላም {name}፣ እንኳን ወደ ET Movie zone Bot በሰላም መጡ!</b>\n\nይህ ቦት የVIP ቻናሎቻችንን በክፍያ ለመቀላቀል እና አገልግሎትዎን ለመቆጣጠር ይረዳዎታል። ለመጀመር ከታች ካሉት አማራጮች አንዱን ይምረጡ።",
        "not_member": "<b>ሰላም፣ እስካሁን የET Movie zone አባል አልሆኑም ወይም ጊዜዎ አልቋል።</b>\n\nአባል ለመሆን '💎 VIP ለመመዝገብ' የሚለውን ይጫኑ።",
        "my_short": "<b>🎉 ውድ {name}፣ የET Movie zone አባል ስለሆኑ እናመሰግናለን!</b>\n\n📅 <b>የገቡበት፦</b> {joined}\n⏳ <b>የሚያበቃው፦</b> {expiry}\n\nET Movie ቻናሎችን ለማግኘት ከታች ያለውን ቁልፍ ይጫኑ 👇",
        "my_short_btn": "📺 ET Movie ቻናሎችን ለማግኘት ይጫኑ",
        "my_full": "<b>👤 ስም፦</b> {name}\n<b>💎 የአባልነት አይነት፦</b> {plan}\n<b>⏳ የሚያበቃው፦</b> {expiry}\n\n<b>ሁኔታዎች፦</b>\n✅ - ቻናሉ ውስጥ ገብተዋል\n☑️ - ቻናሉ ውስጥ አልገቡም\n\nሊንኮቹን በመጫን ይቀላቀሉ 👇",
        "expired_alert": "የአገልግሎት ጊዜዎ አልቋል ወይም አባል አይደሉም።",
        "choose_plan": "<b>ለመመዝገብ የሚፈልጉትን ጥቅል ይምረጡ፦</b>",
        "choose_bank": "<b>ለመክፈል የሚፈልጉትን የባንክ አይነት ይምረጡ፦</b>",
        "bank_cbe": "🏦 CBE (ንግድ ባንክ)",
        "bank_aby": "🏦 Abyssinia (አቢሲኒያ)",
        "bank_tele": "📱 Telebirr (ቴሌብር)",
        "acc_cbe": "<b>🏦 የኢትዮጵያ ንግድ ባንክ (CBE)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>1000355140206</code>",
        "acc_aby": "<b>🏦 አቢሲኒያ ባንክ (Abyssinia)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>167829104</code>",
        "acc_tele": "<b>📱 ቴሌብር (Telebirr)</b>\n👤 ስም: Getamesay Fikru\n🔢 ስልክ: <code>0965979124</code>",
        "pay_instruction": "<b>ውድ {name}፣ {plan} መርጠዋል።</b>\n\n{acc}\n\n<b>📸 ክፍያውን ከፈጸሙ በኋላ የደረሰኙን ፎቶ (Screenshot) እዚህ ይላኩ።</b>\n\nለመሰረዝ /cancel ይበሉ።",
        "cancelled": "ሂደቱ ተሰርዟል።",
        "photo_only": "⚠️ እባክዎ የደረሰኙን ፎቶ (Screenshot) ብቻ ይላኩ!\nለመሰረዝ /cancel ይበሉ።",
        "ask_name": "<b>✅ ደረሰኙን ተቀብያለሁ!</b>\nአሁን ደግሞ በክፍያ ደረሰኙ ላይ የሚገኘውን ሙሉ ስም በ አማርኛ ወይም በእንግሊዝኛ ይላኩ፦",
        "confirm_name": "ተቀብያለሁ <b>{name}</b>!\n\nያስገቡት ስም እርግጠኛ ከሆኑ ከታች ያለውን ቁልፍ ይጫኑ፤ ስሙ ስህተት ካለበት ደግሞ ትክክለኛውን ስም ድጋሚ ይጻፉ።",
        "finish_btn": "ሁሉንም ነገር ጨርሻለሁ ላክ",
        "press_finish": "እባክዎ 'ሁሉንም ነገር ጨርሻለሁ ላክ' የሚለውን ይጫኑ።",
        "sent_ok": "<b>✅ በስኬት ተልኳል!</b>\nአድሚኑ ደረሰኙን አይቶ በቅርቡ ያረጋግጥልዎታል።",
        "no_channel_added": "ምንም ቻናል አልተጨመረም",
        "refresh_btn": "🔄 ሁሉም ቻናል መግባቶን ያረጋግጡ (Refresh)",
        "refresh_alert": "🔄 ተሻሽሏል!\n\n✅ ማለት ቻናሉ ውስጥ ገብተዋል ማለት ነው።\n☑️ ማለት ገና አልገቡም ማለት ነው፤ ሊንኩን ተጭነው ይቀላቀሉ።",
        "no_channels": "<b>❌ ምንም ቻናል የለም።</b>",
        "channel_list_title": "<b>📜 የVIP ቻናሎች ዝርዝር፦</b>\nስለ ቻናሉ ለማወቅ ስሙን ይጫኑ 👇",
        "no_channel_found": "<b>❌ ምንም ቻናል አልተገኘም።</b>",
        "movies_title": "<b>🎬 የፊልም ፖስተሮች፦</b>\n\nየፊልም ፎቶዎችን ለማየት የቻናሉን ስም ይጫኑ 👇",
        "no_desc": "ለዚህ ቻናል ምንም መግለጫ አልተጻፈም።",
        "desc_alert": "📝 የቻናሉ መግለጫ፦\n\n{desc}",
        "desc_err": "❌ መግለጫውን ማግኘት አልተቻለም።\nምክንያት፦ {err}",
        "progress_wait": "<b>🎬 ET Movie zone — የፊልም ፖስተሮች</b>\n\n⏳ እባክዎ ይጠብቁ...\n\n▱▱▱▱▱▱▱▱▱▱\n<b>0%</b>",
        "progress": "<b>🎬 {title}</b>\n\n⏳ ፖስተሮችን እያዘጋጀሁ ነው...\n\n{bar}\n<b>{percent}%</b>",
        "posters_header": "<b>🎬 ከ {title} የተመረጡ አዳዲስ የፊልም ፖስተሮች፦</b>",
        "no_posters": "<b>❌ በዚህ ቻናል ላይ ምንም የፊልም ፖስተር (ፎቶ) አልተገኘም።</b>",
        "get_vip": "<b>✅ ሁሉንም ፊልሞች ለማግኘት VIP አባል ይሁኑ!</b>",
        "posters_fail": "❌ ፊልሞቹን ማግኘት አልተቻለም።",
        "approved_head": "<b>✅ እንኳን ደስ አለዎት! ክፍያዎ ተረጋግጧል።</b>\n\n",
        "rejected_head": "<b>❌ ክፍያዎ ውድቅ ተደርጓል።</b>",
        "rej_receipt": "🚫 የላኩት ደረሰኝ ትክክል አይደለም። እባክዎ ትክክለኛውን የክፍያ ደረሰኝ (Screenshot) ደግመው ይላኩ።",
        "rej_amount": "📉 የከፈሉት ብር ከጥቅሉ ዋጋ ያነሰ ነው። እባክዎ ትክክለኛውን መጠን ከፍለው ደረሰኙን ደግመው ይላኩ።",
        "rej_again": "ደግመው ለመመዝገብ '💎 VIP ለመመዝገብ' የሚለውን ይጫኑ።",
        "expired": "<b>⚠️ የአገልግሎት ጊዜዎ አብቅቷል!</b>\n\nከVIP ቻናሎች በራስ-ሰር ተወግደዋል። አገልግሎቱን ለመቀጠል እባክዎ ደግመው ይክፈሉ እና ደረሰኝ ይላኩ።",
        "help_fail": "❌ እገዛውን ማምጣት አልተቻለም። እባክዎ ቆይተው ደግመው ይሞክሩ።",
        "lang_changed": "✅ ቋንቋ ወደ አማርኛ ተቀይሯል",
    },
    "en": {
        "welcome": "<b>Hello {name}, welcome to the ET Movie zone Bot!</b>\n\nThis bot helps you join our VIP channels with a paid subscription and manage your service. To begin, choose one of the options below.",
        "not_member": "<b>Hello, you are not an ET Movie zone member yet, or your subscription has expired.</b>\n\nTo become a member, tap '💎 Join VIP'.",
        "my_short": "<b>🎉 Dear {name}, thank you for joining ET Movie zone!</b>\n\n📅 <b>Joined:</b> {joined}\n⏳ <b>Expires:</b> {expiry}\n\nTap the button below to get the ET Movie channels 👇",
        "my_short_btn": "📺 Get ET Movie channels",
        "my_full": "<b>👤 Name:</b> {name}\n<b>💎 Plan:</b> {plan}\n<b>⏳ Expires:</b> {expiry}\n\n<b>Status:</b>\n✅ - You have joined the channel\n☑️ - You have not joined the channel yet\n\nTap the links to join 👇",
        "expired_alert": "Your subscription has expired or you are not a member.",
        "choose_plan": "<b>Choose the plan you want to subscribe to:</b>",
        "choose_bank": "<b>Choose the payment method:</b>",
        "bank_cbe": "🏦 CBE (Commercial Bank)",
        "bank_aby": "🏦 Abyssinia Bank",
        "bank_tele": "📱 Telebirr",
        "acc_cbe": "<b>🏦 Commercial Bank of Ethiopia (CBE)</b>\n👤 Name: Getamesay Fikru\n🔢 Acc: <code>1000355140206</code>",
        "acc_aby": "<b>🏦 Abyssinia Bank</b>\n👤 Name: Getamesay Fikru\n🔢 Acc: <code>167829104</code>",
        "acc_tele": "<b>📱 Telebirr</b>\n👤 Name: Getamesay Fikru\n🔢 Phone: <code>0965979124</code>",
        "pay_instruction": "<b>Dear {name}, you have chosen {plan}.</b>\n\n{acc}\n\n<b>📸 After paying, send a photo (screenshot) of the receipt here.</b>\n\nTo cancel, type /cancel.",
        "cancelled": "The process has been cancelled.",
        "photo_only": "⚠️ Please send only a photo (screenshot) of the receipt!\nTo cancel, type /cancel.",
        "ask_name": "<b>✅ Receipt received!</b>\nNow please send the full name shown on the payment receipt (in Amharic or English):",
        "confirm_name": "Received <b>{name}</b>!\n\nIf you are sure the name is correct, tap the button below; if it has a mistake, type the correct name again.",
        "finish_btn": "✅ Done, Submit",
        "press_finish": "Please tap '✅ Done, Submit'.",
        "sent_ok": "<b>✅ Sent successfully!</b>\nThe admin will review your receipt and confirm shortly.",
        "no_channel_added": "No channel has been added",
        "refresh_btn": "🔄 Check all channel memberships (Refresh)",
        "refresh_alert": "🔄 Refreshed!\n\n✅ means you have joined the channel.\n☑️ means you have not joined yet; tap the link to join.",
        "no_channels": "<b>❌ There are no channels.</b>",
        "channel_list_title": "<b>📜 VIP channel list:</b>\nTap a name to learn about the channel 👇",
        "no_channel_found": "<b>❌ No channel found.</b>",
        "movies_title": "<b>🎬 Movie posters:</b>\n\nTap a channel name to see its movie photos 👇",
        "no_desc": "No description has been written for this channel.",
        "desc_alert": "📝 Channel description:\n\n{desc}",
        "desc_err": "❌ Could not get the description.\nReason: {err}",
        "progress_wait": "<b>🎬 ET Movie zone — Movie posters</b>\n\n⏳ Please wait...\n\n▱▱▱▱▱▱▱▱▱▱\n<b>0%</b>",
        "progress": "<b>🎬 {title}</b>\n\n⏳ Preparing the posters...\n\n{bar}\n<b>{percent}%</b>",
        "posters_header": "<b>🎬 Latest movie posters selected from {title}:</b>",
        "no_posters": "<b>❌ No movie poster (photo) was found in this channel.</b>",
        "get_vip": "<b>✅ Become a VIP member to get all the movies!</b>",
        "posters_fail": "❌ Could not get the movies.",
        "approved_head": "<b>✅ Congratulations! Your payment has been confirmed.</b>\n\n",
        "rejected_head": "<b>❌ Your payment was rejected.</b>",
        "rej_receipt": "🚫 The receipt you sent is not valid. Please send the correct payment receipt (screenshot) again.",
        "rej_amount": "📉 The amount you paid is less than the plan price. Please pay the correct amount and send the receipt again.",
        "rej_again": "To register again, tap '💎 Join VIP'.",
        "expired": "<b>⚠️ Your subscription has expired!</b>\n\nYou have been automatically removed from the VIP channels. To continue, please pay again and send the receipt.",
        "help_fail": "❌ Could not load the help content. Please try again later.",
        "lang_changed": "✅ Language changed to English",
    },
}


def lang_of(uid):
    """Returns the saved language of a user ('am' is the default)"""
    try:
        u = users_col.find_one({"user_id": uid}, {"lang": 1})
        return "en" if u and u.get("lang") == "en" else "am"
    except Exception:
        return "am"


def t(lang, key, **kw):
    """Returns a translated text"""
    table = TXT["en"] if lang == "en" else TXT["am"]
    return table[key].format(**kw)


def esc(text):
    return html.escape(str(text)) if text else ""


def plan_name(plan_id, lang="am"):
    plan = PLANS.get(plan_id)
    if not plan:
        return "Unknown" if lang == "en" else "ያልታወቀ"
    return plan["name_en"] if lang == "en" else plan["name"]


def plan_label(user, lang="am"):
    """Plan name of a user (also supports manual 'other time' plans)"""
    plan = PLANS.get((user or {}).get("plan"))
    if plan:
        return plan["name_en"] if lang == "en" else plan["name"]
    if lang == "en":
        return user.get("custom_label_en") or user.get("custom_label") or "Unknown"
    return user.get("custom_label") or "ያልታወቀ"


def arrange_buttons(markup, buttons, short_len=16):
    """አጭር ከሆነ 3፣ ረጅም ከሆነ 2 በአንድ ረድፍ"""
    current = []
    for btn in buttons:
        if not btn:
            continue
        limit = 3 if all(len(b.text) <= short_len for b in current + [btn]) else 2
        if len(current) >= limit:
            markup.row(*current)
            current = []
        current.append(btn)
    if current:
        markup.row(*current)


# =========================================================================
# 3. UTILITY FUNCTIONS
# =========================================================================
def to_eth_date(timestamp, lang="am"):
    """Converts Unix timestamp to Ethiopian Date String (English → international calendar)"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        if lang == "en":
            return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
        conv = EthiopianDateConverter.to_ethiopian(dt.year, dt.month, dt.day)
        months = ["", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"]
        return f"{months[conv.month]} {conv.day}፣ {conv.year}"
    except Exception as e:
        logger.error(f"Date conversion error: {e}")
        return "Unknown date" if lang == "en" else "ያልታወቀ ቀን"

def is_restriction_on():
    """Checks if content protection is enabled"""
    data = settings_col.find_one({"type": "config"})
    return data.get("restriction", True) if data else True

def get_channel_status_markup(user_id):
    """Generates a list of channels with join status icons and numbers"""
    markup = InlineKeyboardMarkup()
    channels = list(channels_col.find())

    # ← አዲስ: ቀደም ብለው የተፈጠሩ ሊንኮችን ከዳታቤዝ ማምጣት
    user_data = users_col.find_one({"user_id": user_id}) or {}
    lang = "en" if user_data.get("lang") == "en" else "am"
    
    if not channels:
        markup.add(InlineKeyboardButton(t(lang, "no_channel_added"), callback_data="none"))
        return markup

    current_exp = user_data.get("expiry", 0)
    saved = user_data.get("invite_links", {})
    saved_links = saved.get("links", {}) if saved.get("exp") == current_exp else {}
    new_links = {}

    # enumerate በመጠቀም 1, 2, 3 እያለ ቁጥር ይሰጣል
    def build_button(index, ch):
        try:
            member = bot.get_chat_member(ch["id"], user_id)
            status_icon = "✅" if member.status in ['member', 'administrator', 'creator'] else "☑️"
            
            # ← አዲስ: የተቀመጠ ሊንክ ካለ እሱን መጠቀም፣ ከሌለ ብቻ አዲስ መፍጠር
            key = str(ch["id"])
            invite = saved_links.get(key)
            if not invite:
                invite = bot.create_chat_invite_link(ch["id"], member_limit=1).invite_link
                new_links[key] = invite
            
            # ስሙን በቁጥር (ምሳሌ፦ ✅ Channel Name 1) እንዲያሳይ
            return InlineKeyboardButton(f"{status_icon} {ch['name']} {index}", url=invite)
        except Exception:
            return None

    # ← አዲስ: ሁሉንም ቻናሎች በአንድ ጊዜ መፈተሽ (ፈጣን)
    with ThreadPoolExecutor(max_workers=8) as pool:
        buttons = list(pool.map(lambda x: build_button(*x), enumerate(channels, start=1)))

    # ← አዲስ: አጭር ከሆነ 3፣ ረጅም ከሆነ 2 በአንድ ረድፍ
    arrange_buttons(markup, buttons)

    # ← አዲስ: አዲስ የተፈጠሩ ሊንኮችን ዳታቤዝ ላይ ማስቀመጥ
    if new_links:
        merged = {**saved_links, **new_links}
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"invite_links": {"exp": current_exp, "links": merged}}},
            upsert=True
        )
            
    # የፈለግከው "Refresh" በተን እዚህ ጋር አለ
    markup.add(InlineKeyboardButton(t(lang, "refresh_btn"), callback_data="refresh_service"))
    return markup

# =========================================================================
# 4. BACKGROUND WORKER (AUTO-KICK)
# =========================================================================
def auto_kick_worker():
    """Continuously checks for expired subscriptions and removes users"""
    while True:
        try:
            current_time = datetime.now().timestamp()
            expired_users = users_col.find({"active": True, "expiry": {"$lt": current_time}})
            
            for user in expired_users:
                uid = user["user_id"]
                logger.info(f"Expiring user: {uid}")
                
                # Kick from all registered channels
                for ch in list(channels_col.find()):
                    try:
                        bot.ban_chat_member(ch["id"], uid)
                        bot.unban_chat_member(ch["id"], uid) # Unban so they can rejoin later
                    except Exception as e:
                        logger.error(f"Error kicking {uid} from {ch['id']}: {e}")
                
                # Update database
                users_col.update_one({"user_id": uid}, {"$set": {"active": False}})
                
                # Notify user
                try:
                    msg = t(user.get("lang", "am"), "expired")
                    bot.send_message(uid, msg)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Auto-kick worker error: {e}")
            
        time.sleep(60) # Check every 60 seconds

# =========================================================================
# 5. KEYBOARDS
# =========================================================================
def main_menu_keyboard(lang="am"):
    i = 1 if lang == "en" else 0
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(BTN_REGISTER[i]), KeyboardButton(BTN_MY[i]))
    markup.add(KeyboardButton(BTN_MOVIES[i]), KeyboardButton(BTN_LIST[i]))
    markup.add(KeyboardButton(BTN_HELP[i]), KeyboardButton(BTN_LANG[i]))
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
    # የቻናል ስሞችን ማደሻ አዲሱ በተን
    markup.add(InlineKeyboardButton("🔄 የቻናል ስሞችን አድስ (Sync)", callback_data="adm_sync_names"))
    
    res_text = "🚫 Restriction: ON" if is_restriction_on() else "🔓 Restriction: OFF"
    markup.add(InlineKeyboardButton(res_text, callback_data="adm_toggle_res"))
    markup.add(InlineKeyboardButton("👤 ተጠቃሚ ማባረር (Manual)", callback_data="adm_manual_remove"))
    markup.add(InlineKeyboardButton("➕ VIP አባል ጨምር (Manual)", callback_data="adm_add_vip"))

    return markup


# =========================================================================
# 6. MESSAGE HANDLERS
# =========================================================================
@bot.message_handler(commands=['start'])
def handle_start(message):
    uid = message.chat.id
    first_name = message.from_user.first_name

    # ← አዲስ: @username ን ማስቀመጥ (አድሚኑ በ @username VIP ለመጨመር)
    if message.from_user.username:
        users_col.update_one({"user_id": uid}, {"$set": {"username": message.from_user.username.lower()}}, upsert=True)

    lang = lang_of(uid)
    welcome_text = t(lang, "welcome", name=first_name)
    bot.send_message(uid, welcome_text, reply_markup=main_menu_keyboard(lang))
    
    if uid == ADMIN_ID:
        bot.send_message(ADMIN_ID, "<b>🛠 Master Admin Panel:</b>", reply_markup=admin_panel_keyboard())

# ← አዲስ: ቋንቋ መቀየሪያ (አማርኛ ⇄ English)
@bot.message_handler(func=lambda m: m.text in BTN_LANG)
def handle_language_toggle(message):
    uid = message.from_user.id
    new_lang = "en" if message.text == BTN_LANG[0] else "am"
    users_col.update_one({"user_id": uid}, {"$set": {"lang": new_lang}}, upsert=True)
    bot.send_message(message.chat.id, t(new_lang, "lang_changed"), reply_markup=main_menu_keyboard(new_lang))

@bot.message_handler(func=lambda m: m.text in BTN_MY)
def handle_my_service(message):
    uid = message.from_user.id
    user_data = users_col.find_one({"user_id": uid})
    lang = "en" if (user_data or {}).get("lang") == "en" else "am"
    
    if not user_data or not user_data.get("active"):
        bot.send_message(uid, t(lang, "not_member"))
        return
    
    # ← አዲስ: አጭር መልዕክት + ቁልፍ (ሙሉው መልዕክት ቁልፉ ሲነካ ይመጣል)
    short_text = t(
        lang, "my_short",
        name=esc(message.from_user.first_name),
        joined=to_eth_date(user_data.get("joined_at"), lang),
        expiry=to_eth_date(user_data["expiry"], lang),
    )
    short_markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, "my_short_btn"), callback_data="my_service_full")
    )
    bot.send_message(uid, short_text, reply_markup=short_markup, protect_content=is_restriction_on())

@bot.message_handler(func=lambda m: m.text in BTN_REGISTER)
def handle_registration(message):
    lang = lang_of(message.from_user.id)
    markup = InlineKeyboardMarkup()
    for key, val in PLANS.items():
        markup.add(InlineKeyboardButton(f"💳 {plan_name(key, lang)}", callback_data=f"buy_{key}"))
    
    bot.send_message(message.chat.id, t(lang, "choose_plan"), reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in BTN_LIST)
def handle_channel_list(message):
    lang = lang_of(message.from_user.id)
    channels = list(channels_col.find())
    if not channels:
        bot.send_message(message.chat.id, t(lang, "no_channels"))
        return
        
    markup = InlineKeyboardMarkup()
    # ቻናሎቹን በተን ላይ ብቻ እንጨምራለን
    buttons = []
    for index, ch in enumerate(channels, start=1):
        buttons.append(InlineKeyboardButton(f"🔹 {ch['name']} {index}", callback_data=f"view_ch_{ch['id']}"))

    # ← አዲስ: አጭር ከሆነ 3፣ ረጅም ከሆነ 2 በአንድ ረድፍ
    arrange_buttons(markup, buttons)
        
    # ጽሁፉን አጥፍተን ርዕሱን እና በተኖቹን ብቻ እንልካለን
    bot.send_message(message.chat.id, t(lang, "channel_list_title"), reply_markup=markup)
    
import random # ይህን ከላይ ከኢምፖርቶች ጋር ጨምረው

@bot.message_handler(func=lambda m: m.text in BTN_MOVIES)
def handle_new_movies(message):
    lang = lang_of(message.from_user.id)
    all_channels = list(channels_col.find())
    if not all_channels:
        bot.send_message(message.chat.id, t(lang, "no_channel_found"))
        return

    # የመጀመሪያዎቹን 20 ቻናሎች መምረጥ እና ቦታቸውን መቀያየር
    selected_channels = random.sample(all_channels[:20], len(all_channels[:20]))  # ← አዲስ
    
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = []
    
    for ch in selected_channels:
        # ስሙን ማጽዳት (ከ '-' በፊት ያለውን ብቻ መውሰድ)
        clean_name = ch['name'].split('-')[0].strip()
        clean_name = ''.join([i for i in clean_name if not i.isdigit()]).strip()
        
        buttons.append(InlineKeyboardButton(f"🎬 {clean_name}", callback_data=f"get_last_5_{ch['id']}"))
    
    markup.add(*buttons)
    bot.send_message(message.chat.id, t(lang, "movies_title"), reply_markup=markup)

# ← አዲስ: እገዛ (Help) — ከቻናሉ ፖስት ኮፒ አድርጎ ይልካል ("Forwarded from" ሳይታይ)
HELP_CHANNEL = "@info_Etmoviezone"
HELP_MESSAGE_IDS = [2]  # ተጨማሪ ፖስት ከፈለግህ ቁጥሩን እዚህ ጨምር፣ ለምሳሌ [2, 3]

@bot.message_handler(func=lambda m: m.text in BTN_HELP)
def handle_help(message):
    uid = message.chat.id
    lang = lang_of(message.from_user.id)
    for msg_id in HELP_MESSAGE_IDS:
        try:
            bot.copy_message(uid, HELP_CHANNEL, msg_id)
        except Exception as e:
            logger.error(f"Help copy error: {e}")
            bot.send_message(uid, t(lang, "help_fail"))
            break


# =========================================================================
# 7. CALLBACK QUERY HANDLER
# =========================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    uid, mid = call.from_user.id, call.message.message_id
    
    # User: Plan Selection
    if call.data.startswith("buy_"):
        lang = lang_of(uid)
        plan_id = call.data.split("_")[1]
        users_col.update_one({"user_id": uid}, {"$set": {"pending_plan": plan_id}}, upsert=True)
        
        bank_markup = InlineKeyboardMarkup(row_width=2)
        bank_markup.add(
            InlineKeyboardButton(t(lang, "bank_cbe"), callback_data="pay_cbe"),
            InlineKeyboardButton(t(lang, "bank_aby"), callback_data="pay_aby")
        )
        bank_markup.add(InlineKeyboardButton(t(lang, "bank_tele"), callback_data="pay_tele"))
        
        bot.edit_message_text(t(lang, "choose_bank"), uid, mid, reply_markup=bank_markup)

    # User: Payment Method
    elif call.data.startswith("pay_"):
        lang = lang_of(uid)
        method = call.data.split("_")[1]
        if method == "cbe":
            acc_info = t(lang, "acc_cbe")
        elif method == "aby":
            acc_info = t(lang, "acc_aby")
        else:
            acc_info = t(lang, "acc_tele")

        # ← አዲስ: የመረጠውን ጥቅል ከዳታቤዝ ማምጣት
        user_data = users_col.find_one({"user_id": uid}) or {}
        plan_id = user_data.get("pending_plan")
        plan_id = plan_id if plan_id in PLANS else "plan1"

        instruction = t(lang, "pay_instruction", name=esc(call.from_user.first_name), plan=plan_name(plan_id, lang), acc=acc_info)
        bot.edit_message_text(instruction, uid, mid)
        bot.register_next_step_handler(call.message, get_payment_screenshot)

    # ← አዲስ: ሙሉ "የእኔ አገልግሎት" መልዕክት (ቁልፉ ሲነካ)
    elif call.data == "my_service_full":
        user_data = users_col.find_one({"user_id": uid})
        lang = "en" if (user_data or {}).get("lang") == "en" else "am"
        if not user_data or not user_data.get("active"):
            bot.answer_callback_query(call.id, t(lang, "expired_alert"), show_alert=True)
            return
        bot.answer_callback_query(call.id)

        status_text = t(
            lang, "my_full",
            name=esc(call.from_user.first_name),
            plan=plan_label(user_data, lang),
            expiry=to_eth_date(user_data["expiry"], lang),
        )
        bot.send_message(uid, status_text, reply_markup=get_channel_status_markup(uid), protect_content=is_restriction_on())

    # ← አዲስ: Refresh — የቻናል መግባት ሁኔታን ማደስ
    elif call.data == "refresh_service":
        lang = lang_of(uid)
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, mid,
                reply_markup=get_channel_status_markup(uid)
            )
        except Exception:
            pass  # ምንም ለውጥ ከሌለ ቴሌግራም ስህተት ይመልሳል፤ ችግር የለውም

        bot.answer_callback_query(call.id, t(lang, "refresh_alert"), show_alert=True)

    # ← አዲስ: ውድቅ የተደረገበት ምክንያት (ዝግጁ መልዕክቶች)
    elif call.data.startswith("rj_msg_"):
        _, _, target_id, reason = call.data.split("_")
        target_id = int(target_id)
        tl = lang_of(target_id)
        if reason == "receipt":
            reason_text = t(tl, "rej_receipt")
            admin_reason = "የደረሰኝ ስህተት"
        else:
            reason_text = t(tl, "rej_amount")
            admin_reason = "ብር አነስተኛ ነው"
        try:
            bot.send_message(target_id, f"{t(tl, 'rejected_head')}\n\n{reason_text}\n\n{t(tl, 'rej_again')}")
        except Exception:
            pass
        bot.answer_callback_query(call.id, "ውድቅ ተደርጓል")
        bot.edit_message_text(f"❌ ተጠቃሚ {target_id} ውድቅ ተደርጓል።\nምክንያት፦ {admin_reason}", ADMIN_ID, mid)

    # ← አዲስ: ውድቅ የተደረገበት ምክንያት (የራስህን መልዕክት ጻፍ)
    elif call.data.startswith("rj_custom_"):
        target_id = int(call.data.split("_")[2])
        bot.answer_callback_query(call.id)
        msg = bot.send_message(ADMIN_ID, f"✍️ ለተጠቃሚ {target_id} የሚላከውን መልዕክት ይጻፉ፦\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(msg, lambda m: process_reject_custom(m, target_id))

    # ← አዲስ: አድሚን በእጅ VIP አባል ሲጨምር
    elif call.data == "adm_add_vip":
        if uid != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(ADMIN_ID, "➕ <b>VIP አባል መጨመር</b>\n\nተጠቃሚውን በ <b>User ID</b>፣ በ <b>@username</b> ወይም ከተጠቃሚው የተላከ መልዕክት <b>ፎርዋርድ</b> በማድረግ ይላኩ።\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(msg, process_add_vip_user)

    elif call.data.startswith("admvip_plan_"):
        if uid != ADMIN_ID:
            return
        _, _, target_id, plan_id = call.data.split("_")
        target_id = int(target_id)
        bot.answer_callback_query(call.id)
        if plan_id == "custom":
            msg = bot.send_message(ADMIN_ID, "⏱ <b>የአባልነቱን ቆይታ ይጻፉ</b> (ዝቅተኛው 3 ደቂቃ)\n\nምሳሌ፦ <code>3 ደቂቃ</code>፣ <code>1 ሰዓት</code>፣ <code>3 ቀን</code>\n(ወይም <code>3m</code>፣ <code>1h</code>፣ <code>3d</code>)\n\nለመሰረዝ /cancel ይበሉ።")
            bot.register_next_step_handler(msg, lambda m: process_add_vip_duration(m, target_id))
        else:
            ask_vip_start(target_id, plan_id, PLANS[plan_id]["days"] * 86400, PLANS[plan_id]["name"], PLANS[plan_id]["name_en"])

    # Admin: List Users
    elif call.data == "adm_users" or call.data == "adm_list":
        active_users = list(users_col.find({"active": True}))
        if not active_users:
            bot.send_message(ADMIN_ID, "ምንም ገባሪ ደንበኛ የለም።")
            return
            
        bot.send_message(ADMIN_ID, f"<b>📋 የደንበኞች ዝርዝር ({len(active_users)}):</b>")
        for u in active_users:
            u_id = u["user_id"]
            plan = plan_label(u) if (u.get("plan") in PLANS or u.get("custom_label")) else "N/A"
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

    # Admin: Remove User
    elif call.data.startswith("adm_kick_"):
        target_id = int(call.data.split("_")[2])
        users_col.update_one({"user_id": target_id}, {"$set": {"active": False, "expiry": 0}})
        
        # Kick from channels
        for ch in list(channels_col.find()):
            try:
                bot.ban_chat_member(ch["id"], target_id)
                bot.unban_chat_member(ch["id"], target_id)
            except: pass
            
        bot.answer_callback_query(call.id, "ተጠቃሚው ተወግዷል።")
        bot.edit_message_text(f"✅ ተጠቃሚ {target_id} ከአገልግሎት ተወግዷል።", ADMIN_ID, mid)

        # Admin: Add Channel
    elif call.data == "adm_add_ch":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
        msg = bot.send_message(ADMIN_ID, "እባክዎ መጨመር ከሚፈልጉት ቻናል አንድ መልዕክት <b>ፎርዋርድ</b> ያድርጉልኝ፦\n\nሲጨርሱ ቁልፉን ይጫኑ።", reply_markup=markup)
        bot.register_next_step_handler(msg, process_add_channel)

    # Admin: Remove Channel List
    elif call.data == "adm_rem_ch":
        markup = InlineKeyboardMarkup()
        channels = list(channels_col.find())
        for index, ch in enumerate(channels, start=1):
            markup.add(InlineKeyboardButton(f"❌ {ch['name']} {index}", callback_data=f"adm_confirm_del_{ch['id']}"))
        
        # አዲሱ "ሁሉንም አስወግድ" በተን እዚህ ጋር ነው
        markup.add(InlineKeyboardButton("🔥 ሁሉንም ቻናል አስወግድ", callback_data="adm_del_all_confirm"))
        bot.edit_message_text("መሰረዝ የሚፈልጉትን ቻናል ይምረጡ፦", ADMIN_ID, mid, reply_markup=markup)

    # ሁሉንም ለማጥፋት ማረጋገጫ መጠየቂያ
    elif call.data == "adm_del_all_confirm":
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ አዎ! ሁሉንም ሰርዝ", callback_data="adm_do_del_all_final"),
            InlineKeyboardButton("❌ አይ ተመለስ", callback_data="adm_rem_ch")
        )
        bot.edit_message_text("⚠️ <b>እርግጠኛ ነዎት?</b> ሁሉንም ቻናሎች ከዳታቤዝ ላይ ያጠፋቸዋል!", ADMIN_ID, mid, reply_markup=markup)

    # ሁሉንም የማጥፊያ እርምጃ (Logic)
    elif call.data == "adm_do_del_all_final":
        channels_col.delete_many({}) # ዳታቤዙን ባዶ ያደርገዋል
        bot.answer_callback_query(call.id, "ሁሉም ቻናሎች ተሰርዘዋል!")
        bot.edit_message_text("✅ ሁሉም የVIP ቻናሎች በስኬት ተሰርዘዋል።", ADMIN_ID, mid)

    # Admin: Confirm Channel Delete
    elif call.data.startswith("adm_confirm_del_"):
        ch_id = call.data.split("_")[3]
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("አዎ ሰርዝ", callback_data=f"adm_do_del_{ch_id}"),
            InlineKeyboardButton("አይ ተመለስ", callback_data="adm_rem_ch")
        )
        bot.edit_message_text("<b>እርግጠኛ ነዎት ይህ ቻናል ይጥፋ?</b>", ADMIN_ID, mid, reply_markup=markup)

    # Admin: Execute Delete
    elif call.data.startswith("adm_do_del_"):
        ch_id = int(call.data.split("_")[3])
        channels_col.delete_one({"id": ch_id})
        bot.answer_callback_query(call.id, "ቻናሉ ተሰርዟል!")
        bot.edit_message_text("✅ ቻናሉ በስኬት ተሰርዟል።", ADMIN_ID, mid)

    # Admin: Toggle Restriction
    elif call.data == "adm_toggle_res":
        current = is_restriction_on()
        settings_col.update_one({"type": "config"}, {"$set": {"restriction": not current}}, upsert=True)
        bot.answer_callback_query(call.id, "Restriction Status Updated!")
        bot.edit_message_reply_markup(ADMIN_ID, mid, reply_markup=admin_panel_keyboard())

        # Admin: Manual Remove User
    elif call.data == "adm_manual_remove":
        msg = bot.send_message(ADMIN_ID, "እባክዎ ማስወገድ የሚፈልጉትን ተጠቃሚ ID (User ID) ይላኩ፦\n(ለመለሰረዝ /cancel ይበሉ)")
        bot.register_next_step_handler(msg, process_manual_remove)

    elif call.data == "adm_sync_names":
        bot.answer_callback_query(call.id, "የቻናል ስሞችን የማደስ ስራ እየተሰራ ነው...")
        channels = list(channels_col.find())
        updated_count = 0
        
        for ch in channels:
            try:
                # ከቴሌግራም ወቅታዊውን ስም መውሰድ
                chat_info = bot.get_chat(ch["id"])
                # ዳታቤዝ ላይ ስሙን ማዘመን
                channels_col.update_one({"id": ch["id"]}, {"$set": {"name": chat_info.title}})
                updated_count += 1
            except Exception:
                continue
                
        bot.send_message(ADMIN_ID, f"✅ የ {updated_count} ቻናሎች ስም በስኬት ታድሷል!\nአሁን ለሁሉም ተጠቃሚዎች አዲሱ ስም ይታያል።")

  # User: Approve Payment (By Admin)
    elif call.data.startswith("approve_"):
        _, target_id, plan_id = call.data.split("_")
        target_id = int(target_id)
        
        days = PLANS[plan_id]["days"]
        expiry_ts = (datetime.now() + timedelta(days=days)).timestamp()
        
        # የዳታቤዝ ማሻሻያ
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"active": True, "expiry": expiry_ts, "plan": plan_id, "joined_at": time.time()}},
            upsert=True
        )
        
        # መረጃውን ከዳታቤዝ እናምጣ
        u = users_col.find_one({"user_id": target_id})
        tl = "en" if u.get("lang") == "en" else "am"

        # የተጠቃሚውን ስም ከቴሌግራም ማምጣት
        try:
            target_name = bot.get_chat(target_id).first_name
        except Exception:
            target_name = ""

        # "የእኔ አገልግሎት" ሲጫን የሚመጣው ዓይነት መልዕክት
        status_text = t(tl, "approved_head") + t(
            tl, "my_full",
            name=esc(target_name),
            plan=plan_name(plan_id, tl),
            expiry=to_eth_date(u['expiry'], tl),
        )
        
        bot.send_message(target_id, status_text, reply_markup=get_channel_status_markup(target_id), protect_content=is_restriction_on())
        bot.edit_message_text(f"✅ ተጠቃሚ {target_id} ጸድቋል!", ADMIN_ID, mid)

    # User: Reject Payment (By Admin)
    elif call.data.startswith("reject_"):
        target_id = int(call.data.split("_")[1])
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🚫 የደረሰኝ ስህተት", callback_data=f"rj_msg_{target_id}_receipt"),
            InlineKeyboardButton("📉 ብር አነስተኛ ነው", callback_data=f"rj_msg_{target_id}_amount")
        )
        markup.add(InlineKeyboardButton("✍️ የራስህን መልዕክት ጻፍ", callback_data=f"rj_custom_{target_id}"))
        bot.edit_message_text("ውድቅ የተደረገበትን ምክንያት ይምረጡ፦", ADMIN_ID, mid, reply_markup=markup)

    # User: View Description with Real-time Update
    # User: View Description
    elif call.data.startswith("view_ch_"):
        lang = lang_of(uid)
        try:
            ch_id = int(call.data.split("_")[2])
            info = bot.get_chat(ch_id)
            description = info.description if info.description else t(lang, "no_desc")
            bot.answer_callback_query(call.id, t(lang, "desc_alert", desc=description), show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, t(lang, "desc_err", err=e), show_alert=True)

            # የፊልም ፖስተር ማምጫ (ቅደም ተከተል የተስተካከለ)
    elif call.data.startswith("get_last_5_"):
        ch_id = int(call.data.split("_")[3])
        uid = call.from_user.id
        lang = lang_of(uid)
        bot.answer_callback_query(call.id)  # ← አዲስ

        # ← አዲስ: የሂደት መስመር ማሳያ
        def show_progress(title, percent):
            filled = percent // 10
            bar = "▰" * filled + "▱" * (10 - filled)
            try:
                bot.edit_message_text(
                    t(lang, "progress", title=title, bar=bar, percent=percent),
                    uid,
                    wait_msg.message_id
                )
            except Exception:
                pass

        wait_msg = bot.send_message(uid, t(lang, "progress_wait"))  # ← አዲስ (የነበረውን መልዕክት ተክቷል)
        try:
            ch_info = bot.get_chat(ch_id)
            bot.send_message(uid, t(lang, "posters_header", title=ch_info.title))
            
            temp_msg = bot.send_message(ch_id, ".")
            last_id = temp_msg.message_id
            bot.delete_message(ch_id, last_id)
            
            photo_ids = []
            posts = []  # ← አዲስ: እያንዳንዱ የቴሌግራም ፖስት (አልበም ሁሉም ፎቶ በአንድ) እንደ 1 ፖስት
            last_percent = 0
            # ወደ ኋላ በመሄድ አዳዲሶቹን 5 ፖስቶች መፈለግ (አልበሞች ብዙ መልዕክት ስለሚይዙ እስከ 100)
            for msg_id in range(last_id - 1, last_id - 101, -1):  # ← አዲስ

                # ፐርሰንቱ በእውነተኛ ፍለጋ ሂደት ይሰላል
                scanned = (last_id - 1) - msg_id
                percent = min(100, max(len(posts) * 20, scanned)) // 10 * 10
                if percent > last_percent:
                    last_percent = percent
                    show_progress(ch_info.title, percent)

                try:
                    test_msg = bot.forward_message(ADMIN_ID, ch_id, msg_id)
                    stop = False
                    if test_msg.content_type == 'photo':
                        # ← አዲስ: በአንድ ጊዜ የተለጠፉ ተከታታይ ፎቶዎች (አልበም) አንድ ፖስት ናቸው
                        key = (getattr(test_msg, "media_group_id", None)
                               or getattr(test_msg, "forward_date", None)
                               or getattr(getattr(test_msg, "forward_origin", None), "date", None))
                        same_post = bool(
                            posts and key is not None
                            and posts[-1]["key"] == key
                            and posts[-1]["ids"][-1] - msg_id == 1
                        )
                        if same_post:
                            posts[-1]["ids"].append(msg_id)
                        elif len(posts) < 5:
                            posts.append({"key": key, "ids": [msg_id]})
                        else:
                            stop = True
                    elif len(posts) >= 5:
                        stop = True
                    try:
                        bot.delete_message(ADMIN_ID, test_msg.message_id)
                    except Exception:
                        pass
                    if stop:
                        break
                except: continue

            # ← አዲስ: ሁሉንም የፖስቶች ፎቶዎች ወደ አንድ ዝርዝር (ከዚህ በታች ያለው እንዳለ ነው)
            photo_ids = [i for p in posts for i in p["ids"]]
            
            show_progress(ch_info.title, 100)  # ← አዲስ: ፍለጋው ሲያልቅ 100%

            if not photo_ids:
                bot.send_message(uid, t(lang, "no_posters"))
            else:
                # --- ቁልፍ ለውጥ እዚህ ጋር ነው ---
                # የፎቶዎቹን ቅደም ተከተል ወደ መደበኛ እንመልሰዋለን (አዲሱ መጨረሻ ላይ እንዲሆን)
                photo_ids.reverse() 
                
                bot.forward_messages(uid, ch_id, photo_ids)
                bot.send_message(uid, t(lang, "get_vip"))
        except Exception as e:
            bot.send_message(uid, t(lang, "posters_fail"))
        bot.delete_message(uid, wait_msg.message_id)


# =========================================================================
# 8. PAYMENT & ADMIN PROCESSES
# =========================================================================
def get_payment_screenshot(message):
    lang = lang_of(message.from_user.id)
    if message.text == "/cancel":
        bot.send_message(message.chat.id, t(lang, "cancelled"), reply_markup=main_menu_keyboard(lang))
        return
    
    if not message.photo:
        bot.send_message(message.chat.id, t(lang, "photo_only"))
        bot.register_next_step_handler(message, get_payment_screenshot)
        return
    
    bot.send_message(message.chat.id, t(lang, "ask_name"))
    bot.register_next_step_handler(message, lambda m: collect_name_and_submit(m, message))

def collect_name_and_submit(message, photo_msg):
    uid, name = message.from_user.id, message.text
    if message.text == "/cancel": return
    lang = lang_of(uid)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add(t(lang, "finish_btn"))
    bot.send_message(uid, t(lang, "confirm_name", name=esc(name)), reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, name))

def finalize_submission(message, photo_msg, full_name):
    uid = message.from_user.id
    lang = lang_of(uid)
    if message.text not in (TXT["am"]["finish_btn"], TXT["en"]["finish_btn"]):
        if message.text == "/cancel":
            bot.send_message(uid, t(lang, "cancelled"), reply_markup=main_menu_keyboard(lang))
            return
        if message.text:
            # ← አዲስ: ሌላ ጽሁፍ ከላከ እንደ አዲስ ስም ተቆጥሮ እንደገና ማረጋገጫ ይጠየቃል
            collect_name_and_submit(message, photo_msg)
            return
        bot.send_message(uid, t(lang, "press_finish"), reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(t(lang, "finish_btn")))
        bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, full_name))
        return

    user_data = users_col.find_one({"user_id": uid})
    plan_id = user_data.get("pending_plan", "plan1")
    plan_name_am = PLANS[plan_id]["name"]
    
    approve_markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}_{plan_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}")
    )
    
    admin_msg = (
        "<b>💰 አዲስ የክፍያ ጥያቄ!</b>\n\n"
        f"👤 <b>ስም፦</b> {full_name}\n"
        f"🆔 <b>ID፦</b> <a href='tg://user?id={uid}'>{uid}</a>\n"
        f"💎 <b>ጥቅል፦</b> {plan_name_am}"
    )
    
    bot.send_message(ADMIN_ID, admin_msg)
    bot.forward_message(ADMIN_ID, uid, photo_msg.message_id)
    bot.send_message(ADMIN_ID, "ያረጋግጡ፦", reply_markup=approve_markup)
    
    bot.send_message(uid, t(lang, "sent_ok"), reply_markup=main_menu_keyboard(lang))

def process_add_channel(message):
    # 'ሁሉንም ጨርሻለሁ' የሚለውን ቁልፍ ከነካ
    if message.text == "✅ ሁሉንም ጨርሻለሁ":
        bot.send_message(ADMIN_ID, "<b>ስራው ተጠናቋል!</b> ቻናሎቹ ገብተዋል።", reply_markup=main_menu_keyboard())
        bot.send_message(ADMIN_ID, "<b>🛠 Master Admin Panel:</b>", reply_markup=admin_panel_keyboard())
        return

    # መልዕክቱ ፎርዋርድ የተደረገ ካልሆነ
    if not message.forward_from_chat:
        bot.send_message(ADMIN_ID, "❌ ስህተት! እባክዎ መልዕክቱን ከቻናሉ ፎርዋርድ ያድርጉት።\n\nካበቁ <b>'✅ ሁሉንም ጨርሻለሁ'</b> የሚለውን ይጫኑ።")
        bot.register_next_step_handler(message, process_add_channel)
        return
    
    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title
    
    try:
        # ቦቱ መረጃ ማንበብ እንደሚችል ያረጋግጣል
        bot.get_chat(ch_id)
        
        # ዳታቤዝ ላይ መረጃውን ማደስ/መጨመር
        channels_col.update_one(
            {"id": ch_id}, 
            {"$set": {"name": ch_name, "id": ch_id}}, 
            upsert=True
        )
        
        # ለቀጣዩ ዝግጁ እንዲሆን
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("✅ ሁሉንም ጨርሻለሁ"))
        
        bot.send_message(ADMIN_ID, f"✅ ቻናል <b>{ch_name}</b> ገብቷል!\n\nአሁንም ሌላ ቻናል <b>forward</b> ማድረግ ይችላሉ። ሲጨርሱ ቁልፉን ይጫኑ።", reply_markup=markup)
        
        # እንደገና ራሱን ይጠራል (ይህ ነው ብዙ ቻናል በአንድ ጊዜ እንዲያስገባ የሚያደርገው)
        bot.register_next_step_handler(message, process_add_channel)
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ ስህተት፦ ቦቱ በቻናሉ ላይ አድሚን መሆኑን ያረጋግጡ።\nምክንያት፦ {e}")
        bot.register_next_step_handler(message, process_add_channel)

        
def process_manual_remove(message):
    uid_text = message.text.strip()
    
    if uid_text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return

    if not uid_text.isdigit():
        bot.send_message(ADMIN_ID, "❌ ስህተት! እባክዎ ትክክለኛ የቁጥር ID ብቻ ያስገቡ።")
        bot.register_next_step_handler(message, process_manual_remove)
        return

    target_id = int(uid_text)
    
    # 1. ከዳታቤዝ አገልግሎቱን ማቋረጥ
    users_col.update_one({"user_id": target_id}, {"$set": {"active": False, "expiry": 0}})
    
    # 2. ከሁሉም VIP ቻናሎች ማስወገድ
    success_count = 0
    channels = list(channels_col.find())
    
    for ch in channels:
        try:
            bot.ban_chat_member(ch["id"], target_id)
            bot.unban_chat_member(ch["id"], target_id) 
            success_count += 1
        except Exception:
            continue

    bot.send_message(ADMIN_ID, f"✅ ተጠቃሚ {target_id} ከ {success_count} ቻናሎች ተወግዷል፤ በዳታቤዝም አገልግሎቱ ተዘግቷል።", reply_markup=admin_panel_keyboard())


# ← አዲስ: ውድቅ ሲደረግ የራስህን መልዕክት መላክ
def process_reject_custom(message, target_id):
    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል።")
        return

    if not message.text:
        bot.send_message(ADMIN_ID, "⚠️ እባክዎ የጽሁፍ መልዕክት ብቻ ይላኩ።\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(message, lambda m: process_reject_custom(m, target_id))
        return

    tl = lang_of(target_id)
    try:
        bot.send_message(target_id, f"{t(tl, 'rejected_head')}\n\n{html.escape(message.text)}")
        bot.send_message(ADMIN_ID, f"✅ ለተጠቃሚ {target_id} መልዕክቱ ተልኳል።")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ መልዕክቱን መላክ አልተቻለም።\nምክንያት፦ {e}")


# ← አዲስ: አድሚን በእጅ VIP አባል ሲጨምር
def parse_duration(text):
    """'3 ደቂቃ' / '1 ሰዓት' / '3 ቀን' (ወይም 3m / 1h / 3d) → (ሰከንድ, አማርኛ, English). ዝቅተኛው 3 ደቂቃ"""
    m = re.match(r"^(\d+)\s*(ደቂቃ|ሰዓት|ቀን|m|min|h|hr|d)$", text.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    plural = "s" if n != 1 else ""
    if unit in ("ደቂቃ", "m", "min"):
        seconds, label_am, label_en = n * 60, f"{n} ደቂቃ", f"{n} minute{plural}"
    elif unit in ("ሰዓት", "h", "hr"):
        seconds, label_am, label_en = n * 3600, f"{n} ሰዓት", f"{n} hour{plural}"
    else:
        seconds, label_am, label_en = n * 86400, f"{n} ቀን", f"{n} day{plural}"
    if seconds < 180:
        return None
    return seconds, label_am, label_en


def process_add_vip_user(message):
    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return

    target_id = None
    fwd = getattr(message, "forward_from", None)
    if not fwd:
        fwd = getattr(getattr(message, "forward_origin", None), "sender_user", None)
    if fwd:
        target_id = fwd.id
    elif message.text:
        txt = message.text.strip()
        if txt.isdigit():
            target_id = int(txt)
        elif txt.startswith("@"):
            found = users_col.find_one({"username": txt[1:].lower()})
            if found:
                target_id = found["user_id"]

    if not target_id:
        bot.send_message(ADMIN_ID, "❌ ተጠቃሚውን ማግኘት አልተቻለም።\n\nትክክለኛ ID ይላኩ ወይም መልዕክቱን ፎርዋርድ ያድርጉ። (@username የሚሠራው ቦቱን ለጀመሩ ሰዎች ብቻ ነው፤ ፎርዋርድ ደግሞ ተጠቃሚው ስሙን ከደበቀ አይሠራም።)\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(message, process_add_vip_user)
        return

    markup = InlineKeyboardMarkup()
    for key, val in PLANS.items():
        markup.add(InlineKeyboardButton(val["name"], callback_data=f"admvip_plan_{target_id}_{key}"))
    markup.add(InlineKeyboardButton("⏱ ሌላ ጊዜ (ደቂቃ / ሰዓት / ቀን)", callback_data=f"admvip_plan_{target_id}_custom"))
    bot.send_message(ADMIN_ID, f"👤 ተጠቃሚ፦ <code>{target_id}</code>\n\nየሚሰጡትን ጥቅል ይምረጡ፦", reply_markup=markup)


def ask_vip_start(target_id, plan_id, duration, label_am, label_en):
    msg = bot.send_message(
        ADMIN_ID,
        "📅 <b>የአባልነቱ መጀመሪያ ቀንና ሰዓት</b> (በኢትዮጵያ አቆጣጠር) ይጻፉ፦\n\n"
        "ቅርጹ፦ <code>ቀን/ወር/ዓመት ሰዓት:ደቂቃ</code>\nምሳሌ፦ <code>06/03/2019 14:30</code>\n\n"
        "አሁኑን ለመውሰድ <b>አሁን</b> ብለው ይጻፉ።\nለመሰረዝ /cancel ይበሉ።"
    )
    bot.register_next_step_handler(msg, lambda m: process_add_vip_time(m, target_id, plan_id, duration, label_am, label_en))


def process_add_vip_duration(message, target_id):
    text = (message.text or "").strip()
    if text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return
    parsed = parse_duration(text)
    if not parsed:
        bot.send_message(ADMIN_ID, "❌ ቅርጹ ትክክል አይደለም ወይም ቆይታው ከ3 ደቂቃ ያነሰ ነው።\n\nምሳሌ፦ <code>3 ደቂቃ</code>፣ <code>1 ሰዓት</code>፣ <code>3 ቀን</code>\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(message, lambda m: process_add_vip_duration(m, target_id))
        return
    seconds, label_am, label_en = parsed
    ask_vip_start(target_id, "custom", seconds, label_am, label_en)


def process_add_vip_time(message, target_id, plan_id, duration, label_am, label_en):
    text = (message.text or "").strip()

    if text == "/cancel":
        bot.send_message(ADMIN_ID, "ሂደቱ ተሰርዟል!", reply_markup=admin_panel_keyboard())
        return

    try:
        if text == "አሁን":
            start_ts = time.time()
        else:
            date_part, time_part = text.split()
            d, mo, y = [int(x) for x in date_part.split("/")]
            hh, mm = [int(x) for x in time_part.split(":")]
            g = EthiopianDateConverter.to_gregorian(y, mo, d)
            eat = timezone(timedelta(hours=3))  # የኢትዮጵያ ሰዓት
            start_ts = datetime(g.year, g.month, g.day, hh, mm, tzinfo=eat).timestamp()
    except Exception:
        bot.send_message(ADMIN_ID, "❌ ቅርጹ ትክክል አይደለም።\n\nምሳሌ፦ <code>06/03/2019 14:30</code> ወይም <b>አሁን</b>\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(message, lambda m: process_add_vip_time(m, target_id, plan_id, duration, label_am, label_en))
        return

    expiry_ts = start_ts + duration
    if expiry_ts <= time.time():
        bot.send_message(ADMIN_ID, "⚠️ በዚህ ቀን የሚሰላው ማብቂያ አልፏል፤ ተጠቃሚው ወዲያው ይወገድ ነበር። ሌላ ቀን ይጻፉ።\n\nለመሰረዝ /cancel ይበሉ።")
        bot.register_next_step_handler(message, lambda m: process_add_vip_time(m, target_id, plan_id, duration, label_am, label_en))
        return

    update = {"$set": {"active": True, "expiry": expiry_ts, "plan": plan_id, "joined_at": start_ts}}
    if plan_id == "custom":
        update["$set"]["custom_label"] = label_am
        update["$set"]["custom_label_en"] = label_en
    else:
        update["$unset"] = {"custom_label": "", "custom_label_en": ""}
    users_col.update_one({"user_id": target_id}, update, upsert=True)

    tl = lang_of(target_id)
    try:
        target_name = bot.get_chat(target_id).first_name
    except Exception:
        target_name = ""

    status_text = t(tl, "approved_head") + t(
        tl, "my_full",
        name=esc(target_name),
        plan=label_en if tl == "en" else label_am,
        expiry=to_eth_date(expiry_ts, tl),
    )
    try:
        bot.send_message(target_id, status_text, reply_markup=get_channel_status_markup(target_id), protect_content=is_restriction_on())
        notified = "✅ ለተጠቃሚው መልዕክት ተልኳል።"
    except Exception:
        notified = "⚠️ ለተጠቃሚው መልዕክት መላክ አልተቻለም (ቦቱን ጀምሮ ላይሆን ይችላል)፤ አባልነቱ ግን ተመዝግቧል።"

    eat = timezone(timedelta(hours=3))
    end_clock = datetime.fromtimestamp(expiry_ts, eat).strftime("%H:%M")
    bot.send_message(
        ADMIN_ID,
        f"✅ ተጠቃሚ {target_id} VIP አባል ሆኗል ({label_am})።\n"
        f"📅 የጀመረው፦ {to_eth_date(start_ts)}\n"
        f"⏳ የሚያበቃው፦ {to_eth_date(expiry_ts)} ሰዓት {end_clock}\n\n{notified}",
        reply_markup=admin_panel_keyboard()
    )


# =========================================================================
# 9. RUN BOT
# =========================================================================
if __name__ == "__main__":
    logger.info("Starting ET Movie zone Pro Bot...")
    
    # Start Keep Alive Server
    start_keep_alive()
    
    # Start Expiration Checker
    kick_thread = threading.Thread(target=auto_kick_worker, daemon=True)
    kick_thread.start()
    
    # Start Polling
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling Error: {e}")
            time.sleep(15)
