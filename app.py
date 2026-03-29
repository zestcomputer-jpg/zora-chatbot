"""
ZORA Ai Agent - Facebook Messenger Chatbot for ZEST Mobile Shop
================================================================
A Flask-based webhook application for Facebook Messenger that handles:
1. Phone model inquiries with prices and stock status
2. Store location information
3. Order collection (name, phone, address, model)
4. YouTube video recommendations for phone-related questions
"""

import os
import json
import re
import logging
import time
import threading
from flask import Flask, request, jsonify
import requests
from difflib import SequenceMatcher
from threading import Lock, Thread

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)

# Facebook credentials (set via environment variables)
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "zora_verify_token_2024")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real-time API Caching System
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cache configuration
CACHE_TTL = 600  # 10 minutes in seconds
API_BASE = "https://zestmobileshop.com/api/trpc/phones.search"

# Cache state
cache_lock = Lock()
cache_data = {
    "phones": [],
    "timestamp": 0
}

def fetch_phones_from_api(page=1, page_size=100):
    """Fetch phones from the ZEST Mobile Shop API."""
    try:
        params = {
            "batch": "1",
            "input": json.dumps({
                "0": {
                    "json": {
                        "search": "",
                        "brand": "all",
                        "stock": "all",
                        "sort": "default",
                        "page": page,
                        "pageSize": page_size
                    }
                }
            })
        }
        resp = requests.get(API_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data[0]["result"]["data"]["json"]["phones"]
    except Exception as e:
        logger.error(f"Error fetching phones from API: {e}")
        return []

def fetch_all_phones_from_api():
    """Fetch all phones from the API with pagination."""
    all_phones = []
    page = 1
    max_pages = 10  # Safety limit
    
    while page <= max_pages:
        try:
            phones = fetch_phones_from_api(page=page, page_size=100)
            if not phones:
                break
            all_phones.extend(phones)
            logger.info(f"Fetched page {page}: {len(phones)} phones (total: {len(all_phones)})")
            if len(phones) < 100:
                break
            page += 1
        except Exception as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
    
    # Extract relevant fields
    catalog = []
    for p in all_phones:
        catalog.append({
            "id": p.get("id"),
            "brand": p.get("brand", ""),
            "name": p.get("name", ""),
            "storage": p.get("storage", ""),
            "colors": p.get("colors", ""),
            "price": p.get("price", ""),
            "stock": p.get("stock", ""),
            "tag": p.get("tag", ""),
        })
    
    return catalog

def get_phone_catalog():
    """Get phone catalog with intelligent caching.
    
    Returns cached data if fresh (< 10 minutes old).
    Otherwise fetches fresh data from the API.
    """
    global cache_data
    
    current_time = time.time()
    cache_age = current_time - cache_data["timestamp"]
    
    # Return cached data if still fresh
    if cache_data["phones"] and cache_age < CACHE_TTL:
        logger.info(f"Using cached phone catalog (age: {cache_age:.0f}s)")
        return cache_data["phones"]
    
    # Fetch fresh data from API
    logger.info("Fetching fresh phone catalog from API...")
    with cache_lock:
        # Double-check after acquiring lock
        cache_age = time.time() - cache_data["timestamp"]
        if cache_data["phones"] and cache_age < CACHE_TTL:
            return cache_data["phones"]
        
        # Fetch new data
        phones = fetch_all_phones_from_api()
        if phones:
            cache_data["phones"] = phones
            cache_data["timestamp"] = time.time()
            logger.info(f"Updated cache with {len(phones)} phones")
        else:
            logger.warning("API returned no phones, using existing cache")
        
        return cache_data["phones"]

# Load YouTube videos (static, doesn't change often)
YOUTUBE_VIDEOS = []
try:
    with open(os.path.join(BASE_DIR, "data", "youtube_videos.json"), "r", encoding="utf-8") as f:
        YOUTUBE_VIDEOS = json.load(f)
    logger.info(f"Loaded {len(YOUTUBE_VIDEOS)} YouTube videos")
except Exception as e:
    logger.warning(f"Could not load YouTube videos: {e}")
    YOUTUBE_VIDEOS = []

# Initialize cache on startup
logger.info("Initializing phone catalog cache on startup...")
def init_cache():
    """Initialize cache in a background thread to not block startup."""
    try:
        initial_phones = fetch_all_phones_from_api()
        if initial_phones:
            cache_data["phones"] = initial_phones
            cache_data["timestamp"] = time.time()
            logger.info(f"✅ Initialized cache with {len(initial_phones)} phones")
        else:
            logger.warning("⚠️ Failed to initialize cache from API, will retry on first request")
    except Exception as e:
        logger.error(f"Error initializing cache: {e}")

# Start cache initialization in background thread
init_thread = Thread(target=init_cache, daemon=True)
init_thread.start()

# ---------------------------------------------------------------------------
# Store Information
# ---------------------------------------------------------------------------
STORE_INFO = """🏪 ZEST Mobile Shop
📍 မဘ-၁၄၃၊လမ်းမတော်
တရားရုံးရှေ့၊မြင်းဘက်ရပ်ကွက်
ပျော်ဘွယ်မြို့။

☎ 09 797 8855 85
☎ 09 9649 555 99
☎ 09 25 82 11110
☎ 09 69 743 7889

🕐 မနက် ၈:၀၀ မှ ည ၇:၀၀ ထိ
📅 နေ့တိုင်းဖွင့်ပါတယ်

🌐 https://zestmobileshop.com
💬 m.me/zestmobileshop

#Zest_is_the_Best"""

GREETING_MESSAGE = """မင်္ဂလာပါ ခင်ဗျာ လူကြီးမင်း သိရှိလိုသည့် ဈေးနှုန်း ဖုန်း အမျိုးအစားများကို မေးမြန်းထားပေးပါ။ 
ZORA Ai Agent မှ ဖြေကြားပေးထားပါမယ်။
မနက် (၈)နာရီမှ ည (၈)နာရီအတွင်း ကျွန်တော်တို့ ZEST MOBILE မှ CB တွင်ဝင်ရောက်စစ်ဆေးသည့် အချိန်၌သိရှိလိုသည်များကို ပြန်လည်ဖြေကြားပေးပါမယ်ခင်ဗျာ။  09 7978855 85 သို့ဆက်သွယ်မေးမြန်နိုင်ပါတယ်။
https://zestmobileshop.com မှာလဲဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်။"""

# ---------------------------------------------------------------------------
# Order State Management (in-memory; use DB for production)
# ---------------------------------------------------------------------------
user_sessions = {}

ORDER_STEPS = {
    "awaiting_name": "အော်ဒါမှာယူရန် - ဦးစွာ သင့်အမည်ကို ပြောပြပေးပါ ခင်ဗျာ။",
    "awaiting_phone": "ဖုန်းနံပါတ်ကို ပြောပြပေးပါ ခင်ဗျာ။ (ဥပမာ - 09xxxxxxxxx)",
    "awaiting_address": "ပို့ဆောင်ရမည့် လိပ်စာကို ပြောပြပေးပါ ခင်ဗျာ။",
    "awaiting_model": "မှာယူလိုသည့် ဖုန်းအမျိုးအစားကို ပြောပြပေးပါ ခင်ဗျာ။",
    "confirm": "confirm",
}


def get_session(sender_id):
    """Get or create a user session."""
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {"state": None, "order": {}}
    return user_sessions[sender_id]


def reset_session(sender_id):
    """Reset user session."""
    user_sessions[sender_id] = {"state": None, "order": {}}


# ---------------------------------------------------------------------------
# Phone Search Logic
# ---------------------------------------------------------------------------
def normalize(text):
    """Normalize text for matching."""
    text = text.lower().strip()
    # Remove common filler words
    text = re.sub(r'\s+', ' ', text)
    return text


def search_phones(query):
    """Search for phones matching the query."""
    query_norm = normalize(query)
    results = []

    # Get fresh phone catalog (with caching)
    phone_catalog = get_phone_catalog()
    if not phone_catalog:
        logger.warning("No phone catalog available")
        return []

    # Direct brand/model matching
    for phone in phone_catalog:
        name_norm = normalize(phone["name"])
        brand_norm = normalize(phone["brand"])
        full_name = f"{brand_norm} {name_norm}"

        # Exact or partial match
        score = 0
        query_words = query_norm.split()

        # Check if all query words appear in the phone name or brand
        all_match = all(
            w in full_name or w in name_norm or w in brand_norm
            for w in query_words
        )
        if all_match and query_words:
            score = 100

        # Fuzzy match
        if score == 0:
            ratio = SequenceMatcher(None, query_norm, full_name).ratio()
            if ratio > 0.4:
                score = int(ratio * 80)

        # Partial keyword match
        if score == 0:
            for word in query_words:
                if len(word) >= 2 and (word in full_name):
                    score = max(score, 60)

        if score > 0:
            results.append((score, phone))

    # Sort by score descending
    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:8]]


