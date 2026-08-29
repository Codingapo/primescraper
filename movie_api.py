#!/usr/bin/env python3
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query

from movie_scraper import scrape, scrape_episodes, scrape_catalog

DEFAULT_URL = "https://www.primevideo.com/region/eu/detail/0HBRA2TBBIGCHAUVN2HBNUVF44?jic=16%7CCgNhbGwSA2FsbA%3D%3D&ref_=atv_dp_amz_c_TS8274d_1_7"
JSON_FILE = Path("/home/ubuntu/live_movie.json")
EPISODES_JSON_FILE = Path("/home/ubuntu/live_episodes.json")
CATALOG_JSON_FILE = Path("/home/ubuntu/live_catalog.json")
LOCK = Lock()
app = FastAPI(title="Live Movie Metadata API", version="2.0.0")


def fetch_html(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"www.primevideo.com", "primevideo.com"}:
        raise ValueError("Only primevideo.com URLs are allowed")
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MovieMetadataAPI/2.0)"}, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_and_save(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"www.primevideo.com", "primevideo.com"}:
        raise ValueError("Only primevideo.com URLs are allowed")
    html = fetch_html(url)
    temp = Path("/tmp/live_primevideo_page.html")
    temp.write_text(html, encoding="utf-8")
    data = scrape(temp)
    data["fetched_from"] = url
    data["fetched_at_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    JSON_FILE.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


@app.get("/")
def home():
    return {
        "service": "Live Movie Metadata API",
        "default_url": DEFAULT_URL,
        "endpoints": {
            "scrape": "/scrape?url=<PRIME_VIDEO_URL>",
            "refresh": "/refresh?url=<PRIME_VIDEO_URL>",
            "episodes": "/episodes?url=<PRIME_VIDEO_SEASON_URL>",
            "episodes_json": "/episodes.json",
            "saved_json": "/movie.json",
            "docs": "/docs",
        },
        "example": "/scrape?url=" + DEFAULT_URL,
    }


@app.get("/app", response_class=__import__("fastapi").responses.HTMLResponse)
def app_page():
    return '''<!doctype html><meta charset="utf-8"><title>Live Movie Scraper</title>
    <style>body{font:16px system-ui;max-width:850px;margin:40px auto;padding:0 20px;background:#f6f7f9;color:#17202a}input{width:75%;padding:12px;border:1px solid #aaa;border-radius:6px}button{padding:12px 18px;margin-left:6px;border:0;border-radius:6px;background:#075985;color:white;cursor:pointer}pre{white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:16px;border-radius:8px;max-height:650px;overflow:auto}.muted{color:#64748b}</style>
    <h1>Live Movie Scraper</h1><p>Paste an authorized Prime Video detail URL. The page will fetch it and display the completed JSON when ready.</p>
    <form id="f"><input id="u" type="url" required placeholder="https://www.primevideo.com/region/.../detail/..."/><button>Scrape</button></form><p id="s" class="muted"></p><pre id="o">Waiting for a URL.</pre>
    <script>f.onsubmit=async(e)=>{e.preventDefault();s.textContent='Fetching and parsing…';o.textContent='';try{const r=await fetch('/scrape?url='+encodeURIComponent(u.value));const j=await r.json();o.textContent=JSON.stringify(j,null,2);s.textContent=r.ok?'Done.':'Request failed.'}catch(x){s.textContent='Request failed';o.textContent=x}}</script>'''


@app.get("/health")
def health():
    return {"status": "ok", "json_file": str(JSON_FILE), "exists": JSON_FILE.exists()}


@app.get("/scrape")
def scrape_url(url: str = Query(..., description="Prime Video detail page URL")):
    try:
        with LOCK:
            return fetch_and_save(url)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch Prime Video page: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/catalog")
def catalog(url: str = Query(..., description="Prime Video storefront, category, search, or listing URL")):
    try:
        with LOCK:
            html = fetch_html(url)
            temp = Path("/tmp/live_primevideo_catalog.html")
            temp.write_text(html, encoding="utf-8")
            data = scrape_catalog(temp)
            data["fetched_from"] = url
            data["fetched_at_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            CATALOG_JSON_FILE.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
            return data
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch Prime Video page: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/search")
def search(query: str = Query(..., min_length=1, description="Search phrase"), page: int = Query(1, ge=1)):
    from urllib.parse import urlencode
    url = "https://www.primevideo.com/region/eu/search?" + urlencode({"phrase": query, "page": page})
    return catalog(url)


@app.get("/categories")
def categories():
    return catalog("https://www.primevideo.com/region/eu/categories")


@app.get("/storefront")
def storefront():
    return catalog("https://www.primevideo.com/region/eu/storefront")


@app.get("/episodes")
def episodes(url: str = Query(..., description="Prime Video TV-season or series URL"), season_number: int | None = Query(None, ge=1, description="Optional season number if it is not present in the page HTML")):
    try:
        with LOCK:
            html = fetch_html(url)
            temp = Path("/tmp/live_primevideo_episodes.html")
            temp.write_text(html, encoding="utf-8")
            data = scrape_episodes(temp)
            if season_number is not None:
                data["season_number"] = season_number
                for episode in data["episodes"]:
                    episode["season_number"] = season_number
            data["fetched_from"] = url
            data["fetched_at_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            EPISODES_JSON_FILE.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return data
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch Prime Video page: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/refresh")
def refresh(url: str = Query(DEFAULT_URL, description="Prime Video detail page URL")):
    try:
        with LOCK:
            return fetch_and_save(url)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch Prime Video page: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/movie")
def movie(refresh: bool = Query(False, description="Fetch the page again before returning JSON")):
    if refresh or not JSON_FILE.exists():
        return refresh_endpoint()
    return __import__("json").loads(JSON_FILE.read_text(encoding="utf-8"))


def refresh_endpoint():
    try:
        with LOCK:
            return fetch_and_save(DEFAULT_URL)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch Prime Video page: {exc}")


@app.get("/catalog.json")
def saved_catalog_json():
    if not CATALOG_JSON_FILE.exists():
        raise HTTPException(status_code=404, detail="No catalog JSON has been generated yet. Call /catalog?url=... first.")
    return __import__("json").loads(CATALOG_JSON_FILE.read_text(encoding="utf-8"))


@app.get("/episodes.json")
def saved_episodes_json():
    if not EPISODES_JSON_FILE.exists():
        raise HTTPException(status_code=404, detail="No episode JSON has been generated yet. Call /episodes?url=... first.")
    return __import__("json").loads(EPISODES_JSON_FILE.read_text(encoding="utf-8"))


@app.get("/movie.json")
def saved_json():
    if not JSON_FILE.exists():
        return refresh_endpoint()
    return __import__("json").loads(JSON_FILE.read_text(encoding="utf-8"))
