# hianimez_scraper.py
import re, asyncio, time
from urllib.parse import urljoin, urlparse, quote_plus
from typing import List, Tuple, Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import cloudscraper
import requests

from config import HIANIME_DOMAIN_POOL, COMMON_HEADERS, HTTP_TIMEOUT, RETRIES

# ------------------------
# Domain selection helpers
# ------------------------
def _pick_live_base() -> str:
    """
    Try domains in HIANIME_DOMAIN_POOL and return the first that responds 200
    for the home page. Falls back to the first in the list if all fail.
    """
    sess = requests.Session()
    sess.headers.update(COMMON_HEADERS)
    for base in HIANIME_DOMAIN_POOL:
        try:
            r = sess.get(base, timeout=10)
            if r.status_code < 500:
                return base.rstrip("/")
        except Exception:
            continue
    return HIANIME_DOMAIN_POOL[0].rstrip("/")

def _base_of(url: str) -> str:
    """
    Return scheme://host of a fully-qualified URL. If url is relative, use a live base.
    """
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return _pick_live_base()

def _abs(base: str, maybe_rel: str) -> str:
    return urljoin(base + "/", maybe_rel)

# ------------------------
# Playwright-rendered fetch
# ------------------------
async def _fetch_rendered_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": COMMON_HEADERS["User-Agent"]})
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # tiny delay for dynamic lists
        try:
            await page.wait_for_timeout(800)
        except:
            pass
        html = await page.content()
        await browser.close()
        return html

def _rendered_html(url: str) -> str:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_fetch_rendered_html(url))
    finally:
        loop.close()

# ------------------------
# 1) SEARCH
# ------------------------
def search_anime(query: str) -> List[Tuple[str, str, str]]:
    """
    Returns list of tuples: (title, anime_url, anime_url)
    """
    base = _pick_live_base()
    url = f"{base}/search?keyword={quote_plus(query)}"
    html = _rendered_html(url)

    soup = BeautifulSoup(html, "lxml")
    results = []
    container = soup.find("div", class_="film-list-wrap") or soup
    for a in container.select("div.film-poster a[href]"):
        rel_link = a.get("href", "").strip()
        if not rel_link:
            continue
        anime_url = _abs(base, rel_link)
        # try to get title
        title = a.get("title") or a.get_text(strip=True) or "Unknown"
        results.append((title, anime_url, anime_url))
    return results

# ------------------------
# 2) EPISODE LIST
# ------------------------
async def _fetch_episodes_html(anime_url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": COMMON_HEADERS["User-Agent"]})
        await page.goto(anime_url, wait_until="domcontentloaded", timeout=45000)
        # Try common containers
        for sel in ["ul.episodes", "div.episode-list", "div#episodes", "div#episode_page"]:
            try:
                await page.wait_for_selector(sel, timeout=15000)
                break
            except:
                continue
        html = await page.content()
        await browser.close()
        return html

def get_episodes_list(anime_url: str) -> List[Tuple[str, str]]:
    """
    Returns sorted list of tuples (ep_num_str, ep_url)
    """
    base = _base_of(anime_url)
    html = _rendered_html(anime_url)
    soup = BeautifulSoup(html, "lxml")

    # Try multiple patterns
    candidates = []
    for container_sel in ["ul.episodes", "div.episode-list", "div#episodes", "div#episode_page"]:
        container = soup.select_one(container_sel)
        if container:
            candidates = container.select("a[href]")
            if candidates:
                break
    if not candidates:
        candidates = soup.select("a[href*='episode']")

    episodes = []
    for a in candidates:
        href = a.get("href", "").strip()
        if not href:
            continue
        ep_url = _abs(base, href)
        text = a.get_text(" ", strip=True)
        # Prefer explicit episode numbers
        m = re.search(r"Episode\s*([0-9]+)", text, re.I)
        ep_num = m.group(1) if m else None
        if not ep_num:
            # fallback: digits in href
            m2 = re.search(r"episode[-_/ ]?(\d+)", href, re.I)
            ep_num = m2.group(1) if m2 else "?"
        episodes.append((ep_num, ep_url))

    # deduplicate and sort numerically when possible
    seen = {}
    for num, url in episodes:
        seen[(num, url)] = True
    episodes = sorted(seen.keys(), key=lambda x: (int(x[0]) if x[0].isdigit() else 10**9, x[1]))
    return episodes

# ------------------------
# 3) EXTRACT HD-2 + ENGLISH SUB
# ------------------------
def _scraper_session():
    s = cloudscraper.create_scraper()
    s.headers.update(COMMON_HEADERS)
    return s

def _get_with_retries(session, url: str) -> str:
    last = None
    for _ in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code >= 500:
                time.sleep(0.6); continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(0.4)
    raise last

def extract_episode_stream_and_subtitle(episode_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (hls_1080p_url, english_sub_url) or (None, None)
    Selecting only SUB: HD-2 and English subtitle (.vtt/.srt).
    """
    session = _scraper_session()
    html = _get_with_retries(session, episode_url)

    # HD-2 sub server m3u8 — look for variants:
    # JSON-ish: {"label":"HD-2","file":"...m3u8","type":"hls"}
    m_hls = re.search(r'"label"\s*:\s*"HD-2"\s*,\s*"(?:file|url)"\s*:\s*"([^"]+\.m3u8)"', html, re.I)
    hls_url = m_hls.group(1) if m_hls else None

    # English subtitle (common variations)
    # {"srclang":"en","file":"...vtt"} or {"lang":"English","url":"...srt"}
    m_sub = (
        re.search(r'"srclang"\s*:\s*"en"\s*,\s*"(?:file|url|src)"\s*:\s*"([^"]+\.(?:vtt|srt))"', html, re.I)
        or re.search(r'"lang"\s*:\s*"English[^"]*"\s*,\s*"(?:file|url|src)"\s*:\s*"([^"]+\.(?:vtt|srt))"', html, re.I)
    )
    sub_url = m_sub.group(1) if m_sub else None

    return hls_url, sub_url