def format_stock_status(stock):
    """Format stock status in Burmese."""
    status_map = {
        "instock": "✅ ရရှိနိုင်ပါသည်",
        "outstock": "❌ ပစ္စည်းကုန်နေပါသည်",
        "preorder": "📦 ကြိုတင်မှာယူနိုင်ပါသည် (Pre-Order)",
    }
    return status_map.get(stock, "❓ မသိရှိပါ")


def format_phone_result(phone):
    """Format a single phone result for display."""
    name = phone["name"]
    brand = phone["brand"]
    price = phone["price"]
    stock = format_stock_status(phone["stock"])
    storage = phone.get("storage", "")
    colors = phone.get("colors", "")

    msg = f"📱 {brand} {name}\n"
    msg += f"💰 ဈေးနှုန်း - {price}\n"
    if storage:
        msg += f"💾 Storage - {storage}\n"
    if colors:
        msg += f"🎨 အရောင် - {colors}\n"
    msg += f"📊 အခြေအနေ - {stock}\n"
    return msg


def format_phone_results(phones):
    """Format multiple phone results."""
    if not phones:
        return "တောင်းပန်ပါတယ် ခင်ဗျာ၊ ရှာဖွေသည့် ဖုန်းမော်ဒယ်ကို ရှာမတွေ့ပါ။ 🙏\n\nအခြားဖုန်းအမျိုးအစားကို ထပ်မံမေးမြန်းနိုင်ပါတယ်။\nသို့မဟုတ် 09 797 8855 85 သို့ ဆက်သွယ်မေးမြန်းနိုင်ပါတယ်။"

    msg = f"🔍 ရှာဖွေတွေ့ရှိချက် ({len(phones)} မျိုး)\n"
    msg += "━━━━━━━━━━━━━━━\n\n"

    for i, phone in enumerate(phones, 1):
        msg += f"{i}. {format_phone_result(phone)}\n"

    msg += "━━━━━━━━━━━━━━━\n"
    msg += "📞 ဈေးနှုန်းများ ပြောင်းလဲနိုင်ပါသည်။\nအတည်ပြုရန် 09 797 8855 85 သို့ ဆက်သွယ်ပါ။\n"
    msg += "\n💡 မှာယူလိုပါက \"order\" သို့မဟုတ် \"မှာမယ်\" ဟု ရိုက်ထည့်ပါ။"
    return msg


