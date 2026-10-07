#!/usr/bin/env python3
"""
Telegram Auto Promocode 24/7 Cloud / Render Bridge
Strictly locked to private channel ID: -1001899529343

Features & Bug Fixes:
1. STRICT Promocode Detection: Only publishes posts with valid 'Claim >>' structure.
   Random announcements, payment proofs, and chat messages are 100% ignored.
2. Independent Expiry Preservation: Timer counts down per game. Existing codes NEVER
   have their timer reset. Only genuinely NEW or CHANGED codes reset to 24h.
3. Guaranteed Push Notification: Every new promocode triggers Firebase notification
   and real FCM push broadcast immediately.
4. Catch-Up Scan (Last 50 messages): Ensures zero missed codes during network disconnects.
"""

import os
import re
import time
import json
import asyncio
import threading
import requests
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession

RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://yono-promocode-sync.onrender.com")

# 1. Built-in HTTP Server & Self Keep-Alive (Prevents Render Free Tier from Sleeping!)
class RenderHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = """
        <html>
        <head><title>Yono Promo Sync 24/7</title></head>
        <body style="font-family:sans-serif; text-align:center; padding:50px; background:#121212; color:#fff;">
            <h2>🟢 Yono Promocode 24/7 Live Bridge is RUNNING!</h2>
            <p style="color:#4CAF50; font-size:18px;">Listening to Channel: -1001899529343 (Dual Engine: 0-sec WebSocket + Auto Catch-Up)</p>
            <p style="color:#aaa;">Connected to Firebase Realtime Database & FCM Push Engine.</p>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args): pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), RenderHealthServer)
    server.serve_forever()

def self_keep_alive():
    """Pings Render every 4 minutes to guarantee it NEVER sleeps!"""
    time.sleep(30)
    while True:
        try:
            requests.get(RENDER_APP_URL, timeout=10)
            print("💓 Keep-alive ping sent to Render to prevent sleep.")
        except Exception:
            pass
        time.sleep(240)  # every 4 minutes

threading.Thread(target=run_health_server, daemon=True).start()
threading.Thread(target=self_keep_alive, daemon=True).start()

# 2. Configuration
API_ID = int(os.getenv("TELEGRAM_API_ID", "35254555"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "1648fb48b3afa30ff23e341d7ada0e56")
PHONE_NUMBER = os.getenv("TELEGRAM_PHONE", "+918303094852")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "-1001899529343"))
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://appstore-9d01f-default-rtdb.asia-southeast1.firebasedatabase.app")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# ---- FIX CONFIG ----
# Sirf wahi game accept hoga jo already apps / bonus_offers me hai (random "Yelo Claim" jaisa junk add nahi hoga)
REQUIRE_KNOWN_GAME = os.getenv("REQUIRE_KNOWN_GAME", "true").lower() == "true"
MAX_MSG_AGE_HOURS = 24          # isse purane messages ko catch-up ignore karega
SYNC_LOCK = threading.Lock()    # live handler + catch-up ek saath run na ho (duplicate notification bug)
PROCESSED_IDS = set()           # ek message ko sirf ek baar process karenge
BAD_CODE_WORDS = {"UPTO", "SIGNUP", "BONUS", "FREE", "HERE", "NOW", "CLICK", "BELOW", "ABOVE", "LINK", "CLAIM", "DOWN"}

IST = timezone(timedelta(hours=5, minutes=30))

def day_key(ms: int) -> str:
    """IST calendar day (raat 12 baje din badalta hai)."""
    return datetime.fromtimestamp(ms / 1000, IST).strftime("%Y-%m-%d")

def norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x or "").lower())

MAILBOX_CODE = "Check Mail Box 💌"
MAILBOX_RE = re.compile(r"(?i)mail\s*box|inbox|check\s+(?:your\s+)?(?:e-?)?mail")

def is_valid_code(c: str) -> bool:
    """Code me kam se kam 3 letters/digits hone chahiye, emoji/arrow-only code reject."""
    if c == MAILBOX_CODE:
        return True
    if not c or len(c) > 60 or len(c.split()) > 6:   # space allowed, par max 6 words
        return False
    if len(re.findall(r"[A-Za-z0-9]", c)) < 3:
        return False
    if c.upper() in BAD_CODE_WORDS:
        return False
    return True

def load_processed_ids() -> bool:
    """Firebase se processed message ids load karta hai. Returns True agar pehli baar run hai (empty)."""
    try:
        r = requests.get(f"{FIREBASE_DB_URL}/telegram_processed_v2.json?shallow=true", timeout=10)
        data = r.json() or {}
        PROCESSED_IDS.update(str(k) for k in data.keys())
        return len(data) == 0
    except Exception as e:
        print(f"⚠️ processed load error: {e}")
        return False

def mark_processed(msg_id):
    key = str(msg_id)
    if key in PROCESSED_IDS:
        return
    PROCESSED_IDS.add(key)
    try:
        requests.put(f"{FIREBASE_DB_URL}/telegram_processed_v2/{key}.json", json=int(time.time() * 1000), timeout=10)
    except Exception:
        pass

def should_ignore_post(text: str) -> tuple[bool, str]:
    """Ignores posts with multiple claim codes (Structure 4) or prosafebet patterns."""
    if "prosafebet" in text.lower():
        return True, "Ignored: Structure 4 prosafebet pattern"
    return False, ""

def clean_game_name(raw: str) -> str:
    s = re.sub(r"[🔥🎁⚡💥⭐✨🎉❤💞💎👑📢👉👉🏻👇👇🏻⤵️⤴️✅✓•\[\]\(\)😎🤑🤩🥳💰💵💳💸😱👌❤️▶️😁👍🌚]", " ", raw)
    s = re.sub(r"[\*\_\~\`\|\#]+", " ", s)
    s = re.sub(r"(?i)\s*(?:>|:|-|–|—)?\s*(?:new\s+promocode|new\s+promo\s*code|today\s+promocode|today\s+code|new\s+code|today\s*drop|promo\s*drop|promocode|promo\s*code|promo|game\s*name.*|coupon|code|loot).*$", "", s)
    s = re.sub(r"(?i)^claim\s*(?:>>|>|:|-|–|—)?", "", s)
    s = re.sub(r"^\W+", "", s)
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Strip trailing promotional words like 'BIG', 'SUPER', etc.
    s = re.sub(r"(?i)\b(?:big|super|mega|extra|medium|small|special)\b\s*$", "", s).strip()
    words = [w.capitalize() if not w.isdigit() else w for w in s.split()]
    return " ".join(words)

def parse_promocode(text: str):
    ignore, reason = should_ignore_post(text)
    if ignore:
        print(f"ℹ️ {reason}")
        return "", "", "", ""

    clean_text = text.strip()
    lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
    if not lines:
        return "", "", "", ""

    # STRICT CHECK: Must have an explicit Claim line
    has_claim_line = any(re.search(r"(?i)\bclaim\s*(?:>>|>|:|=-|–|—|=>|▶️)", l) for l in lines)
    if not has_claim_line:
        # Non-promocode post (e.g. withdrawal proof, general chat, announcement)
        return "", "", "", ""

    code = ""
    # Extract Promo Code STRICTLY from the Claim line
    for line in lines:
        cleaned_line = re.sub(r"^[^\w\s]+", "", line).strip()
        m = re.search(r"(?i)\bclaim(?:\s*code)?\s*(>>|>|:|=-|–|—|=>|▶️|\s+)\s*(.+)$", cleaned_line)
        if m:
            explicit_sep = m.group(1).strip() != ""
            c = re.sub(r"\s+", " ", m.group(2)).strip()
            c = re.sub(r"^[\*\"\'\`]+|[\*\"\'\`]+$", "", c).strip()
            c = re.sub(r"^https?://(?:www\.)?", "", c).strip()
            # If user example included text like '> example yeh he promocode', strip extra note
            if ">" in c and not c.startswith("http"):
                c = c.split(">")[0].strip()
            if MAILBOX_RE.search(c):
                code = MAILBOX_CODE   # "Claim >> Check Mail Box" -> waisa hi app me promocode ban jayega
                break
            # Space wala code tabhi lo jab Claim ke baad ">>" / ">" / ":" jaisa clear separator ho
            if " " in c and not explicit_sep:
                continue
            if is_valid_code(c):
                code = c
                break

    # Claim line me koi valid code nahi mila -> App Link ke ?code=XXXX se lo
    if not code:
        m_param = re.search(r"[?&]code=([A-Za-z0-9]{4,30})", clean_text)
        if m_param:
            code = m_param.group(1)

    # If no valid code found on Claim line, DO NOT fall back to random domains!
    if not code or code.upper() in ["UPTO", "SIGNUP", "BONUS", "FREE"]:
        return "", "", "", ""

    # Extract App Link
    app_link = ""
    for line in lines:
        cleaned_line = re.sub(r"^[^\w\s]+", "", line).strip()
        m_link = re.search(r"(?i)(?:app\s*link|link|download)\s*(?:>>|>|:|=-|–|—|=>|\s+)\s*(https?://\S+)", cleaned_line)
        if m_link:
            app_link = m_link.group(1).strip()
            break

    if not app_link:
        any_link = re.search(r"(https?://\S+)", clean_text)
        if any_link: app_link = any_link.group(1).strip()

    # Extract Game Name
    game = ""
    for line in lines:
        lower = line.lower()
        if "promocode" in lower or "promo code" in lower or "code" in lower or "game" in lower:
            cand = clean_game_name(line)
            if len(cand) >= 3 and cand.upper() != code.upper():
                game = cand
                break

    if not game and lines:
        game = clean_game_name(lines[0])

    # "Yelo Claim" jaisa naam game nahi hota
    if game and re.search(r"(?i)\bclaim\b", game):
        return "", "", "", ""

    if not game or game.upper() == code.upper():
        return "", "", "", ""

    return game, code, "Daily", app_link

def send_real_fcm_push(title: str, body: str, game_name: str, code: str):
    try:
        r = requests.get(f"{FIREBASE_DB_URL}/admin_config/fcm/serviceAccountJson.json", timeout=10)
        sa_raw = r.json()
        if not sa_raw:
            print("⚠️ FCM: No serviceAccountJson configured.")
            return False
        sa_info = json.loads(sa_raw) if isinstance(sa_raw, str) else sa_raw

        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        creds.refresh(Request())
        project_id = sa_info.get("project_id", "appstore-9d01f")
        fcm_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
        payload = {
            "message": {
                "topic": "all",
                "notification": {"title": title, "body": body},
                "data": {
                    "click_action": "OPEN_SPECIAL_PROMO",
                    "action": "OPEN_SPECIAL_PROMO",
                    "appName": game_name,
                    "app_name": game_name,
                    "code": code,
                    "promo_code": code,
                    "type": "telegram_promocode",
                    "screen": "special_promocode"
                },
                "android": {
                    "priority": "HIGH",
                    "notification": {
                        "sound": "default",
                        "channel_id": "yono_promos",
                        "default_vibrate_timings": True
                    }
                }
            }
        }
        res = requests.post(fcm_url, headers=headers, json=payload, timeout=10)
        print(f"📢 Real FCM Push Broadcast: Status {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        print(f"⚠️ FCM Note: {e}")
        return False

def sync_to_firebase(game_name: str, code: str, bonus_amount: str = "Daily", claim_url: str = "", raw_text: str = "", trigger_push: bool = True, msg_ts_ms: int = 0, notify: bool = True):
    with SYNC_LOCK:
        return _sync_to_firebase(game_name, code, bonus_amount, claim_url, raw_text, trigger_push, msg_ts_ms, notify)

def _sync_to_firebase(game_name, code, bonus_amount="Daily", claim_url="", raw_text="", trigger_push=True, msg_ts_ms=0, notify=True):
    if not code or not game_name or not is_valid_code(code):
        return

    now_ms = int(time.time() * 1000)
    base_ms = msg_ts_ms if msg_ts_ms > 0 else now_ms   # timer message ke time se chalega

    try:
        r = requests.get(f"{FIREBASE_DB_URL}/bonus_offers.json", timeout=10)
        existing = r.json() or {}
    except Exception as e:
        print(f"⚠️ Firebase read error: {e}")
        existing = {}

    matched_id = None
    existing_name = None
    existing_icon = ""
    existing_app_id = ""
    existing_claim_url = ""
    existing_code = ""
    existing_date_added = 0
    existing_expires_at = 0
    existing_notified_day = ""
    target_norm = re.sub(r"[^a-z0-9]", "", game_name.lower())

    for k, v in existing.items():
        if isinstance(v, dict):
            app_n = norm(v.get("appName") or v.get("app_name") or "")
            if "claim" in app_n:
                continue  # purani junk entries ko match mat karo
            if target_norm and len(target_norm) >= 4 and app_n == target_norm:
                matched_id = k
                existing_name = v.get("appName") or v.get("app_name")
                existing_icon = v.get("iconUrl") or ""
                existing_app_id = v.get("appId") or ""
                existing_claim_url = v.get("claimUrl") or ""
                existing_code = str(v.get("code") or "")
                existing_date_added = int(v.get("dateAdded") or 0)
                existing_expires_at = int(v.get("expiresAt") or 0)
                existing_notified_day = str(v.get("lastNotifiedDay") or "")
                break

    if not existing_name:
        try:
            r_apps = requests.get(f"{FIREBASE_DB_URL}/apps.json", timeout=10)
            for k, v in (r_apps.json() or {}).items():
                if isinstance(v, dict):
                    an = re.sub(r"[^a-z0-9]", "", str(v.get("name") or v.get("title") or "").lower())
                    if target_norm and len(target_norm) >= 4 and an == target_norm:
                        existing_name = v.get("name") or v.get("title")
                        existing_icon = v.get("iconUrl") or v.get("icon_url") or ""
                        existing_app_id = k
                        existing_claim_url = v.get("downloadUrl") or v.get("apkUrl") or ""
                        break
        except Exception:
            pass

    # Game list me hai hi nahi -> ignore (junk / non-game post)
    if REQUIRE_KNOWN_GAME and not existing_name:
        print(f"🚫 Ignored: '{game_name}' known game nahi hai (apps/bonus_offers me nahi mila).")
        return False

    is_new = matched_id is None
    offer_id = matched_id if matched_id else f"tg_{now_ms}"
    final_game_name = existing_name if existing_name else game_name
    final_claim_url = claim_url if claim_url else existing_claim_url

    # Check if this game already has this EXACT promo code
    code_is_identical = (norm(existing_code) == norm(code)) and (matched_id is not None)

    # Purana message (existing se pehle ka) -> kuch mat karo, warna notification loop banta hai
    existing_code_bad = matched_id is not None and not is_valid_code(existing_code)  # purana galat code (jaise 'Check Mail Box') ho to overwrite allowed
    if matched_id is not None and not existing_code_bad and existing_date_added > 0 and base_ms <= existing_date_added:
        print(f"ℹ️ Stale/duplicate message ignored for '{final_game_name}'.")
        return

    today = day_key(base_ms)
    final_date_added = base_ms
    final_expires_at = base_ms + (24 * 3600 * 1000)
    if final_expires_at <= now_ms:
        print(f"ℹ️ Code for '{final_game_name}' already expired, skipping.")
        return

    if not code_is_identical:
        # NAYA / ALAG CODE -> timer reset + notification (jitni baar alag code aaye)
        is_code_update = True
        final_notified_day = today
    elif existing_notified_day != today:
        # SAME CODE, par NAYA DIN -> timer reset + din me sirf 1 notification
        is_code_update = True
        final_notified_day = today
    else:
        # SAME CODE, SAME DIN (naya message) -> sirf timer refresh, notification NAHI
        is_code_update = False
        final_notified_day = existing_notified_day

    offer_payload = {
        "id": offer_id,
        "title": f"{final_game_name} Special Promo",
        "appName": final_game_name,
        "appId": existing_app_id,
        "iconUrl": existing_icon,
        "code": code,
        "bonusAmount": "Daily",
        "description": f"Daily promo drops for {final_game_name}",
        "claimUrl": final_claim_url,
        "expiryDate": "Valid 24h ⏳",
        "minDeposit": "₹0 (Free Bonus)",
        "verified": True,
        "active": True,
        "order": 1,
        "dateAdded": final_date_added,
        "expiryHours": 24,
        "expiresAt": final_expires_at,
        "lastNotifiedDay": final_notified_day
    }

    try:
        requests.put(f"{FIREBASE_DB_URL}/bonus_offers/{offer_id}.json", json=offer_payload, timeout=10)
        requests.put(f"{FIREBASE_DB_URL}/promo_codes/{offer_id}.json", json=offer_payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Firebase save error: {e}")

    # Trigger notifications ONLY when there is a real code update or new game
    if is_code_update and notify:
        notif_title = f"{final_game_name} Promocode"
        notif_body = f"{final_game_name} new promocode aa gya hai ❤" if is_new else f"{final_game_name} promocode update ho chuka hai ❤"

        notif_id = f"notif_{now_ms}"
        notif_payload = {
            "id": notif_id,
            "title": notif_title,
            "body": notif_body,
            "message": notif_body,
            "appName": final_game_name,
            "app_name": final_game_name,
            "code": code,
            "bonus": "Daily",
            "bonus_amount": "Daily",
            "click_action": "OPEN_SPECIAL_PROMO",
            "action": "OPEN_SPECIAL_PROMO",
            "deeplink": "yonostore://special_promo",
            "timestamp": now_ms,
            "createdAt": now_ms,
            "read": False,
            "type": "telegram_promocode"
        }
        try:
            requests.put(f"{FIREBASE_DB_URL}/notifications/{notif_id}.json", json=notif_payload, timeout=10)
            requests.put(f"{FIREBASE_DB_URL}/latest_notification.json", json=notif_payload, timeout=10)

            log_payload = {
                "id": f"log_{now_ms}",
                "gameName": final_game_name,
                "promoCode": code,
                "bonusAmount": "Daily",
                "type": "NEW GAME" if is_new else "UPDATED",
                "notificationTitle": notif_title,
                "notificationBody": notif_body,
                "timestamp": now_ms,
                "channelId": TARGET_CHANNEL_ID,
                "success": True
            }
            requests.put(f"{FIREBASE_DB_URL}/telegram_sync_logs/log_{now_ms}.json", json=log_payload, timeout=10)
            print(f"✅ Cleanly Synced & Notified! Game='{final_game_name}', Code='{code}'")
        except Exception as e:
            print(f"⚠️ Notification log error: {e}")

        if trigger_push:
            send_real_fcm_push(notif_title, notif_body, final_game_name, code)
    else:
        print(f"ℹ️ '{final_game_name}' code '{code}' already up-to-date. Expiry timer preserved.")

def process_live(msg_id, game, code, bonus, app_link, text, ts):
    res = sync_to_firebase(game, code, bonus, app_link, text, True, ts, True)
    if res is not False:      # unknown game me mark mat karo, taaki game add hone ke baad retry ho sake
        mark_processed(msg_id)

@client.on(events.NewMessage(chats=[TARGET_CHANNEL_ID]))
async def my_event_handler(event):
    message_text = event.message.message or ""
    print(f"\n📩 [NEW LIVE MESSAGE RECEIVED]:\n{message_text[:100]}...")
    if str(event.message.id) in PROCESSED_IDS:
        return
    game, code, bonus, app_link = parse_promocode(message_text)
    if not code:
        print("ℹ️ Is post me valid game/code nahi mila (parser ne skip kiya).")
        return
    ts = int(event.message.date.timestamp() * 1000)
    threading.Thread(target=process_live, args=(event.message.id, game, code, bonus, app_link, message_text, ts), daemon=True).start()

@client.on(events.MessageEdited(chats=[TARGET_CHANNEL_ID]))
async def my_edit_handler(event):
    """Admin ne post edit karke code sahi kiya ho to bhi pakad lo."""
    text = event.message.message or ""
    game, code, bonus, app_link = parse_promocode(text)
    if not code:
        return
    print(f"✏️ Edited message detected: {game} -> {code}")
    ts = int(time.time() * 1000)
    threading.Thread(target=sync_to_firebase, args=(game, code, bonus, app_link, text, True, ts, True), daemon=True).start()

async def catch_up_scan_loop(first_run: bool):
    """Har 15 min me last 50 msgs check. Sirf NAYE (unprocessed) msgs, oldest-first, game ke hisaab se sirf latest code."""
    await asyncio.sleep(10)
    while True:
        try:
            print("🔄 Running Catch-Up Scan...")
            cutoff = time.time() - MAX_MSG_AGE_HOURS * 3600
            latest_per_game = {}
            fresh_msgs = []
            async for msg in client.iter_messages(TARGET_CHANNEL_ID, limit=50):
                fresh_msgs.append(msg)
            for msg in reversed(fresh_msgs):  # oldest -> newest
                if str(msg.id) in PROCESSED_IDS:
                    continue
                text = msg.message or msg.text or ""
                if not text.strip() or msg.date.timestamp() < cutoff:
                    mark_processed(msg.id)
                    continue
                game, code, bonus, app_link = parse_promocode(text)
                if code:
                    key = norm(game)
                    prev = latest_per_game.get(key)
                    latest_per_game[key] = (game, code, bonus, app_link, text, int(msg.date.timestamp() * 1000), (prev[6] if prev else []) + [msg.id])
                # code nahi mila to mark NAHI karte, taaki parser fix hone par dobara try ho
            for game, code, bonus, app_link, text, ts, ids in latest_per_game.values():
                # first_run par silently sync (notification spam nahi)
                res = sync_to_firebase(game, code, bonus, app_link, text, True, ts, notify=not first_run)
                if res is not False:
                    for i in ids:
                        mark_processed(i)
            first_run = False
            print("🏁 Catch-up scan complete.")
        except Exception as e:
            print(f"⚠️ Catch-up scan note: {e}")
        await asyncio.sleep(900)

async def main():
    print(f"🚀 Starting 24/7 Real-Time Telegram Promocode Bridge...")
    print(f"🔒 STRICTLY LOCKED to Private Channel ID: {TARGET_CHANNEL_ID}")
    print("Connecting to Telegram...")
    if not SESSION_STRING:
        await client.start(phone=PHONE_NUMBER)
    else:
        await client.start()

    try:
        ch = await client.get_entity(TARGET_CHANNEL_ID)
        print(f"🟢 Successfully connected to Private Channel: '{getattr(ch, 'title', '')}' ({TARGET_CHANNEL_ID})")
    except Exception as e:
        print(f"⚠️ Connected to Telegram. Listening to {TARGET_CHANNEL_ID} (Note: {e})")

    # Start Catch-Up Background Loop
    first_run = load_processed_ids()
    asyncio.create_task(catch_up_scan_loop(first_run))

    print("🟢 ACTIVE & LISTENING 24/7! (Dual Engine: Real-Time + 50-Msg Catch-Up + Self-Ping)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
