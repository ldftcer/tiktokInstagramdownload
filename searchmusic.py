import os
import os
import telebot
from telebot import types
import yt_dlp
import re
from concurrent.futures import ThreadPoolExecutor
import time
import logging
from functools import lru_cache
import asyncio
import shutil
import threading
import psutil
import hashlib
from collections import OrderedDict

# Настройка логирования с цветным форматированием
logging.basicConfig(
    format='\033[92m%(asctime)s\033[0m - \033[94m%(name)s\033[0m - \033[93m%(levelname)s\033[0m - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = '7939631781:AAFaHutampCPWQpXktRNOSUVxvlLcezcA4U'
OWNER_ID = 5743254515
BANNED_USERS_FILE = 'banned_users.txt'
DOWNLOAD_FOLDER = 'downloads'
CACHE_FOLDER = 'music_cache'
MAX_WORKERS = 20
CACHE_SIZE = 250
MAX_FILE_AGE = 86400  # Хранение файлов 24 часа
CHUNK_SIZE = 8192
MAX_CACHE_SIZE_MB = 5000  # Максимальный размер кэша (5 ГБ)

# Создаем необходимые папки
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(CACHE_FOLDER, exist_ok=True)

# Инициализация бота и сервисов
bot = telebot.TeleBot(TOKEN, threaded=True)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Оптимизированное хранение
search_cache = {}
active_downloads = {}  # Теперь это словарь: {video_id: [user_ids]}
file_cache = OrderedDict()  # Кэш файлов: {video_id: (filename, title, timestamp)}
memory_monitor_active = False

# Загрузка списка заблокированных пользователей
banned_users = set()
try:
    if os.path.exists(BANNED_USERS_FILE):
        with open(BANNED_USERS_FILE, 'r') as file:
            banned_users = set(line.strip() for line in file)
except Exception as e:
    logger.error(f"Ошибка при загрузке списка заблокированных пользователей: {e}")

def add_banned_user(user_id):
    banned_users.add(str(user_id))
    try:
        with open(BANNED_USERS_FILE, 'a') as file:
            file.write(f"{user_id}\n")
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя {user_id} в черный список: {e}")
        return False

def remove_banned_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in banned_users:
        banned_users.remove(user_id_str)
        try:
            with open(BANNED_USERS_FILE, 'w') as file:
                file.writelines(f"{uid}\n" for uid in banned_users)
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id} из черного списка: {e}")
    return False

# Генерация уникального ID для кэширования
def get_video_cache_id(video_id):
    return hashlib.md5(video_id.encode()).hexdigest()

# Проверка наличия файла в кэше
def check_cache(video_id):
    cache_id = get_video_cache_id(video_id)
    if cache_id in file_cache:
        filepath, title, _ = file_cache[cache_id]
        if os.path.exists(filepath):
            # Обновляем timestamp и перемещаем в конец OrderedDict
            file_cache.move_to_end(cache_id)
            file_cache[cache_id] = (filepath, title, time.time())
            return filepath, title
    return None, None

# Добавление файла в кэш
def add_to_cache(video_id, filepath, title):
    cache_id = get_video_cache_id(video_id)
    file_cache[cache_id] = (filepath, title, time.time())
    # Если кэш слишком большой, удаляем старые файлы
    cleanup_cache()

# Очистка кэша по размеру
def cleanup_cache():
    total_size = 0
    for cache_id, (filepath, _, _) in list(file_cache.items()):
        if os.path.exists(filepath):
            total_size += os.path.getsize(filepath) / (1024 * 1024)  # МБ
    
    # Удаляем старые файлы если превышен лимит
    if total_size > MAX_CACHE_SIZE_MB:
        while total_size > MAX_CACHE_SIZE_MB * 0.8 and file_cache:  # Оставляем 80%
            cache_id, (filepath, _, _) = file_cache.popitem(last=False)
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath) / (1024 * 1024)
                os.remove(filepath)
                total_size -= file_size
                logger.info(f"Удален старый кэшированный файл: {filepath}, освобождено {file_size:.2f} МБ")

@lru_cache(maxsize=CACHE_SIZE)
def search_youtube(query):
    query_hash = hash(query)
    current_time = time.time()
    
    if query_hash in search_cache:
        cache_time, results = search_cache[query_hash]
        if current_time - cache_time < 3600:
            return results
    
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'extract_flat': True,
        'skip_download': True,
        'format': 'bestaudio',
        'youtube_include_dash_manifest': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            if result and 'entries' in result:
                entries = result['entries']
                filtered_results = []
                
                for entry in entries:
                    if entry and ('url' in entry or 'id' in entry):
                        for key in list(entry.keys()):
                            if key not in ['id', 'url', 'title', 'duration']:
                                entry.pop(key, None)
                        filtered_results.append(entry)
                
                search_cache[query_hash] = (current_time, filtered_results)
                return filtered_results
    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
    
    return []