# ---------------------------------------------------------------------------
# YouTube Video Matching
# ---------------------------------------------------------------------------
def find_relevant_videos(query, max_results=3):
    """Find YouTube videos relevant to the query."""
    query_norm = normalize(query)
    results = []

    for video in YOUTUBE_VIDEOS:
        title_norm = normalize(video["title"])
        score = 0

        # Check keyword overlap
        query_words = query_norm.split()
        for word in query_words:
            if len(word) >= 2 and word in title_norm:
                score += 30

        # Fuzzy match
        ratio = SequenceMatcher(None, query_norm, title_norm).ratio()
        score += int(ratio * 50)

        if score > 20:
            results.append((score, video))

    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:max_results]]


def format_video_results(videos, query=""):
    """Format YouTube video results."""
    if not videos:
        return None

    msg = "🎬 ZEST YouTube Channel မှ ဗီဒီယိုများ\n"
    msg += "━━━━━━━━━━━━━━━\n\n"

    for i, video in enumerate(videos, 1):
        msg += f"{i}. 📺 {video['title']}\n"
        msg += f"   🔗 {video['url']}\n\n"

    msg += "📺 ကျွန်တော်တို့ Channel ကို Subscribe လုပ်ထားပေးပါနော်!\n"
    msg += "🔗 https://www.youtube.com/channel/UClZasg2VGtrRxklU_uWFcFQ"
    return msg


# ---------------------------------------------------------------------------
# Intent Detection
# ---------------------------------------------------------------------------
# Keywords for intent detection
GREETING_KEYWORDS = [
    "hi", "hello", "hey", "mingalar", "mingalaba",
    "မင်္ဂလာပါ", "ဟယ်လို", "ဟိုင်း", "get started",
    "start", "help", "အကူအညီ", "စတင်", "ဟယ်", "ပါ"
]

