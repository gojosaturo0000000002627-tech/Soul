#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rajasthan Exam Helper Bot
=========================
Telegram bot for Rajasthan exam preparation:
  📚 Syllabus  |  📄 Old Papers  |  ❓ MCQ Quiz  |  ⏰ Reminder  |  📝 Notes  |  🆘 Help

Setup: README.md dekhein. Token config.py me ya BOT_TOKEN env variable me daalein.
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
import threading
import urllib.parse
from datetime import time as dtime
from difflib import get_close_matches
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

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
    "❓ MCQ Quiz — विषय चुनो (इतिहास, भूगोल, राजव्यवस्था, कला-संस्कृति), फिर टॉपिक चुनो "
    "या पूरा विषय एक साथ करो। सही/गलत तुरंत पता चलेगा और अंत में स्कोर भी मिलेगा।\n\n"
    "⏰ Reminder — bas itna likho:\n"
    "   /setreminder 07:30   (roz 7:30 baje reminder milega)\n"
    "   /stopreminder        (reminder band karne ke liye)\n\n"
    "📝 Notes — chhote revision notes (history, geography, polity, culture).\n\n"
    "Commands: /start /menu /quiz /help /setreminder /stopreminder"
)

# Token: pehle environment variable (Render/hosting ke liye), fir config.py ka fallback
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    try:
        from config import BOT_TOKEN as _CFG_TOKEN  # type: ignore
        BOT_TOKEN = (_CFG_TOKEN or "").strip()
    except Exception:
        pass

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
    rows.append([InlineKeyboardButton("➕ और exams चाहिए?", callback_data="menu:more")])
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def subject_keyboard():
    """MCQ — pehla step: kaunsa vishay?"""
    rows = []
    row = []
    for key, t in MCQ_TOPICS.items():
        n = len(t.get("questions", []))
        row.append(
            InlineKeyboardButton(
                f"{t['label']} ({n})", callback_data=f"mcqsub:{key}"
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton("🎲 Mix — थोड़े सब विषयों से", callback_data="mcqstart:mix")]
    )
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def subtopic_keyboard(key):
    """MCQ — doosra step: vishay ke andar kaunsa topic ya pura vishay?"""
    t = MCQ_TOPICS[key]
    counts = {}
    for q in t.get("questions", []):
        counts[q.get("sub", "")] = counts.get(q.get("sub", ""), 0) + 1
    rows = []
    for sub, label in t.get("sublabels", {}).items():
        n = counts.get(sub, 0)
        if n:
            rows.append(
                [InlineKeyboardButton(
                    f"{label} ({n} प्रश्न)", callback_data=f"mcqstart:{key}:{sub}"
                )]
            )
    rows.append(
        [
            InlineKeyboardButton(
                f"📚 पूरा विषय — सभी {len(t['questions'])} प्रश्न",
                callback_data=f"mcqstart:{key}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("⬅️ विषय सूची", callback_data="menu:mcq")])
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
    # Devanagari + English dono ke liye (\w unicode letters ko rakhta hai)
    return re.sub(r"[\W_]+", "", s.lower())


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


MAX_PDF_MB = 45  # Telegram bot API ki sima ~50MB hai


def _pdf_filename(title):
    """Title se theek-theek filename banao."""
    name = re.sub(r"[^\w\-.() ]+", "_", title)[:60].strip(" _")
    if not name:
        name = "question_paper"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


async def send_pdf_document(context, chat_id, title, url):
    """URL se PDF download karke Telegram me document ke roop me bhejo."""
    await context.bot.send_chat_action(chat_id, action="upload_document")
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(180.0),
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    data = resp.content
    if len(data) > MAX_PDF_MB * 1024 * 1024:
        raise ValueError("PDF bahut badi hai")
    if not data.startswith(b"%PDF"):
        raise ValueError("Ye file PDF nahi nikli")
    await context.bot.send_document(
        chat_id,
        document=BytesIO(data),
        filename=_pdf_filename(title),
        caption=title[:950],
    )


async def on_pdf_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ne 📥 PDF wala button dabaya."""
    q = update.callback_query
    try:
        _, section, exam_idx, item_idx = q.data.split(":")
        ex = EXAMS[int(exam_idx)]
        links = ex.get("old_papers" if section == "oldpapers" else "syllabus", [])
        item = links[int(item_idx)]
    except (ValueError, IndexError, KeyError):
        await q.answer("Ye button purana ho gaya — dobara exam select karo.")
        return

    await q.answer("⏳ PDF laa rahe hain...")
    chat_id = update.effective_chat.id
    try:
        await send_pdf_document(context, chat_id, item["title"], item["url"])
    except Exception as e:
        log.warning("PDF send failed (%s): %s", item["url"], e)
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔗 Browser me kholo", url=item["url"])]]
        )
        await context.bot.send_message(
            chat_id,
            "⚠️ PDF download nahi ho paayi. Seedha link try karo:",
            reply_markup=kb,
        )


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
    for i, lnk in enumerate(links):
        if lnk["url"].lower().endswith(".pdf"):
            # direct PDF — button dabate hi Telegram me aa jayegi
            kb.append(
                [
                    InlineKeyboardButton(
                        "📥 " + lnk["title"][:58],
                        callback_data=f"pdf:{section}:{idx}:{i}",
                    )
                ]
            )
        else:
            kb.append(
                [InlineKeyboardButton("🔗 " + lnk["title"][:58], url=lnk["url"])]
            )
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
        note = ("\n\n📥 wale button dabao — PDF seedha Telegram me aa jayegi! "
                "Agar 📥 nahi hai (jaise RSSB ke kuch exams) to 📖 official "
                "page khulega jahan exam/year select karke PDF download karni hogi.")
    else:
        note = "\n\n📥 wale button dabao — syllabus PDF seedha Telegram me aa jayegi."

    await context.bot.send_message(
        chat_id,
        header + note,
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ------------------------------------------------------------------- quiz ----


def build_quiz(spec):
    """spec = 'mix' | vishay-key | vishay-key:subtopic — sawal shuffle karke."""
    if spec == "mix":
        qs = []
        for t in MCQ_TOPICS.values():
            qs.extend(t.get("questions", []))
        label = "🎲 Mix Quiz"
        if len(qs) > QUIZ_LENGTH:
            qs = random.sample(qs, QUIZ_LENGTH)
    elif ":" in spec:
        key, sub = spec.split(":", 1)
        t = MCQ_TOPICS.get(key)
        if not t:
            return None, []
        qs = [q for q in t.get("questions", []) if q.get("sub") == sub]
        label = f"{t['label']} — {t.get('sublabels', {}).get(sub, sub)}"
    else:
        t = MCQ_TOPICS.get(spec)
        if not t:
            return None, []
        qs = list(t.get("questions", []))
        label = t.get("label", spec)
    if not qs:
        return label, []
    random.shuffle(qs)
    prepared = []
    for q in qs:
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
        f"❓ प्रश्न {i + 1}/{len(qz['qs'])} — {qz['label']}\n\n"
        f"{q['q']}\n\n{opts}"
    )
    kb = [
        [InlineKeyboardButton(L, callback_data=f"quiz:{i}:{j}") for j, L in enumerate("ABCD")],
        [InlineKeyboardButton("✖️ क्विज़ बंद करें", callback_data="quiz:quit")],
    ]
    await context.bot.send_message(
        chat_id, text, reply_markup=InlineKeyboardMarkup(kb)
    )


async def start_quiz(update, context, spec):
    label, qs = build_quiz(spec)
    if not qs:
        await update.callback_query.message.reply_text(
            "इस टॉपिक में अभी प्रश्न उपलब्ध नहीं हैं। 😅"
        )
        return
    context.chat_data["quiz"] = {
        "label": label,
        "spec": spec,
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
    context.chat_data["await"] = "mcqtopic"
    await update.message.reply_text(
        "❓ किस विषय के MCQ करने हैं?\n\nनीचे से चुनो — या बस विषय का नाम लिख दो "
        "(जैसे: इतिहास, Geography, भूगोल...) 👇",
        reply_markup=subject_keyboard(),
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
        context.chat_data["await"] = "mcqtopic"
        await context.bot.send_message(
            chat_id,
            "❓ किस विषय के MCQ करने हैं? विषय चुनो — फिर टॉपिक मिलेगा, चाहो तो पूरा "
            "विषय भी कर सकते हो 👇",
            reply_markup=subject_keyboard(),
        )

    elif section == "more":
        context.chat_data["await"] = "anyexam"
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🏛️ RPSC site", url="https://rpsc.rajasthan.gov.in"),
                 InlineKeyboardButton("🏛️ RSSB site", url="https://rssb.rajasthan.gov.in")],
                [InlineKeyboardButton("🏫 BSER / REET site", url="https://rajeduboard.rajasthan.gov.in"),
                 InlineKeyboardButton("🚓 Police site", url="https://police.rajasthan.gov.in")],
            ]
        )
        await context.bot.send_message(
            chat_id,
            "➕ कोई और exam चाहिए? बस उसका नाम नीचे लिख दो! 👇\n\n"
            "अगर वो मेरी list में है तो सीधे उसकी syllabus और old papers दे दूँगा। "
            "नहीं है तो भी चिंता मत करो — उस exam के लिए ढूंढने के links बना दूँगा। \n\n"
            "(जैसे लिखो: animal attendant, jailor, वन रक्षक, high court...)",
            reply_markup=kb,
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


async def ddg_search(query, n=5):
    """DuckDuckGo HTML search — (title, url) ki list. Fail hone par khali list."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=25,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        ) as client:
            r = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        results = []
        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S
        ):
            url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            mm = re.search(r"uddg=([^&]+)", url)
            if mm:
                url = urllib.parse.unquote(mm.group(1))
            elif url.startswith("//"):
                url = "https:" + url
            if "duckduckgo.com" in url or not title:
                continue
            title = title.replace("&", "&")[:60]
            results.append((title, url))
            if len(results) >= n:
                break
        return results
    except Exception as e:
        log.warning("DDG search failed: %s", e)
        return []


def _rank_results(results):
    """Behtar results upar: pehle PDF, fir official rajasthan.gov.in, fir badi sites."""
    def score(item):
        _t, url = item
        s = 0
        if url.lower().split("?")[0].endswith(".pdf"):
            s -= 10
        if "rajasthan.gov.in" in url:
            s -= 5
        if any(d in url for d in ("sarkariresult", "adda247", "testbook", "jagranjosh", "freshersnow")):
            s -= 2
        return s
    return sorted(results, key=score)


async def send_exam_all(context, chat_id, idx):
    """Ek exam ka syllabus + old papers dono ek saath bhejo."""
    ex = EXAMS[idx]
    await context.bot.send_message(
        chat_id,
        f"✅ मिल गया! {ex['name']} — सब कुछ नीचे है 👇",
    )
    await send_exam(context, chat_id, idx, "syllabus")
    if ex.get("old_papers"):
        await send_exam(context, chat_id, idx, "oldpapers")


def _close_exams(query, n=4):
    """List me se milte-julte exams ke index dhoondo."""
    q = _norm(query)
    if not q:
        return []
    keymap = {}
    for i, ex in enumerate(EXAMS):
        for k in [ex["name"]] + ex.get("aliases", []):
            nk = _norm(k)
            if nk:
                keymap[nk] = i
    close = get_close_matches(q, list(keymap.keys()), n=n, cutoff=0.45)
    out = []
    for c in close:
        idx = keymap[c]
        if idx not in out:
            out.append(idx)
    return out


async def on_exam_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suggestion button — is exam ka sab kuch bhejo."""
    q = update.callback_query
    await q.answer()
    try:
        idx = int(q.data.split(":")[1])
    except (ValueError, IndexError):
        return
    if idx >= len(EXAMS):
        await q.message.reply_text("Ye exam abhi available nahi hai.")
        return
    context.chat_data["await"] = None
    await send_exam_all(context, update.effective_chat.id, idx)


def find_subject(query):
    """User ke likhe naam se MCQ vishay/subtopic dhoondo. Return: 'key' | 'key:sub' | None"""
    q = _norm(query)
    if not q:
        return None
    # vishay ke naam + english key dono se match
    for key, t in MCQ_TOPICS.items():
        names = [t.get("label", "").replace(key, ""), key]
        for n in names:
            n = _norm(n)
            if n and (n in q or q in n):
                return key
    # ab subtopic labels se
    for key, t in MCQ_TOPICS.items():
        for sub, label in t.get("sublabels", {}).items():
            sl = _norm(label)
            if sl and (sl in q or q in sl):
                return f"{key}:{sub}"
    return None


async def on_pdf_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search result ka 📥 PDF button — seedha Telegram me bhejo."""
    q = update.callback_query
    pool = context.chat_data.get("search_pdfs") or []
    try:
        item = pool[int(q.data.split(":")[1])]
    except (ValueError, IndexError):
        await q.answer("Ye button purana ho gaya — dobara exam likho.")
        return
    await q.answer("⏳ PDF laa rahe hain...")
    chat_id = update.effective_chat.id
    try:
        await send_pdf_document(context, chat_id, item["title"], item["url"])
    except Exception as e:
        log.warning("Search PDF send failed (%s): %s", item["url"], e)
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔗 Browser me kholo", url=item["url"])]]
        )
        await context.bot.send_message(
            chat_id, "⚠️ PDF download nahi ho paayi. Seedha link try karo:", reply_markup=kb
        )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ka text message — section ke hisaab se exam ya topic dhoondo."""
    mode = context.chat_data.get("await")
    if not mode:
        await update.message.reply_text(
            " Kripya /menu se main menu kholein. 🙂", reply_markup=main_menu()
        )
        return

    query = update.message.text.strip()
    context.chat_data["await"] = None

    if mode == "mcqtopic":
        spec = find_subject(query)
        if spec is None:
            await update.message.reply_text(
                f'"{query}" — ye vishay mujhe samajh nahi aaya 😅\n'
                "Neeche se chuno:",
                reply_markup=subject_keyboard(),
            )
            return
        if ":" in spec:
            await start_quiz(update, context, spec)
        else:
            await update.message.reply_text(
                "✅ विषय चुना गया! अब बताओ — पूरा विषय या कोई टॉपिक? 👇",
                reply_markup=subtopic_keyboard(spec),
            )
        return

    if mode == "anyexam":
        idx = find_exam(query)
        if idx is not None:
            await send_exam_all(context, update.effective_chat.id, idx)
            return

        # list me nahi — internet par asli search karke results lao
        await update.message.reply_text(
            f"⏳ '{query}' ke liye internet par ढूंढ रहा हूँ... कुछ seconds रुको 🙏"
        )
        syl_res = await ddg_search(f"{query} rajasthan syllabus pdf")
        pap_res = await ddg_search(
            f"{query} rajasthan previous year question paper pdf"
        )

        if not syl_res and not pap_res:
            # search hi fail — Google buttons par wapas
            q_enc = urllib.parse.quote_plus(f"{query} rajasthan")
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔍 Google: syllabus ढूंढो", url=f"https://www.google.com/search?q={q_enc}+syllabus+pdf")],
                    [InlineKeyboardButton("🔍 Google: old papers ढूंढो", url=f"https://www.google.com/search?q={q_enc}+previous+year+question+paper+pdf")],
                    [InlineKeyboardButton("🏛️ RPSC", url="https://rpsc.rajasthan.gov.in"), InlineKeyboardButton("🏛️ RSSB", url="https://rssb.rajasthan.gov.in")],
                    [InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")],
                ]
            )
            await update.message.reply_text(
                "😅 अभी search से results नहीं मिले। In buttons se try karo 👇",
                reply_markup=kb,
            )
            return

        kb = []
        pdf_pool = []  # chat_data me rakhenge — direct PDF bhejne ke liye

        for close_idx in _close_exams(query)[:2]:
            kb.append(
                [
                    InlineKeyboardButton(
                        "👉 " + EXAMS[close_idx]["name"] + " — यही चाहिए?",
                        callback_data=f"examboth:{close_idx}",
                    )
                ]
            )

        for label, res in (("📚 Syllabus", syl_res), ("📄 Old Papers", pap_res)):
            for title, url in _rank_results(res)[:3]:
                if url.lower().split("?")[0].endswith(".pdf"):
                    pdf_pool.append({"title": title, "url": url})
                    kb.append(
                        [
                            InlineKeyboardButton(
                                f"📥 {label}: {title}"[:60],
                                callback_data=f"pdfget:{len(pdf_pool) - 1}",
                            )
                        ]
                    )
                else:
                    kb.append(
                        [InlineKeyboardButton(f"🔗 {label}: {title}"[:60], url=url)]
                    )

        q_enc = urllib.parse.quote_plus(f"{query} rajasthan")
        kb.append(
            [
                InlineKeyboardButton("🔍 Aur chahiye? Google", url=f"https://www.google.com/search?q={q_enc}+syllabus+pdf"),
            ]
        )
        kb.append(
            [
                InlineKeyboardButton("🏛️ RPSC", url="https://rpsc.rajasthan.gov.in"),
                InlineKeyboardButton("🏛️ RSSB", url="https://rssb.rajasthan.gov.in"),
            ]
        )
        kb.append(
            [
                InlineKeyboardButton("➕ दूसरा exam लिखो", callback_data="menu:more"),
                InlineKeyboardButton("⬅️ Menu", callback_data="menu:main"),
            ]
        )
        context.chat_data["search_pdfs"] = pdf_pool
        await update.message.reply_text(
            f'✅ "{query}" के लिए ये मिले 👇\n\n'
            "📥 वाले button दबाओ — PDF सीधे Telegram में आ जाएगी!\n"
            "🔗 वाले button पर नतीजे खुलेंगे।",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    idx = find_exam(query)
    if idx is None:
        await update.message.reply_text(
            f'"{query}" — ye exam mujhe samajh nahi aaya 😅\n'
            "Neeche list me se chuno, ya sahi naam se dobara likho:",
            reply_markup=exam_keyboard(mode),
        )
        return
    await send_exam(context, update.effective_chat.id, idx, mode)


async def on_mcq_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ne vishay chuna — ab subtopic dikhao."""
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    if key not in MCQ_TOPICS:
        await q.message.reply_text("Ye vishay abhi available nahi hai.")
        return
    t = MCQ_TOPICS[key]
    await q.message.reply_text(
        f"✅ {t['label']} — {len(t['questions'])} प्रश्न इस विषय में।\n\n"
        "अब बताओ — कोई एक टॉपिक करना है या पूरा विषय? 👇",
        reply_markup=subtopic_keyboard(key),
    )


async def on_mcq_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subtopic ya pura vishay chuna gaya — quiz shuru!"""
    await update.callback_query.answer()
    spec = update.callback_query.data.split(":", 1)[1]
    await start_quiz(update, context, spec)


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
        await q.answer("Ye purana sawal hai — agle sawal ka jawab do 🙂")
        return

    question = qz["qs"][si]
    correct = question["answer"]
    if oi == correct:
        qz["score"] += 1
        await q.answer("✅ सही उत्तर!")
        result = "✅ सही उत्तर! 🎉"
    else:
        await q.answer("❌ गलत")
        result = f"❌ गलत — सही उत्तर: {'ABCD'[correct]}) {question['options'][correct]}"
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
                        "🔁 दोबारा खेलो", callback_data=f"mcqstart:{qz['spec']}"
                    ),
                    InlineKeyboardButton(
                        "📚 दूसरा विषय", callback_data="menu:mcq"
                    ),
                ],
                [InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")],
            ]
        )
        await q.message.reply_text(
            f"🎉 क्विज़ पूरा हुआ!\n\nआपका स्कोर: {score}/{total} {emoji}", reply_markup=kb
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
    app.add_handler(CallbackQueryHandler(on_exam_all, pattern=r"^examboth:"))
    app.add_handler(CallbackQueryHandler(on_mcq_sub, pattern=r"^mcqsub:"))
    app.add_handler(CallbackQueryHandler(on_mcq_start, pattern=r"^mcqstart:"))
    app.add_handler(CallbackQueryHandler(on_quiz_answer, pattern=r"^quiz:"))
    app.add_handler(CallbackQueryHandler(on_note, pattern=r"^note:"))
    app.add_handler(CallbackQueryHandler(on_pdf_button, pattern=r"^pdf:"))
    app.add_handler(CallbackQueryHandler(on_pdf_get, pattern=r"^pdfget:"))
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

    # Python 3.14+ me get_event_loop() apne aap loop nahi banata
    # (telegram library ispe depend karti hai) — isliye hum khud bana dete hain
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

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