# Улучшенная загрузка аудио с поддержкой кэширования
async def download_audio_async(video_id, user_id, status_message_id, chat_id, progress_callback=None):
    # Проверяем кэш сначала
    cached_file, cached_title = check_cache(video_id)
    if cached_file:
        logger.info(f"Файл найден в кэше: {cached_file}")
        return cached_file, cached_title, True
    
    # Если уже загружается, добавляем пользователя в очередь
    if video_id in active_downloads:
        active_downloads[video_id].append((user_id, status_message_id, chat_id))
        return None, "В процессе загрузки другими пользователями", False
    
    active_downloads[video_id] = [(user_id, status_message_id, chat_id)]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    cache_id = get_video_cache_id(video_id)
    output_template = f'{CACHE_FOLDER}/{cache_id}.%(ext)s'
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'progress_hooks': [progress_callback] if progress_callback else None,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            title = info_dict.get('title', 'Unknown')
            filename = ydl.prepare_filename(info_dict).rsplit('.', 1)[0] + '.mp3'
            
            # Оптимизация размера файла
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                if file_size > 45 * 1024 * 1024:  # Если больше 45 МБ
                    new_filename = filename.replace('.mp3', '_opt.mp3')
                    os.system(f'ffmpeg -i "{filename}" -codec:a libmp3lame -qscale:a 6 "{new_filename}" -y')
                    if os.path.exists(new_filename):
                        os.remove(filename)
                        filename = new_filename
                
            # Добавляем в кэш
            add_to_cache(video_id, filename, title)
            return filename, title, False
    except Exception as e:
        logger.error(f"Ошибка при загрузке: {e}")
        return None, None, False
    finally:
        # Очищаем очередь загрузки
        if video_id in active_downloads:
            del active_downloads[video_id]

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Դուք չունեք այս հրամանը կատարելու իրավունք։")
        return

    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "⚠️ Օգտագործում: /ban {օգտատիրոջ ID կամ @username}")
        return

    identifier = args[1]
    if identifier.isdigit():
        if add_banned_user(identifier):
            bot.reply_to(message, f"✅ Օգտատերը ID {identifier} արգելափակված է։")
            try:
                bot.send_message(int(identifier), "❌ Դուք արգելափակված եք բոտում։")
            except Exception:
                pass
        else:
            bot.reply_to(message, "❌ Սխալ օգտատիրոջը արգելափակելիս։")
    else:
        bot.reply_to(message, "❌ Սխալ ֆորմատ։ Օգտագործեք ID։")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Դուք չունեք այս հրամանը կատարելու իրավունք։")
        return

    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "⚠️ Օգտագործում: /unban {օգտատիրոջ ID}")
        return

    user_id = args[1]
    if not user_id.isdigit():
        bot.reply_to(message, "❌ Սխալ ID։")
        return

    if remove_banned_user(user_id):
        bot.reply_to(message, f"✅ Օգտատերը ID {user_id} ապաբլոկավորված է։")
        try:
            bot.send_message(int(user_id), "✅ Դուք ապաբլոկավորված եք բոտում։")
        except Exception:
            pass
    else:
        bot.reply_to(message, "❌ Սխալ օգտատիրոջը ապաբլոկավորելիս։")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if str(message.from_user.id) in banned_users:
        bot.reply_to(message, "❌ Դուք արգելափակված եք և չեք կարող օգտվել բոտից։")
        return
        
    welcome_text = (
        "✨ *•.¸♫•¸.•* ✨ *•.¸♫•¸.•* ✨\n\n"
        "🎧 **Բարի գալուստ Melody Bot!**\n\n"
        "🎵 Ես կարող եմ:\n"
        "🔍 *Գտնել* երգեր YouTube-ում\n"
        "📩 *Ուղարկել* MP3 ֆորմատով\n"
        "⚡ *Արագ* աշխատել բազմաթիվ օգտատերերի հետ\n\n"
        "📝 *Օգտագործումը պարզ է:*\n"
        "• Ուղարկիր երգի անունը\n"
        "• Ընտրիր արդյունքներից\n"
        "• Ստացիր MP3 ֆայլը\n\n"
        "💡 *Օրինակ:* `Miyagi I Got Love`\n\n"
        "📌 Օգնության համար սեղմեք /help\n\n"
        "✨ *•.¸♫•¸.•* ✨ *•.¸♫•¸.•* ✨"
    )
    
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def send_help(message):
    if str(message.from_user.id) in banned_users:
        bot.reply_to(message, "❌ Դուք արգելափակված եք և չեք կարող օգտվել բոտից։")
        return
        
    help_text = (
        "✨ ━━━━━━━━━━━━━━━━ ✨\n"
        "🔊 **Ինչպես օգտվել Melody Bot-ից**\n"
        "✨ ━━━━━━━━━━━━━━━━ ✨\n\n"
        "🎧 **Երաժշտություն որոնելու համար:**\n"
        "1️⃣ *Ուղարկեք* երգի/արտիստի անունը\n"
        "2️⃣ *Ընտրեք* առաջարկվող արդյունքներից\n"
        "3️⃣ *Սպասեք* MP3 ձևափոխման ավարտին\n"
        "4️⃣ *Ստացեք* երգը և վայելեք այն!\n\n"
        "⚡ **Հուշումներ:**\n"
        "• *Արագ ներբեռնում* - եթե երգը արդեն ներբեռնվել է\n"
        "• *Պահպանում* - երգերը պահվում են 24 ժամ\n"
        "• *Կարիք չկա կրկնակի ներբեռնել* նույն երգը\n\n"
        "🔔 **Առաջարկներ կամ խնդիրներ?**\n"
        "📩 Դիմեք: @ldftcer\n\n"
        "✨ ━━━━━━━━━━━━━━━━ ✨"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_query(message):
    if str(message.from_user.id) in banned_users:
        bot.reply_to(message, "❌ Դուք արգելափակված եք և չեք կարող օգտվել բոտից։")
        return

    query = message.text
    processing_msg = bot.send_message(
        message.chat.id,
        f"🔍 *Որոնում եմ:* `{query}`\n\n"
        "⏳ Խնդրում եմ սպասել...\n"
        "╱✨╲╱✨╲╱✨╲╱✨╲╱✨╲╱✨╲",
        parse_mode="Markdown"
    )
    
    def search_and_respond():
        try:
            results = search_youtube(query)
            
            if not results:
                bot.edit_message_text(
                    "😔 *Երգը չգտնվեց*\n\n"
                    "╱✨╲╱✨╲╱✨╲╱✨╲╱✨╲╱✨╲\n\n"
                    "• Փորձեք փոխել որոնման տեքստը\n"
                    "• Ավելացրեք արտիստի անունը\n"
                    "• Փորձեք անգլերեն", 
                    message.chat.id, 
                    processing_msg.message_id,
                    parse_mode="Markdown"
                )
                return
            
            results = results[:5]
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            for result in results:
                if 'url' in result or 'id' in result:
                    title = re.sub(r'\[.*?\]', '', result.get('title', 'No Title'))
                    duration = result.get('duration', 0)

                    if duration:
                        minutes = int(duration) // 60
                        seconds = int(duration) % 60
                        duration_str = f" ({minutes}:{seconds:02d})"
                    else:
                        duration_str = ""

                    video_id = result['id'] if 'id' in result else str(hash(result['url']) % 10**12)
                    button_text = f"🎵 {title}{duration_str}"
                    callback_data = f"dl_{video_id}"

                    button = types.InlineKeyboardButton(text=button_text, callback_data=callback_data)
                    markup.add(button)
            
            bot.edit_message_text(
                f"✨ *Որոնման արդյունքները* ✨\n\n"
                f"Հարցում: `{query}`\n\n"
                f"🎧 Ընտրեք երգը ստորև ⬇️", 
                message.chat.id, 
                processing_msg.message_id, 
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}")
            bot.edit_message_text(
                "❌ Տեղի է ունեցել սխալ։\n"
                "Խնդրում եմ փորձեք կրկին։", 
                message.chat.id, 
                processing_msg.message_id
            )
    
    executor.submit(search_and_respond)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if str(call.from_user.id) in banned_users:
        bot.answer_callback_query(call.id, "❌ Դուք արգելափակված եք։")
        return
    
    callback_data = call.data
    
    if callback_data.startswith("search_"):
        bot.answer_callback_query(call.id, "🔍 Նոր որոնում...")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id, 
            "🔍 Գրեք նոր հարցում երաժշտություն որոնելու համար։"
        )
        return
        
    bot.answer_callback_query(call.id, "⏳ Սկսում եմ... խնդրում եմ սպասել...")
    
    video_id = callback_data.replace("dl_", "")
    
    loading_icons = ["⏳", "⌛", "⏳", "⌛"]
    current_icon_index = 0
    
    status_message = bot.edit_message_text(
        f"{loading_icons[0]} **Ներբեռնում եմ երգը...**\n\n"
        "╭────────────────╮\n"
        "│▓▓▓             │ 20%\n"
        "╰────────────────╯",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    progress_updates = {}
    
    def update_progress():
        nonlocal current_icon_index
        cached_file, _ = check_cache(video_id)
        
        if cached_file:
            try:
                bot.edit_message_text(
                    f"⚡ **Ерг знайдено в кеші!**\n\n"
                    f"╭────────────────╮\n"
                    f"│▓▓▓▓▓▓▓▓▓▓      │ 90%\n"
                    f"╰────────────────╯",
                    call.message.chat.id,
                    status_message.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return
            
        while video_id in active_downloads:
            current_icon_index = (current_icon_index + 1) % len(loading_icons)
            icon = loading_icons[current_icon_index]
            
            progress = progress_updates.get(video_id, 20)
            progress_bar = "▓" * int(progress/10) + " " * (10 - int(progress/10))
            
            try:
                bot.edit_message_text(
                    f"{icon} **Ներբեռնում եմ երգը...**\n\n"
                    f"╭────────────────╮\n"
                    f"│{progress_bar}│ {progress}%\n"
                    f"╰────────────────╯",
                    call.message.chat.id,
                    status_message.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
                
            time.sleep(0.8)
    
    def progress_hook(d):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes', d.get('total_bytes_estimate', 0))
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int(downloaded / total * 100)
                    progress_updates[video_id] = progress
            except Exception:
                pass
    
    def download_and_send():
        progress_thread = threading.Thread(target=update_progress)
        progress_thread.daemon = True
        progress_thread.start()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audio_file, title, from_cache = loop.run_until_complete(
                download_audio_async(video_id, call.from_user.id, status_message.message_id, call.message.chat.id, progress_hook))
            loop.close()
            
            if audio_file and os.path.exists(audio_file):
                if not from_cache:
                    bot.edit_message_text(
                        "✅ **Երգը պատրաստ է! Ուղարկում եմ...**\n\n"
                        "╭────────────────╮\n"
                        "│▓▓▓▓▓▓▓▓▓▓      │ 90%\n"
                        "╰────────────────╯", 
                        call.message.chat.id, 
                        status_message.message_id, 
                        parse_mode="Markdown"
                    )
                
                try:
                    with open(audio_file, 'rb') as audio:
                        caption = "✨ Ներբեռնվել է @melodyi_bot | Հաճելի ունկնդրում! 🎧"
                        if from_cache:
                            caption = "⚡️ " + caption 
                            
                        bot.send_audio(
                            call.message.chat.id, 
                            audio, 
                            title=title,
                            performer="Music Bot",
                            caption=caption
                        )
                    
                    bot.edit_message_text(
                        "✨ Ընտրեք երգը ստորև 👇\n"
                        "Կամ սկսեք նոր որոնում․",
                        call.message.chat.id,
                        status_message.message_id,
                        reply_markup=call.message.reply_markup
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке файла: {e}")
                    bot.edit_message_text(
                        "❌ Չհաջողվեց ուղարկել երգը։ Խնդրում եմ փորձեք կրկին։",
                        call.message.chat.id,
                        status_message.message_id
                    )
            else:
                bot.edit_message_text(
                    "❌ Չհաջողվեց ներբեռնել երգը։ Խնդրում եմ փորձեք կրկին։",
                    call.message.chat.id,
                    status_message.message_id
                )
        except Exception as e:
            logger.error(f"Ошибка при загрузке: {e}")
            bot.edit_message_text(
                "❌ Տեղի է ունեցել սխալ։ Խնդրում եմ փորձեք կրկին։",
                call.message.chat.id,
                status_message.message_id
            )
    
    executor.submit(download_and_send)

def monitor_memory_usage():
    global memory_monitor_active
    
    if memory_monitor_active:
        return
        
    memory_monitor_active = True
    
    while True:
        try:
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 / 1024
            
            if memory_usage > 500:
                search_cache.clear()
                cleanup_cache()
                logger.info(f"Выполнена очистка памяти. Было: {memory_usage:.2f} МБ")
        except Exception as e:
            logger.error(f"Ошибка в мониторинге памяти: {e}")
            
        time.sleep(300)

if __name__ == "__main__":
    try:
        memory_thread = threading.Thread(target=monitor_memory_usage)
        memory_thread.daemon = True
        memory_thread.start()
        
        logger.info("\n" + "✨"*20)
        logger.info("🎶 Բոտը հաջողությամբ գործարկված է! Վայելեք երաժշտությունը!")
        logger.info("✨"*20 + "\n")
        
        bot.polling(none_stop=True, timeout=90, interval=0.2)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        cleanup_cache()
        executor.shutdown(wait=False)
