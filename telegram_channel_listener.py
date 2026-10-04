import os, re, time, requests
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "35254555"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "1648fb48b3afa30ff23e341d7ada0e56")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "-1001899529343"))
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://appstore-9d01f-default-rtdb.asia-southeast1.firebasedatabase.app")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

STOP_WORDS = set([
    "UPTO", "SIGNUP", "SIGN", "BONUS", "FREE", "CLAIM", "OFFER", "CODE",
    "PROMO", "PROMOCODE", "TODAY", "SPECIAL", "DAILY", "LOOT", "VERIFIED",
    "VALID", "TIME", "LIMITED", "CASH", "MONEY", "PLAY", "WIN", "GAME", "GAMES",
    "APP", "APPS", "DOWNLOAD", "REGISTER", "CLICK", "GET", "WELCOME", "VIP",
    "NEW", "SHARE", "ALL", "EARNER", "CHANNEL", "JOIN", "LINK", "JACKPOT",
    "WITHDRAW", "DEPOSIT", "CHECK", "MAIL", "BOX", "UPDATE", "HTTP", "HTTPS", "TELEGRAM"
])

def is_valid_promocode(cand):
    if not cand or len(cand) < 4 or len(cand) > 35: return False
    if cand.upper().strip() in STOP_WORDS: return False
    if cand.startswith("http://") or cand.startswith("https://") or "?" in cand or "=" in cand or "/" in cand:
        return False
    return True

