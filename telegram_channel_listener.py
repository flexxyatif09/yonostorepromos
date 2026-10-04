import os, re, time, requests
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "35254555"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "1648fb48b3afa30ff23e341d7ada0e56")
PHONE_NUMBER = os.getenv("TELEGRAM_PHONE", "+918303094852")
TARGET_CHANNEL = os.getenv("TELEGRAM_TARGET_CHANNEL", "All Yono Earner")
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://appstore-9d01f-default-rtdb.asia-southeast1.firebasedatabase.app")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "").strip()

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

def clean_emoji(s):
    return re.sub(r"[\s]+", " ", re.sub(r"[🔥🎁⚡💥⭐✨🎉❤💞💎👑📢👉👉🏻👇👇🏻⤵️⤴️✅✓•\[\]\(\)😎🤑🤩🥳💰💵💳]", " ", s)).strip()

def parse_promocode(text):
    clean_text = text.strip()
    now_time = datetime.now().strftime("%I:%M %p")
    post_time_tag = f"Post Time# {now_time}"

    text_no_url = re.sub(r"https?://\S+", " ", clean_text)
    text_no_url = re.sub(r"[a-zA-Z0-9.-]+\.(?:xyz|com|net|org|app|in|io|me|vip|top|site|link)\S*", " ", text_no_url)

    arrow_match = re.search(r"(?i)(?:claim|code|promo(?:code)?|coupon|bonus)\s*(?:>>|>|:|=-|–|—|=>|\s+)\s*([A-Za-z0-9._\-]{4,35})", text_no_url)
    code = arrow_match.group(1).strip() if arrow_match else ""

    if not code:
        code_lbl = re.search(r"(?i)(?:promo(?:code)?\s*code|bonus\s*code|coupon|code)\s*[:=\-–—]\s*([A-Za-z0-9._\-]{3,30})", text_no_url)
        code = code_lbl.group(1).strip() if code_lbl else ""

    game = ""
    lbl_match = re.search(r"(?i)(?:game\s*name|game|app|application)\s*[:=\-–—>]\s*([^\n\r,]+)", text_no_url)
    if lbl_match:
        game = clean_emoji(lbl_match.group(1))

    if not game:
        for line in [l.strip() for l in text_no_url.split("\n") if l.strip()][:3]:
            cand = clean_emoji(line)
            cand = re.sub(r"(?i)\s*(?:>|:|-|–|—)?\s*(?:game\s*name.*|new\s+promocode|new\s+promo\s*code|promocode|promo\s*code|code).*$", "", cand)
            cand = re.sub(r"(?i)^claim\s*(?:>>|>|:|-|–|—)?", "", cand).strip()
            if cand and 3 <= len(cand) <= 35 and cand != code and cand.upper() not in ["PROMO", "CODE", "SIGNUP", "BONUS"]:
                game = cand
                break

    if not game: game = TARGET_CHANNEL

    bonus_match = re.search(r"(?i)(?:bonus\s*upto|signup\s*bonus|bonus|amount|get|claim|free|upto)\s*[:=\-–—]?\s*(?:₹|Rs\.?|INR)?\s*([0-9]{1,5})", clean_text)
    bonus = f"₹{bonus_match.group(1)} Bonus • {post_time_tag}" if bonus_match else post_time_tag

    return game, code, bonus

def sync_to_firebase(game_name, code, bonus_amount):
    now_ms = int(time.time() * 1000)
    expires_at = now_ms + (24 * 3600 * 1000)

    r = requests.get(f"{FIREBASE_DB_URL}/bonus_offers.json", timeout=10)
    existing = r.json() or {}
    matched_id = None
    target_norm = re.sub(r"[^a-z0-9]", "", game_name.lower())

    for k, v in existing.items():
        if isinstance(v, dict):
            app_n = re.sub(r"[^a-z0-9]", "", str(v.get("appName") or v.get("app_name") or "").lower())
            if target_norm and (app_n == target_norm or (len(target_norm) >= 4 and target_norm in app_n)):
                matched_id = k
                break

    is_new = matched_id is None
    offer_id = matched_id if matched_id else f"tg_{now_ms}"
    notif_title = f"{game_name} ka New Promocode aa gya hai 💞" if is_new else f"{game_name} promocode update ho gya hai 💞"

    offer_payload = {
        "id": offer_id, "title": f"{game_name} Special Promo", "appName": game_name,
        "code": code, "bonusAmount": bonus_amount, "description": f"Daily promo drops for {game_name}",
        "expiryDate": "Valid 24h ⏳", "minDeposit": "₹0 (Free Bonus)", "verified": True,
        "active": True, "dateAdded": now_ms, "expiryHours": 24, "expiresAt": expires_at
    }

    requests.put(f"{FIREBASE_DB_URL}/bonus_offers/{offer_id}.json", json=offer_payload, timeout=10)
    requests.put(f"{FIREBASE_DB_URL}/promo_codes/{offer_id}.json", json=offer_payload, timeout=10)
    print(f"✅ Success! {game_name} -> {code} ({bonus_amount})")