STORE_KEYWORDS = [
    "store", "shop", "location", "address", "where",
    "ဆိုင်", "လိပ်စာ", "တည်နေရာ", "ဘယ်မှာ", "ဖုန်းနံပါတ်",
    "phone number", "contact", "ဆက်သွယ်", "နံပါတ်", "map",
    "ပျော်ဘွယ်", "pyawbwe", "opening", "ဖွင့်ချိန်", "ညွှန်ကြား"
]

ORDER_KEYWORDS = [
    "order", "buy", "purchase", "မှာ", "ဝယ်", "မှာမယ်",
    "ဝယ်မယ်", "အော်ဒါ", "မှာယူ", "ဝယ်ယူ", "order မှာမယ်",
    "မှာချင်", "ဝယ်ချင်"
]

PRICE_KEYWORDS = [
    "price", "cost", "how much", "ဈေး", "ဈေးနှုန်း", "ဘယ်လောက်",
    "စျေး", "စျေးနှုန်း", "ကျပ်", "သိန်း", "ks"
]

VIDEO_KEYWORDS = [
    "review", "unboxing", "video", "youtube", "tip", "compare",
    "comparison", "camera", "battery", "performance", "benchmark",
    "ဗီဒီယို", "ရီဗျူး", "သုံးသပ်", "နှိုင်းယှဉ်", "ကင်မရာ",
    "ဘက်ထရီ", "အားထုတ်", "ကြည့်", "ဖွင့်", "unbox"
]

CANCEL_KEYWORDS = [
    "cancel", "stop", "ပယ်ဖျက်", "ရပ်", "မလိုတော့", "ပြန်",
    "back", "exit", "quit"
]

THANKS_KEYWORDS = [
    "thanks", "thank", "ကျေးဇူး", "ကျေးဇူးပါ", "ကျေးဇူးတင်",
    "thx", "ty", "ok", "okay", "အိုကေ"
]


def detect_intent(text):
    """Detect user intent from message text."""
    text_lower = normalize(text)

    # Check for cancel
    if any(kw in text_lower for kw in CANCEL_KEYWORDS):
        return "cancel"

    # Check for thanks
    if any(kw in text_lower for kw in THANKS_KEYWORDS) and len(text_lower) < 30:
        return "thanks"

    # Check for order intent
    if any(kw in text_lower for kw in ORDER_KEYWORDS):
        return "order"

    # Check for store info
    if any(kw in text_lower for kw in STORE_KEYWORDS):
        return "store"

    # Check for greeting
    if any(kw in text_lower for kw in GREETING_KEYWORDS) and len(text_lower) < 40:
        return "greeting"

    # Check for video/review queries
    video_score = sum(1 for kw in VIDEO_KEYWORDS if kw in text_lower)
    price_score = sum(1 for kw in PRICE_KEYWORDS if kw in text_lower)

    if video_score > price_score and video_score > 0:
        return "video"

    # Default: treat as phone search
    return "phone_search"


# ---------------------------------------------------------------------------
# AI Response (Optional - uses OpenAI if available)
# ---------------------------------------------------------------------------
def get_ai_response(user_message, context=""):
    """Get AI-generated response for complex queries (optional enhancement)."""
    if not OPENAI_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI()

        system_prompt = f"""You are ZORA Ai Agent, a helpful assistant for ZEST Mobile Shop in Pyawbwe, Myanmar.
You MUST respond in Burmese (Myanmar) language.
You help customers with phone inquiries, prices, and orders.
Keep responses concise and friendly.

Store Info:
{STORE_INFO}

Context: {context}"""

        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI response error: {e}")
        return None


