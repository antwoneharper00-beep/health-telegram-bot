import os
import re
import asyncio
import threading
import requests
import base64

from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters


BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL")

LOCAL_TZ = ZoneInfo("America/New_York")
TELEGRAM_WEBHOOK_PATH = "/telegram"
TELEGRAM_WEBHOOK_URL = PUBLIC_URL + TELEGRAM_WEBHOOK_PATH

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
bot_loop = asyncio.new_event_loop()
flask_app = Flask(__name__)


def parse_time_from_message(text):
    lower = text.lower()
    now = datetime.now(LOCAL_TZ)

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", lower)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        now = now.replace(year=year, month=month, day=day)

    t = re.search(r"(?:@|at)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)", lower)
    if t:
        hour = int(t.group(1))
        minute = int(t.group(2) or 0)
        ampm = t.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return now


def send_to_health_log(payload):
    try:
        r = requests.post(WEBHOOK_URL, json=payload, allow_redirects=True, timeout=90)
        body = r.text.strip()
        print(r.status_code, body, flush=True)
        return r.status_code in [200, 302] and body.startswith("OK"), body
    except Exception as e:
        print(str(e), flush=True)
        return False, str(e)


def build_vital(name, value, unit, notes, captured):
    return {
        "token": WEBHOOK_TOKEN,
        "type": "Vitals",
        "entry": {
            "captured_at": captured.isoformat(),
            "date": captured.strftime("%Y-%m-%d"),
            "time": captured.strftime("%-I:%M %p"),
            "name": name,
            "value": value,
            "unit": unit,
            "notes": notes,
        },
    }


def build_wound(notes, captured, photo_url="", photo_file_id="", photo_base64=""):
    lower = notes.lower()

    return {
        "token": WEBHOOK_TOKEN,
        "type": "Wound",
        "entry": {
            "captured_at": captured.isoformat(),
            "date": captured.strftime("%Y-%m-%d"),
            "time": captured.strftime("%-I:%M %p"),
            "name": "Driveline Site",
            "value": "",
            "unit": "",
            "notes": notes,
            "photo_url": photo_url,
            "photo_file_id": photo_file_id,
            "photo_base64": photo_base64,
            "drainage": "Some" if "drainage" in lower else "",
            "odor": "No" if "no odor" in lower else "",
            "redness": "No" if "no redness" in lower else "",
            "swelling": "No" if "no swelling" in lower else "",
            "pain": "",
            "status": "",
        },
    }


async def start(update, context):
    await update.message.reply_text("Health bot is online ✅")


async def reimburse(update, context):
    await update.message.reply_text(
        "Reimbursement commands:\n\n"
        "/newclaim TR-0006\n"
        "/receipt TR-0006 gas 42.18 Sheetz\n\n"
        "For receipts, send a photo with the /receipt caption."
    )


async def newclaim(update, context):
    if not context.args:
        await update.message.reply_text("Use: /newclaim TR-0006")
        return

    trip_id = context.args[0].upper()

    payload = {
        "token": WEBHOOK_TOKEN,
        "type": "ReimbursementAction",
        "action": "create_claim",
        "payload": {"tripId": trip_id},
    }

    ok, msg = send_to_health_log(payload)
    await update.message.reply_text(msg if ok else f"Error: {msg}")


async def receipt(update, context):
    await update.message.reply_text(
        "Send a receipt photo with caption like:\n\n"
        "/receipt TR-0006 gas 42.18 Sheetz"
    )


