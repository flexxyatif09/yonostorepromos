import re
import time
import json
import os
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db

# Aapka Firebase RTDB URL
FIREBASE_DATABASE_URL = "https://appstore-9d01f-default-rtdb.asia-southeast1.firebasedatabase.app"

def initialize_firebase():
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if service_account_json:
        cred_dict = json.loads(service_account_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
    else:
        print("Error: FIREBASE_SERVICE_ACCOUNT environment variable missing!")

def sync_promocodes_only():
    url = "https://t.me/s/YonoGamesofficialCodee"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to load Telegram channel: HTTP {response.status_code}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.find_all('div', class_='tgme_widget_message_wrap')

    ref = db.reference("bonus_offers")
    
    # 1. Pehle database se existing saare promo codes fetch karega
    existing_data = ref.get() or {}

    # Map bana lenge comparison ke liye: { "yono slots": "purana_code", "dhan game": "purana_code" }
    current_codes_map = {}
    for key, val in existing_data.items():
        if isinstance(val, dict):
            app_n = val.get("appName", "").strip().lower()
            c_code = val.get("code", "").strip()
            if app_n:
                current_codes_map[app_n] = (key, c_code)

    # 2. Latest messages check karega
    for msg in reversed(messages):
        text_div = msg.find('div', class_='tgme_widget_message_text')
        if not text_div:
            continue
            
        text = text_div.get_text(separator="\n").strip()

        # Sirf Game Name aur Promo Code extract karega
        game_match = re.search(r'([A-Za-z0-9\-_ ]+?)\s*(?:New\s+)?PromoCode', text, re.IGNORECASE)
        code_match = re.search(r'Claim\s*(?:>>|>|:)\s*([a-zA-Z0-9\.\-_]+)', text, re.IGNORECASE)

        if game_match and code_match:
            raw_game = game_match.group(1).replace('-', ' ').replace('_', ' ').strip()
            game_name = re.sub(r'[^\w\s]', '', raw_game).strip()
            new_code = code_match.group(1).strip()
            
            clean_app_key = game_name.lower()

            # Check if this app exists in DB
            if clean_app_key in current_codes_map:
                db_id, existing_code = current_codes_map[clean_app_key]
                
                # Check agar code pehle se added hai ya same hai
                if existing_code == new_code:
                    print(f"⏩ [Skip] {game_name}: Code '{new_code}' already exists in DB.")
                else:
                    # Sirf CODE aur TIME update karega (Link / Bonus / Description wahi purana rahega)
                    ref.child(db_id).update({
                        "code": new_code,
                        "dateAdded": int(time.time() * 1000)
                    })
                    print(f"🔥 [UPDATED] {game_name}: Old '{existing_code}' -> New Code '{new_code}'")
                    current_codes_map[clean_app_key] = (db_id, new_code)
            else:
                # Agar bilkul naya game hai jo DB me nahi tha
                new_id = "promo_" + re.sub(r'[^a-zA-Z0-9]', '_', clean_app_key)
                ref.child(new_id).update({
                    "id": new_id,
                    "appName": game_name,
                    "title": f"{game_name} Daily Loot",
                    "code": new_code,
                    "bonusAmount": "₹51",
                    "claimUrl": "",
                    "description": "Daily official drop. Claim free cash now!",
                    "expiryDate": "Active Today",
                    "minDeposit": "₹0 (No Deposit)",
                    "verified": True,
                    "active": True,
                    "dateAdded": int(time.time() * 1000)
                })
                print(f"✨ [NEW GAME ADDED] {game_name}: Code '{new_code}'")
                current_codes_map[clean_app_key] = (new_id, new_code)

if __name__ == "__main__":
    initialize_firebase()
    sync_promocodes_only()