# ---------------------------------------------------------------------------
# Message Processing
# ---------------------------------------------------------------------------
def process_message(sender_id, text):
    """Process incoming message and return response text(s)."""
    session = get_session(sender_id)
    responses = []

    # Handle ongoing order flow
    if session["state"] in ORDER_STEPS:
        return handle_order_flow(sender_id, text, session)

    # Detect intent
    intent = detect_intent(text)

    if intent == "greeting":
        responses.append(GREETING_MESSAGE)
        responses.append("💡 အောက်ပါတို့ကို လုပ်ဆောင်နိုင်ပါတယ်:\n\n"
                         "📱 ဖုန်းအမည်/Brand ရိုက်ထည့်ပြီး ဈေးနှုန်းစစ်ဆေးပါ\n"
                         "🏪 \"ဆိုင်\" ဟုရိုက်ပြီး ဆိုင်တည်နေရာ ကြည့်ပါ\n"
                         "🛒 \"မှာမယ်\" ဟုရိုက်ပြီး အော်ဒါမှာယူပါ\n"
                         "🎬 \"review\" + ဖုန်းအမည် ရိုက်ပြီး ဗီဒီယို ကြည့်ပါ")

    elif intent == "store":
        responses.append(STORE_INFO)

    elif intent == "order":
        session["state"] = "awaiting_name"
        session["order"] = {}
        responses.append("🛒 အော်ဒါမှာယူခြင်း\n━━━━━━━━━━━━━━━\n\n" + ORDER_STEPS["awaiting_name"])

    elif intent == "cancel":
        reset_session(sender_id)
        responses.append("✅ ပယ်ဖျက်ပြီးပါပြီ ခင်ဗျာ။ အခြားအကူအညီ လိုအပ်ပါက မေးမြန်းနိုင်ပါတယ်။ 🙏")

    elif intent == "thanks":
        responses.append("ကျေးဇူးတင်ပါတယ် ခင်ဗျာ! 🙏\nအခြားအကူအညီ လိုအပ်ပါက ထပ်မံမေးမြန်းနိုင်ပါတယ်။\n\n#Zest_is_the_Best")

    elif intent == "video":
        videos = find_relevant_videos(text)
        if videos:
            responses.append(format_video_results(videos, text))
        else:
            # Try to find any related videos
            # Extract potential phone brand/model from query
            for word in text.split():
                videos = find_relevant_videos(word)
                if videos:
                    responses.append(format_video_results(videos, text))
                    break
            if not videos:
                responses.append(
                    "🎬 သက်ဆိုင်ရာ ဗီဒီယို ရှာမတွေ့ပါ။\n\n"
                    "📺 ZEST YouTube Channel တွင် Unboxing နှင့် Review ဗီဒီယိုများ ကြည့်ရှုနိုင်ပါတယ်:\n"
                    "🔗 https://www.youtube.com/channel/UClZasg2VGtrRxklU_uWFcFQ"
                )

    elif intent == "phone_search":
        phones = search_phones(text)
        responses.append(format_phone_results(phones))

        # Also check for relevant videos
        videos = find_relevant_videos(text, max_results=2)
        if videos:
            video_msg = "\n🎬 ဆက်စပ် ဗီဒီယိုများ:\n"
            for v in videos:
                video_msg += f"📺 {v['title']}\n🔗 {v['url']}\n"
            responses.append(video_msg)

    else:
        # Fallback
        ai_response = get_ai_response(text)
        if ai_response:
            responses.append(ai_response)
        else:
            responses.append(
                "တောင်းပန်ပါတယ် ခင်ဗျာ၊ နားမလည်ပါ။ 🙏\n\n"
                "📱 ဖုန်းအမည် ရိုက်ထည့်ပြီး ဈေးနှုန်းစစ်ဆေးနိုင်ပါတယ်\n"
                "🏪 \"ဆိုင်\" - ဆိုင်တည်နေရာ\n"
                "🛒 \"မှာမယ်\" - အော်ဒါမှာယူရန်\n"
                "🎬 \"review\" + ဖုန်းအမည် - ဗီဒီယိုကြည့်ရန်"
            )

    return responses


