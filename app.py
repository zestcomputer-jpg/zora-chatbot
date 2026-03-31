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
from flask import Flask, request, jsonify, make_response
import requests
from difflib import SequenceMatcher
from threading import Lock, Thread
import uuid

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config["SECRET_KEY"] = os.urandom(24)

# CORS configuration for web chat widget
ALLOWED_ORIGINS = [
    "https://zestmobileshop.com",
    "https://www.zestmobileshop.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5500",
]

def add_cors_headers(response, origin=None):
    """Add CORS headers to response."""
    if origin and (origin in ALLOWED_ORIGINS or origin.endswith('.manus.computer')):
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://zestmobileshop.com'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Session-ID'
    response.headers['Access-Control-Max-Age'] = '86400'
    return response

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
API_LIST = "https://zestmobileshop.com/api/trpc/phones.list"

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
    """Fetch all phones using the phones.list endpoint (richer data)."""
    try:
        params = {
            "batch": "1",
            "input": json.dumps({"0": {"json": None}})
        }
        resp = requests.get(API_LIST, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        all_phones = data[0]["result"]["data"]["json"]
        logger.info(f"Fetched {len(all_phones)} phones from phones.list API")
    except Exception as e:
        logger.error(f"phones.list failed, falling back to paginated search: {e}")
        # Fallback to paginated search
        all_phones = []
        page = 1
        while page <= 10:
            try:
                phones = fetch_phones_from_api(page=page, page_size=100)
                if not phones:
                    break
                all_phones.extend(phones)
                if len(phones) < 100:
                    break
                page += 1
            except Exception as e2:
                logger.error(f"Error fetching page {page}: {e2}")
                break
    
    # Extract relevant fields including new ones
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
            "gsmArenaUrl": p.get("gsmArenaUrl", ""),
            "priceChange": p.get("priceChange", "stable"),
            "showInPriceList": p.get("showInPriceList", True),
            "showInCatalog": p.get("showInCatalog", True),
            "youtubeReviewUrl": p.get("youtubeReviewUrl", ""),
            "img": p.get("img", ""),
        })
    
    # Validate price data quality: reject catalog if >50% of phones have empty prices
    # This prevents caching bad data during website price updates
    if catalog:
        phones_with_price = sum(1 for p in catalog if p.get("price", "").strip())
        price_coverage = phones_with_price / len(catalog)
        if price_coverage < 0.5:
            logger.warning(
                f"Price data quality check FAILED: only {phones_with_price}/{len(catalog)} "
                f"phones ({price_coverage:.0%}) have prices. Discarding this fetch."
            )
            return []  # Return empty so caller knows to retry
        logger.info(
            f"Price data quality OK: {phones_with_price}/{len(catalog)} phones "
            f"({price_coverage:.0%}) have prices."
        )
    
    return catalog

def _refresh_cache_background():
    """Refresh phone catalog cache in a background thread (non-blocking)."""
    def _do_refresh():
        phones = fetch_all_phones_from_api()
        if phones:
            with cache_lock:
                cache_data["phones"] = phones
                cache_data["timestamp"] = time.time()
            logger.info(f"Background cache refresh: updated with {len(phones)} phones")
        else:
            logger.warning(
                "Background cache refresh: API returned no phones or failed price quality check. "
                "Keeping existing cache data."
            )
    t = Thread(target=_do_refresh, daemon=True)
    t.start()


def get_phone_catalog():
    """Get phone catalog with stale-while-revalidate caching.
    
    - If cache is fresh (< 10 min): return immediately.
    - If cache is stale but exists: return stale data instantly AND trigger
      a background refresh so the NEXT request gets fresh data.
    - If cache is empty: block and fetch (first cold start only).
    This ensures users NEVER wait for an API call during normal operation.
    """
    global cache_data
    
    current_time = time.time()
    cache_age = current_time - cache_data["timestamp"]
    
    # Cache is fresh — return immediately
    if cache_data["phones"] and cache_age < CACHE_TTL:
        return cache_data["phones"]
    
    # Cache is stale but we have data — return stale instantly, refresh in background
    if cache_data["phones"] and cache_age >= CACHE_TTL:
        logger.info(f"Cache stale ({cache_age:.0f}s), serving stale data and refreshing in background")
        _refresh_cache_background()
        return cache_data["phones"]
    
    # Cache is empty (first cold start) — must block and fetch
    logger.info("Cache empty, fetching phone catalog from API (cold start)...")
    with cache_lock:
        # Double-check after acquiring lock
        if cache_data["phones"]:
            return cache_data["phones"]
        phones = fetch_all_phones_from_api()
        if phones:
            cache_data["phones"] = phones
            cache_data["timestamp"] = time.time()
            logger.info(f"Cold start cache loaded with {len(phones)} phones")
        else:
            logger.warning("API returned no phones on cold start")
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

