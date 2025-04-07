import json
import logging
import os
import asyncio
import re
import time
import shutil
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
import yt_dlp

TOKEN = "7531357371:AAFCcim-k6PuxYNMWOLHn4_Ss7JYgq9wBn8"
ADMIN_ID = "5743254515"
ADMIN_USERNAME = "ldftcer"
BACKUP_CHAT_ID = "-100123456789"  # Replace with your backup chat ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

DATA_FILE = "user_data.json"
STATS_FILE = "stats.json"
TEMP_DIR = "downloads"
LOG_DIR = "logs"

# Create necessary directories
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Load user data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        user_data = json.load(f)
else:
    user_data = {"users": {}, "banned": [], "premium": []}

# Load stats data
if os.path.exists(STATS_FILE):
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        stats = json.load(f)
else:
    stats = {"total_downloads": 0, "daily": {}, "users": {}, "platforms": {"tiktok": 0, "instagram": 0}}

def save_data():
    # Create backup before saving
    if os.path.exists(DATA_FILE):
        shutil.copy2(DATA_FILE, f"{DATA_FILE}.bak")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, indent=4, ensure_ascii=False)

def save_stats():
    # Create backup before saving
    if os.path.exists(STATS_FILE):
        shutil.copy2(STATS_FILE, f"{STATS_FILE}.bak")
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

def update_stats(user_id, success=True, platform=None):
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in stats["daily"]:
        stats["daily"][today] = {"success": 0, "failed": 0}
    
    if success:
        stats["total_downloads"] += 1
        stats["daily"][today]["success"] += 1
        if platform:
            stats["platforms"][platform] = stats["platforms"].get(platform, 0) + 1
    else:
        stats["daily"][today]["failed"] += 1
    
    if user_id not in stats["users"]:
        stats["users"][user_id] = {"downloads": 0, "failed": 0, "platforms": {}}
    
    if success:
        stats["users"][user_id]["downloads"] += 1
        if platform:
            stats["users"][user_id]["platforms"][platform] = stats["users"][user_id]["platforms"].get(platform, 0) + 1
    else:
        stats["users"][user_id]["failed"] += 1
    
    save_stats()

def get_platform(url):
    if "tiktok.com" in url:
        return "tiktok"
    elif "instagram.com" in url:
        return "instagram"
    return None

def clean_old_files():
    now = time.time()
    for filename in os.listdir(TEMP_DIR):
        file_path = os.path.join(TEMP_DIR, filename)
        if os.path.isfile(file_path) and os.path.getmtime(file_path) < now - 3600:  # 1 hour
            os.remove(file_path)

lang_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇼🇲 Հայերեն")],
        [KeyboardButton(text="🇬🇧 English")],
        [KeyboardButton(text="🇷🇺 Русский")]
    ],
    resize_keyboard=True
)

def get_menu_keyboard(lang, is_premium=False):
    premium_button = []
    if not is_premium:
        if lang == "hy":
            premium_button = [KeyboardButton(text="⭐️ Premium")]
        elif lang == "en":
            premium_button = [KeyboardButton(text="⭐️ Premium")]
        elif lang == "ru":
            premium_button = [KeyboardButton(text="⭐️ Premium")]
            
    if lang == "hy":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="ℹ️ Օգնություն"), KeyboardButton(text="🔄 Փոխել լեզուն")],
                premium_button
            ],
            resize_keyboard=True
        )
    elif lang == "en":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="ℹ️ Help"), KeyboardButton(text="🔄 Change language")],
                premium_button
            ],
            resize_keyboard=True
        )
    else:  # default to Russian
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="🔄 Сменить язык")],
                premium_button
            ],
            resize_keyboard=True
        )

