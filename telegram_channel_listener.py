import os, re, time, json, threading, requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# HTTP Health Server for Render Free Tier
class RenderHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<html><body><h2>Yono Promocode 24/7 Live Bridge is RUNNING!</h2></body></html>")
    def log_message(self, format, *args): pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), RenderHealthServer)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# Configuration
API_ID = int(os.getenv("TELEGRAM_API_ID", "35254555"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "1648fb48b3afa30ff23e341d7ada0e56")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "-1001899529343"))
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://appstore-9d01f-default-rtdb.asia-southeast1.firebasedatabase.app")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

def clean_game_name(raw: str) -> str:
    s = re.sub(r"[🔥🎁⚡💥⭐✨🎉❤💞💎👑📢👉👉🏻👇👇🏻⤵️⤴️✅✓•\[\]\(\)😎🤑🤩🥳💰💵💳💸😱👌❤️]", " ", raw)
    s = re.sub(r"[\*\_\~\`\|\#]+", " ", s)
    s = re.sub(r"(?i)\s*(?:>|:|-|–|—)?\s*(?:new\s+promocode|new\s+promo\s*code|promocode|promo\s*code|game\s*name.*|code).*$", "", s)
    s = re.sub(r"(?i)^claim\s*(?:>>|>|:|-|–|—)?", "", s)
    s = re.sub(r"^\W+", "", s)
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    words = [w.capitalize() if not w.isdigit() else w for w in s.split()]
    return " ".join(words)

def parse_promocode(text: str):
    clean_text = text.strip()
    lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
    code, game, app_link = "", "", ""

    for line in lines:
        m = re.search(r"(?i)^claim\s*(?:>>|>|:|=-|–|—|=>)\s*(.+)$", line)
        if m:
            c = m.group(1).strip()
            c = re.sub(r"^[\*\"\'\`]+|[\*\"\'\`]+$", "", c).strip()
            if not c.startswith("http://") and not c.startswith("https://") and len(c) >= 3:
                code = c
                break

    if not code:
        text_no_http = re.sub(r"https?://\S+", " ", clean_text)
        dom = re.search(r"\b([A-Za-z0-9._\-]+\.(?:com|app|win|vip|xyz|in|net|org|bet|diy|casino))\b", text_no_http, re.IGNORECASE)
        if dom: code = dom.group(1).strip()

    if not code or code.upper() in ["UPTO", "SIGNUP", "BONUS", "FREE"]:
        return "", "", "", ""

    for line in lines:
        m_link = re.search(r"(?i)(?:app\s*link|link|download)\s*(?:>>|>|:|=-|–|—|=>)\s*(https?://\S+)", line)
        if m_link:
            app_link = m_link.group(1).strip()
            break

    for line in lines:
        if "promocode" in line.lower() or "promo code" in line.lower():
            cand = clean_game_name(line)
            if len(cand) >= 3:
                game = cand
                break

    if not game and lines: game = clean_game_name(lines[0])
    if not game: game = "Special Promo Game"

    return game, code, "Daily", app_link

