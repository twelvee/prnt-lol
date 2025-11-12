import random
import string
import threading
import time
from collections import deque
from typing import Optional, Deque, Dict, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from requests.adapters import HTTPAdapter

PRNT_BASE_URL = "https://prnt.sc"

app = FastAPI(
    title="Prnt.sc Random Screenshot API",
    description="API delivering random screenshots from prnt.sc",
    version="2.1.0",
)

                                                              
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

                                                                      

CACHE_MAX_SIZE = 60
CACHE_PREFILL_TARGET = 40
CACHE_WORKER_COUNT = 4
CACHE_REFILL_DELAY_OK = 0.3
CACHE_REFILL_DELAY_FAIL = 1

cache: Deque[Dict[str, Any]] = deque()
cache_lock = threading.Lock()
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(pool_connections=64, pool_maxsize=64))
SESSION.mount("http://", HTTPAdapter(pool_connections=64, pool_maxsize=64))

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

                                                                                       
BLOCKED_DOMAINS = [
    "imgur.com",
    "i.imgur.com",
]

SITE_TITLE = "prnt.lol (prnt.sc random images)"

LANGUAGE_TEXT = {
    "ru": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "Оригинал:",
        "hint": "Нажми “Следующий” или обнови страницу (F5) для новой картинки.",
        "button": "Следующий",
        "language_name": "🇷🇺",
        "language_label": "Русский",
        "loading_hint": "Если долго грузит — обнови страницу.",
        "title_popover": "prnt.sc — часть интернет-культуры, этот сайт помогает быстро вспомнить и поностальгировать.",
    },
    "en": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "Original:",
        "hint": "Tap “Next” or refresh (F5) to get another screenshot.",
        "button": "Next",
        "language_name": "🇬🇧",
        "language_label": "English",
        "loading_hint": "If it loads too long, refresh the page.",
        "title_popover": "prnt.sc is a slice of internet culture—this viewer brings the nostalgia back in one click.",
    },
    "uk": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "Оригінал:",
        "hint": "Натисни “Наступний” або онови сторінку (F5), щоб побачити інший скрин.",
        "button": "Наступний",
        "language_name": "🇺🇦",
        "language_label": "Українська",
        "loading_hint": "Якщо довго вантажиться — онови сторінку.",
        "title_popover": "prnt.sc — частинка інтернет-культури, а цей сайт дозволяє легко згадати її й поностальгувати.",
    },
    "pt-br": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "Original:",
        "hint": "Clique em “Próximo” ou atualize (F5) para ver outra captura.",
        "button": "Próximo",
        "language_name": "🇧🇷",
        "language_label": "Português (BR)",
        "loading_hint": "Se demorar para carregar, atualize a página.",
        "title_popover": "prnt.sc faz parte da cultura da internet, e este site ajuda a reviver essa nostalgia facilmente.",
    },
    "ja": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "オリジナル:",
        "hint": "「次へ」を押すかページを更新（F5）して新しいスクリーンショットを表示。",
        "button": "次へ",
        "language_name": "🇯🇵",
        "language_label": "日本語",
        "loading_hint": "読み込みが長いときはページをリロードしてください。",
        "title_popover": "prnt.sc はインターネット文化の一部。このビューアで気軽に思い出してノスタルジーに浸ろう。",
    },
    "zh": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "原始链接:",
        "hint": "点击“下一张”或刷新页面 (F5) 获取新的截图。",
        "button": "下一张",
        "language_name": "🇨🇳",
        "language_label": "中文",
        "loading_hint": "如果加载太久，请刷新页面。",
        "title_popover": "prnt.sc 是互联网文化的一部分，这个站点让你轻松回味那份怀旧。",
    },
    "de": {
        "page_title": SITE_TITLE,
        "viewer_title": SITE_TITLE,
        "original_label": "Original:",
        "hint": "Klicke auf „Weiter“ oder aktualisiere (F5), um einen weiteren Screenshot zu sehen.",
        "button": "Weiter",
        "language_name": "🇩🇪",
        "language_label": "Deutsch",
        "loading_hint": "Wenn das Laden zu lange dauert, lade die Seite neu.",
        "title_popover": "prnt.sc ist ein Stück Internetkultur – dieser Viewer holt das Nostalgiegefühl sofort zurück.",
    },
}

DEFAULT_LANG = "en"

templates = Jinja2Templates(directory="templates")
templates.env.auto_reload = True


                                                                      

def generate_id(length: int = 6) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def _extract_image_url_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")

                                 
    meta = soup.find("meta", property="og:image")
    if meta and meta.get("content"):
        return meta["content"]

                                                
    img = soup.find("img", id="screenshot-image")
    if img and img.get("src"):
        return img.get("src")

    return None


