import json
import logging
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
import yt_dlp

TKEN = "7531357371:AAFCcim-k6PuxYNMWOLHn4_Ss7JYgq9wBn8"
ADMIN_ID = "5743254515"

bot = Bot(token=TOKEN)
dp = Dispatcher()

DATA_FILE = "user_data.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        user_data = json.load(f)
else:
    user_data = {"users": {}, "banned": []}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, indent=4, ensure_ascii=False)

lang_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇼🇲 Հայերեն")],
        [KeyboardButton(text="🇬🇧 English")],
        [KeyboardButton(text="🇷🇺 Русский")]
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
    },
    "en": {
        "choose_language": "Choose language:",
        "saved_language": "Language saved! Now send a video link.",
        "send_link": "Send a video link from TikTok or Instagram.",
        "downloading": "⏳ Please wait...",
        "download_error": "❌ Error downloading video.",
        "banned": "⛔ You are banned from this bot.",
    },
    "ru": {
        "choose_language": "Выберите язык:",
        "saved_language": "Язык сохранён! Теперь отправьте ссылку на видео.",
        "send_link": "Отправьте ссылку на видео из TikTok или Instagram.",
        "downloading": "⏳ Подождите несколько секунд...",
        "download_error": "❌ Ошибка при скачивании видео.",
        "banned": "⛔ Вы заблокированы в этом боте.",
    }
}

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id in user_data["banned"]:
        return await message.answer(translations["ru"]["banned"])
    
    if user_id not in user_data["users"]:
        user_data["users"][user_id] = {"language": None}
        save_data()
        await message.answer(translations["ru"]["choose_language"], reply_markup=lang_keyboard)
    else:
        lang = user_data["users"].get(user_id, {}).get("language", "ru")
        await message.answer(translations[lang]["send_link"])

@dp.message()
async def handle_message(message: types.Message):
    user_id = str(message.from_user.id)
    lang_map = {
        "🇼🇲 Հայերեն": "hy",
        "🇬🇧 English": "en",
        "🇷🇺 Русский": "ru"
    }
    
    # Проверка, если пользователь выбрал язык
    if message.text in lang_map:
        user_data["users"][user_id]["language"] = lang_map[message.text]
        save_data()
        await message.answer(translations[lang_map[message.text]]["saved_language"])
        return  
    
    if user_id not in user_data["users"] or user_data["users"][user_id]["language"] is None:
        await message.answer(translations["ru"]["choose_language"], reply_markup=lang_keyboard)
        return
    
    lang = user_data["users"].get(user_id, {}).get("language", "ru")
    
    if "tiktok.com" in message.text or "instagram.com" in message.text:
        if user_id in user_data["banned"]:
            return await message.answer(translations[lang]["banned"])
        
        url = message.text
        await message.answer(translations[lang]["downloading"])
        
        output_file = f"downloads/{user_id}.mp4"
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
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            await message.answer_video(types.FSInputFile(output_file))
            os.remove(output_file)
        except Exception as e:
            await message.answer(translations[lang]["download_error"])
            logging.error(e)

async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