# Load Research Tools
RESEARCH_TOOLS = []
try:
    with open(os.path.join(BASE_DIR, "data", "research_tools.json"), "r", encoding="utf-8") as f:
        RESEARCH_TOOLS = json.load(f)
    logger.info(f"Loaded {len(RESEARCH_TOOLS)} research tools")
except Exception as e:
    logger.warning(f"Could not load research tools: {e}")
    RESEARCH_TOOLS = [
        {"name": "GSMArena Phone Comparison", "name_my": "GSMArena \u1016\u102f\u1014\u103a\u1038\u1014\u103e\u102d\u102f\u1004\u103a\u1038\u101a\u103e\u1025\u103a", "url": "https://www.gsmarena.com/compare.php3?idPhone1=14507"},
        {"name": "NanoReview SOC Compare", "name_my": "NanoReview SOC \u1014\u103e\u102d\u102f\u1004\u103a\u1038\u101a\u103e\u1025\u103a", "url": "https://nanoreview.net/en/soc-compare"},
        {"name": "NanoReview SOC Ranking", "name_my": "NanoReview SOC \u1021\u1006\u1004\u103a\u1037\u101e\u1010\u103a\u1019\u103e\u1010\u103a\u1001\u103b\u1000\u103a", "url": "https://nanoreview.net/en/soc-list/rating"},
        {"name": "NanoReview Battery Endurance", "name_my": "NanoReview \u1018\u1000\u103a\u1011\u101b\u102e \u1021\u1006\u1004\u103a\u1037", "url": "https://nanoreview.net/en/phone-list/endurance-rating"},
        {"name": "DXOMark Camera Ranking", "name_my": "DXOMark \u1000\u1004\u103a\u1019\u101b\u102c \u1021\u1006\u1004\u103a\u1037", "url": "https://www.dxomark.com/smartphones/"},
        {"name": "AnTuTu Performance Ranking", "name_my": "AnTuTu Performance \u1021\u1006\u1004\u103a\u1037", "url": "https://www.antutu.com/web/ranking"},
        {"name": "Geekbench 6 Android Benchmarks", "name_my": "Geekbench 6 Android Benchmarks", "url": "https://browser.geekbench.com/android-benchmarks"},
        {"name": "Kimovil Phone Comparison", "name_my": "Kimovil \u1016\u102f\u1014\u103a\u1038\u1014\u103e\u102d\u102f\u1004\u103a\u1038\u101a\u103e\u1025\u103a", "url": "https://www.kimovil.com/en/compare"},
    ]

# Initialize cache on startup
logger.info("Initializing phone catalog cache on startup...")
def init_cache():
    """Initialize cache in a background thread to not block startup.
    
    Retries up to 3 times if the API returns data with empty prices
    (can happen during website price updates).
    """
    max_retries = 3
    retry_delay = 10  # seconds between retries
    for attempt in range(1, max_retries + 1):
        try:
            initial_phones = fetch_all_phones_from_api()
            if initial_phones:
                cache_data["phones"] = initial_phones
                cache_data["timestamp"] = time.time()
                logger.info(f"✅ Initialized cache with {len(initial_phones)} phones (attempt {attempt})")
                return  # Success
            else:
                logger.warning(
                    f"⚠️ Cache init attempt {attempt}/{max_retries}: API returned no phones or "
                    f"failed price quality check. "
                    + (f"Retrying in {retry_delay}s..." if attempt < max_retries else "Giving up.")
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Error initializing cache (attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)

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


def format_price_change(change):
    """Format price change indicator."""
    indicators = {
        "up": "📈 ဈေးတက်",
        "down": "📉 ဈေးကျ",
        "stable": "➡️ ဈေးတည်ငြိမ်",
    }
    return indicators.get(change, "")


def format_phone_result(phone):
    """Format a single phone result for display."""
    name = phone["name"]
    brand = phone["brand"]
    price = phone["price"]
    stock = format_stock_status(phone["stock"])
    storage = phone.get("storage", "")
    colors = phone.get("colors", "")
    gsm_url = phone.get("gsmArenaUrl", "")
    price_change = phone.get("priceChange", "")

    msg = f"📱 {brand} {name}\n"
    msg += f"💰 ဈေးနှုန်း - {price}\n"
    if storage:
        msg += f"💾 Storage - {storage}\n"
    if colors:
        msg += f"🎨 အရောင် - {colors}\n"
    msg += f"📊 အခြေအနေ - {stock}\n"
    if price_change and price_change != "stable":
        msg += f"{format_price_change(price_change)}\n"
    if gsm_url and gsm_url.startswith("http"):
        msg += f"🔗 Specs - {gsm_url}\n"
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
# Price List Features
# ---------------------------------------------------------------------------
def get_price_list_brands():
    """Get available brands from the price list."""
    catalog = get_phone_catalog()
    brands = sorted(set(p["brand"] for p in catalog if p.get("showInPriceList")))
    return brands


def get_price_list_by_brand(brand, page=1, page_size=10):
    """Get price list filtered by brand with pagination."""
    catalog = get_phone_catalog()
    # Filter by brand
    if brand.lower() == "all":
        filtered = [p for p in catalog if p.get("showInPriceList")]
    else:
        filtered = [p for p in catalog if p.get("showInPriceList") and p["brand"].lower() == brand.lower()]
    
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "brand": brand
    }