def handle_order_flow(sender_id, text, session):
    """Handle the multi-step order flow."""
    state = session["state"]
    responses = []

    # Allow cancellation at any step
    if any(kw in normalize(text) for kw in CANCEL_KEYWORDS):
        reset_session(sender_id)
        return ["✅ အော်ဒါ ပယ်ဖျက်ပြီးပါပြီ ခင်ဗျာ။ 🙏"]

    if state == "awaiting_name":
        session["order"]["name"] = text.strip()
        session["state"] = "awaiting_phone"
        responses.append(f"✅ အမည် - {text.strip()}\n\n" + ORDER_STEPS["awaiting_phone"])

    elif state == "awaiting_phone":
        phone = text.strip()
        # Basic phone validation
        phone_digits = re.sub(r'[^\d]', '', phone)
        if len(phone_digits) < 8:
            responses.append("⚠️ ဖုန်းနံပါတ် မှားနေပါတယ်။ ထပ်မံရိုက်ထည့်ပေးပါ ခင်ဗျာ။\n(ဥပမာ - 09xxxxxxxxx)")
            return responses
        session["order"]["phone"] = phone
        session["state"] = "awaiting_address"
        responses.append(f"✅ ဖုန်းနံပါတ် - {phone}\n\n" + ORDER_STEPS["awaiting_address"])

    elif state == "awaiting_address":
        session["order"]["address"] = text.strip()
        session["state"] = "awaiting_model"
        responses.append(f"✅ လိပ်စာ - {text.strip()}\n\n" + ORDER_STEPS["awaiting_model"])

    elif state == "awaiting_model":
        session["order"]["model"] = text.strip()
        session["state"] = "confirm"

        order = session["order"]
        confirm_msg = "📋 အော်ဒါ အချက်အလက်များ\n"
        confirm_msg += "━━━━━━━━━━━━━━━\n\n"
        confirm_msg += f"👤 အမည် - {order['name']}\n"
        confirm_msg += f"📞 ဖုန်း - {order['phone']}\n"
        confirm_msg += f"📍 လိပ်စာ - {order['address']}\n"
        confirm_msg += f"📱 ဖုန်းမော်ဒယ် - {order['model']}\n\n"

        # Try to find the phone and show price
        phones = search_phones(order["model"])
        if phones:
            confirm_msg += f"💰 ဈေးနှုန်း - {phones[0]['price']}\n"
            confirm_msg += f"📊 အခြေအနေ - {format_stock_status(phones[0]['stock'])}\n\n"

        confirm_msg += "━━━━━━━━━━━━━━━\n"
        confirm_msg += "✅ အတည်ပြုရန် \"yes\" သို့မဟုတ် \"ဟုတ်\" ရိုက်ပါ\n"
        confirm_msg += "❌ ပယ်ဖျက်ရန် \"cancel\" သို့မဟုတ် \"ပယ်ဖျက်\" ရိုက်ပါ"
        responses.append(confirm_msg)

    elif state == "confirm":
        if any(kw in normalize(text) for kw in ["yes", "ဟုတ်", "ကဲ", "ok", "okay", "confirm", "အတည်ပြု", "ဟုတ်ကဲ့", "ဟုတ်တယ်"]):
            order = session["order"]
            order_summary = (
                f"🎉 အော်ဒါ အောင်မြင်စွာ လက်ခံရရှိပါပြီ ခင်ဗျာ!\n"
                f"━━━━━━━━━━━━━━━\n\n"
                f"👤 {order['name']}\n"
                f"📞 {order['phone']}\n"
                f"📍 {order['address']}\n"
                f"📱 {order['model']}\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"ကျွန်တော်တို့ ZEST Mobile မှ အမြန်ဆုံး ပြန်လည်ဆက်သွယ်ပေးပါမယ် ခင်ဗျာ။ 🙏\n\n"
                f"☎ 09 797 8855 85\n"
                f"#Zest_is_the_Best"
            )
            responses.append(order_summary)
            # Log the order
            logger.info(f"NEW ORDER: {json.dumps(order, ensure_ascii=False)}")
            reset_session(sender_id)
        else:
            reset_session(sender_id)
            responses.append("❌ အော်ဒါ ပယ်ဖျက်ပြီးပါပြီ ခင်ဗျာ။\nအခြားအကူအညီ လိုအပ်ပါက မေးမြန်းနိုင်ပါတယ်။ 🙏")

    return responses


# ---------------------------------------------------------------------------
# Facebook Messenger API
# ---------------------------------------------------------------------------
def send_message(recipient_id, text):
    """Send a text message to a Facebook Messenger user."""
    if not PAGE_ACCESS_TOKEN:
        logger.warning("PAGE_ACCESS_TOKEN not set. Message not sent.")
        return

    url = "https://graph.facebook.com/v19.0/me/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": PAGE_ACCESS_TOKEN}

    # Split long messages (Messenger has 2000 char limit)
    max_len = 2000
    chunks = []
    if len(text) <= max_len:
        chunks = [text]
    else:
        lines = text.split('\n')
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ('\n' if current_chunk else '') + line
        if current_chunk:
            chunks.append(current_chunk)

    for chunk in chunks:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": chunk},
            "messaging_type": "RESPONSE"
        }
        try:
            resp = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Send message failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Send message error: {e}")


def send_typing_indicator(recipient_id, action="typing_on"):
    """Send typing indicator."""
    if not PAGE_ACCESS_TOKEN:
        return

    url = "https://graph.facebook.com/v19.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "sender_action": action
    }
    try:
        requests.post(url, params=params, json=payload, timeout=5)
    except Exception:
        pass


