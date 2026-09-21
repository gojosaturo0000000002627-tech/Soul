#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rajasthan Exam Helper Bot
=========================
Telegram bot for Rajasthan exam preparation:
  📚 Syllabus  |  📄 Old Papers  |  ❓ MCQ Quiz  |  ⏰ Reminder  |  📝 Notes  |  🆘 Help

Setup: README.md dekhein. Token config.py me ya BOT_TOKEN env variable me daalein.
"""

import json
import logging
import os
import random
import re
import sys
import threading
from datetime import time as dtime
from difflib import get_close_matches
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------- basics ----

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
TZ = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("rajbot")

QUIZ_LENGTH = 10  # ek quiz me kitne sawal


def _load_json(name, default):
    path = DATA_DIR / name
    if not path.exists():
        log.warning("Data file missing: %s", path)
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("Could not parse %s: %s", path, e)
        return default


EXAMS = _load_json("exams.json", {"exams": []}).get("exams", [])
MCQ_TOPICS = _load_json("mcq.json", {"topics": {}}).get("topics", {})
NOTES = _load_json("notes.json", [])
REMINDER_FILE = DATA_DIR / "reminders.json"

REMINDER_TEXT = (
    "⏰ Good morning, aspirant! 💪\n\n"
    "Aaj ka target:\n"
    "1️⃣ 1 ghanta — Rajasthan GK (Culture + Current Affairs)\n"
    "2️⃣ 1 ghanta — apna subject practice ( Maths / Reasoning / Hindi )\n"
    "3️⃣ 25-30 MCQ quiz laga lo — is bot me /quiz se\n"
    "4️⃣ 1 old paper ka analysis — /menu se Old Papers section tak jao\n\n"
    "Consistency hi selection ki chaabi hai. Chalo, aaj ka din jeet lo! 🔥"
)

HELP_TEXT = (
    "🆘 Help — ye bot kaise use karein\n\n"
    "📚 Syllabus — button dabao, apne exam ka naam likho (jaise: RAS, REET, "
    "Patwari, Police). Bot official syllabus ka link/PDF de dega.\n\n"
    "📄 Old Papers — exam ka naam likho, purane question papers ke official "
    "links milenge (RPSC / RSSB / BSER official sites se).\n\n"
    "❓ MCQ Quiz — topic chuno, 10 sawal ka quiz hoga. Jawab dote hi sahi / galat "
    "pata chal jayega, aur end me score bhi milega.\n\n"
    "⏰ Reminder — bas itna likho:\n"
    "   /setreminder 07:30   (roz 7:30 baje reminder milega)\n"
    "   /stopreminder        (reminder band karne ke liye)\n\n"
    "📝 Notes — chhote revision notes (history, geography, polity, culture).\n\n"
    "Commands: /start /menu /quiz /help /setreminder /stopreminder"
)

# Token: config.py se ya environment variable se
try:
    from config import BOT_TOKEN  # type: ignore
except Exception:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# ------------------------------------------------------------- keyboards ----


def main_menu():
    kb = [
        [
            InlineKeyboardButton("📚 Syllabus", callback_data="menu:syllabus"),
            InlineKeyboardButton("📄 Old Papers", callback_data="menu:oldpapers"),
        ],
        [
            InlineKeyboardButton("❓ MCQ Quiz", callback_data="menu:mcq"),
            InlineKeyboardButton("⏰ Reminder", callback_data="menu:reminder"),
        ],
        [
            InlineKeyboardButton("📝 Notes", callback_data="menu:notes"),
            InlineKeyboardButton("🆘 Help", callback_data="menu:help"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


def exam_keyboard(section):
    """Sabhi exams ke buttons + Menu button."""
    rows = []
    row = []
    for i, ex in enumerate(EXAMS):
        row.append(
            InlineKeyboardButton(ex["name"], callback_data=f"exam:{i}:{section}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def topic_keyboard():
    rows = []
    row = []
    for key, t in MCQ_TOPICS.items():
        row.append(InlineKeyboardButton(t["label"], callback_data=f"mcqtopic:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton("🎲 Mix — sab topics", callback_data="mcqtopic:mix")]
    )
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def notes_keyboard():
    rows = []
    row = []
    for i, n in enumerate(NOTES):
        row.append(InlineKeyboardButton(n["title"], callback_data=f"note:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------- exam matching ----


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_exam(query):
    """User ke likhe naam se exam dhoondo (exact / partial / fuzzy)."""
    q = _norm(query)
    if not q:
        return None
    # exact ya partial match
    for i, ex in enumerate(EXAMS):
        keys = [_norm(ex["name"])] + [_norm(a) for a in ex.get("aliases", [])]
        for k in keys:
            if not k:
                continue
            if k == q or (len(k) >= 4 and k in q) or (len(q) >= 4 and q in k):
                return i
    # fuzzy match
    pairs = []
    for i, ex in enumerate(EXAMS):
        pairs.append((_norm(ex["name"]), i))
        for a in ex.get("aliases", []):
            pairs.append((_norm(a), i))
    lookup = {k: i for k, i in pairs}
    close = get_close_matches(q, list(lookup.keys()), n=1, cutoff=0.6)
    if close:
        return lookup[close[0]]
    return None


async def send_exam(context, chat_id, idx, section):
    """Ek exam ka syllabus ya old-paper links bhejo."""
    ex = EXAMS[idx]
    if section == "oldpapers":
        links = ex.get("old_papers", [])
        header = f"📄 {ex['name']} — Old Question Papers"
    else:
        links = ex.get("syllabus", [])
        header = f"📚 {ex['name']} — Syllabus"

    kb = []
    for item in links:
        kb.append([InlineKeyboardButton("⬇️ " + item["title"], url=item["url"])])
    if ex.get("website"):
        kb.append(
            [
                InlineKeyboardButton(
                    "🌐 Official Website", url=ex["website"]
                )
            ]
        )
    kb.append([InlineKeyboardButton("🔍 Koi aur exam", callback_data=f"menu:{section}")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])

    note = ""
    if section == "oldpapers":
        note = "\n\nYe links official sites ke hain — wahan exam/year select karke PDF download ho jayegi."
    else:
        note = "\n\nOfficial page par apne exam ka naam dhundo aur PDF download kar lo."

    await context.bot.send_message(
        chat_id,
        header + note,
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ------------------------------------------------------------------- quiz ----


def build_quiz(topic_key):
    """Topic se 10 sawal ka quiz banao (shuffle karke)."""
    if topic_key == "mix":
        qs = []
        for t in MCQ_TOPICS.values():
            qs.extend(t.get("questions", []))
        label = "🎲 Mix Quiz"
    else:
        t = MCQ_TOPICS.get(topic_key)
        if not t:
            return None, []
        qs = list(t.get("questions", []))
        label = t.get("label", topic_key)
    if not qs:
        return label, []

    picked = random.sample(qs, min(len(qs), QUIZ_LENGTH))
    prepared = []
    for q in picked:
        pairs = list(enumerate(q["options"]))
        random.shuffle(pairs)
        new_answer = [orig for orig, _ in pairs].index(q["answer"])
        prepared.append(
            {
                "q": q["q"],
                "options": [opt for _, opt in pairs],
                "answer": new_answer,
                "explain": q.get("explain", ""),
            }
        )
    return label, prepared


async def send_question(context, chat_id):
    qz = context.chat_data.get("quiz")
    if not qz:
        return
    i = qz["i"]
    q = qz["qs"][i]
    opts = "\n\n".join(f"{L}) {o}" for L, o in zip("ABCD", q["options"]))
    text = (
        f"❓ Sawal {i + 1}/{len(qz['qs'])} — {qz['label']}\n\n"
        f"{q['q']}\n\n{opts}"
    )
    kb = [
        [InlineKeyboardButton(L, callback_data=f"quiz:{i}:{j}") for j, L in enumerate("ABCD")],
        [InlineKeyboardButton("✖️ Quiz band karo", callback_data="quiz:quit")],
    ]
    await context.bot.send_message(
        chat_id, text, reply_markup=InlineKeyboardMarkup(kb)
    )


async def start_quiz(update, context, topic_key):
    label, qs = build_quiz(topic_key)
    if not qs:
        await update.callback_query.message.reply_text(
            "Is topic me abhi sawal available nahi hain. 😅"
        )
        return
    context.chat_data["quiz"] = {
        "label": label,
        "topic": topic_key,
        "qs": qs,
        "i": 0,
        "score": 0,
    }
    await send_question(context, update.effective_chat.id)


# --------------------------------------------------------------- reminder ----


def _save_reminders(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(REMINDER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


async def daily_message(context):
    chat_id = context.job.chat_id
    try:
        await context.bot.send_message(chat_id, REMINDER_TEXT)
    except Exception as e:
        log.warning("Reminder send failed for %s: %s", chat_id, e)


async def _remove_reminder(context, chat_id):
    jobs = context.job_queue.get_jobs_by_name(f"remind:{chat_id}")
    for j in jobs:
        j.schedule_removal()
    rems = _load_json("reminders.json", {})
    if str(chat_id) in rems:
        del rems[str(chat_id)]
        _save_reminders(rems)


async def cmd_setreminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.job_queue is None:
        await update.message.reply_text(
            "Reminder feature ke liye python-telegram-bot[job-queue] install hona chahiye. "
            "README.md dekhein."
        )
        return
    args = context.args or []
    if not args or not re.fullmatch(r"\d{1,2}:\d{2}", args[0]):
        await update.message.reply_text(
            "Sahi tarika: /setreminder 07:30\n"
            "(24-ghante format, IST — jaise 06:00, 14:30, 20:45)"
        )
        return
    hh, mm = map(int, args[0].split(":"))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        await update.message.reply_text("Time galat hai. Jaise: /setreminder 07:30")
        return
    chat_id = update.effective_chat.id
    await _remove_reminder(context, chat_id)
    context.job_queue.run_daily(
        daily_message,
        dtime(hh, mm, tzinfo=TZ),
        chat_id=chat_id,
        name=f"remind:{chat_id}",
    )
    rems = _load_json("reminders.json", {})
    rems[str(chat_id)] = f"{hh:02d}:{mm:02d}"
    _save_reminders(rems)
    await update.message.reply_text(
        f"⏰ Ho gaya! Roz {hh:02d}:{mm:02d} baje (IST) aapko study reminder milega. 🔥\n\n"
        "Band karne ke liye: /stopreminder"
    )


async def cmd_stopreminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.job_queue is not None:
        await _remove_reminder(context, update.effective_chat.id)
    await update.message.reply_text("⏰ Reminder band kar diya. Jab chaho phir se: /setreminder 07:30")


# ------------------------------------------------------------- interactions ----


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["await"] = None
    await update.message.reply_text(
        "Namaste! 👋 Main aapka *Rajasthan Exam Helper* hoon.\n\n"
        "Neeche ke buttons se apni taiyari shuru karo — syllabus, old papers, "
        "MCQ quiz, daily reminder aur revision notes, sab milega. 👇",
        reply_markup=main_menu(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["await"] = None
    await update.message.reply_text("📋 Main menu 👇", reply_markup=main_menu())


async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["await"] = None
    await update.message.reply_text(
        "❓ Kaunsa topic chahiye? Quiz me 10 sawal honge 👇",
        reply_markup=topic_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    section = q.data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    if section == "main":
        context.chat_data["await"] = None
        await context.bot.send_message(chat_id, "📋 Main menu 👇", reply_markup=main_menu())

    elif section in ("syllabus", "oldpapers"):
        context.chat_data["await"] = section
        pretty = "Syllabus" if section == "syllabus" else "Old Papers"
        await context.bot.send_message(
            chat_id,
            f"🔍 *{pretty}*\n\nApne exam ka naam likho (jaise: RAS, REET, Patwari, "
            "Police, CET...)\n\nYa phir neeche wale buttons me se chuno: 👇",
            reply_markup=exam_keyboard(section),
        )

    elif section == "mcq":
        context.chat_data["await"] = None
        await context.bot.send_message(
            chat_id, "❓ Topic chuno — 10 sawal ka quiz hoga 👇", reply_markup=topic_keyboard()
        )

    elif section == "reminder":
        rems = _load_json("reminders.json", {})
        current = rems.get(str(chat_id))
        status = (
            f"✅ Aapka reminder set hai: roz {current} baje (IST)."
            if current
            else "❌ Abhi koi reminder set nahi hai."
        )
        await context.bot.send_message(
            chat_id,
            "⏰ *Reminder*\n\n"
            + status
            + "\n\nSet karne ke liye likho: /setreminder 07:30\n"
            "Badalne ke liye naya time bhej do: /setreminder 06:00\n"
            "Band karne ke liye: /stopreminder",
        )

    elif section == "notes":
        context.chat_data["await"] = None
        if not NOTES:
            await context.bot.send_message(chat_id, "Abhi koi notes available nahi hain. 😅")
        else:
            await context.bot.send_message(
                chat_id, "📝 Kaunse notes chahiye? 👇", reply_markup=notes_keyboard()
            )

    elif section == "help":
        await context.bot.send_message(chat_id, HELP_TEXT)


async def on_exam_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        _, idx, section = q.data.split(":")
        idx = int(idx)
    except ValueError:
        return
    if idx >= len(EXAMS):
        await q.message.reply_text("Ye exam abhi available nahi hai.")
        return
    context.chat_data["await"] = None
    await send_exam(context, update.effective_chat.id, idx, section)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ka text message — agar koi section wait kar raha ho to exam dhoondo."""
    mode = context.chat_data.get("await")
    if not mode:
        await update.message.reply_text(
            " Kripya /menu se main menu kholein. 🙂", reply_markup=main_menu()
        )
        return

    query = update.message.text.strip()
    context.chat_data["await"] = None
    idx = find_exam(query)
    if idx is None:
        await update.message.reply_text(
            f"\"{query}\" — ye exam mujhe samajh nahi aaya 😅\n"
            "Neeche list me se chuno, ya sahi naam se dobara likho:",
            reply_markup=exam_keyboard(mode),
        )
        return
    await send_exam(context, update.effective_chat.id, idx, mode)


