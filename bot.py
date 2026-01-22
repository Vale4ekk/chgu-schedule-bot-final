import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, Text
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://your-bot.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

MY_SUBGROUP = 2
SCHEDULE_URL = "https://tt.chuvsu.ru/index/grouptt/gr/7681"

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
        [KeyboardButton(text="🗓 Неделя")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

def is_even_week() -> bool:
    week_number = datetime.now().isocalendar()[1]
    return week_number % 2 == 0

def parse_schedule(html: str) -> Dict[str, List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    days = {}

    day_headers = soup.find_all("h3")
    for header in day_headers:
        day_name = header.get_text(strip=True).rstrip(':')
        if day_name not in WEEKDAYS_RU:
            continue

        table = header.find_next("table")
        if not table:
            continue

        lessons = []
        rows = table.find_all("tr")[1:]

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            time_cell = cells[0].get_text(strip=True)
            subject_cell = cells[1].get_text(strip=True)

            if not subject_cell or subject_cell == "—":
                continue

            is_even_marker = "**" in subject_cell
            is_odd_marker = "*" in subject_cell and not is_even_marker

            clean_text = subject_cell.replace("**", "").replace("*", "").strip()
            lines = [line.strip() for line in clean_text.split("\n") if line.strip()]

            my_lesson = None
            for line in lines:
                if f"({MY_SUBGROUP})" in line:
                    my_lesson = line.split(")", 1)[1].strip()
                    break
                elif "(" not in line and ")" not in line:
                    my_lesson = line
                    break

            if my_lesson and my_lesson != "—":
                lessons.append(f"{time_cell} — {my_lesson}")

        days[day_name] = lessons

    return days

async def fetch_schedule() -> Optional[Dict[str, List[str]]]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = await client.get(SCHEDULE_URL, headers=headers)
            resp.raise_for_status()
        return parse_schedule(resp.text)
    except Exception as e:
        logging.error(f"Ошибка загрузки расписания: {e}")
        return None

def format_day_schedule(day_name: str, lessons: List[str]) -> str:
    if not lessons:
        return f"*{day_name}:*\n—\n"
    lessons_text = "\n".join(lessons)
    return f"*{day_name}:*\n{lessons_text}\n"

@router.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Привет! Я бот твоего расписания ЧГУ.\nНажми на кнопку ниже:",
        reply_markup=main_kb
    )

@router.message(Text("📅 Сегодня"))
async def today(message: Message):
    schedule = await fetch_schedule()
    if schedule is None:
        await message.answer("❌ Не удалось загрузить расписание. Попробуй позже.")
        return

    today_weekday = datetime.now().weekday()
    if today_weekday >= len(WEEKDAYS_RU):
        await message.answer("Сегодня выходной!")
        return

    day_name = WEEKDAYS_RU[today_weekday]
    lessons = schedule.get(day_name, [])
    await message.answer(format_day_schedule(day_name, lessons), parse_mode="Markdown")

@router.message(Text("📆 Завтра"))
async def tomorrow(message: Message):
    schedule = await fetch_schedule()
    if schedule is None:
        await message.answer("❌ Не удалось загрузить расписание. Попробуй позже.")
        return

    tomorrow_weekday = (datetime.now().weekday() + 1) % 7
    if tomorrow_weekday >= len(WEEKDAYS_RU):
        await message.answer("Завтра выходной!")
        return

    day_name = WEEKDAYS_RU[tomorrow_weekday]
    lessons = schedule.get(day_name, [])
    await message.answer(format_day_schedule(day_name, lessons), parse_mode="Markdown")

@router.message(Text("🗓 Неделя"))
async def week(message: Message):
    schedule = await fetch_schedule()
    if schedule is None:
        await message.answer("❌ Не удалось загрузить расписание. Попробуй позже.")
        return

    text = "📅 *Расписание на текущую неделю:*\n\n"
    for day in WEEKDAYS_RU:
        lessons = schedule.get(day, [])
        text += format_day_schedule(day, lessons)
    await message.answer(text, parse_mode="Markdown")

dp.include_router(router)

async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()

if __name__ == "__main__":
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)
    port = int(os.getenv("PORT", 8000))
    web.run_app(app, host="0.0.0.0", port=port)