def setup_messenger_profile():
    """Set up Messenger profile (greeting, get started button, persistent menu)."""
    if not PAGE_ACCESS_TOKEN:
        logger.warning("PAGE_ACCESS_TOKEN not set. Cannot setup profile.")
        return

    url = "https://graph.facebook.com/v19.0/me/messenger_profile"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}

    payload = {
        "greeting": [
            {
                "locale": "default",
                "text": "မင်္ဂလာပါ! ZEST Mobile Shop မှ ကြိုဆိုပါတယ်။ ZORA Ai Agent မှ ဖုန်းဈေးနှုန်းများ၊ အော်ဒါမှာယူခြင်းနှင့် အခြားအကူအညီများ ပေးနိုင်ပါတယ်။"
            }
        ],
        "get_started": {
            "payload": "GET_STARTED"
        },
        "persistent_menu": [
            {
                "locale": "default",
                "composer_input_disabled": False,
                "call_to_actions": [
                    {
                        "type": "postback",
                        "title": "📱 ဖုန်းဈေးနှုန်းများ",
                        "payload": "PHONE_PRICES"
                    },
                    {
                        "type": "postback",
                        "title": "🏪 ဆိုင်တည်နေရာ",
                        "payload": "STORE_LOCATION"
                    },
                    {
                        "type": "postback",
                        "title": "🛒 အော်ဒါမှာယူမယ်",
                        "payload": "ORDER"
                    },
                    {
                        "type": "web_url",
                        "title": "🌐 Website",
                        "url": "https://zestmobileshop.com"
                    },
                    {
                        "type": "web_url",
                        "title": "🎬 YouTube Channel",
                        "url": "https://www.youtube.com/channel/UClZasg2VGtrRxklU_uWFcFQ"
                    }
                ]
            }
        ]
    }

    try:
        resp = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        logger.info(f"Messenger profile setup: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Messenger profile setup error: {e}")


# ---------------------------------------------------------------------------
# Webhook Routes
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    """Health check / landing page."""
    return jsonify({
        "name": "ZORA Ai Agent",
        "description": "Facebook Messenger Chatbot for ZEST Mobile Shop",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health",
            "test": "/test?q=<phone_model>"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "bot": "ZORA Ai Agent"})