async def handle_text(update, context):
    text = update.message.text.strip()
    lower = text.lower()
    captured = parse_time_from_message(text)
    notes = "Logged from Telegram"

    bp = re.search(r"(\d{2,3})\/(\d{2,3})", text)
    if bp and ("bp" in lower or "blood pressure" in lower):
        value = f"{bp.group(1)}/{bp.group(2)}"
        ok, msg = send_to_health_log(build_vital("Blood Pressure", value, "mmHg", notes, captured))
        await update.message.reply_text(f"✅ Logged BP {value}" if ok else msg)
        return

    if "sugar" in lower or "blood sugar" in lower:
        m = re.search(r"(\d+)", lower)
        if m:
            value = m.group(1)
            ok, msg = send_to_health_log(build_vital("Blood Sugar", value, "mg/dL", notes, captured))
            await update.message.reply_text(f"✅ Logged Sugar {value}" if ok else msg)
            return

    if "urine" in lower:
        m = re.search(r"(\d+)\s*(ml|mL)", text)
        if m:
            value = m.group(1)
            ok, msg = send_to_health_log(build_vital("Urine Output", value, "mL", notes, captured))
            await update.message.reply_text(f"✅ Logged Urine {value}mL" if ok else msg)
            return

    if "weight" in lower:
        m = re.search(r"(\d{2,3}(?:\.\d+)?)", lower)
        if m:
            value = m.group(1)
            ok, msg = send_to_health_log(build_vital("Weight", value, "lbs", notes, captured))
            await update.message.reply_text(f"✅ Logged Weight {value}" if ok else msg)
            return

    if lower in ["bm", "bowel movement", "poop"] or lower.startswith("bm ") or lower.startswith("bowel movement"):
        ok, msg = send_to_health_log(build_vital("Bowel Movement", "1", "count", text, captured))
        await update.message.reply_text("✅ Logged Bowel Movement" if ok else msg)
        return

    if lower.startswith("wound") or " wound " in lower:
        ok, msg = send_to_health_log(build_wound(text, captured))
        await update.message.reply_text("✅ Logged Wound Entry" if ok else msg)
        return

    await update.message.reply_text("I couldn't understand that entry.")


async def handle_photo(update, context):
    caption = update.message.caption or ""
    lower = caption.lower()

    photo = update.message.photo[-1]
    file_id = photo.file_id

    tg_file = await context.bot.get_file(file_id)
    photo_bytes = await tg_file.download_as_bytearray()
    photo_base64 = base64.b64encode(photo_bytes).decode("utf-8")

    if lower.startswith("/receipt"):
        parts = caption.split()

        if len(parts) < 4:
            await update.message.reply_text("Use caption: /receipt TR-0006 gas 42.18 Sheetz")
            return

        trip_id = parts[1].upper()
        category = parts[2]
        amount = parts[3]
        vendor = " ".join(parts[4:]) if len(parts) > 4 else ""

        payload = {
            "token": WEBHOOK_TOKEN,
            "type": "ReimbursementAction",
            "action": "log_receipt",
            "payload": {
                "tripId": trip_id,
                "category": category,
                "amount": amount,
                "vendor": vendor,
                "receiptDate": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
                "fileName": f"{trip_id}_{category}_{datetime.now(LOCAL_TZ).strftime('%Y%m%d_%H%M%S')}.jpg",
                "photoBase64": photo_base64,
            },
        }

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(msg if ok else f"Error: {msg}")
        return

    if not caption or not lower.startswith("wound"):
        await update.message.reply_text("Photo received, but add a wound caption starting with: Wound")
        return

    captured = parse_time_from_message(caption)

    ok, msg = send_to_health_log(
        build_wound(
            caption,
            captured,
            "",
            file_id,
            photo_base64,
        )
    )

    await update.message.reply_text("✅ Logged Wound Photo Entry" if ok else msg)


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("reimburse", reimburse))
telegram_app.add_handler(CommandHandler("newclaim", newclaim))
telegram_app.add_handler(CommandHandler("receipt", receipt))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


def run_bot():
    asyncio.set_event_loop(bot_loop)

    async def startup():
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.bot.delete_webhook(drop_pending_updates=True)
        await telegram_app.bot.set_webhook(url=TELEGRAM_WEBHOOK_URL, drop_pending_updates=True)
        info = await telegram_app.bot.get_webhook_info()
        print(info, flush=True)

    bot_loop.run_until_complete(startup())
    bot_loop.run_forever()


threading.Thread(target=run_bot, daemon=True).start()


@flask_app.route("/")
def home():
    return "Health Bot Running"


@flask_app.route("/ping")
def ping():
    return "pong"


@flask_app.route("/telegram", methods=["POST"])
def telegram():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, telegram_app.bot)
        future = asyncio.run_coroutine_threadsafe(telegram_app.process_update(update), bot_loop)
        future.result(timeout=60)
        return "OK", 200
    except Exception as e:
        print(str(e), flush=True)
        return "ERROR", 500


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