def format_price_list(data):
    """Format price list for display."""
    brand = data["brand"]
    items = data["items"]
    total = data["total"]
    page = data["page"]
    total_pages = data["total_pages"]
    
    if not items:
        return f"❌ {brand} brand ဖြင့် ဖုန်းရှာမတွေ့ပါ။"
    
    brand_label = brand if brand.lower() != "all" else "အားလုံး"
    msg = f"📋 ဈေးနှုန်းစာရင်း - {brand_label}\n"
    msg += f"━━━━━━━━━━━━━━━\n"
    msg += f"စုစုပေါင်း {total} မျိုး | စာမျက်နှာ {page}/{total_pages}\n\n"
    
    for i, phone in enumerate(items, (page - 1) * 10 + 1):
        change_icon = ""
        pc = phone.get("priceChange", "stable")
        if pc == "up":
            change_icon = " 📈"
        elif pc == "down":
            change_icon = " 📉"
        
        msg += f"{i}. {phone['brand']} {phone['name']}\n"
        msg += f"   💰 {phone['price']}{change_icon}\n\n"
    
    msg += "━━━━━━━━━━━━━━━\n"
    
    if total_pages > 1:
        if page < total_pages:
            next_cmd = f"pricelist {brand} {page + 1}" if brand.lower() != "all" else f"pricelist all {page + 1}"
            msg += f"📄 နောက်စာမျက်နှာ ကြည့်ရန် \"{next_cmd}\" ရိုက်ပါ\n"
        if page > 1:
            prev_cmd = f"pricelist {brand} {page - 1}" if brand.lower() != "all" else f"pricelist all {page - 1}"
            msg += f"📄 ယခင်စာမျက်နှာ ကြည့်ရန် \"{prev_cmd}\" ရိုက်ပါ\n"
    
    msg += "\n⚠️ အချိန်နှင့်အမျှ အပြောင်းအလဲရှိနိုင်ပါသဖြင့် ဖုန်းဖြင့် တိုက်ရိုက် ဆက်သွယ်စုံစမ်းနိုင်ပါသည်။\n"
    msg += "📞 09 797 8855 85\n"
    msg += "🌐 https://zestmobileshop.com/price-list"
    return msg


def format_price_list_brands():
    """Format the list of available brands (single catalog fetch)."""
    catalog = get_phone_catalog()  # Only one fetch
    # Build brand -> count map in one pass
    brand_counts = {}
    for p in catalog:
        if p.get("showInPriceList"):
            b = p["brand"]
            brand_counts[b] = brand_counts.get(b, 0) + 1
    brands = sorted(brand_counts.keys())

    msg = "📋 ဈေးနှုန်းစာရင်း - ရရှိုန်းနိုင်း Brand များ\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    
    for i, brand in enumerate(brands, 1):
        count = brand_counts[brand]
        msg += f"{i}. {brand} ({count} မျိုး)\n"
    
    msg += "\n━━━━━━━━━━━━━━━\n"
    msg += "💡 Brand တစ်ခု၏ ဈေးနှုန်းစာရင်း ကြည့်ရန်:\n"
    msg += "   \"pricelist iPhone\" သို့မဟုတ် \"pricelist Samsung\"\n"
    msg += "   \"pricelist all\" - အားလုံးကြည့်ရန်\n\n"
    msg += "🌐 https://zestmobileshop.com/price-list"
    return msg