async def on_mcq_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    topic_key = update.callback_query.data.split(":", 1)[1]
    await start_quiz(update, context, topic_key)


async def on_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    qz = context.chat_data.get("quiz")

    if data == "quiz:quit":
        context.chat_data["quiz"] = None
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await q.message.reply_text(
            "Quiz band kar diya. Koi baat nahi — jab chaho phir se! 💪",
            reply_markup=main_menu(),
        )
        return

    if not qz:
        await q.answer("Pehle quiz shuru karo — /quiz likho 🙂")
        return
    try:
        _, si, oi = data.split(":")
        si, oi = int(si), int(oi)
    except ValueError:
        return
    if si != qz["i"]:
        await q.answer("Ye purana sawal hai — agli sawal ka jawab do 🙂")
        return

    question = qz["qs"][si]
    correct = question["answer"]
    if oi == correct:
        qz["score"] += 1
        await q.answer("✅ Sahi jawab!")
        result = "✅ Sahi jawab! 🎉"
    else:
        await q.answer("❌ Galat")
        result = f"❌ Galat — sahi jawab: {'ABCD'[correct]}) {question['options'][correct]}"
    expl = f"\n💡 {question['explain']}" if question.get("explain") else ""

    try:
        await q.message.edit_text(
            q.message.text + "\n\n" + result + expl, reply_markup=None
        )
    except Exception:
        pass

    qz["i"] += 1
    if qz["i"] >= len(qz["qs"]):
        score = qz["score"]
        total = len(qz["qs"])
        emoji = "🏆" if score == total else ("🔥" if score >= total * 0.7 else "💪")
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔁 Dubara khelo", callback_data=f"mcqtopic:{qz['topic']}"
                    ),
                    InlineKeyboardButton("⬅️ Menu", callback_data="menu:main"),
                ]
            ]
        )
        await q.message.reply_text(
            f"🎉 Quiz khatam!\n\nAapka score: {score}/{total} {emoji}", reply_markup=kb
        )
        context.chat_data["quiz"] = None
    else:
        await send_question(context, update.effective_chat.id)