translations = {
    "hy": {
        "choose_language": "Ընտրեք լեզուն:",
        "saved_language": "Լեզուն պահպանված է: Այժմ ուղարկեք տեսանյութի հղումը:",
        "send_link": "Ուղարկեք տեսանյութի հղումը TikTok կամ Instagram-ից:",
        "downloading": "⏳ Խնդրում ենք սպասել...",
        "download_error": "❌ Սխալ վիդեո ներբեռնելիս:",
        "banned": "⛔ Դուք արգելափակված եք այս բոտում:",
        "help": "🔹 Ուղարկեք տեսանյութի հղումը TikTok կամ Instagram-ից։\n🔹 Սպասեք մի քանի վայրկյան\n🔹 Ստացեք տեսանյութը առանց ջրանշան",
        "change_language": "Կրկին ընտրեք լեզուն:",
        "unsupported_link": "⚠️ Չաջակցվող հղում: Խնդրում ենք օգտագործել միայն TikTok կամ Instagram-ի հղումներ:",
        "premium_info": "⭐️ Premium հաշիվը տալիս է հետևյալ առավելությունները:\n✅ Ավելի արագ ներբեռնում\n✅ Բարձր որակ\n✅ Գովազդ չկա\n✅ Առաջնահերթ աջակցություն\n\nԳինը: $5/ամիս",
        "contact_admin": "💬 Կապվեք ադմինի հետ",
        "rate_limit": "⚠️ Դուք հասել եք օրական սահմանին: Սպասեք 24 ժամ կամ բարելավեք Premium-ի համար"
    },
    "en": {
        "choose_language": "Choose language:",
        "saved_language": "Language saved! Now send a video link.",
        "send_link": "Send a video link from TikTok or Instagram.",
        "downloading": "⏳ Please wait...",
        "download_error": "❌ Error downloading video.",
        "banned": "⛔ You are banned from this bot.",
        "help": "🔹 Send a TikTok or Instagram video link\n🔹 Wait a few seconds\n🔹 Get your video without watermarks",
        "change_language": "Choose your language again:",
        "unsupported_link": "⚠️ Unsupported link. Please use only TikTok or Instagram links.",
        "premium_info": "⭐️ Premium account gives you these benefits:\n✅ Faster downloads\n✅ Higher quality\n✅ No ads\n✅ Priority support\n\nPrice: $5/month",
        "contact_admin": "💬 Contact Admin",
        "rate_limit": "⚠️ You've reached your daily limit. Wait 24 hours or upgrade to Premium"
    },
    "ru": {
        "choose_language": "Выберите язык:",
        "saved_language": "Язык сохранён! Теперь отправьте ссылку на видео.",
        "send_link": "Отправьте ссылку на видео из TikTok или Instagram.",
        "downloading": "⏳ Подождите несколько секунд...",
        "download_error": "❌ Ошибка при скачивании видео.",
        "banned": "⛔ Вы заблокированы в этом боте.",
        "help": "🔹 Отправьте ссылку на видео из TikTok или Instagram\n🔹 Подождите несколько секунд\n🔹 Получите видео без водяных знаков",
        "change_language": "Выберите язык снова:",
        "unsupported_link": "⚠️ Неподдерживаемая ссылка. Пожалуйста, используйте только ссылки TikTok или Instagram.",
        "premium_info": "⭐️ Премиум аккаунт даёт следующие преимущества:\n✅ Быстрая загрузка\n✅ Высокое качество\n✅ Без рекламы\n✅ Приоритетная поддержка\n\nЦена: $5/месяц",
        "contact_admin": "💬 Связаться с администратором",
        "rate_limit": "⚠️ Вы достигли дневного лимита. Подождите 24 часа или обновитесь до Premium"
    }
}

help_texts = {
    "ℹ️ Օգնություն": "hy",
    "ℹ️ Help": "en",
    "ℹ️ Помощь": "ru"
}

change_lang_texts = {
    "🔄 Փոխել լեզուն": "hy",
    "🔄 Change language": "en",
    "🔄 Сменить язык": "ru"
}

premium_texts = {
    "⭐️ Premium": "all"
}

async def is_rate_limited(user_id):
    # Skip rate limiting for premium users
    if user_id in user_data.get("premium", []):
        return False
        
    # Check how many downloads user has today
    today = datetime.now().strftime("%Y-%m-%d")
    downloads_today = stats.get("daily", {}).get(today, {}).get("success", 0)
    user_downloads = stats.get("users", {}).get(user_id, {}).get("downloads", 0)
    
    # For demonstration, limit to 5 downloads per day for free users
    return user_downloads > 5