# ---------------------------------------------------------------------------
# Research Tools
# ---------------------------------------------------------------------------
def format_research_tools():
    """Format research tools list."""
    msg = "🔬 Research Tools - ဖုန်းသုတေသန ကိရိယာများ\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    
    for i, tool in enumerate(RESEARCH_TOOLS, 1):
        name_my = tool.get("name_my", tool["name"])
        desc_my = tool.get("description_my", tool.get("description", ""))
        msg += f"{i}. {name_my}\n"
        if desc_my:
            msg += f"   {desc_my}\n"
        msg += f"   🔗 {tool['url']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━\n"
    msg += "💡 ဖုန်းတစ်လုံး၏ specs ကြည့်ရန် \"specs iPhone 16\" ရိုက်ပါ\n"
    msg += "🌐 https://zestmobileshop.com"
    return msg


def get_phone_specs_link(query):
    """Find GSMArena specs link for a specific phone."""
    phones = search_phones(query)
    if not phones:
        return None
    
    results = []
    for phone in phones[:3]:
        gsm_url = phone.get("gsmArenaUrl", "")
        if gsm_url and gsm_url.startswith("http"):
            results.append({
                "name": f"{phone['brand']} {phone['name']}",
                "price": phone['price'],
                "url": gsm_url
            })
    return results


def format_specs_results(results, query):
    """Format specs lookup results."""
    if not results:
        return (f"❌ \"{query}\" အတွက် specs link ရှာမတွေ့ပါ။\n\n"
                f"🔍 GSMArena တွင် တိုက်ရိုက်ရှာရန်:\n"
                f"🔗 https://www.gsmarena.com/results.php3?sQuickSearch=yes&sName={query.replace(' ', '+')}")
    
    msg = f"🔬 \"{query}\" Specs & Details\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    
    for i, r in enumerate(results, 1):
        msg += f"{i}. 📱 {r['name']}\n"
        msg += f"   💰 {r['price']}\n"
        msg += f"   🔗 {r['url']}\n\n"
    
    msg += "━━━━━━━━━━━━━━━\n"
    msg += "💡 အခြား Research Tools ကြည့်ရန် \"research tools\" ရိုက်ပါ"
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
    "စျေး", "စျေးနှုန်း", "ကျပ်", "သိန်း", "ks",
    "ဖုန်းဈေးနှုန်း", "ဖုန်းစျေးနှုန်း"
]

VIDEO_KEYWORDS = [
    "review", "unboxing", "video", "youtube", "tip", "compare",
    "comparison", "camera", "battery", "performance", "benchmark",
    "ဗီဒီယို", "ရီဗျူး", "သုံးသပ်", "နှိုင်းယှဉ်", "ကင်မရာ",
    "ဘက်ထရီ", "အားထုတ်", "ကြည့်", "ဖွင့်", "unbox"
]

PRICELIST_KEYWORDS = [
    "price list", "pricelist", "ဈေးနှုန်းစာရင်း", "စာရင်း",
    "ဈေးစာရင်း", "စျေးစာရင်း", "စျေးနှုန်းစာရင်း",
    "brand list", "all prices", "ဈေးအားလုံး"
]

RESEARCH_KEYWORDS = [
    "research", "tools", "compare", "comparison", "benchmark",
    "gsmarena", "nanoreview", "dxomark", "antutu", "geekbench", "kimovil",
    "soc", "chip", "processor", "cpu", "gpu",
    "research tools", "သုတေသန", "ကိရိယာ",
    "နှိုင်းယှဉ်", "စစ်ဆေး"
]

