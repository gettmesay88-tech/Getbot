import os
import telebot
import time
import threading
import logging
from datetime import datetime, timedelta
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
    return "<b>Gett VIP Pro Bot is running smoothly!</b>"

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
    "plan1": {"duration": 30, "price": 200, "name": "የ 1 ወር (200 ብር)", "days": 30},
    "plan2": {"duration": 60, "price": 380, "name": "የ 2 ወር (380 ብር)", "days": 60},
    "plan3": {"duration": 90, "price": 550, "name": "የ 3 ወር (550 ብር)", "days": 90},
    "plan5": {"duration": 150, "price": 1050, "name": "የ 5 ወር (1050 ብር)", "days": 150},
    "plan12": {"duration": 365, "price": 2000, "name": "የ 1 አመት (2000 ብር)", "days": 365}
}

# =========================================================================
# 3. UTILITY FUNCTIONS
# =========================================================================
def to_eth_date(timestamp):
    """Converts Unix timestamp to Ethiopian Date String"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        conv = EthiopianDateConverter.to_ethiopian(dt.year, dt.month, dt.day)
        months = ["", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"]
        return f"{months[conv.month]} {conv.day}፣ {conv.year}"
    except Exception as e:
        logger.error(f"Date conversion error: {e}")
        return "ያልታወቀ ቀን"

def execute_manual_vip(target_id, days, message):
    expiry_ts = (datetime.now() + timedelta(days=days)).timestamp()
    eth_date = to_eth_date(expiry_ts)

    # ዳታቤዝ ላይ መመዝገብ
    users_col.update_one(
        {"user_id": target_id},
        {"$set": {"active": True, "expiry": expiry_ts, "plan": f"custom_{days}day", "joined_at": time.time()}},
        upsert=True
    )

    bot.send_message(ADMIN_ID, f"✅ ተሳክቷል!\n👤 ID: `{target_id}`\n📅 ቆይታ: {days} ቀን\n🔚 የሚያበቃው: {eth_date}")

    try:
        bot.send_message(target_id, 
            f"<b>✅ እንኳን ደስ አለዎት! የአባልነትዎ ጸድቋል።</b>\n\n"
            f"📅 ቆይታ፦ {days} ቀናት\n"
            f"⏳ የሚያበቃው፦ {eth_date}\n\n"
            f"የቻናል ሊንኮችን ለማግኘት '👤 የእኔ አገልግሎት' የሚለውን ይጫኑ።")
    except:
        bot.send_message(ADMIN_ID, "⚠️ ለተጠቃሚው መልዕክት መላክ አልተቻለም።")

def is_restriction_on():
    """Checks if content protection is enabled"""
    data = settings_col.find_one({"type": "config"})
    return data.get("restriction", True) if data else True

def get_channel_status_markup(user_id):
    markup = InlineKeyboardMarkup()
    channels = list(channels_col.find())
    
    for index, ch in enumerate(channels, start=1):
        try:
            member = bot.get_chat_member(ch["id"], user_id)
            if member.status in ['member', 'administrator', 'creator']:
                status_icon = "✅"
                # ቀጥታ ወደ ቻናሉ የሚወስድ ሊንክ
                link = f"https://t.me/c/{str(ch['id']).replace('-100', '')}/1" 
            else:
                status_icon = "☑️"
                # አዲስ የግብዣ ሊንክ
                link = bot.create_chat_invite_link(ch["id"], member_limit=1).invite_link
            
            markup.add(InlineKeyboardButton(f"{status_icon} {ch['name']} {index}", url=link))
        except Exception:
            continue
            
    # የፈለግከው "Refresh" በተን እዚህ ጋር አለ
    markup.add(InlineKeyboardButton("🔄 ሁሉም ቻናል መግባቶን ያረጋግጡ (Refresh)", callback_data="refresh_service"))
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
                    msg = "<b>⚠️ የአገልግሎት ጊዜዎ አብቅቷል!</b>\n\nከVIP ቻናሎች በራስ-ሰር ተወግደዋል። አገልግሎቱን ለመቀጠል እባክዎ ደግመው ይክፈሉ እና ደረሰኝ ይላኩ።"
                    bot.send_message(uid, msg)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Auto-kick worker error: {e}")
            
        time.sleep(60) # Check every 60 seconds

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
    # አዲሱ በተን እዚህ አለ
    markup.add(InlineKeyboardButton("💎 VIP አባል ጨምር", callback_data="adm_add_vip")) 
    
    markup.add(InlineKeyboardButton("🔄 የቻናል ስሞችን አድስ (Sync)", callback_data="adm_sync_names"))
    
    res_text = "🚫 Restriction: ON" if is_restriction_on() else "🔓 Restriction: OFF"
    markup.add(InlineKeyboardButton(res_text, callback_data="adm_toggle_res"))
    markup.add(InlineKeyboardButton("👤 ተጠቃሚ ማባረር (Manual)", callback_data="adm_manual_remove")) 

    return markup


# =========================================================================
# 6. MESSAGE HANDLERS
# =========================================================================
@bot.message_handler(commands=['vip'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_add_vip_manual(message):
    msg = bot.send_message(ADMIN_ID, "👤 VIP የሚሆነውን ሰው መልዕክት **Forward** ያድርጉ ወይም **ID** (ቁጥር) ይላኩ፦")
    bot.register_next_step_handler(msg, process_vip_input)

def process_vip_input(message):
    target_id = None
    user_label = "ተጠቃሚ"

    if message.forward_from:
        target_id = message.forward_from.id
        user_label = message.forward_from.first_name
    elif message.text and message.text.isdigit():
        target_id = int(message.text)
        user_label = f"ID: {target_id}"
    
    if target_id:
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("1 ቀን", callback_data=f"manadd_{target_id}_1"),
            InlineKeyboardButton("7 ቀን", callback_data=f"manadd_{target_id}_7")
        )
        markup.row(
            InlineKeyboardButton("1 ወር (30)", callback_data=f"manadd_{target_id}_30"),
            InlineKeyboardButton("3 ወር (90)", callback_data=f"manadd_{target_id}_90")
        )
        markup.add(InlineKeyboardButton("✍️ የራስህን ቀን ጻፍ", callback_data=f"manadd_custom_{target_id}"))
        markup.add(InlineKeyboardButton("❌ ሰርዝ", callback_data="cancel_admin"))
        
        bot.send_message(ADMIN_ID, f"🎯 <b>{user_label}</b> ተለይቷል።\nለስንት ቀን አባል እንዲሆን ይፈልጋሉ?", reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID, "❌ ስህተት፦ እባክዎ መልዕክት Forward ያድርጉ ወይም ትክክለኛ ID ይላኩ።")

@bot.message_handler(commands=['start'])
def handle_start(message):
    uid = message.chat.id
    first_name = message.from_user.first_name
    
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
    bot.send_message(uid, status_text, reply_markup=get_channel_status_markup(uid), protect_content=is_restriction_on())

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
    # ቻናሎቹን በተን ላይ ብቻ እንጨምራለን
    for index, ch in enumerate(channels, start=1):
        markup.add(InlineKeyboardButton(f"🔹 {ch['name']} {index}", callback_data=f"view_ch_{ch['id']}"))
        
    # ጽሁፉን አጥፍተን ርዕሱን እና በተኖቹን ብቻ እንልካለን
    bot.send_message(message.chat.id, "<b>📜 የVIP ቻናሎች ዝርዝር፦</b>\nስለ ቻናሉ ለማወቅ ስሙን ይጫኑ 👇", reply_markup=markup)
    
import random # ይህን ከላይ ከኢምፖርቶች ጋር ጨምረው

@bot.message_handler(func=lambda m: m.text == "🎬 አዳዲስ ፊልሞች")
def handle_new_movies(message):
    all_channels = list(channels_col.find())
    if not all_channels:
        bot.send_message(message.chat.id, "<b>❌ ምንም ቻናል አልተገኘም።</b>")
        return

    # 12 ቻናሎችን መምረጥ
    selected_channels = random.sample(all_channels, min(len(all_channels), 12))
    
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = []
    
    for ch in selected_channels:
        # ስሙን ማጽዳት (ከ '-' በፊት ያለውን ብቻ መውሰድ)
        clean_name = ch['name'].split('-')[0].strip()
        clean_name = ''.join([i for i in clean_name if not i.isdigit()]).strip()
        
        buttons.append(InlineKeyboardButton(f"🎬 {clean_name}", callback_data=f"get_last_5_{ch['id']}"))
    
    markup.add(*buttons)
    bot.send_message(message.chat.id, "<b>🎬 የፊልም ፖስተሮች፦</b>\n\nየፊልም ፎቶዎችን ለማየት የቻናሉን ስም ይጫኑ 👇", reply_markup=markup)


# =========================================================================
# 7. CALLBACK QUERY HANDLER
# =========================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    uid, mid = call.from_user.id, call.message.message_id

        # --- የአድሚን VIP መጨመሪያ Button Logic ---
    if call.data.startswith('manadd_'):
        if call.data.startswith('manadd_custom_'):
            t_id = call.data.split('_')[2]
            msg = bot.send_message(ADMIN_ID, "✍️ እባክዎ የቀናትን ብዛት በቁጥር ብቻ ይላኩ (ለምሳሌ፦ 10)፦")
            bot.register_next_step_handler(msg, lambda m: execute_manual_vip(int(t_id), int(m.text), m) if m.text.isdigit() else bot.send_message(ADMIN_ID, "❌ ስህተት፦ ቁጥር ብቻ ያስገቡ!"))
            return

        _, t_id, days = call.data.split('_')
        execute_manual_vip(int(t_id), int(days), call.message)
        return

    if call.data == "cancel_admin":
        bot.edit_message_text("❌ ተግባሩ ተሰርዟል።", ADMIN_ID, mid)
        return

    
    # User: Plan Selection
    if call.data.startswith("buy_"):
        plan_id = call.data.split("_")[1]
        users_col.update_one({"user_id": uid}, {"$set": {"pending_plan": plan_id}}, upsert=True)
        
        bank_markup = InlineKeyboardMarkup(row_width=2)
        bank_markup.add(
            InlineKeyboardButton("🏦 CBE (ንግድ ባንክ)", callback_data="pay_cbe"),
            InlineKeyboardButton("🏦 Abyssinia (አቢሲኒያ)", callback_data="pay_aby")
        )
        bank_markup.add(InlineKeyboardButton("📱 Telebirr (ቴሌብር)", callback_data="pay_tele"))
        
        bot.edit_message_text("<b>ለመክፈል የሚፈልጉትን የባንክ አይነት ይምረጡ፦</b>", uid, mid, reply_markup=bank_markup)

    # User: Payment Method
    elif call.data.startswith("pay_"):
        method = call.data.split("_")[1]
        if method == "cbe":
            acc_info = "<b>🏦 የኢትዮጵያ ንግድ ባንክ (CBE)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>1000355140206</code>"
        elif method == "aby":
            acc_info = "<b>🏦 አቢሲኒያ ባንክ (Abyssinia)</b>\n👤 ስም: Getamesay Fikru\n🔢 Acc: <code>167829104</code>"
        else:
            acc_info = "<b>📱 ቴሌብር (Telebirr)</b>\n👤 ስም: Getamesay Fikru\n🔢 ስልክ: <code>0965979124</code>"
            
        instruction = f"{acc_info}\n\n<b>📸 ክፍያውን ከፈጸሙ በኋላ የደረሰኙን ፎቶ (Screenshot) እዚህ ይላኩ።</b>\n\nለመሰረዝ /cancel ይበሉ።"
        bot.edit_message_text(instruction, uid, mid)
        bot.register_next_step_handler(call.message, get_payment_screenshot)
            # ይህንን እዚህ ጋር ጨምር
    elif call.data == "adm_add_vip_manual":
        admin_add_vip_manual(call.message)
        return

         # Admin: List Users
    elif call.data == "adm_users" or call.data == "adm_list":
        active_users = list(users_col.find({"active": True}))
        if not active_users: # ይህ መስመር ከ elif ጋር ትይዩ መሆን አለበት
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

    # አድሚን VIP ለመጨመር ሲጀምር (ፎርዋርድ የሚጠይቀው)
    elif call.data == "adm_add_vip":
        msg = bot.send_message(ADMIN_ID, "እባክዎ አባል ማድረግ የሚፈልጉትን የሰውን መልዕክት <b>ፎርዋርድ (Forward)</b> ያድርጉልኝ፦")
        bot.register_next_step_handler(msg, process_forward_vip)

    # አድሚን ጥቅሉን ሲመርጥ (በቀጥታ አባል የሚያደርገው)
    elif call.data.startswith("adm_set_vip_"):
        # callback: adm_set_vip_{target_id}_{plan_id}
        data_parts = call.data.split("_")
        target_id = int(data_parts[3])
        plan_id = data_parts[4]
        
        # ቀን ማስላት
        days = PLANS[plan_id]["days"]
        expiry_ts = (datetime.now() + timedelta(days=days)).timestamp()
        
        # ዳታቤዝ ማዘመን
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"active": True, "expiry": expiry_ts, "plan": plan_id, "joined_at": time.time()}},
            upsert=True
        )
        
        bot.answer_callback_query(call.id, "✅ ተጠቃሚው VIP ሆኗል!")
        bot.edit_message_text(f"✅ ተጠቃሚ {target_id} ለ {PLANS[plan_id]['name']} VIP ሆኖ ተመዝግቧል።", ADMIN_ID, mid)
        
        # ተጠቃሚውን ማሳወቅ
        try:
            bot.send_message(target_id, "<b>🎉 እንኳን ደስ አለዎት!</b>\n\nአድሚኑ VIP አባል አድርገውዎታል። አሁን '👤 የእኔ አገልግሎት' የሚለውን በመጫን ቻናሎቹን መከታተል ይችላሉ።")
        except:
            pass
        
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
        # እዚህ ጋር 3ቱንም ክፍል መያዝ አለብህ (የመጀመሪያውን _ ችላ ብለነዋል)
        _, target_id_str, plan_id = call.data.split("_")
        target_id = int(target_id_str)
        
        # መጀመሪያ የተጠቃሚውን ዳታ ከ DB መጥራት አለብህ
        u = users_col.find_one({"user_id": target_id}) 
        
        # የ indentation ስህተት እዚህ ነበር - if ከ u ጋር መስመር ላይ መሆን አለበት
        if not u:
            bot.send_message(ADMIN_ID, "ተጠቃሚው በዳታቤዝ ውስጥ አልተገኘም!")
            return

        # የተጠቃሚውን መረጃ ከቴሌግራም ለማምጣት
        user_info = bot.get_chat(target_id)
        u_name = user_info.first_name if user_info.first_name else "ተጠቃሚ"

        # ... (ሌላው የዳታቤዝ ኮድህ እንዳለ ይቀጥላል)

        msg = (
            f"<b>✅ እንኳን ደስ አለዎት! ክፍያዎ ተረጋግጧል።</b>\n\n"
            f"👤 ስም: {call.from_user.first_name}\n" 
            f"📅 የገቡበት: {to_eth_date(u.get('joined_at', time.time()))}\n" 
            f"⏳ የሚያበቃው {to_eth_date(u['expiry'])}\n\n" 
            f"☑️ - ቻናል ውስጥ አልገቡም\n"
            f"✅ - ቻናል ውስጥ ገብተዋል\n\n" 
            f"የሁሉንም ቻናሎች ሊንኮች ከታች ይገናኛሉ🔻"
        )
        
        bot.send_message(target_id, msg, reply_markup=get_channel_status_markup(target_id))
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

    elif call.data == "refresh_service":
        bot.answer_callback_query(call.id, "መረጃው እየታደሰ ነው...")
        handle_my_service(call.message) # መልዕክቱን እንዲያድሰው

          # User: View Description with Real-time Update
          # User: View Description
    elif call.data.startswith("view_ch_"):
        try:
            ch_id = int(call.data.split("_")[2])
            info = bot.get_chat(ch_id)
            description = info.description if info.description else "ለዚህ ቻናል ምንም መግለጫ አልተጻፈም።"
            bot.answer_callback_query(call.id, f"📝 የቻናሉ መግለጫ፦\n\n{description}", show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ መግለጫውን ማግኘት አልተቻለም።\nምክንያት፦ {e}", show_alert=True)

            # የፊልም ፖስተር ማምጫ (ቅደም ተከተል የተስተካከለ)
    elif call.data.startswith("get_last_5_"):
        ch_id = int(call.data.split("_")[3])
        uid = call.from_user.id
        wait_msg = bot.send_message(uid, "<b>⏳ እባክዎ ይጠብቁ... ፊልሞችን እያመጣሁ ነው</b>")
        try:
            ch_info = bot.get_chat(ch_id)
            bot.send_message(uid, f"<b>🎬 ከ {ch_info.title} የተመረጡ አዳዲስ የፊልም ፖስተሮች፦</b>")
            
            temp_msg = bot.send_message(ch_id, ".")
            last_id = temp_msg.message_id
            bot.delete_message(ch_id, last_id)
            
            photo_ids = []
            # ወደ ኋላ በመሄድ አዳዲሶቹን 5 ፎቶዎች መፈለግ
            for msg_id in range(last_id - 1, last_id - 51, -1):
                if len(photo_ids) >= 5: break
                try:
                    test_msg = bot.forward_message(ADMIN_ID, ch_id, msg_id)
                    if test_msg.content_type == 'photo':
                        photo_ids.append(msg_id)
                    bot.delete_message(ADMIN_ID, test_msg.message_id)
                except: continue
            
            if not photo_ids:
                bot.send_message(uid, "<b>❌ በዚህ ቻናል ላይ ምንም የፊልም ፖስተር አልተገኘም።</b>")
            else:
                photo_ids.reverse() 
                for p_id in photo_ids:
                    bot.forward_message(uid, ch_id, p_id) # በአንድ በአንድ መላክ
                bot.send_message(uid, "<b>✅ ሁሉንም ፊልሞች ለማግኘት VIP አባል ይሁኑ!</b>")

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
    uid, name = message.from_user.id, message.text
    if message.text == "/cancel": return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("ሁሉንም ነገር ጨርሻለሁ ላክ")
    bot.send_message(uid, f"ተቀብያለሁ <b>{name}</b>! ለመጨረስ ከታች ያለውን ቁልፍ ይጫኑ።", reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, name))

def finalize_submission(message, photo_msg, full_name):
    uid = message.from_user.id
    if message.text != "ሁሉንም ነገር ጨርሻለሁ ላክ":
        bot.send_message(uid, "እባክዎ 'ሁሉንም ነገር ጨርሻለሁ ላክ' የሚለውን ይጫኑ።", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("ሁሉንም ነገር ጨርሻለሁ ላክ"))
        bot.register_next_step_handler(message, lambda m: finalize_submission(m, photo_msg, full_name))
        return

    user_data = users_col.find_one({"user_id": uid})
    plan_id = user_data.get("pending_plan", "plan1")
    plan_name = PLANS[plan_id]["name"]
    
    approve_markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}_{plan_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}")
    )
    
    admin_msg = (
        "<b>💰 አዲስ የክፍያ ጥያቄ!</b>\n\n"
        f"👤 <b>ስም፦</b> {full_name}\n"
        f"🆔 <b>ID፦</b> <a href='tg://user?id={uid}'>{uid}</a>\n"
        f"💎 <b>ጥቅል፦</b> {plan_name}"
    )
    
    bot.send_message(ADMIN_ID, admin_msg)
    bot.forward_message(ADMIN_ID, uid, photo_msg.message_id)
    bot.send_message(ADMIN_ID, "ያረጋግጡ፦", reply_markup=approve_markup)
    
    bot.send_message(uid, "<b>✅ በስኬት ተልኳል!</b>\nአድሚኑ ደረሰኙን አይቶ በቅርቡ ያረጋግጥልዎታል።", reply_markup=main_menu_keyboard())

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

def process_forward_vip(message):
    # ተጠቃሚው መልዕክት ፎርዋርድ ማድረጉን ማረጋገጥ
    if not message.forward_from:
        bot.send_message(ADMIN_ID, "❌ ስህተት! የላከው መልዕክት የደንበኛው መረጃ (Forward info) የለውም። \n\nእባክዎ እንደገና ሌላ መልዕክት ፎርዋርድ ያድርጉ።")
        return

    target_id = message.forward_from.id
    target_name = message.forward_from.first_name
    
    # ፓኬጆችን ለማሳየት
    markup = InlineKeyboardMarkup()
    for key, val in PLANS.items():
        markup.add(InlineKeyboardButton(f"💳 {val['name']}", callback_data=f"adm_set_vip_{target_id}_{key}"))
    
    bot.send_message(ADMIN_ID, f"✅ ተገኝቷል፦ <b>{target_name}</b> (ID: <code>{target_id}</code>)\n\nለዚህ ተጠቃሚ የሚሰጠውን ፓኬጅ ይምረጡ፦", reply_markup=markup)

# =========================================================================
# 9. RUN BOT
# =========================================================================
if __name__ == "__main__":
    logger.info("Starting Gett VIP Pro Bot...")
    
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
