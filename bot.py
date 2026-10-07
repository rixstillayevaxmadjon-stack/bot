import asyncio
import html
import io
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from google import genai
from google.genai import types

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} topilmadi. Railway Variables bo'limiga {name} ni qo'shing."
        )
    return value


TELEGRAM_BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = required_env("GEMINI_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Tashkent"))
DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or os.getenv("DATA_DIR") or "."
DB_PATH = os.getenv("DB_PATH") or str(Path(DATA_DIR) / "xarajatlar.db")

BTN_TODAY = "💸 Bugungi xarajat"
BTN_MONTH = "📆 Oylik xarajat"
BTN_YEAR = "📊 Yillik xarajat"

MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
          "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]

bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
gemini = genai.Client(api_key=GEMINI_API_KEY)

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_TODAY)],
        [KeyboardButton(text=BTN_MONTH), KeyboardButton(text=BTN_YEAR)],
    ],
    resize_keyboard=True,
)


# ============================ BAZA ============================
def ensure_db_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def db():
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.execute(
            """CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                spent_on TEXT NOT NULL,      -- YYYY-MM-DD
                amount INTEGER NOT NULL,
                category TEXT NOT NULL,
                description TEXT
            )"""
        )


def money(n) -> str:
    return f"{int(n):,}".replace(",", " ") + " so'm"


def esc(s) -> str:
    return html.escape(str(s))


# ============================ GEMINI ============================
SYSTEM_PROMPT = """Sen xarajatlarni hisoblovchi yordamchisan. Foydalanuvchi o'zbek tilida
(ba'zan rus so'zlari aralash) o'z xarajatlarini aytadi. Barcha xarajatlarni ajratib ol.

Qoidalar:
- Bugungi sana: {today} ({weekday}). "bugun", "kecha", "o'tgan dushanba" kabilarni shu sanaga nisbatan hisobla.
- Sana aytilmasa, bugungi sanani qo'y.
- amount: so'mda butun son. "50 ming" = 50000, "1 million" = 1000000, "yuz yigirma ming" = 120000.
- category faqat shulardan biri: Oziq-ovqat, Transport, Kommunal, Kiyim, Salomatlik, Ko'ngilochar, Ta'lim, Aloqa, Uy-ro'zg'or, Restoran/Kafe, Boshqa.
- description: nimaga sarflangani, juda qisqa (masalan "taksiga", "tushlikka", "benzinga").
- transcript: aytilgan gapning matni.
- Faqat JSON qaytar:
{{"transcript":"...","expenses":[{{"date":"YYYY-MM-DD","amount":15000,"category":"Transport","description":"taksiga"}}]}}
- Xarajat aytilmagan bo'lsa: "expenses": []"""


def analyze_sync(audio: bytes | None = None, text: str | None = None):
    now = datetime.now(TZ)
    weekdays = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
    system = SYSTEM_PROMPT.format(today=now.strftime("%Y-%m-%d"), weekday=weekdays[now.weekday()])

    if audio is not None:
        contents = [types.Part.from_bytes(data=audio, mime_type="audio/ogg"),
                    "Shu ovozdagi xarajatlarni ajratib ol."]
    else:
        contents = [text]

    last_err = None
    for attempt in range(3):
        try:
            resp = gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            raw = resp.text.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(raw)
            return data.get("transcript", ""), data.get("expenses", [])
        except Exception as e:
            last_err = e
            import time
            time.sleep(2)
    raise last_err


async def analyze(audio=None, text=None):
    return await asyncio.to_thread(analyze_sync, audio, text)