SPECS_KEYWORDS = [
    "specs", "spec", "specification", "detail",
    "အသေးစိတ်", "သတ်မှတ်ချက်"
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

    # Check for pricelist command (e.g., "pricelist iPhone", "pricelist all 2")
    if text_lower.startswith("pricelist ") or text_lower == "pricelist":
        return "pricelist_browse"

    # Check for specs command (e.g., "specs iPhone 16")
    if text_lower.startswith("specs "):
        return "specs"

    # Check for price list intent
    if any(kw in text_lower for kw in PRICELIST_KEYWORDS):
        return "pricelist"

    # Check for research tools intent
    if any(kw in text_lower for kw in RESEARCH_KEYWORDS):
        return "research"

    # Check for specs intent
    if any(kw in text_lower for kw in SPECS_KEYWORDS):
        return "specs"

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
        # Special dict: web-chat renders as shortcut buttons; Messenger uses send_quick_replies
        responses.append({
            "__type": "quick_replies",
            "text": "ဘာများကူညီရမလဲ ခင်ဗျာ? 🌟\nအောက်ပါ ခလုတ်များကို နှိပ်ပြီး လိုအပ်သည်ကို ရွေးချယ်နိုင်ပါတယ်။",
            "quick_replies": [
                {"label": "📱 ဖုန်းဈေးနှုန်း",    "message": "ဖုန်းဈေးနှုန်း"},
                {"label": "📋 ဈေးနှုန်းစာရင်း",  "message": "ဈေးနှုန်းစာရင်း"},
                {"label": "🔍 Specs ကြည့်မယ်",   "message": "specs "},
                {"label": "🔬 Research Tools",    "message": "research tools"},
                {"label": "🏠 ဆိုင်တည်နေရာ",    "message": "ဆိုင်"},
                {"label": "🛒 အော်ဒါမှာမယ်",    "message": "မှာမယ်"},
                {"label": "🎬 Review ဗီဒီယို",  "message": "review"},
                {"label": "📞 ဆက်သွယ်ရန်",      "message": "ဆက်သွယ်"},
            ]
        })

    elif intent == "pricelist":
        responses.append(format_price_list_brands())

    elif intent == "pricelist_browse":
        # Parse "pricelist <brand> <page>"
        parts = text.strip().split()
        brand = "all"
        page = 1
        if len(parts) >= 2:
            brand = parts[1]
        if len(parts) >= 3:
            try:
                page = int(parts[2])
            except ValueError:
                page = 1
        data = get_price_list_by_brand(brand, page)
        responses.append(format_price_list(data))

    elif intent == "research":
        responses.append(format_research_tools())

    elif intent == "specs":
        # Extract phone name from "specs <phone>" or general specs query
        query = text.strip()
        if query.lower().startswith("specs "):
            query = query[6:].strip()
        results = get_phone_specs_link(query)
        responses.append(format_specs_results(results, query))

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
        # If the message is exactly the quick-reply label (no specific model), prompt for model name
        generic_price_triggers = ["ဖုန်းဈေးနှုန်း", "ဖုန်းစျေးနှုန်း", "phone price", "price"]
        if text.strip().lower() in [t.lower() for t in generic_price_triggers]:
            responses.append(
                "📱 ဖုန်းဈေးနှုန်း စစ်ဆေးရန်\n\n"
                "ဖုန်းအမည် သိုမှုတ် Brand ကို ရိုက်ထည့်ပြီးပါ ခင်ဗျာ\u2193\n\n"
                "ဥပမာ၊\n"
                "\u2022 iPhone 16\n"
                "\u2022 Samsung S25\n"
                "\u2022 Redmi Note 15\n"
                "\u2022 Tecno Spark 30\n"
                "\u2022 Infinix Hot 50\n"
                "\u2022 Vivo Y300\n\n"
                "📋 ဖုန်းအမည်အအးကို \"ဈေးနှုန်းစာရင်း\" ကို မေးမြန်းပါခင်ဘဗျာ။"
            )
        else:
            phones = search_phones(text)
            responses.append(format_phone_results(phones))

        # Also check for relevant videos (skip for generic triggers)
        videos = [] if text.strip().lower() in [t.lower() for t in generic_price_triggers] else find_relevant_videos(text, max_results=2)
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
        
        # Check if this might be a phone model name instead of a phone number
        # This helps users who accidentally type a phone model during order flow
        if len(phone_digits) < 8:
            # Try searching for it as a phone model
            potential_phones = search_phones(phone)
            if potential_phones:
                # User likely typed a phone model name, not a phone number
                responses.append(
                    f"📱 \"{phone}\" သည် ဖုန်းမော်ဒယ်အမည်ကဲ့သို့ ထင်ရှားပါတယ်။\n\n"
                    f"💡 အော်ဒါမှာယူရန် သင့်ဖုန်းနံပါတ်ကို ပြောပြပေးပါ ခင်ဗျာ။\n"
                    f"(ဥပမာ - 09xxxxxxxxx)\n\n"
                    f"📱 \"{ potential_phones[0]['brand']} {potential_phones[0]['name']}\" ၏ ဈေးနှုန်းကို ကြည့်လိုပါက \"cancel\" ရိုက်ပြီး \"{ potential_phones[0]['brand']} {potential_phones[0]['name']}\" ကို ရိုက်ပါ။"
                )
                return responses
            else:
                # Not a phone model either, show error
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


# Quick reply shortcuts shown after greeting
GREETING_QUICK_REPLIES = [
    {"content_type": "text", "title": "📱 ဖုန်းဈေးနှုန်း",     "payload": "QR_PHONE_PRICES"},
    {"content_type": "text", "title": "📋 ဈေးနှုန်းစာရင်း",   "payload": "QR_PRICE_LIST"},
    {"content_type": "text", "title": "🔍 Specs ကြည့်မယ်",    "payload": "QR_SPECS"},
    {"content_type": "text", "title": "🔬 Research Tools",     "payload": "QR_RESEARCH"},
    {"content_type": "text", "title": "🏠 ဆိုင်တည်နေရာ",     "payload": "QR_STORE"},
    {"content_type": "text", "title": "🛒 အော်ဒါမှာမယ်",     "payload": "QR_ORDER"},
    {"content_type": "text", "title": "🎬 Review ဗီဒီယို",   "payload": "QR_VIDEO"},
    {"content_type": "text", "title": "📞 ဆက်သွယ်ရန်",       "payload": "QR_CONTACT"},
]


def send_quick_replies(recipient_id, text, quick_replies):
    """Send a message with Facebook Messenger Quick Reply buttons."""
    if not PAGE_ACCESS_TOKEN:
        logger.warning("PAGE_ACCESS_TOKEN not set. Quick reply not sent.")
        return

    url = "https://graph.facebook.com/v19.0/me/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {
            "text": text,
            "quick_replies": quick_replies[:13],  # Messenger allows max 13
        },
    }
    try:
        resp = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Send quick replies failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Send quick replies error: {e}")


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
                        "title": "📋 ဈေးနှုန်းစာရင်း",
                        "payload": "PRICE_LIST"
                    },
                    {
                        "type": "postback",
                        "title": "🔬 Research Tools",
                        "payload": "RESEARCH_TOOLS"
                    },
                    {
                        "type": "postback",
                        "title": "🏠 ဆိုင်တည်နေရာ",
                        "payload": "STORE_LOCATION"
                    },
                    {
                        "type": "postback",
                        "title": "🛒 အော်ဒါမှာယူမယ်",
                        "payload": "ORDER"
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
@app.route("/ping", methods=["GET", "HEAD"])
def ping():
    """Ultra-lightweight ping endpoint for keep-alive monitors (no DB, no cache)."""
    return "pong", 200


@app.route("/", methods=["GET"])
def index():
    """Health check / landing page."""
    return jsonify({
        "name": "ZORA Ai Agent",
        "description": "Facebook Messenger Chatbot for ZEST Mobile Shop",
        "status": "running",
        "version": "3.0.0",
        "endpoints": {
            "webhook": "/webhook",
            "health": "/health",
            "ping": "/ping",
            "test": "/test?q=<phone_model>",
            "web_chat": "/web-chat",
            "web_chat_greeting": "/web-chat/greeting",
            "widget": "/widget.js",
            "setup": "/setup"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "bot": "ZORA Ai Agent"})


@app.route("/widget.js", methods=["GET"])
def serve_widget():
    """Serve the chat widget JavaScript with CORS headers."""
    widget_path = os.path.join(BASE_DIR, "static", "zora-widget.js")
    try:
        with open(widget_path, "r", encoding="utf-8") as f:
            js_content = f.read()
        resp = make_response(js_content)
        resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'public, max-age=300, must-revalidate'
        return resp
    except Exception as e:
        logger.error(f"Error serving widget: {e}")
        return "// Widget not found", 404


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
                    if isinstance(resp, dict) and resp.get("__type") == "quick_replies":
                        # Send native Messenger quick reply buttons
                        send_quick_replies(sender_id, resp["text"], [
                            {"content_type": "text", "title": qr["label"], "payload": "QR_" + qr["message"].upper().replace(" ", "_")[:20]}
                            for qr in resp["quick_replies"]
                        ])
                    else:
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
        send_quick_replies(
            sender_id,
            "ဘာများကူညီရမလဲ ခင်ဗျာ? \U0001f31f\nအောက်ပါ ခလုတ်များကို နှိပ်ပြီး လိုအပ်သည်ကို ရွေးချယ်နိုင်ပါတယ်။",
            GREETING_QUICK_REPLIES
        )
    elif payload in ("PHONE_PRICES", "QR_PHONE_PRICES"):
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
    elif payload in ("PRICE_LIST", "QR_PRICE_LIST"):
        send_message(sender_id, format_price_list_brands())
    elif payload in ("RESEARCH_TOOLS", "QR_RESEARCH"):
        send_message(sender_id, format_research_tools())
    elif payload in ("STORE_LOCATION", "QR_STORE"):
        send_message(sender_id, STORE_INFO)
    elif payload in ("ORDER", "QR_ORDER"):
        session = get_session(sender_id)
        session["state"] = "awaiting_name"
        session["order"] = {}
        send_message(
            sender_id,
            "🛒 အော်ဒါမှာမယ်ခြင်း\n━━━━━━━━━━━━━━━\n\n" + ORDER_STEPS["awaiting_name"]
        )
    elif payload == "QR_SPECS":
        send_message(
            sender_id,
            "\U0001f50d Specs \u1000\u103c\u100a\u1037\u103a\u101b\u1014\u103a\n\n"
            "\u1016\u102f\u1014\u103a\u1038\u1021\u1019\u100a\u103a\u1000\u102d\u102f \u101b\u102d\u102f\u1000\u103a\u1011\u100a\u103a\u1037\u1015\u103c\u102e\u1038 \u1015\u103c\u102f\u1015\u103c\u102e\u1038\u1015\u102b \u1001\u1004\u103a\u1018\u1017\u103b\u102c\u104b\n\n"
            "\u1025\u1015\u1019\u102c\u104a\n"
            "\u2022 specs iPhone 16\n"
            "\u2022 specs Samsung S25\n"
            "\u2022 specs Redmi Note 15"
        )
    elif payload == "QR_VIDEO":
        send_message(
            sender_id,
            "\U0001f3ac Review \u1017\u102e\u1012\u102e\u101a\u102d\u102f \u1000\u103c\u100a\u1037\u103a\u101b\u1014\u103a\n\n"
            "\u1016\u102f\u1014\u103a\u1038\u1021\u1019\u100a\u103a\u1000\u102d\u102f \u101b\u102d\u102f\u1000\u103a\u1011\u100a\u103a\u1037\u1015\u103c\u102e\u1038 \u1015\u103c\u102f\u1015\u103c\u102e\u1038\u1015\u102b \u1001\u1004\u103a\u1018\u1017\u103b\u102c\u104b\n\n"
            "\u1025\u1015\u1019\u102c\u104a\n"
            "\u2022 iPhone 16 review\n"
            "\u2022 Samsung S25 unboxing\n"
            "\u2022 Redmi Note 15 \u1017\u102e\u1012\u102e"
        )
    elif payload == "QR_CONTACT":
        send_message(sender_id, STORE_INFO)


# ---------------------------------------------------------------------------
# Web Chat API Endpoint (for website widget)
# ---------------------------------------------------------------------------
@app.route("/web-chat", methods=["POST", "OPTIONS"])
def web_chat():
    """API endpoint for the website chat widget.
    
    Accepts POST with JSON: {"message": "...", "session_id": "..."}
    Returns JSON: {"responses": [...], "session_id": "..."}
    """
    origin = request.headers.get('Origin', '')
    
    # Handle CORS preflight
    if request.method == "OPTIONS":
        resp = make_response('', 204)
        return add_cors_headers(resp, origin)
    
    data = request.get_json()
    if not data or "message" not in data:
        resp = jsonify({"error": "Missing 'message' field"})
        return add_cors_headers(resp, origin), 400
    
    message = data["message"].strip()
    session_id = data.get("session_id", f"web_{uuid.uuid4().hex[:12]}")
    
    # Prefix web sessions to avoid collision with Messenger sessions
    web_session_id = f"web_{session_id}" if not session_id.startswith("web_") else session_id
    
    if not message:
        resp = jsonify({"error": "Empty message"})
        return add_cors_headers(resp, origin), 400
    
    logger.info(f"Web chat [{web_session_id}]: {message}")
    
    # Process message using the same logic as Messenger
    raw_responses = process_message(web_session_id, message)
    
    # Separate plain text responses from quick_reply dicts
    text_responses = []
    quick_replies_data = None
    for r in raw_responses:
        if isinstance(r, dict) and r.get("__type") == "quick_replies":
            quick_replies_data = r  # widget will render these as tap buttons
        else:
            text_responses.append(r)
    
    response_payload = {
        "responses": text_responses,
        "session_id": session_id,
        "intent": detect_intent(message)
    }
    if quick_replies_data:
        response_payload["quick_replies"] = quick_replies_data
    
    resp = jsonify(response_payload)
    return add_cors_headers(resp, origin)


@app.route("/web-chat/greeting", methods=["GET", "OPTIONS"])
def web_chat_greeting():
    """Return the greeting message for the web chat widget."""
    origin = request.headers.get('Origin', '')
    
    if request.method == "OPTIONS":
        resp = make_response('', 204)
        return add_cors_headers(resp, origin)
    
    resp = jsonify({
        "greeting": GREETING_MESSAGE,
        "greeting_reply": {
            "text": "ဘာများကူညီရမလဲ ခင်ဗျာ? 🌟\nအောက်ပါ ခလုတ်များကို နှိပ်ပြီး လိုအပ်သည်ကို ရွေးချယ်နိုင်ပါတယ်။",
            "quick_replies": [
                {"label": "📱 ဖုန်းဈေးနှုန်း",   "message": "ဖုန်းဈေးနှုန်း"},
                {"label": "📋 ဈေးနှုန်းစာရင်း", "message": "ဈေးနှုန်းစာရင်း"},
                {"label": "🔍 Specs ကြည့်မယ်",  "message": "specs "},
                {"label": "🔬 Research Tools",   "message": "research tools"},
                {"label": "🏠 ဆိုင်တည်နေရာ",   "message": "ဆိုင်"},
                {"label": "🛒 အော်ဒါမှာမယ်",   "message": "မှာမယ်"},
                {"label": "🎬 Review ဗီဒီယို", "message": "review"},
                {"label": "📞 ဆက်သွယ်ရန်",     "message": "ဆက်သွယ်"}
            ]
        },
        "quick_actions": [
            {"label": "📱 ဖုန်းဈေးနှုန်း",   "message": "ဖုန်းဈေးနှုန်း"},
            {"label": "📋 ဈေးနှုန်းစာရင်း", "message": "ဈေးနှုန်းစာရင်း"},
            {"label": "🔍 Specs ကြည့်မယ်",  "message": "specs "},
            {"label": "🔬 Research Tools",   "message": "research tools"},
            {"label": "🏠 ဆိုင်တည်နေရာ",   "message": "ဆိုင်"},
            {"label": "🛒 အော်ဒါမှာမယ်",   "message": "မှာမယ်"},
            {"label": "🎬 Review ဗီဒီယို", "message": "review"},
            {"label": "📞 ဆက်သွယ်ရန်",     "message": "ဆက်သွယ်"}
        ]
    })
    return add_cors_headers(resp, origin)


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
    This pings the health endpoint every 10 minutes to keep the app alive.
    We also use an external UptimeRobot-style approach: ping our own public URL.
    """
    global keep_alive_enabled
    
    # Use the public Render URL if available, otherwise localhost
    server_url = os.environ.get("SERVER_URL", "")
    if not server_url:
        # Auto-detect from RENDER_EXTERNAL_URL (Render sets this automatically)
        server_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")
    
    logger.info(f"🔄 Keep-alive worker started. Will ping {server_url}/health every 10 minutes")
    
    # Do an immediate first ping after 30 seconds to confirm the URL works
    time.sleep(30)
    try:
        response = requests.get(f"{server_url}/ping", timeout=15)
        logger.info(f"✅ Keep-alive initial ping: {response.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Keep-alive initial ping failed (will retry): {e}")
    
    while keep_alive_enabled:
        try:
            time.sleep(600)  # Wait 10 minutes (well under Render's 15-min sleep threshold)
            if not keep_alive_enabled:
                break
            
            response = requests.get(f"{server_url}/ping", timeout=15)
            if response.status_code == 200:
                logger.info(f"✅ Keep-alive ping OK at {time.strftime('%Y-%m-%d %H:%M:%S')}")
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
# Module-level startup (runs in BOTH gunicorn workers AND direct python run)
# ---------------------------------------------------------------------------
def _on_startup():
    """Called at module import time so Gunicorn workers also initialise properly."""
    # Start keep-alive for Render / production (works with Gunicorn)
    if os.environ.get("RENDER") == "true" or os.environ.get("ENVIRONMENT") == "production":
        start_keep_alive()
        logger.info("🚀 Keep-alive activated (Render/production mode)")

_on_startup()


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

    # Use app.run() for development, gunicorn for production
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
