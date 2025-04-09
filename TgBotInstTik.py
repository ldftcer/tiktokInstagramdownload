import json
import logging
import os
import asyncio
import re
import time
import shutil
import hashlib
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
import yt_dlp

# Конфигурация
TOKEN = "7531357371:AAFCcim-k6PuxYNMWOLHn4_Ss7JYgq9wBn8"
ADMIN_ID = "5743254515"
ADMIN_USERNAME = "ldftcer"
BACKUP_CHAT_ID = "-100123456789"

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Константы
DATA_FILE = "user_data.json"
STATS_FILE = "stats.json"
TEMP_DIR = "downloads"
LOG_DIR = "logs"
CACHE_DIR = "cache"
MAX_CACHE_SIZE = 500 * 1024 * 1024  # 500MB
DOWNLOAD_EXECUTOR = ThreadPoolExecutor(4)  # Параллельные загрузки

# Создание директорий
for dir_path in [TEMP_DIR, LOG_DIR, CACHE_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Загрузка данных
def load_json(file_path, default):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in {file_path}, using default")
    return default.copy()

user_data = load_json(DATA_FILE, {"users": {}, "banned": [], "premium": []})
stats = load_json(STATS_FILE, {"total_downloads": 0, "daily": {}, "users": {}, "platforms": {"tiktok": 0, "instagram": 0}})

# Улучшенное сохранение данных
def save_json(file_path, data, backup=True):
    try:
        if backup and os.path.exists(file_path):
            shutil.copy2(file_path, f"{file_path}.bak")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving {file_path}: {e}")

def save_data():
    save_json(DATA_FILE, user_data)

def save_stats():
    save_json(STATS_FILE, stats)

# Управление кешем
def clean_cache():
    try:
        cache_files = []
        total_size = 0
        
        for filename in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, filename)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                cache_files.append((file_path, os.path.getmtime(file_path), file_size))
                total_size += file_size
        
        if total_size > MAX_CACHE_SIZE:
            cache_files.sort(key=lambda x: x[1])  # Сортировка по времени изменения
            while total_size > MAX_CACHE_SIZE * 0.9 and cache_files:  # Оставляем 90% лимита
                oldest_file, _, size = cache_files.pop(0)
                try:
                    os.remove(oldest_file)
                    total_size -= size
                except Exception as e:
                    logging.error(f"Error removing cache file {oldest_file}: {e}")
                    
    except Exception as e:
        logging.error(f"Error in clean_cache: {e}")

# Улучшенная загрузка видео
async def download_video(url: str, user_id: str, is_premium: bool) -> tuple:
    """Возвращает (file_path, platform, error)"""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cached_file = os.path.join(CACHE_DIR, f"{url_hash}.mp4")
    platform = get_platform(url)
    
    # Проверка кеша
    if os.path.exists(cached_file):
        file_size = os.path.getsize(cached_file)
        if file_size > 0:
            output_file = os.path.join(TEMP_DIR, f"{user_id}_{int(time.time())}.mp4"
            shutil.copy2(cached_file, output_file)
            return output_file, platform, None
    
    # Настройки для разных платформ
    ydl_opts = {
        'format': 'bestvideo[height<=1080]+bestaudio/best' if is_premium else 'best[filesize<20M]',
        'outtmpl': os.path.join(TEMP_DIR, f"{user_id}_%(id)s.%(ext)s"),
        'quiet': True,
        'noplaylist': True,
        'extractor_args': {
            'instagram': {'skip': ['dash']},
            'tiktok': {'force_generic_extractor': True}
        },
        'merge_output_format': 'mp4'
    }
    
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(DOWNLOAD_EXECUTOR, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        
        # Находим скачанный файл
        for f in os.listdir(TEMP_DIR):
            if f.startswith(f"{user_id}_"):
                output_file = os.path.join(TEMP_DIR, f)
                if os.path.getsize(output_file) > 0:
                    # Сохраняем в кеш
                    shutil.copy2(output_file, cached_file)
                    clean_cache()
                    return output_file, platform, None
                
        return None, platform, "Downloaded file not found"
    except yt_dlp.DownloadError as e:
        logging.error(f"Download error: {e}")
        return None, platform, str(e)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None, platform, "Internal error"

# Остальные функции (handle_message, admin_command и т.д.) остаются аналогичными,
# но используют новую систему загрузки

async def main():
    """Улучшенная инициализация"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log")),
            logging.StreamHandler()
        ]
    )
    
    # Запуск фоновых задач
    asyncio.create_task(periodic_tasks())
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Очистка при завершении
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                os.remove(file_path)
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
