import base64
import json
import mimetypes
import random
import string
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Deque, Dict, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
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

                                                                      

CACHE_MAX_SIZE = 20
CACHE_PREFILL_TARGET = 20
CACHE_WORKER_COUNT = 4
CACHE_REFILL_DELAY_OK = 0.3
CACHE_REFILL_DELAY_FAIL = 1.5

DISK_CACHE_DIR = Path("storage/images")
DISK_CACHE_MAX_ITEMS = 1000
DISK_IDLE_SLEEP = 5
DISK_META_SUFFIX = ".json"
DISK_IMAGE_DEFAULT_SUFFIX = ".bin"

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

PRNT_RATE_LIMIT = 45
PRNT_RATE_WINDOW = 60
PRNT_RATE_SLEEP_SLICE = 0.5

BAN_INTERVAL_SECONDS = 15 * 60
BAN_NOTICE_TEXT = "Sorry, waiting for prnt.sc to unban us."
BAN_STATUS_CODES = {403, 429, 503}
BAN_KEYWORDS = ("temporarily blocked", "access denied", "rate limit")

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

cache: Deque[Dict[str, Any]] = deque()
cache_lock = threading.Lock()
disk_cache_lock = threading.Lock()
disk_cache_count = 0
disk_serving_lock = threading.Lock()
disk_serving_registry: Dict[str, Dict[str, Any]] = {}

prnt_rate_lock = threading.Lock()
prnt_request_times: Deque[float] = deque()

prnt_ban_lock = threading.Lock()
prnt_ban_active = False
prnt_next_retry_ts = 0.0
prnt_ban_reason = ""

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


def init_disk_cache_dir():
    global disk_cache_count
    DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with disk_cache_lock:
        valid_files = set()
        for meta_path in DISK_CACHE_DIR.glob(f"*{DISK_META_SUFFIX}"):
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                meta_path.unlink(missing_ok=True)
                continue
            file_name = meta.get("file_name") or f"{meta.get('id')}{DISK_IMAGE_DEFAULT_SUFFIX}"
            image_path = DISK_CACHE_DIR / file_name
            if image_path.exists():
                valid_files.add(file_name)
            else:
                meta_path.unlink(missing_ok=True)
        for file_path in DISK_CACHE_DIR.iterdir():
            if not file_path.is_file():
                continue
            if file_path.suffix == DISK_META_SUFFIX:
                continue
            if file_path.name not in valid_files:
                file_path.unlink(missing_ok=True)
        disk_cache_count = len(valid_files)


def get_disk_cache_count() -> int:
    with disk_cache_lock:
        return disk_cache_count


def determine_disk_file_name(item: Dict[str, Any]) -> str:
    content_type = (item.get("content_type") or "").split(";")[0].lower()
    suffix = CONTENT_TYPE_EXTENSIONS.get(content_type, DISK_IMAGE_DEFAULT_SUFFIX)
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{item['id']}{suffix}"


def register_disk_file_inflight(file_name: str, content_type: str):
    with disk_serving_lock:
        disk_serving_registry[file_name] = {
            "path": str(DISK_CACHE_DIR / file_name),
            "content_type": content_type or "image/png",
        }


def mark_disk_file_served(file_name: str):
    with disk_serving_lock:
        disk_serving_registry.pop(file_name, None)
    file_path = DISK_CACHE_DIR / file_name
    try:
        file_path.unlink(missing_ok=True)
    finally:
        with disk_cache_lock:
            global disk_cache_count
            disk_cache_count = max(0, disk_cache_count - 1)


def guess_content_type_from_name(file_name: str, default: str = "image/png") -> str:
    content_type, _ = mimetypes.guess_type(file_name)
    return content_type or default


def sanitize_disk_file_name(file_name: str) -> Optional[str]:
    candidate = Path(file_name).name
    if candidate != file_name or candidate.startswith("."):
        return None
    return candidate


def save_item_to_disk(item: Dict[str, Any]) -> bool:
    if not item or not item.get("image_bytes"):
        return False
    with disk_cache_lock:
        global disk_cache_count
        if disk_cache_count >= DISK_CACHE_MAX_ITEMS:
            return False
        meta_path = DISK_CACHE_DIR / f"{item['id']}{DISK_META_SUFFIX}"
        file_name = determine_disk_file_name(item)
        data_path = DISK_CACHE_DIR / file_name
        if meta_path.exists() or data_path.exists():
            return False
        try:
            data_path.write_bytes(item["image_bytes"])
            meta = {
                "id": item["id"],
                "page_url": item["page_url"],
                "content_type": item["content_type"],
                "original_image_url": item.get("original_image_url"),
                "saved_at": time.time(),
                "file_name": file_name,
            }
            meta_path.write_text(json.dumps(meta))
            disk_cache_count += 1
            print(f"[disk] stored id={item['id']}, disk_size={disk_cache_count}")
            return True
        except OSError as exc:
            print(f"[disk] failed to store id={item['id']}: {exc}")
            if data_path.exists():
                data_path.unlink(missing_ok=True)
            if meta_path.exists():
                meta_path.unlink(missing_ok=True)
            return False


