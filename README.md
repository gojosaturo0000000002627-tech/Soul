# 📚 Rajasthan Exam Helper Bot (Telegram)

Rajasthan ke exams (RAS, REET, Patwari, Police, CET, LDC, VDO...) ki taiyari ke liye
Telegram bot. Ek hi jagah par — Syllabus, Old Papers, MCQ Quiz, Daily Reminder aur
Revision Notes.

---

## 🎛️ Bot me kya-kya hai (buttons)

| Button | Kya karta hai |
|---|---|
| 📚 Syllabus | Exam ka naam likho (jaise "RAS", "REET", "Patwari") — official syllabus ka link/PDF milega |
| 📄 Old Papers | Exam ka naam likho — purane question papers ke official links (RPSC / RSSB / BSER sites se) |
| ❓ MCQ Quiz | Topic chuno — 10 sawal ka quiz, turant sahi/galat + explanation + end me score |
| ⏰ Reminder | `/setreminder 07:30` likho — roz us time study reminder message milega |
| 📝 Notes | Rajasthan GK ke chhote revision notes |
| 🆘 Help | Sab kuch dobara samjha deta hai |

Commands: `/start` `/menu` `/quiz` `/help` `/setreminder HH:MM` `/stopreminder`

---

## 🚀 Chalane ka tarika (step by step)

### Step 1 — Bot banao (Telegram me, 2 minute)
1. Telegram me **@BotFather** kholo
2. `/newbot` likho
3. Bot ka naam likho (jaise: `Rajasthan Exam Helper`)
4. Username likho (jaise: `rajasthan_helper_bot` — end me `bot` hona chahiye)
5. BotFather ek **token** dega — copy kar lo (kisi ko na dikhao!)

### Step 2 — Computer par bot chalao
1. Python 3.10+ installed hona chahiye — [python.org](https://www.python.org/downloads/) se
2. Ye folder download karke kholo (zip se extract karo)
3. Terminal/CMD kholo (is folder me) aur chalao:
   ```
   pip install -r requirements.txt
   ```
4. `config.py` file kholo aur apna token paste karo:
   ```python
   BOT_TOKEN = "123456789:AAHfk3j9d..."
   ```
5. Bot start karo:
   ```
   python bot.py
   ```
6. Telegram me apna bot kholo aur `/start` bhejo — ho gaya! 🎉

> Token environment variable se bhi de sakte ho:
> Windows: `set BOT_TOKEN=123456:ABC...` | Linux/Mac: `export BOT_TOKEN=123456:ABC...`

---

## ☁️ Bot ko 24x7 chalana (hosting)

Apna band kholne par hi reminder bhej paane ke liye bot hamesha chalta rehna chahiye:

- **Apna PC/laptop** — bot tab tak chalega jab tak computer on aur script chalu hai (bilkul free)
- **PythonAnywhere** (pythonanywhere.com) — free account banao, "Files" me ye project
  upload karo, Bash console me `pip install --user python-telegram-bot[job-queue]` chalao,
  phir `python3 bot.py` chalao. Console tab tak bot chalayega. (Restart hone par dobara chalana padega)
- **Render / Railway** — free/paid hosting, GitHub par code push karke "Background Worker"
  bana sakte ho — permanently 24x7 ke liye yahi behtar hai

---

## ➕ Naya exam ya nayi PDF link add karna

`data/exams.json` kholo. Har exam aise dikhta hai:

```json
{
  "name": "Naya Exam ka naam",
  "aliases": ["chhota naam", "dusra naam"],
  "website": "https://official-site",
  "syllabus": [
    {"title": "Syllabus PDF", "url": "https://...pdf-ka-link..."}
  ],
  "old_papers": [
    {"title": "Old Paper 2023", "url": "https://...link..."}
  ]
}
```

- `aliases` me wo shabd daalo jo log type karte hain (jaise "ras", "patwari")
- Agar kisi official PDF ka direct link hai to seedha `url` me daal do — button
  click karte hi PDF khul jayegi
- Bot restart karne par naye changes aa jayenge

**Direct PDF links kahan se milein:** RPSC/RSSB ke official pages par exam-wise
PDF padi hoti hain — download link copy karke `exams.json` me daal do.

---

## ➕ Naye MCQ / Notes add karna

- **MCQ:** `data/mcq.json` me apne topic me sawal jodo:
  `"q"` sawal, `"options"` 4 options, `"answer"` sahi option ka number (0=A, 1=B, 2=C, 3=D),
  `"explain"` chhoti detail
- **Notes:** `data/notes.json` me `{ "title": "...", "text": "..." }` jodo

---

## ⚠️ Dhyan rakhein

- Saare syllabus/old-paper links **official sites** (rpsc.rajasthan.gov.in,
  rssb.rajasthan.gov.in, rajeduboard.rajasthan.gov.in, police.rajasthan.gov.in) ke hain —
  kabhi site ka structure badal jaye to link update karna pad sakta hai (exams.json me)
- Old papers wale pages par exam/year select karke PDF download karni hoti hai —
  bot aapko wahan tak le jata hai
- `config.py` me apna token **kisi ko na dikhao** — jo bhi token janta hai wo aapka
  bot chala sakta hai

Happy preparation! All the best! 💪🔥