async def backup_data():
    # Create weekly backup
    current_time = datetime.now()
    if current_time.weekday() == 0 and current_time.hour == 0:  # Monday at midnight
        backup_time = current_time.strftime("%Y%m%d")
        
        # Backup user data
        backup_data = {"user_data": user_data, "stats": stats}
        backup_file = f"backup_{backup_time}.json"
        
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4, ensure_ascii=False)
            
        # Send backup to admin
        if os.path.exists(backup_file):
            try:
                await bot.send_document(
                    ADMIN_ID, 
                    types.FSInputFile(backup_file),
                    caption=f"Weekly backup {backup_time}"
                )
                # Also send to backup chat
                await bot.send_document(
                    BACKUP_CHAT_ID, 
                    types.FSInputFile(backup_file),
                    caption=f"Weekly backup {backup_time}"
                )
                os.remove(backup_file)
            except Exception as e:
                logging.error(f"Error sending backup: {e}")

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id in user_data["banned"]:
        return await message.answer(translations["ru"]["banned"])
    
    if user_id not in user_data["users"]:
        user_data["users"][user_id] = {
            "language": None,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "join_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_activity": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_data()
        await message.answer(translations["ru"]["choose_language"], reply_markup=lang_keyboard)
    else:
        # Update last activity
        user_data["users"][user_id]["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data()
        
        lang = user_data["users"].get(user_id, {}).get("language", "ru")
        is_premium = user_id in user_data.get("premium", [])
        await message.answer(
            translations[lang]["send_link"], 
            reply_markup=get_menu_keyboard(lang, is_premium)
        )

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id != ADMIN_ID:
        return
    
    admin_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="📝 Список пользователей", callback_data="users")],
        [InlineKeyboardButton(text="🚫 Заблокировать пользователя", callback_data="ban")],
        [InlineKeyboardButton(text="✅ Разблокировать пользователя", callback_data="unban")],
        [InlineKeyboardButton(text="⭐️ Добавить Premium", callback_data="add_premium")],
        [InlineKeyboardButton(text="📢 Отправить сообщение всем", callback_data="broadcast")],
        [InlineKeyboardButton(text="🗄️ Резервная копия", callback_data="backup")]
    ]
)
    
    await message.answer("Admin Panel:", reply_markup=admin_keyboard)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    if user_id != ADMIN_ID:
        return await callback.answer("Access denied")
    
    if callback.data == "stats":
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        total = stats.get("total_downloads", 0)
        today_stats = stats.get("daily", {}).get(today, {"success": 0, "failed": 0})
        yesterday_stats = stats.get("daily", {}).get(yesterday, {"success": 0, "failed": 0})
        
        active_users = sum(1 for uid, udata in user_data["users"].items() 
                          if datetime.now() - datetime.strptime(udata.get("last_activity", "2000-01-01"), "%Y-%m-%d %H:%M:%S") < timedelta(days=7))
        
        stats_text = (
            f"📊 Statistics:\n\n"
            f"Total downloads: {total}\n"
            f"Today successful: {today_stats['success']}\n"
            f"Today failed: {today_stats['failed']}\n"
            f"Yesterday: {yesterday_stats.get('success', 0)}\n"
            f"TikTok downloads: {stats.get('platforms', {}).get('tiktok', 0)}\n"
            f"Instagram downloads: {stats.get('platforms', {}).get('instagram', 0)}\n"
            f"Total users: {len(user_data['users'])}\n"
            f"Active users (7d): {active_users}\n"
            f"Premium users: {len(user_data.get('premium', []))}\n"
            f"Banned users: {len(user_data['banned'])}"
        )
        
        await callback.message.answer(stats_text)
    
    elif callback.data == "users":
        # Sort users by recent activity
        sorted_users = sorted(
            user_data["users"].items(),
            key=lambda x: datetime.strptime(x[1].get("last_activity", "2000-01-01"), "%Y-%m-%d %H:%M:%S"),
            reverse=True
        )
        
        user_list = "👥 Recent active users:\n\n"
        for uid, udata in sorted_users[:10]:
            username = udata.get("username", "No username")
            first_name = udata.get("first_name", "Unknown")
            last_activity = udata.get("last_activity", "Unknown")
            downloads = stats.get("users", {}).get(uid, {}).get("downloads", 0)
            premium = "⭐️ " if uid in user_data.get("premium", []) else ""
            user_list += f"ID: {uid}\nName: {first_name}\nUsername: @{username}\nLast active: {last_activity}\nDownloads: {downloads}\n{premium}\n\n"
        
        await callback.message.answer(user_list)
    
    elif callback.data == "ban":
        await callback.message.answer("Reply to this message with the user ID to ban:")
        
    elif callback.data == "unban":
        if not user_data["banned"]:
            return await callback.message.answer("No banned users")
        
        unban_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=uid, callback_data=f"unban_{uid}")] 
            for uid in user_data["banned"][:10]  # Show only first 10 to avoid button limits
        ])
        
        await callback.message.answer("Select user to unban:", reply_markup=unban_keyboard)
    
    elif callback.data.startswith("unban_"):
        uid = callback.data.split("_")[1]
        if uid in user_data["banned"]:
            user_data["banned"].remove(uid)
            save_data()
            await callback.message.answer(f"User {uid} has been unbanned")
        else:
            await callback.message.answer(f"User {uid} is not banned")
    
    elif callback.data == "add_premium":
        await callback.message.answer("Reply to this message with the user ID to add premium:")
    
    elif callback.data == "broadcast":
        await callback.message.answer("Reply to this message with the broadcast text:")
    
    elif callback.data == "backup":
        # Create backup file
        backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_data = {"user_data": user_data, "stats": stats}
        backup_file = f"backup_{backup_time}.json"
        
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4, ensure_ascii=False)
            
        # Send backup to admin
        if os.path.exists(backup_file):
            await callback.message.answer_document(
                types.FSInputFile(backup_file),
                caption=f"Backup {backup_time}"
            )
            os.remove(backup_file)
    
    await callback.answer()