def load_item_from_disk() -> Optional[Dict[str, Any]]:
    with disk_cache_lock:
        meta_files = sorted(DISK_CACHE_DIR.glob(f"*{DISK_META_SUFFIX}"), key=lambda p: p.stat().st_mtime)
        for meta_path in meta_files:
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[disk] failed to parse {meta_path.name}: {exc}")
                meta_path.unlink(missing_ok=True)
                continue
            file_name = meta.get("file_name") or f"{meta['id']}{DISK_IMAGE_DEFAULT_SUFFIX}"
            data_path = DISK_CACHE_DIR / file_name
            if not data_path.exists():
                print(f"[disk] missing file for id={meta['id']}, removing meta")
                meta_path.unlink(missing_ok=True)
                continue
            meta_path.unlink(missing_ok=True)
            register_disk_file_inflight(file_name, meta.get("content_type", "image/png"))
            print(f"[disk] queued for serving id={meta['id']}, disk_size={disk_cache_count}")
            return {
                "id": meta["id"],
                "page_url": meta["page_url"],
                "content_type": meta.get("content_type", "image/png"),
                "disk_file_name": file_name,
                "original_image_url": meta.get("original_image_url"),
            }
    return None


def should_idle_fetchers() -> bool:
    return cache_len() >= CACHE_MAX_SIZE and get_disk_cache_count() >= DISK_CACHE_MAX_ITEMS


def enforce_prnt_rate_limit():
    while True:
        with prnt_rate_lock:
            now = time.monotonic()
            while prnt_request_times and now - prnt_request_times[0] >= PRNT_RATE_WINDOW:
                prnt_request_times.popleft()
            if len(prnt_request_times) < PRNT_RATE_LIMIT:
                prnt_request_times.append(now)
                return
            wait_for = PRNT_RATE_WINDOW - (now - prnt_request_times[0])
        sleep_for = max(PRNT_RATE_SLEEP_SLICE, wait_for)
        time.sleep(min(sleep_for, PRNT_RATE_WINDOW))


def attempt_prnt_probe() -> bool:
    print("[ban] attempting probe request to prnt.sc")
    try:
        enforce_prnt_rate_limit()
        resp = SESSION.get(PRNT_BASE_URL, headers=COMMON_HEADERS, timeout=5)
        if resp.status_code == 200:
            print("[ban] probe successful")
            return True
        print(f"[ban] probe failed with status {resp.status_code}")
    except requests.exceptions.RequestException as exc:
        print(f"[ban] probe exception: {exc}")
    return False


def mark_prnt_banned(reason: str):
    global prnt_ban_active, prnt_next_retry_ts, prnt_ban_reason
    with prnt_ban_lock:
        prnt_ban_active = True
        prnt_next_retry_ts = time.monotonic() + BAN_INTERVAL_SECONDS
        prnt_ban_reason = reason
        print(f"[ban] marked prnt.sc as banned: {reason}")


def wait_for_prnt_availability():
    global prnt_ban_active, prnt_ban_reason, prnt_next_retry_ts
    while True:
        with prnt_ban_lock:
            if not prnt_ban_active:
                return
            retry_at = prnt_next_retry_ts
        now = time.monotonic()
        if now < retry_at:
            time.sleep(min(retry_at - now, 5))
            continue
        if attempt_prnt_probe():
            with prnt_ban_lock:
                prnt_ban_active = False
                prnt_ban_reason = ""
                prnt_next_retry_ts = 0.0
            return
        with prnt_ban_lock:
            prnt_next_retry_ts = time.monotonic() + BAN_INTERVAL_SECONDS
        time.sleep(min(BAN_INTERVAL_SECONDS, 10))


def is_prnt_banned() -> bool:
    with prnt_ban_lock:
        return prnt_ban_active


def get_prnt_ban_message() -> Optional[str]:
    if is_prnt_banned():
        return BAN_NOTICE_TEXT
    return None


def build_data_url(item: Dict[str, Any]) -> str:
    b64 = base64.b64encode(item["image_bytes"]).decode("ascii")
    content_type = item.get("content_type", "image/png")
    return f"data:{content_type};base64,{b64}"


def prepare_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "id": item["id"],
        "page_url": item["page_url"],
        "original_image_url": item.get("original_image_url"),
    }
    if item.get("disk_file_name"):
        payload["image_url"] = f"/storage/{item['disk_file_name']}"
        payload["image_source"] = "disk"
    elif item.get("image_bytes"):
        payload["image_url"] = build_data_url(item)
        payload["image_source"] = "memory"
    else:
        payload["image_url"] = item.get("image_url") or item.get("original_image_url")
        payload["image_source"] = "external"
    return payload


                                                                      

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