def clean_date(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(TZ).strftime("%Y-%m-%d")


# ============================ SAQLASH ============================
async def save_and_reply(message: Message, items: list[dict]):
    if not items:
        await message.answer("🤔 Xarajat topilmadi. Masalan: «Bugun taksiga 15 ming sarfladim» deb ayting.")
        return

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    lines, total = [], 0
    with db() as c:
        for it in items:
            amount = int(float(it["amount"]))
            if amount <= 0:
                continue
            d = clean_date(it.get("date", today))
            desc = it.get("description") or it.get("category", "Boshqa")
            c.execute(
                "INSERT INTO expenses (user_id, spent_on, amount, category, description) VALUES (?,?,?,?,?)",
                (message.from_user.id, d, amount, it.get("category", "Boshqa"), desc),
            )
            total += amount
            dt = datetime.strptime(d, "%Y-%m-%d")
            label = "Bugungi xarajat" if d == today else "Xarajat"
            lines.append(
                f"{label}: <b>{money(amount)}</b>, {esc(desc)}\n"
                f"📅 {dt:%d.%m.%Y} ({dt.year} yil)"
            )

    if not lines:
        await message.answer("🤔 Summa aniqlanmadi. Qaytadan ayting.")
        return

    text = "✅ <b>Saqlandi!</b>\n\n" + "\n\n".join(lines)
    if len(lines) > 1:
        text += f"\n\n💰 Jami: <b>{money(total)}</b>"
    await message.answer(text, reply_markup=keyboard)


# ============================ HISOBOTLAR ============================
def category_breakdown(rows) -> str:
    """rows: user xarajatlari. Kategoriya bo'yicha va nimaga ketgani bo'yicha."""
    cats = {}
    for r in rows:
        cat = cats.setdefault(r["category"], {"sum": 0, "items": {}})
        cat["sum"] += r["amount"]
        key = (r["description"] or r["category"]).strip().lower()
        cat["items"][key] = cat["items"].get(key, 0) + r["amount"]

    out = []
    for name, info in sorted(cats.items(), key=lambda x: -x[1]["sum"]):
        out.append(f"\n📁 <b>{esc(name)}</b> — {money(info['sum'])}")
        top = sorted(info["items"].items(), key=lambda x: -x[1])[:5]
        for desc, s in top:
            out.append(f"   • {esc(desc)}: {money(s)}")
    return "\n".join(out)


def fetch(user_id: int, prefix: str):
    with db() as c:
        return c.execute(
            "SELECT * FROM expenses WHERE user_id=? AND spent_on LIKE ? ORDER BY spent_on",
            (user_id, prefix + "%"),
        ).fetchall()


@dp.message(F.text == BTN_MONTH)
async def month_report(message: Message):
    now = datetime.now(TZ)
    rows = fetch(message.from_user.id, now.strftime("%Y-%m"))
    title = f"📆 <b>{MONTHS[now.month - 1]} {now.year}</b>"
    if not rows:
        await message.answer(f"{title}\n\nBu oy hali xarajat yo'q.", reply_markup=keyboard)
        return
    total = sum(r["amount"] for r in rows)
    text = f"{title}\n💰 Jami sarflangan: <b>{money(total)}</b>\n\n<b>Nimaga ishlatilgan:</b>" + category_breakdown(rows)
    await message.answer(text[:4000], reply_markup=keyboard)


@dp.message(F.text == BTN_YEAR)
async def year_report(message: Message):
    now = datetime.now(TZ)
    rows = fetch(message.from_user.id, now.strftime("%Y"))
    title = f"📊 <b>{now.year} yil</b>"
    if not rows:
        await message.answer(f"{title}\n\nBu yil hali xarajat yo'q.", reply_markup=keyboard)
        return

    total = sum(r["amount"] for r in rows)
    by_month = {}
    for r in rows:
        m = int(r["spent_on"][5:7])
        by_month[m] = by_month.get(m, 0) + r["amount"]

    month_lines = "\n".join(f"   • {MONTHS[m - 1]}: {money(s)}" for m, s in sorted(by_month.items()))
    text = (
        f"{title}\n💰 Jami sarflangan: <b>{money(total)}</b>\n\n"
        f"<b>Oylar bo'yicha:</b>\n{month_lines}\n\n"
        f"<b>Nimaga ishlatilgan:</b>" + category_breakdown(rows)
    )
    await message.answer(text[:4000], reply_markup=keyboard)


# ============================ ASOSIY ============================
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Salom! 👋 Men xarajatlaringizni hisoblovchi botman.\n\n"
        "Pastdagi tugmalardan birini tanlang.",
        reply_markup=keyboard,
    )


@dp.message(F.text == BTN_TODAY)
async def today_button(message: Message):
    await message.answer(
        "🎙 Bugungi xarajatingizni <b>ovozli xabar</b> bilan yuboring.\n\n"
        "Masalan: «Taksiga 15 ming, tushlikka 40 ming ketdi».",
        reply_markup=keyboard,
    )


@dp.message(F.voice)
async def on_voice(message: Message):
    status = await message.answer("🎧 Eshityapman va tahlil qilyapman...")
    try:
        buf = io.BytesIO()
        await bot.download(message.voice, destination=buf)
        transcript, items = await analyze(audio=buf.getvalue())
    except Exception as e:
        print("Xatolik:", repr(e))
        await status.edit_text(f"❌ Xatolik: {esc(str(e)[:300])}")
        return

    await status.delete()
    if transcript:
        await message.answer(f"📝 Eshitdim: «{esc(transcript)}»")
    await save_and_reply(message, items)


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message):
    try:
        _, items = await analyze(text=message.text)
    except Exception as e:
        print("Xatolik:", repr(e))
        await message.answer(f"❌ Xatolik: {esc(str(e)[:300])}")
        return
    await save_and_reply(message, items)


async def main():
    init_db()
    print("Bot ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