def clean_game_name(raw):
    s = re.sub(r"[🔥🎁⚡💥⭐✨🎉❤💞💎👑📢👉👉🏻👇👇🏻⤵️⤴️✅✓•\[\]\(\)😎🤑🤩🥳💰💵💳💸]", " ", raw)
    s = re.sub(r"[\*\_\~\`\|\#]+", " ", s)
    s = re.sub(r"(?i)\s*(?:>|:|-|–|—)?\s*(?:game\s*name.*|new\s+promocode|new\s+promo\s*code|promocode|promo\s*code|code).*$", "", s)
    s = re.sub(r"(?i)^claim\s*(?:>>|>|:|-|–|—)?", "", s)
    s = re.sub(r"^\W+", "", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_promocode(text):
    clean_text = text.strip()
    now_time = datetime.now().strftime("%I:%M %p")
    text_no_http = re.sub(r"https?://\S+", " ", clean_text)

    code = ""
    # Priority A: "Claim >> spingoldg.com" or "Code: winrummy.app"
    m = re.search(r"(?i)(?:claim|code|promo(?:code)?|coupon)\s*(?:>>|>|:|=-|–|—|=>|\s+)\s*([A-Za-z0-9._\-]{4,35})", text_no_http)
    if m and is_valid_promocode(m.group(1)):
        code = m.group(1).strip()

    # Priority B: Domain-style promocode (spingoldg.com, winrummy.app, JAIHO777.COM)
    if not code:
        dom_match = re.search(r"\b([A-Za-z0-9._\-]+\.(?:com|app|win|vip|xyz|in|net|org))\b", text_no_http, re.IGNORECASE)
        if dom_match and is_valid_promocode(dom_match.group(1)):
            code = dom_match.group(1).strip()

    # Priority C: Token with letters and numbers (Neta.Vip1749633)
    if not code:
        for t in re.findall(r"\b[A-Za-z0-9._\-]{5,25}\b", text_no_http):
            if is_valid_promocode(t) and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
                code = t.strip()
                break

    if not code: return "", "", ""

    # Game Name
    game = ""
    lbl = re.search(r"(?i)(?:game\s*name|game|app|application)\s*[:=\-–—>]\s*([^\n\r,]+)", text_no_http)
    if lbl:
        c = clean_game_name(lbl.group(1))
        if len(c) >= 3 and not c.startswith("..."): game = c

    if not game:
        for line in [l.strip() for l in text_no_http.split("\n") if l.strip()][:3]:
            c = clean_game_name(line)
            if c and len(c) >= 3 and not c.startswith("...") and c.upper() != code.upper() and c.upper() not in STOP_WORDS:
                game = c
                break

    if not game:
        clean_cand = re.sub(r"\.(?:com|app|win|vip|xyz|in|net|org)$", "", code, flags=re.IGNORECASE)
        game = clean_cand.title() if len(clean_cand) >= 3 else "Special Promo Game"

    b_match = re.search(r"(?i)(?:bonus\s*upto|signup\s*bonus|bonus|amount|get|claim|free|upto)\s*[:=\-–—]?\s*(?:₹|Rs\.?|INR)?\s*([0-9]{1,5})", clean_text)
    bonus = f"₹{b_match.group(1)} ({now_time})" if b_match else f"₹50 ({now_time})"

    return game, code, bonus

def sync_to_firebase(game_name, code, bonus_amount, raw_text=""):
    if not code or not game_name or not is_valid_promocode(code):
        print(f"⚠️ Skipped invalid promo: Game='{game_name}', Code='{code}'")
        return

    now_ms = int(time.time() * 1000)
    expires_at = now_ms + (24 * 3600 * 1000)

    r = requests.get(f"{FIREBASE_DB_URL}/bonus_offers.json", timeout=10)
    existing = r.json() or {}
    matched_id = None
    existing_name = None
    existing_icon = ""
    existing_app_id = ""
    target_norm = re.sub(r"[^a-z0-9]", "", game_name.lower())

    for k, v in existing.items():
        if isinstance(v, dict):
            app_n = re.sub(r"[^a-z0-9]", "", str(v.get("appName") or v.get("app_name") or "").lower())
            if target_norm and len(target_norm) >= 4 and app_n == target_norm:
                matched_id = k
                existing_name = v.get("appName") or v.get("app_name")
                existing_icon = v.get("iconUrl") or ""
                existing_app_id = v.get("appId") or ""
                break

    is_new = matched_id is None
    offer_id = matched_id if matched_id else f"tg_{now_ms}"
    final_game_name = existing_name if (existing_name and not is_new) else game_name

    notif_title = f"{final_game_name} ka New Promocode aa gya hai 💞" if is_new else f"{final_game_name} promocode update ho gya hai 💞"
    notif_body = f"{final_game_name} ka New Promocode aa gya hai 💞 - Abhi open karke bonus claim karo!" if is_new else f"{final_game_name} promocode update ho gya hai 💞 - Abhi claim karein!"

    offer_payload = {
        "id": offer_id, "title": f"{final_game_name} Special Promo", "appName": final_game_name,
        "appId": existing_app_id, "iconUrl": existing_icon, "code": code,
        "bonusAmount": bonus_amount, "description": f"Daily promo drops for {final_game_name}",
        "claimUrl": "", "expiryDate": "Valid 24h ⏳", "minDeposit": "₹0 (Free Bonus)",
        "verified": True, "active": True, "order": 1, "dateAdded": now_ms,
        "expiryHours": 24, "expiresAt": expires_at
    }

    requests.put(f"{FIREBASE_DB_URL}/bonus_offers/{offer_id}.json", json=offer_payload, timeout=10)
    requests.put(f"{FIREBASE_DB_URL}/promo_codes/{offer_id}.json", json=offer_payload, timeout=10)

    notif_payload = {
        "id": f"notif_{now_ms}", "title": notif_title, "body": notif_body, "message": notif_body,
        "appName": final_game_name, "timestamp": now_ms, "createdAt": now_ms, "read": False, "type": "telegram_promocode"
    }
    requests.put(f"{FIREBASE_DB_URL}/notifications/notif_{now_ms}.json", json=notif_payload, timeout=10)
    print(f"✅ Synced! Game='{final_game_name}', Code='{code}', Bonus='{bonus_amount}'")

@client.on(events.NewMessage(chats=[TARGET_CHANNEL_ID]))
async def my_event_handler(event):
    message_text = event.message.message or ""
    print(f"\n📩 New message in private channel ({TARGET_CHANNEL_ID}):\n{message_text[:120]}...")
    game, code, bonus = parse_promocode(message_text)
    if code:
        sync_to_firebase(game, code, bonus, message_text)
