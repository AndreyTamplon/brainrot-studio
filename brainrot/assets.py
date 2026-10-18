import asyncio
import hashlib
import io
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

from .config import DATA

CATALOG = DATA / "catalog.json"
HEADERS = {"User-Agent": "BrainrotStudio/0.1 (local educational video editor)"}


def catalog():
    if not CATALOG.exists():
        return {"backgrounds": [], "speakers": []}
    return json.loads(CATALOG.read_text())


def save_catalog(value):
    temp = CATALOG.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(CATALOG)


def get_asset(kind, asset_id):
    return next((v for v in catalog()[kind] if v["id"] == asset_id), None)


def local_path(relative: str):
    path = (DATA / relative).resolve()
    if not path.is_relative_to(DATA) or not path.is_file():
        raise ValueError("Медиафайл не найден")
    return path


def public_url(relative):
    return "/media/" + relative


def safe_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("Only public HTTP(S) sources are allowed")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Nonstandard source port")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private network sources are blocked")
    return url


async def download_image(url, target: Path, allowed_hosts=None):
    # Every redirect is checked; no cookies, credentials or ambient proxy authorization.
    async with httpx.AsyncClient(timeout=25, headers=HEADERS, trust_env=False) as client:
        for _ in range(4):
            await asyncio.to_thread(safe_url, url)
            if allowed_hosts and urlparse(url).hostname not in allowed_hosts:
                raise ValueError("Unexpected image host")
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers["location"]))
                    continue
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 15_000_000:
                        raise ValueError("Image exceeds 15 MB")
                with Image.open(io.BytesIO(raw)) as source:
                    if source.width * source.height > 40_000_000:
                        raise ValueError("Image dimensions exceed limit")
                    image = ImageOps.exif_transpose(source).convert("RGBA")
                    image.thumbnail((1600, 1600))
                    image.save(target, "PNG")
                return target
    raise ValueError("Too many redirects")


async def commons_search(query: str):
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        response = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size",
                "iiurlwidth": 900,
            },
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
    candidates = []
    for page in pages.values():
        info = page.get("imageinfo", [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url or info.get("width", 0) < 250:
            continue
        if not any(x in url.lower() for x in (".png", ".jpg", ".jpeg", ".webp")):
            continue
        meta = info.get("extmetadata", {})
        candidates.append(
            {
                "id": str(page["pageid"]),
                "title": page["title"],
                "url": url,
                "source": info.get("descriptionurl"),
                "license": meta.get("LicenseShortName", {}).get("value", "Unknown"),
                "artist": BeautifulSoup(
                    meta.get("Artist", {}).get("value", ""), "html.parser"
                ).get_text(" ", strip=True)[:400],
                "description": BeautifulSoup(
                    meta.get("ImageDescription", {}).get("value", ""), "html.parser"
                ).get_text(" ", strip=True)[:2000],
            }
        )
    return candidates


async def fetch_candidate(candidate, directory):
    digest = hashlib.sha256(candidate["url"].encode()).hexdigest()[:16]
    path = directory / f"image-{digest}.png"
    if not path.exists():
        await download_image(
            candidate["url"], path, {"upload.wikimedia.org", "thumb.wikimedia.org"}
        )
    return {
        **candidate,
        "path": str(path.relative_to(DATA)),
        "preview": public_url(str(path.relative_to(DATA))),
    }
