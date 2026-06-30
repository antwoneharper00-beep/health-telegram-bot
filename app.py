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
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://health-telegram-bot-kqqk.onrender.com")

LOCAL_TZ = ZoneInfo("America/New_York")
TELEGRAM_WEBHOOK_PATH = "/telegram"
TELEGRAM_WEBHOOK_URL = PUBLIC_URL + TELEGRAM_WEBHOOK_PATH

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
bot_loop = asyncio.new_event_loop()
flask_app = Flask(__name__)


def parse_time_from_message(text):
    lower = (text or "").lower()
    now = datetime.now(LOCAL_TZ)

    date_match = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", lower)
    if date_match:
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        year = int(date_match.group(3))
        if year < 100:
            year += 2000
        now = now.replace(year=year, month=month, day=day)

    time_match = re.search(r"(?:@|at)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)", lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return now


def send_to_health_log(payload):
    try:
        response = requests.post(WEBHOOK_URL, json=payload, allow_redirects=True, timeout=90)
        body = response.text.strip()
        print("APPS SCRIPT RESPONSE:", response.status_code, body, flush=True)
        ok = response.status_code in [200, 302] and body.startswith("OK")
        return ok, body
    except Exception as error:
        print("SEND ERROR:", str(error), flush=True)
        return False, str(error)


def clean_apps_script_response(msg):
    if not msg:
        return "No response from workbook."
    cleaned = msg.strip()
    if cleaned.startswith("OK_"):
        cleaned = cleaned[3:]
    return cleaned.replace("_", " ")


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
    lower = (notes or "").lower()
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


def build_reimbursement_action(action, payload=None):
    return {
        "token": WEBHOOK_TOKEN,
        "type": "ReimbursementAction",
        "action": action,
        "payload": payload or {},
    }


async def start(update, context):
    await update.message.reply_text("Health bot is online ✅")


async def reimburse(update, context):
    await update.message.reply_text(
        "Reimbursement commands:\n\n"
        "Create trip + claim:\n"
        "Trip 6-29-26 Cath Adult / Biopsy\n\n"
        "Create trip + claim with gas:\n"
        "Trip 6-29-26 Cath Adult / Biopsy gas 42.18\n\n"
        "Add gas later:\n"
        "Gas TR-0007 42.18\n\n"
        "Attach newest receipt PDF from Drive:\n"
        "Receipt Done TR-0007 gas\n\n"
        "Check status:\n"
        "Status TR-0007\n\n"
        "Generate packet:\n"
        "Generate Packet TR-0007"
    )


async def newclaim(update, context):
    if not context.args:
        await update.message.reply_text("Use: /newclaim TR-0006")
        return

    trip_id = context.args[0].upper()
    payload = build_reimbursement_action("create_claim", {"tripId": trip_id})
    ok, msg = send_to_health_log(payload)
    await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))


async def receipt(update, context):
    await update.message.reply_text(
        "Use one of these:\n\n"
        "Receipt TR-0007 gas 42.18 https://drive.google.com/...\n\n"
        "or, after uploading PDF to Drive:\n"
        "Receipt Done TR-0007 gas"
    )