@dp.message()
async def handle_message(message: types.Message):
    user_id = str(message.from_user.id)
    lang_map = {
        "🇼🇲 Հայերեն": "hy",
        "🇬🇧 English": "en",
        "🇷🇺 Русский": "ru"
    }
    
    # Update last activity
    if user_id in user_data["users"]:
        user_data["users"][user_id]["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data()
    
    # Admin broadcast function
    if message.reply_to_message and user_id == ADMIN_ID and message.reply_to_message.text == "Reply to this message with the broadcast text:":
        broadcast_text = message.text
        sent_count = 0
        fail_count = 0
        
        await message.answer("Starting broadcast...")
        
        for uid in user_data["users"]:
            try:
                lang = user_data["users"][uid].get("language", "ru")
                await bot.send_message(uid, broadcast_text)
                sent_count += 1
                await asyncio.sleep(0.05)  # To avoid hitting rate limits
            except Exception as e:
                fail_count += 1
                logging.error(f"Failed to send broadcast to {uid}: {e}")
        
        return await message.answer(f"Broadcast completed. Sent: {sent_count}, Failed: {fail_count}")
    
    # Admin ban function
    if message.reply_to_message and user_id == ADMIN_ID and message.reply_to_message.text == "Reply to this message with the user ID to ban:":
        ban_id = message.text.strip()
        if ban_id in user_data["users"] and ban_id not in user_data["banned"]:
            user_data["banned"].append(ban_id)
            save_data()
            return await message.answer(f"User {ban_id} has been banned")
        else:
            return await message.answer(f"User {ban_id} not found or already banned")
    
    # Admin add premium function
    if message.reply_to_message and user_id == ADMIN_ID and message.reply_to_message.text == "Reply to this message with the user ID to add premium:":
        premium_id = message.text.strip()
        if premium_id in user_data["users"]:
            if "premium" not in user_data:
                user_data["premium"] = []
            
            if premium_id not in user_data["premium"]:
                user_data["premium"].append(premium_id)
                save_data()
                return await message.answer(f"User {premium_id} now has premium access")
            else:
                user_data["premium"].remove(premium_id)
                save_data()
                return await message.answer(f"Premium removed from user {premium_id}")
        else:
            return await message.answer(f"User {premium_id} not found")
    
    # Check if user is banned
    if user_id in user_data["banned"]:
        lang = user_data["users"].get(user_id, {}).get("language", "ru")
        return await message.answer(translations[lang]["banned"])
    
    # Language selection
    if message.text in lang_map:
        user_data["users"][user_id]["language"] = lang_map[message.text]
        save_data()
        is_premium = user_id in user_data.get("premium", [])
        await message.answer(
            translations[lang_map[message.text]]["saved_language"], 
            reply_markup=get_menu_keyboard(lang_map[message.text], is_premium)
        )
        return
    
    # Check if user has selected a language
    if user_id not in user_data["users"] or user_data["users"][user_id]["language"] is None:
        await message.answer(translations["ru"]["choose_language"], reply_markup=lang_keyboard)
        return
    
    lang = user_data["users"].get(user_id, {}).get("language", "ru")
    is_premium = user_id in user_data.get("premium", [])
    
    # Help button handler
    if message.text in help_texts:
        lang = help_texts[message.text]
        return await message.answer(translations[lang]["help"])
    
    # Change language button handler
    if message.text in change_lang_texts:
        return await message.answer(translations[change_lang_texts[message.text]]["change_language"], 
                                  reply_markup=lang_keyboard)
    
    # Premium info handler
    if message.text in premium_texts:
        admin_contact = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(
                text=translations[lang]["contact_admin"], 
                url=f"https://t.me/{ADMIN_USERNAME}" +f"?start=admin_{user_id}"   
            )]]
        )
        return await message.answer(translations[lang]["premium_info"], reply_markup=admin_contact)
    
    # URL detection and processing
    if re.search(r'(tiktok\.com|instagram\.com)', message.text):
        url = message.text.strip()
        platform = get_platform(url)
        
        # Check rate limits for non-premium users
        if await is_rate_limited(user_id) and not is_premium:
            return await message.answer(translations[lang]["rate_limit"])
        
        await message.answer(translations[lang]["downloading"])
        
        output_file = f"{TEMP_DIR}/{user_id}_{int(datetime.now().timestamp())}.mp4"
        
        # Different options for premium vs regular users
        if is_premium:
            ydl_opts = {
                'format': 'best',
                'outtmpl': output_file,
                'quiet': True,
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }]
            }
        else:
            ydl_opts = {
                'format': 'best[filesize<15M]',  # Limit size for non-premium
                'outtmpl': output_file,
                'quiet': True,
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }]
            }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                await message.answer_video(types.FSInputFile(output_file))
                update_stats(user_id, success=True, platform=platform)
            else:
                await message.answer(translations[lang]["download_error"])
                update_stats(user_id, success=False)
        except Exception as e:
            await message.answer(translations[lang]["download_error"])
            update_stats(user_id, success=False)
            logging.error(f"Download error for user {user_id}: {e}")
        finally:
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except Exception as e:
                    logging.error(f"Error removing file {output_file}: {e}")
    else:
        # Not a valid URL
        await message.answer(translations[lang]["unsupported_link"], 
                          reply_markup=get_menu_keyboard(lang, is_premium))

async def periodic_tasks():
    while True:
        try:
            # Clean old files every hour
            clean_old_files()
            
            # Create backup daily
            await backup_data()
            
            # Wait for next check
            await asyncio.sleep(3600)  # 1 hour
        except Exception as e:
            logging.error(f"Error in periodic tasks: {e}")
            await asyncio.sleep(60)  # Wait a minute and try again

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f"{LOG_DIR}/bot_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler()
        ]
    )
    
    # Start periodic tasks
    asyncio.create_task(periodic_tasks())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