def fetch_prnt_image(prnt_id: str) -> Optional[Dict[str, Any]]:
    page_url = f"{PRNT_BASE_URL}/{prnt_id}"

    wait_for_prnt_availability()
    try:
        enforce_prnt_rate_limit()
        resp = SESSION.get(page_url, headers=COMMON_HEADERS, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"[page] error for id={prnt_id}: {e}")
        return None

    if resp.status_code in BAN_STATUS_CODES:
        mark_prnt_banned(f"status {resp.status_code}")
        return None

    if resp.status_code != 200:
        print(f"[page] non-200 ({resp.status_code}) for id={prnt_id}")
        return None

    lowered_html = resp.text.lower()
    if any(keyword in lowered_html for keyword in BAN_KEYWORDS):
        mark_prnt_banned("keyword match in html")
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

            image_buffer = bytearray()
            for chunk in img_resp.iter_content(8192):
                if not chunk:
                    continue
                image_buffer.extend(chunk)
                if len(image_buffer) > MAX_IMAGE_SIZE_BYTES:
                    print(f"[img] too large (> {MAX_IMAGE_SIZE_BYTES}) id={prnt_id}")
                    return None
    except requests.exceptions.RequestException as e:
        print(f"[img] error for id={prnt_id}: {e}")
        return None

    if not image_buffer:
        print(f"[img] empty image for id={prnt_id}")
        return None

    lowered = image_buffer[:1024].lower()
    if b"<html" in lowered or b"<!doctype html" in lowered:
        print(f"[img] looks like HTML, not image, id={prnt_id}")
        return None

    return {
        "id": prnt_id,
        "page_url": page_url,
        "content_type": content_type,
        "image_bytes": bytes(image_buffer),
        "original_image_url": img_url,
    }


def fetch_one_valid_screenshot(max_attempts: int = 10) -> Optional[Dict[str, Any]]:
    last_reason = "unknown"
    for i in range(max_attempts):
        prnt_id = generate_id()
        print(f"[try] {i+1}/{max_attempts}, id={prnt_id}")
        image_item = fetch_prnt_image(prnt_id)
        if image_item:
            print(f"[ok] id={prnt_id} ready for cache")
            return image_item
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
        return prepare_payload(item)

    disk_item = load_item_from_disk()
    if disk_item:
        print(f"[disk] serve id={disk_item['id']}")
        return prepare_payload(disk_item)

    print("[cache] empty, fetching live...")
    item = fetch_one_valid_screenshot()
    if not item:
        message = "Failed to find a valid screenshot. prnt.sc might be unavailable."
        if is_prnt_banned():
            message = "prnt.sc temporarily blocked our requests."
        raise HTTPException(
            status_code=503,
            detail=message,
        )
    return prepare_payload(item)


def cache_worker():
    while True:
        try:
            if should_idle_fetchers():
                print("[cache] idle: memory+disk limits reached")
                time.sleep(DISK_IDLE_SLEEP)
                continue

            if cache_len() < CACHE_MAX_SIZE:
                item = fetch_one_valid_screenshot()
                if not item:
                    time.sleep(CACHE_REFILL_DELAY_FAIL)
                    continue
                if cache_push(item):
                    print(f"[cache] push id={item['id']}, cache_size={cache_len()}")
                    time.sleep(CACHE_REFILL_DELAY_OK)
                    continue
                if save_item_to_disk(item):
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
        elif not save_item_to_disk(item):
            print(f"[prefill] could not store id={item['id']} (cache+disk full)")
            break


@app.on_event("startup")
def on_startup():
    init_disk_cache_dir()
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
        "default_lang": DEFAULT_LANG,
        "emoji_list": ["✨", "⚡️", "🌠", "🎲", "🎯", "🚀", "🌈", "🌀", "💫"],
    }
    ban_message = get_prnt_ban_message()
    if ban_message:
        context["prnt_ban_message"] = ban_message
    return templates.TemplateResponse("show_random.html", context)


@app.get("/storage/{file_name}")
def serve_cached_image(file_name: str, background_tasks: BackgroundTasks):
    safe_name = sanitize_disk_file_name(file_name)
    if not safe_name:
        raise HTTPException(status_code=404, detail="Image was removed.")
    file_path = DISK_CACHE_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image was removed.")
    with disk_serving_lock:
        inflight = disk_serving_registry.pop(safe_name, None)
    content_type = guess_content_type_from_name(safe_name)
    if inflight:
        content_type = inflight.get("content_type", content_type)
    background_tasks.add_task(mark_disk_file_served, safe_name)
    return FileResponse(file_path, media_type=content_type, filename=safe_name)
