from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
import requests
import re
from datetime import datetime

BOT_TOKEN = "8541344854:AAEmaesou7KMJxkI9ddpaPQpSt-UCNW_ouw"

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzaHN8jubk2rnRyn_e1q5iD8scbuDMZDBlTYyCT2oAWY7asVxs5NBtSQX8zmQllH8LU/exec"
WEBHOOK_TOKEN = "AH_HEALTH_2026_7f29xK81vitals"


def parse_time_from_message(lower):
    now = datetime.now()

    time_match = re.search(
        r'(?:@|at)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        lower
    )

    if not time_match:
        return now

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    ampm = time_match.group(3).lower()

    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def send_to_health_log(payload):
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            timeout=20,
            allow_redirects=False
        )

        if response.status_code in [200, 302]:
            return True, response.status_code, response.text

        return False, response.status_code, response.text

    except Exception as e:
        return False, "ERROR", str(e)


def build_base_entry(name, value, unit, notes, captured_dt):
    return {
        "token": WEBHOOK_TOKEN,
        "type": "Vitals",
        "entry": {
            "captured_at": captured_dt.astimezone().isoformat(),
            "date": captured_dt.strftime("%Y-%m-%d"),
            "time": captured_dt.strftime("%-I:%M %p"),
            "name": name,
            "value": value,
            "unit": unit,
            "notes": notes
        }
    }


async def start(update, context):
    await update.message.reply_text(
        "Health bot is online ✅\n\n"
        "Try:\n"
        "blood pressure 133/88 pulse 91\n"
        "bp 133/88 pulse 91 @ 10:05am\n"
        "blood sugar 111 mg @ 8:30am\n"
        "sugar 111\n"
        "urine 350 ml\n"
        "weight 229.4"
    )


async def handle_message(update, context):
    text = update.message.text.strip()
    lower = text.lower()
    captured_dt = parse_time_from_message(lower)

    notes = "Logged from Telegram"

    if "after walking" in lower:
        notes = "After walking"
    elif "test" in lower:
        notes = "Test entry from Telegram"

    # BLOOD PRESSURE
    bp_match = re.search(r'(\d{2,3})\/(\d{2,3})', text)

    if bp_match and ("blood pressure" in lower or "bp" in lower):
        systolic = bp_match.group(1)
        diastolic = bp_match.group(2)

        pulse_match = re.search(r'(pulse|pul)\s*(\d{2,3})', lower)
        pulse_text = f" Pulse {pulse_match.group(2)}" if pulse_match else ""

        value = f"{systolic}/{diastolic}{pulse_text}"
        payload = build_base_entry("Blood Pressure", value, "mmHg", notes, captured_dt)

        ok, code, body = send_to_health_log(payload)

        if ok:
            await update.message.reply_text(
                f"✅ Logged BP: {value} at {captured_dt.strftime('%-I:%M %p')}"
            )
        else:
            await update.message.reply_text(f"⚠️ BP may not have logged. HTTP: {code}")

        return

    # BLOOD SUGAR
    sugar_match = re.search(r'(\d+)\s*(mg|mg\/dl)?', lower)

    if sugar_match and ("blood sugar" in lower or "sugar" in lower):
        value = sugar_match.group(1)
        payload = build_base_entry("Blood Sugar", value, "mg/dL", notes, captured_dt)

        ok, code, body = send_to_health_log(payload)

        if ok:
            await update.message.reply_text(
                f"✅ Logged Blood Sugar: {value} mg/dL at {captured_dt.strftime('%-I:%M %p')}"
            )
        else:
            await update.message.reply_text(f"⚠️ Blood sugar may not have logged. HTTP: {code}")

        return

    # URINE OUTPUT
    urine_match = re.search(r'(\d+)\s*(ml|mL)', text)

    if urine_match and "urine" in lower:
        value = urine_match.group(1)
        payload = build_base_entry("Urine Output", value, "mL", notes, captured_dt)

        ok, code, body = send_to_health_log(payload)

        if ok:
            await update.message.reply_text(
                f"✅ Logged Urine Output: {value} mL at {captured_dt.strftime('%-I:%M %p')}"
            )
        else:
            await update.message.reply_text(f"⚠️ Urine output may not have logged. HTTP: {code}")

        return

    # WEIGHT
    weight_match = re.search(r'(\d{2,3}(?:\.\d+)?)', lower)

    if weight_match and ("weight" in lower or "weigh" in lower):
        value = weight_match.group(1)
        payload = build_base_entry("Weight", value, "lbs", notes, captured_dt)

        ok, code, body = send_to_health_log(payload)

        if ok:
            await update.message.reply_text(
                f"✅ Logged Weight: {value} lbs at {captured_dt.strftime('%-I:%M %p')}"
            )
        else:
            await update.message.reply_text(f"⚠️ Weight may not have logged. HTTP: {code}")

        return

    await update.message.reply_text(
        "I couldn't understand that entry yet.\n\n"
        "Try:\n"
        "blood pressure 133/88 pulse 91\n"
        "bp 133/88 pulse 91 @ 10:05am\n"
        "blood sugar 111 mg @ 8:30am\n"
        "sugar 111\n"
        "urine 350 ml\n"
        "weight 229.4"
    )


app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Health Telegram bot running...")

app.run_polling()