def is_blocked_domain(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
    except Exception:
        return False

    for blocked in BLOCKED_DOMAINS:
        if blocked in host:
            return True
    return False


def fetch_prnt_image(prnt_id: str) -> Optional[str]:
    page_url = f"{PRNT_BASE_URL}/{prnt_id}"

                            
    try:
        resp = SESSION.get(page_url, headers=COMMON_HEADERS, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"[page] error for id={prnt_id}: {e}")
        return None

    if resp.status_code != 200:
        print(f"[page] non-200 ({resp.status_code}) for id={prnt_id}")
        return None

    img_url = _extract_image_url_from_html(resp.text)
    if not img_url:
        print(f"[parse] no img tag for id={prnt_id}")
        return None

                     
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/"):
        img_url = PRNT_BASE_URL + img_url

    if not img_url.startswith("http"):
        print(f"[parse] bad img url for id={prnt_id}: {img_url}")
        return None

                                 
    if is_blocked_domain(img_url):
        print(f"[filter] blocked domain for id={prnt_id}: {img_url}")
        return None

                                 
    bad_parts = ["image-not-found", "st.prntscr.com"]
    if any(bad in img_url for bad in bad_parts):
        print(f"[filter] bad pattern in url for id={prnt_id}: {img_url}")
        return None

                                                                          
    try:
        with SESSION.get(
            img_url,
            headers={**COMMON_HEADERS, "Referer": page_url},
            stream=True,
            timeout=5,
        ) as img_resp:
            if img_resp.status_code != 200:
                print(f"[img] non-200 ({img_resp.status_code}) for id={prnt_id}")
                return None

            content_type = img_resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                print(f"[img] non-image content-type={content_type} for id={prnt_id}")
                return None

            try:
                chunk = next(img_resp.iter_content(1024), b"")
            except Exception as e:
                print(f"[img] read error for id={prnt_id}: {e}")
                return None
    except requests.exceptions.RequestException as e:
        print(f"[img] error for id={prnt_id}: {e}")
        return None

    lowered = chunk.lower()
    if b"<html" in lowered or b"<!doctype html" in lowered:
        print(f"[img] looks like HTML, not image, id={prnt_id}")
        return None

    return img_url


def fetch_one_valid_screenshot(max_attempts: int = 10) -> Optional[Dict[str, Any]]:
    last_reason = "unknown"
    for i in range(max_attempts):
        prnt_id = generate_id()
        print(f"[try] {i+1}/{max_attempts}, id={prnt_id}")
        image_url = fetch_prnt_image(prnt_id)
        if image_url:
            print(f"[ok] id={prnt_id} -> {image_url}")
            return {
                "id": prnt_id,
                "image_url": image_url,
                "page_url": f"{PRNT_BASE_URL}/{prnt_id}",
            }
        else:
            last_reason = "no valid image / timeout / blocked"
    print(f"[fail] couldn't find valid screenshot after {max_attempts} attempts: {last_reason}")
    return None


def cache_len() -> int:
    with cache_lock:
        return len(cache)


def cache_pop() -> Optional[Dict[str, Any]]:
    with cache_lock:
        if cache:
            return cache.popleft()
    return None


def cache_push(item: Dict[str, Any]) -> bool:
    with cache_lock:
        if len(cache) >= CACHE_MAX_SIZE:
            return False
        cache.append(item)
        return True


def get_from_cache_or_live() -> Dict[str, Any]:
    item = cache_pop()
    if item:
        print(f"[cache] pop id={item['id']}, cache_size={cache_len()}")
        return item

    print("[cache] empty, fetching live...")
    item = fetch_one_valid_screenshot()
    if not item:
        raise HTTPException(
            status_code=503,
            detail="Failed to find a valid screenshot. prnt.sc might be unavailable.",
        )
    return item


def cache_worker():
    while True:
        try:
            if cache_len() < CACHE_MAX_SIZE:
                item = fetch_one_valid_screenshot()
                if item and cache_push(item):
                    print(f"[cache] push id={item['id']}, cache_size={cache_len()}")
                    time.sleep(CACHE_REFILL_DELAY_OK)
                else:
                    time.sleep(CACHE_REFILL_DELAY_FAIL)
            else:
                time.sleep(CACHE_REFILL_DELAY_OK)
        except Exception as e:
            print(f"[cache] worker error: {e}")
            time.sleep(CACHE_REFILL_DELAY_FAIL)


def prefill_cache(target: int):
    target = min(target, CACHE_MAX_SIZE)
    while cache_len() < target:
        item = fetch_one_valid_screenshot()
        if not item:
            break
        if cache_push(item):
            print(f"[prefill] push id={item['id']}, cache_size={cache_len()}")


@app.on_event("startup")
def on_startup():
    prefill_cache(CACHE_PREFILL_TARGET)
    for idx in range(CACHE_WORKER_COUNT):
        t = threading.Thread(target=cache_worker, daemon=True)
        t.start()
        print(f"[startup] cache worker {idx+1} started")


                                                                      


@app.get("/", response_class=HTMLResponse)
def show_random_html(request: Request, lang: Optional[str] = Query(None, description="Interface language code")):
    data = get_from_cache_or_live()
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in LANGUAGE_TEXT:
        lang = DEFAULT_LANG
    texts = LANGUAGE_TEXT[lang]
    languages = [
        {
            "code": code,
            "name": info["language_name"],
            "label": info.get("language_label", info["language_name"]),
        }
        for code, info in LANGUAGE_TEXT.items()
    ]
    context = {
        "request": request,
        "data": data,
        "texts": texts,
        "languages": languages,
        "current_lang": lang,
        "site_title": SITE_TITLE,
        "emoji_list": ["✨", "⚡️", "🌠", "🎲", "🎯", "🚀", "🌈", "🌀", "💫"],
    }
    return templates.TemplateResponse("show_random.html", context)