async def try_handle_reimbursement_text(update, text):
    trip_match = re.match(r"trip\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+(.+)", text, re.IGNORECASE)

    if trip_match:
        trip_date = trip_match.group(1)
        rest = trip_match.group(2).strip()

        gas_amount = ""
        gas_match = re.search(r"\bgas\s+\$?(\d+(?:\.\d{1,2})?)", rest, re.IGNORECASE)
        if gas_match:
            gas_amount = gas_match.group(1)
            rest = re.sub(r"\bgas\s+\$?\d+(?:\.\d{1,2})?", "", rest, flags=re.IGNORECASE).strip()

        destination = ""
        to_match = re.search(r"\s+to\s+(.+)$", rest, re.IGNORECASE)
        if to_match:
            destination = to_match.group(1).strip()
            rest = rest[:to_match.start()].strip()

        payload = build_reimbursement_action(
            "create_trip_and_claim",
            {
                "date": trip_date,
                "visit": rest,
                "destination": destination,
                "gasAmount": gas_amount,
                "receiptLink": "",
            },
        )

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    gas_match = re.match(r"gas\s+(TR-\d+)\s+\$?(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)

    if gas_match:
        trip_id = gas_match.group(1).upper()
        amount = gas_match.group(2)

        payload = build_reimbursement_action(
            "log_expense",
            {"tripId": trip_id, "category": "gas", "amount": amount, "vendor": "Gas"},
        )

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    receipt_link_match = re.match(
        r"receipt\s+(TR-\d+)\s+(\w+)\s+\$?(\d+(?:\.\d{1,2})?)\s+(https?://\S+)",
        text,
        re.IGNORECASE,
    )

    if receipt_link_match:
        trip_id = receipt_link_match.group(1).upper()
        category = receipt_link_match.group(2).lower()
        amount = receipt_link_match.group(3)
        drive_link = receipt_link_match.group(4)

        payload = build_reimbursement_action(
            "log_receipt",
            {
                "tripId": trip_id,
                "category": category,
                "amount": amount,
                "driveLink": drive_link,
                "vendor": "",
                "receiptDate": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
                "fileName": "Drive receipt",
            },
        )

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    receipt_done_match = re.match(r"receipt\s+done\s+(TR-\d+)(?:\s+(\w+))?", text, re.IGNORECASE)

    if receipt_done_match:
        trip_id = receipt_done_match.group(1).upper()
        category = (receipt_done_match.group(2) or "gas").lower()

        payload = build_reimbursement_action(
            "attach_latest_receipt",
            {"tripId": trip_id, "category": category},
        )

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    status_match = re.match(r"status\s+(TR-\d+)", text, re.IGNORECASE)

    if status_match:
        trip_id = status_match.group(1).upper()
        payload = build_reimbursement_action("status", {"tripId": trip_id})
        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(clean_apps_script_response(msg) if ok else ("Error: " + msg))
        return True

    packet_match = re.match(r"(?:generate\s+packet|packet)\s+(TR-\d+)", text, re.IGNORECASE)

    if packet_match:
        trip_id = packet_match.group(1).upper()
        payload = build_reimbursement_action("generate_packet", {"tripId": trip_id})
        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    claim_match = re.match(r"claim\s+(TR-\d+)", text, re.IGNORECASE)

    if claim_match:
        trip_id = claim_match.group(1).upper()
        payload = build_reimbursement_action("create_claim", {"tripId": trip_id})
        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return True

    return False


async def handle_text(update, context):
    text = update.message.text.strip()
    lower = text.lower()
    captured = parse_time_from_message(text)
    notes = "Logged from Telegram"

    if await try_handle_reimbursement_text(update, text):
        return

    bp = re.search(r"(\d{2,3})\/(\d{2,3})", text)
    if bp and ("bp" in lower or "blood pressure" in lower):
        value = f"{bp.group(1)}/{bp.group(2)}"
        ok, msg = send_to_health_log(build_vital("Blood Pressure", value, "mmHg", notes, captured))
        await update.message.reply_text(f"✅ Logged BP {value}" if ok else msg)
        return

    if "sugar" in lower or "blood sugar" in lower:
        sugar = re.search(r"(\d+)", lower)
        if sugar:
            value = sugar.group(1)
            ok, msg = send_to_health_log(build_vital("Blood Sugar", value, "mg/dL", notes, captured))
            await update.message.reply_text(f"✅ Logged Sugar {value}" if ok else msg)
            return

    if "urine" in lower:
        urine = re.search(r"(\d+)\s*(ml|mL)", text)
        if urine:
            value = urine.group(1)
            ok, msg = send_to_health_log(build_vital("Urine Output", value, "mL", notes, captured))
            await update.message.reply_text(f"✅ Logged Urine {value}mL" if ok else msg)
            return

    if "weight" in lower:
        weight = re.search(r"(\d{2,3}(?:\.\d+)?)", lower)
        if weight:
            value = weight.group(1)
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

        payload = build_reimbursement_action(
            "log_receipt_photo",
            {
                "tripId": trip_id,
                "category": category,
                "amount": amount,
                "vendor": vendor,
                "receiptDate": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
                "fileName": f"{trip_id}_{category}_{datetime.now(LOCAL_TZ).strftime('%Y%m%d_%H%M%S')}.jpg",
                "photoBase64": photo_base64,
            },
        )

        ok, msg = send_to_health_log(payload)
        await update.message.reply_text(("✅ " + clean_apps_script_response(msg)) if ok else ("Error: " + msg))
        return

    if not caption or not lower.startswith("wound"):
        await update.message.reply_text("Photo received, but add a wound caption starting with: Wound")
        return

    captured = parse_time_from_message(caption)
    ok, msg = send_to_health_log(build_wound(caption, captured, "", file_id, photo_base64))
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
    except Exception as error:
        print(str(error), flush=True)
        return "ERROR", 500


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