def send_real_fcm_push(title: str, body: str, game_name: str, code: str):
    try:
        r = requests.get(f"{FIREBASE_DB_URL}/admin_config/fcm/serviceAccountJson.json", timeout=10)
        sa_raw = r.json()
        if not sa_raw: return False
        sa_info = json.loads(sa_raw) if isinstance(sa_raw, str) else sa_raw

        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        creds.refresh(Request())
        fcm_url = f"https://fcm.googleapis.com/v1/projects/{sa_info.get('project_id', 'appstore-9d01f')}/messages:send"
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
        payload = {
            "message": {
                "topic": "all",
                "notification": {"title": title, "body": body},
                "data": {"click_action": "OPEN_SPECIAL_PROMO", "appName": game_name, "code": code, "type": "telegram_promocode"},
                "android": {"priority": "HIGH", "notification": {"sound": "default", "channel_id": "yono_promos", "default_vibrate_timings": True}}
            }
        }
        res = requests.post(fcm_url, headers=headers, json=payload, timeout=10)
        print(f"📢 Real FCM Push Broadcast: Status {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        print(f"⚠️ FCM Note: {e}")
        return False

def sync_to_firebase(game_name: str, code: str, bonus_amount: str = "Daily", claim_url: str = "", raw_text: str = ""):
    if not code or not game_name or code.upper() in ["UPTO", "SIGNUP", "BONUS", "FREE"]:
        return

    now_ms = int(time.time() * 1000)
    expires_at = now_ms + (24 * 3600 * 1000)

    r = requests.get(f"{FIREBASE_DB_URL}/bonus_offers.json", timeout=10)
    existing = r.json() or {}
    matched_id, existing_name, existing_icon, existing_app_id, existing_claim_url = None, None, "", "", ""
    target_norm = re.sub(r"[^a-z0-9]", "", game_name.lower())

    for k, v in existing.items():
        if isinstance(v, dict):
            app_n = re.sub(r"[^a-z0-9]", "", str(v.get("appName") or v.get("app_name") or "").lower())
            if target_norm and len(target_norm) >= 4 and app_n == target_norm:
                matched_id = k
                existing_name = v.get("appName") or v.get("app_name")
                existing_icon = v.get("iconUrl") or ""
                existing_app_id = v.get("appId") or ""
                existing_claim_url = v.get("claimUrl") or ""
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
        except Exception: pass

    is_new = matched_id is None
    offer_id = matched_id if matched_id else f"tg_{now_ms}"
    final_game_name = existing_name if existing_name else game_name
    final_claim_url = claim_url if claim_url else existing_claim_url

    notif_title = f"{final_game_name} Promocode"
    notif_body = f"{final_game_name} new promocode aa gya hai ❤" if is_new else "Promocode update ho chuka hai ❤"

    offer_payload = {
        "id": offer_id, "title": f"{final_game_name} Special Promo", "appName": final_game_name,
        "appId": existing_app_id, "iconUrl": existing_icon, "code": code,
        "bonusAmount": "Daily", "description": f"Daily promo drops for {final_game_name}",
        "claimUrl": final_claim_url, "expiryDate": "Valid 24h ⏳", "minDeposit": "₹0 (Free Bonus)",
        "verified": True, "active": True, "order": 1, "dateAdded": now_ms,
        "expiryHours": 24, "expiresAt": expires_at
    }

    requests.put(f"{FIREBASE_DB_URL}/bonus_offers/{offer_id}.json", json=offer_payload, timeout=10)
    requests.put(f"{FIREBASE_DB_URL}/promo_codes/{offer_id}.json", json=offer_payload, timeout=10)

    notif_id = f"notif_{now_ms}"
    notif_payload = {
        "id": notif_id, "title": notif_title, "body": notif_body, "message": notif_body,
        "appName": final_game_name, "app_name": final_game_name, "code": code,
        "bonus": "Daily", "bonus_amount": "Daily", "click_action": "OPEN_SPECIAL_PROMO",
        "action": "OPEN_SPECIAL_PROMO", "deeplink": "yonostore://special_promo",
        "timestamp": now_ms, "createdAt": now_ms, "read": False, "type": "telegram_promocode"
    }
    requests.put(f"{FIREBASE_DB_URL}/notifications/{notif_id}.json", json=notif_payload, timeout=10)
    requests.put(f"{FIREBASE_DB_URL}/latest_notification.json", json=notif_payload, timeout=10)

    log_payload = {
        "id": f"log_{now_ms}", "gameName": final_game_name, "promoCode": code, "bonusAmount": "Daily",
        "type": "NEW GAME" if is_new else "UPDATED", "notificationTitle": notif_title,
        "notificationBody": notif_body, "timestamp": now_ms, "channelId": TARGET_CHANNEL_ID, "success": True
    }
    requests.put(f"{FIREBASE_DB_URL}/telegram_sync_logs/log_{now_ms}.json", json=log_payload, timeout=10)
    print(f"✅ Cleanly Synced! Game='{final_game_name}', Code='{code}', Title='{notif_title}', Body='{notif_body}'")

    send_real_fcm_push(notif_title, notif_body, final_game_name, code)

@client.on(events.NewMessage(chats=[TARGET_CHANNEL_ID]))
async def my_event_handler(event):
    message_text = event.message.message or ""
    print(f"\n📩 [REAL-TIME 0-SEC EVENT] New message in private channel ({TARGET_CHANNEL_ID}):\n{message_text[:120]}...")
    game, code, bonus, app_link = parse_promocode(message_text)
    if code:
        sync_to_firebase(game, code, bonus, app_link, message_text)

async def main():
    print(f"🚀 Starting 24/7 Real-Time Telegram Promocode Bridge...")
    print(f"🔒 STRICTLY LOCKED to Private Channel ID: {TARGET_CHANNEL_ID}")
    if not SESSION_STRING:
        await client.start(phone=PHONE_NUMBER)
    else:
        await client.start()

    try:
        ch = await client.get_entity(TARGET_CHANNEL_ID)
        print(f"🟢 Successfully connected to Private Channel: '{getattr(ch, 'title', '')}' ({TARGET_CHANNEL_ID})")
    except Exception as e:
        print(f"⚠️ Connected to Telegram. Listening to {TARGET_CHANNEL_ID} (Note: {e})")

    print("🟢 ACTIVE & LISTENING 24/7! (Incoming messages trigger in 0.1s instant!)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