@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """Verify webhook for Facebook."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully!")
        return challenge, 200
    else:
        logger.warning(f"Webhook verification failed. Token: {token}")
        return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook_handler():
    """Handle incoming webhook events from Facebook."""
    data = request.get_json()

    if not data or data.get("object") != "page":
        return "Not a page event", 404

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue

            # Handle postback (button clicks)
            if "postback" in event:
                payload = event["postback"].get("payload", "")
                handle_postback(sender_id, payload)
                continue

            # Handle text messages
            if "message" in event and "text" in event["message"]:
                text = event["message"]["text"]
                logger.info(f"Message from {sender_id}: {text}")

                # Send typing indicator
                send_typing_indicator(sender_id)

                # Process message
                responses = process_message(sender_id, text)
                for resp in responses:
                    send_message(sender_id, resp)

            # Handle attachments (images, stickers, etc.)
            elif "message" in event and "attachments" in event["message"]:
                send_message(
                    sender_id,
                    "ကျေးဇူးတင်ပါတယ် ခင်ဗျာ! 🙏\n"
                    "ဖုန်းအမျိုးအစား သို့မဟုတ် Brand အမည်ကို စာသားဖြင့် ရိုက်ထည့်ပေးပါ ခင်ဗျာ။"
                )

    return "OK", 200


def handle_postback(sender_id, payload):
    """Handle postback events from buttons/menus."""
    if payload == "GET_STARTED":
        send_message(sender_id, GREETING_MESSAGE)
        send_message(
            sender_id,
            "💡 အောက်ပါတို့ကို လုပ်ဆောင်နိုင်ပါတယ်:\n\n"
            "📱 ဖုန်းအမည်/Brand ရိုက်ထည့်ပြီး ဈေးနှုန်းစစ်ဆေးပါ\n"
            "🏪 \"ဆိုင်\" ဟုရိုက်ပြီး ဆိုင်တည်နေရာ ကြည့်ပါ\n"
            "🛒 \"မှာမယ်\" ဟုရိုက်ပြီး အော်ဒါမှာယူပါ\n"
            "🎬 \"review\" + ဖုန်းအမည် ရိုက်ပြီး ဗီဒီယို ကြည့်ပါ"
        )
    elif payload == "PHONE_PRICES":
        send_message(
            sender_id,
            "📱 ဖုန်းဈေးနှုန်း စစ်ဆေးရန်\n\n"
            "ဖုန်းအမည် သို့မဟုတ် Brand ကို ရိုက်ထည့်ပေးပါ ခင်ဗျာ။\n\n"
            "ဥပမာ:\n"
            "• iPhone 16\n"
            "• Samsung S26\n"
            "• Redmi Note 15\n"
            "• Tecno\n"
            "• Infinix"
        )
    elif payload == "STORE_LOCATION":
        send_message(sender_id, STORE_INFO)
    elif payload == "ORDER":
        session = get_session(sender_id)
        session["state"] = "awaiting_name"
        session["order"] = {}
        send_message(
            sender_id,
            "🛒 အော်ဒါမှာယူခြင်း\n━━━━━━━━━━━━━━━\n\n" + ORDER_STEPS["awaiting_name"]
        )


# ---------------------------------------------------------------------------
# Test Endpoint (for local testing without Facebook)
# ---------------------------------------------------------------------------
@app.route("/test", methods=["GET", "POST"])
def test_endpoint():
    """Test the chatbot without Facebook integration."""
    if request.method == "GET":
        query = request.args.get("q", "")
        sender_id = request.args.get("sender", "test_user")
    else:
        data = request.get_json() or {}
        query = data.get("q", data.get("message", ""))
        sender_id = data.get("sender", "test_user")

    if not query:
        return jsonify({
            "error": "No query provided",
            "usage": "GET /test?q=iPhone 16&sender=test_user"
        })

    responses = process_message(sender_id, query)
    return jsonify({
        "query": query,
        "sender": sender_id,
        "responses": responses,
        "intent": detect_intent(query)
    })


# ---------------------------------------------------------------------------
# Keep-Alive Mechanism (for Render free tier)
# ---------------------------------------------------------------------------
keep_alive_enabled = False
keep_alive_thread = None

def keep_alive_worker():
    """Background thread that pings the server to keep it awake.
    
    Render's free tier puts apps to sleep after 15 minutes of inactivity.
    This pings the health endpoint every 12 minutes to keep the app alive.
    """
    global keep_alive_enabled
    
    # Get the server URL from environment or use localhost for testing
    server_url = os.environ.get("SERVER_URL", "http://localhost:5000")
    
    logger.info(f"🔄 Keep-alive worker started. Will ping {server_url}/health every 12 minutes")
    
    while keep_alive_enabled:
        try:
            time.sleep(720)  # Wait 12 minutes
            if not keep_alive_enabled:
                break
            
            response = requests.get(f"{server_url}/health", timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Keep-alive ping successful at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                logger.warning(f"⚠️ Keep-alive ping returned status {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Keep-alive ping failed: {e}")

def start_keep_alive():
    """Start the keep-alive background thread."""
    global keep_alive_enabled, keep_alive_thread
    
    if keep_alive_enabled:
        logger.warning("Keep-alive already running")
        return
    
    keep_alive_enabled = True
    keep_alive_thread = Thread(target=keep_alive_worker, daemon=True)
    keep_alive_thread.start()
    logger.info("🚀 Keep-alive mechanism activated")

# ---------------------------------------------------------------------------
# Setup on startup
# ---------------------------------------------------------------------------
@app.route("/setup", methods=["POST"])
def setup():
    """Trigger Messenger profile setup."""
    setup_messenger_profile()
    return jsonify({"status": "Messenger profile setup triggered"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🤖 ZORA Ai Agent starting on port {port}")
    logger.info(f"📱 Phone catalog: {len(cache_data['phones'])} phones (loading from API)")
    logger.info(f"🎬 YouTube videos: {len(YOUTUBE_VIDEOS)} videos loaded")

    if PAGE_ACCESS_TOKEN:
        setup_messenger_profile()
    else:
        logger.warning("⚠️ PAGE_ACCESS_TOKEN not set. Running in test mode.")
    
    # Start keep-alive mechanism for Render free tier
    if os.environ.get("ENVIRONMENT") == "production" or os.environ.get("RENDER") == "true":
        start_keep_alive()
    
    # Use app.run() for development, gunicorn for production
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
