# main.py - Telegram personalities bot (FastAPI)
# IMPORTANT: Do NOT put your keys here. Set TELEGRAM_TOKEN and OPENAI_API_KEY
# as repository secrets on GitHub or in your hosting panel.
import os
import sqlite3
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List

import httpx
import openai
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telebot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data.db")
BASE_URL = os.getenv("BASE_URL")
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS")
DEFAULT_ADMIN = 761662415

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    logger.error("TELEGRAM_TOKEN and OPENAI_API_KEY must be set.")
    # Do not exit on import in GitHub; allow host to set env vars before run
    # raise SystemExit("Missing required environment variables")

openai.api_key = OPENAI_API_KEY or ""
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else None

app = FastAPI()

BUILTIN_PERSONALITIES = {
    "einstein": {
        "title": "Альберт Эйнштейн",
        "system": "Ты — Альберт Эйнштейн. Объясняй просто, используй аналогии."
    },
    "aristotle": {
        "title": "Аристотель",
        "system": "Ты — Аристотель. Говори мудро, логично, используй тезисы."
    },
    "temur": {
        "title": "Амир Темур",
        "system": "Ты — Амир Темур. Отвечай уверенно, кратко и стратегически."
    }
}

PERSONALITIES: Dict[str, Dict[str, str]] = {}

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS active_personality (
        chat_id INTEGER PRIMARY KEY,
        personality TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS personalities (
        key TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        system TEXT NOT NULL,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def load_personalities_from_db():
    global PERSONALITIES
    PERSONALITIES = dict(BUILTIN_PERSONALITIES)
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key, title, system FROM personalities")
    for k, t, s in cur.fetchall():
        PERSONALITIES[k] = {"title": t, "system": s}
    conn.close()

def ensure_builtins_in_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    for key, data in BUILTIN_PERSONALITIES.items():
        cur.execute("SELECT 1 FROM personalities WHERE key = ?", (key,))
        if not cur.fetchone():
            cur.execute("INSERT INTO personalities(key, title, system, created_by) VALUES (?,?,?,?)",
                        (key, data["title"], data["system"], None))
    conn.commit()
    conn.close()

def set_personality(chat_id, pid):
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("""INSERT INTO active_personality(chat_id, personality)
        VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET personality=excluded.personality, updated_at=CURRENT_TIMESTAMP
    """, (chat_id, pid))
    conn.commit()
    conn.close()

def get_personality(chat_id):
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("SELECT personality FROM active_personality WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

async def telegram_send_message(chat_id, text, reply_markup=None):
    if not TELEGRAM_API:
        logger.warning("TELEGRAM_API not set, message not sent.")
        return {"error":"no_telegram_api"}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=30)
    return r.json()

def personalities_keyboard():
    return {"inline_keyboard": [[{"text": PERSONALITIES[k]["title"], "callback_data": f"set:{k}"}] for k in PERSONALITIES.keys()]}

def call_openai(system_prompt, user_text):
    if not OPENAI_API_KEY:
        return "OpenAI key not set."
    try:
        res = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_text}],
            max_tokens=600
        )
        return res["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"OpenAI error: {e}"

async def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        data = cb["data"]
        if data.startswith("set:"):
            pid = data.split(":",1)[1]
            if pid in PERSONALITIES:
                set_personality(chat_id, pid)
                await telegram_send_message(chat_id, f"Выбран: <b>{PERSONALITIES[pid]['title']}</b>")
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text","")
        user = msg.get("from",{})
        uid = user.get("id")

        if text == "/start":
            await telegram_send_message(chat_id, "Выбери личность:", personalities_keyboard())
            return
        if text == "/switch":
            await telegram_send_message(chat_id, "Выбор личности:", personalities_keyboard())
            return
        if text.startswith("/listpersonas"):
            s = "\n".join([f"<b>{k}</b> — {p['title']}" for k,p in PERSONALITIES.items()])
            await telegram_send_message(chat_id, s or "Нет персон.")
            return

        pid = get_personality(chat_id)
        if not pid:
            await telegram_send_message(chat_id, "Личность не выбрана. Нажми /switch.")
            return
        system_prompt = PERSONALITIES[pid]["system"]
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, call_openai, system_prompt, text)
        await telegram_send_message(chat_id, reply)

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    update = await request.json()
    background_tasks.add_task(handle_update, update)
    return {"ok": True}

@app.get("/set_webhook")
async def set_webhook():
    if not BASE_URL:
        raise HTTPException(status_code=400, detail="BASE_URL not set")
    url = BASE_URL.rstrip("/") + "/webhook"
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{TELEGRAM_API}/setWebhook", data={"url": url}, timeout=15)
    return res.json()

@app.get("/health")
async def health():
    return {"status":"ok"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    import uvicorn
    init_db()
    ensure_builtins_in_db()
    load_personalities_from_db()
    uvicorn.run("main:app", host="0.0.0.0", port=port)