async def on_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        i = int(q.data.split(":")[1])
    except (ValueError, IndexError):
        return
    if i >= len(NOTES):
        await q.message.reply_text("Ye note available nahi hai.")
        return
    n = NOTES[i]
    await q.message.reply_text(
        f"📝 {n['title']}\n\n{'—' * 22}\n{n['text']}\n{'—' * 22}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Notes", callback_data="menu:notes")]]
        ),
    )


# ---------------------------------------------------------------- startup ----


async def post_init(app):
    """Bot start hote hi saved reminders wapas schedule karo."""
    if app.job_queue is None:
        return
    rems = _load_json("reminders.json", {})
    for chat_id, hm in rems.items():
        try:
            hh, mm = map(int, hm.split(":"))
            app.job_queue.run_daily(
                daily_message,
                dtime(hh, mm, tzinfo=TZ),
                chat_id=int(chat_id),
                name=f"remind:{chat_id}",
            )
            log.info("Restored reminder for chat %s at %s", chat_id, hm)
        except Exception as e:
            log.warning("Bad reminder entry %s: %s", chat_id, e)


def register_handlers(app):
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("setreminder", cmd_setreminder))
    app.add_handler(CommandHandler("stopreminder", cmd_stopreminder))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_exam_button, pattern=r"^exam:"))
    app.add_handler(CallbackQueryHandler(on_mcq_topic, pattern=r"^mcqtopic:"))
    app.add_handler(CallbackQueryHandler(on_quiz_answer, pattern=r"^quiz:"))
    app.add_handler(CallbackQueryHandler(on_note, pattern=r"^note:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))


def _start_keepalive_server():
    """Render jaise platforms web-service ka port khula maangte hain.
    Ye chhota HTTP server background me PORT par sunta rehta hai."""
    port = int(os.environ.get("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Rajasthan Exam Bot is running")

        def log_message(self, *args):
            pass  # har request par log mat bharo

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Keepalive server listening on port %s", port)


def main():
    token = (BOT_TOKEN or "").strip()
    if not token:
        print(
            "\nBOT_TOKEN nahi mila!\n"
            "1) config.py banao aur usme likho:  BOT_TOKEN = \"<apna token>\"\n"
            "   (ya) environment variable set karo:  export BOT_TOKEN=<apna token>\n"
            "   (Render par: Dashboard > Environment > Add Environment Variable)\n"
            "2) Token Telegram ke @BotFather se milega — /newbot likho.\n"
            "Aadhi jankari README.md me hai.\n"
        )
        return

    if os.environ.get("PORT"):  # Render/Cloud Run jaise hosts
        _start_keepalive_server()

    app = Application.builder().token(token).post_init(post_init).build()
    register_handlers(app)
    print("✅ Bot chal raha hai... Band karne ke liye Ctrl+C dabao.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        app = Application.builder().token("123456:TEST-TOKEN").post_init(post_init).build()
        register_handlers(app)
        print("SELFTEST OK — sab handlers register ho gaye.")
    else:
        main()
