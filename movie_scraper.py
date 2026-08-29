#!/usr/bin/env python3
"""Extract useful metadata from a saved Prime Video HTML page.

Usage:
  python3 movie_scraper.py /path/to/page.html -o movie.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def clean(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def unique(values):
    out, seen = [], set()
    for value in values:
        value = clean(value)
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def text_or_content(node):
    if not node:
        return None
    return clean(node.get("content") if node.name == "meta" else node.get_text(" ", strip=True))


def first(soup, selectors):
    for selector in selectors:
        value = text_or_content(soup.select_one(selector))
        if value:
            return value
    return None


def meta_content(soup, name=None, prop=None):
    selector = f'meta[name="{name}"]' if name else f'meta[property="{prop}"]'
    node = soup.select_one(selector)
    return clean(node.get("content")) if node else None


def badge(soup, automation_id, prefix):
    node = soup.select_one(f'[data-automation-id="{automation_id}"]')
    value = text_or_content(node) or (clean(node.get("aria-label")) if node else None)
    if value:
        value = re.sub(rf"^{re.escape(prefix)}\s*", "", value, flags=re.I)
    return value


def links_in_block(node):
    return unique(a.get_text(" ", strip=True) for a in node.select("a"))


def extract_people(soup, testid):
    return unique(node.get_text(" ", strip=True) for node in soup.select(f'[data-testid="{testid}"]'))


def labeled_people(soup, labels):
    """Extract names from blocks containing labels such as Directors or Producers."""
    result = {}
    for label in labels:
        names = []
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*:?", re.I)
        for node in soup.find_all(string=pattern):
            parent = node.parent
            block = parent.parent if parent else None
            for candidate in (parent, block, block.parent if block else None):
                if candidate:
                    names.extend(links_in_block(candidate))
                    if names:
                        break
        result[label.lower()] = unique(names)
    return result


def extract_cards(soup, base_url):
    cards = []
    for card in soup.select('[data-testid="card"], [data-testid="super-carousel-card"]'):
        title = clean(card.get("data-card-title")) or text_or_content(card.select_one("a"))
        if not title:
            continue
        link = card.select_one("a[href]")
        image = card.select_one("img[src]")
        cards.append({
            "title": title,
            "url": urljoin(base_url, link.get("href")) if link else None,
            "image_url": image.get("src") if image else None,
            "entity_type": card.get("data-card-entity-type"),
            "entitlement": card.get("data-card-entitlement"),
        })
    seen, out = set(), []
    for card in cards:
        key = (card["title"], card["url"])
        if key not in seen:
            seen.add(key)
            out.append(card)
    return out


def scrape(path):
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    canonical = first(soup, ['link[rel="canonical"]'])
    if canonical:
        canonical = soup.select_one('link[rel="canonical"]').get("href")
    base_url = canonical or "https://www.primevideo.com/"

    genres = unique(
        node.get_text(" ", strip=True)
        for node in soup.select('[data-testid="genre-texts"], [data-testid="mood-texts"]')
    )
    images = unique(
        [meta_content(soup, prop="og:image")]
        + [img.get("src") for img in soup.select("img[src]") if img.get("src")]
    )

    crew = labeled_people(soup, ["Directors", "Director", "Producers", "Producer", "Writers", "Writer", "Creators", "Creator"])
    # Prefer plural labels, while retaining any other labels found in the page.
    people = {
        "cast": extract_people(soup, "cast-texts"),
        "directors": unique(crew.get("directors", []) + crew.get("director", [])),
        "producers": unique(crew.get("producers", []) + crew.get("producer", [])),
        "writers": unique(crew.get("writers", []) + crew.get("writer", [])),
        "creators": unique(crew.get("creators", []) + crew.get("creator", [])),
    }

    data = {
        "source_file": str(Path(path).resolve()),
        "source_url": canonical,
        "title": first(soup, ['h1[data-automation-id="title"]', 'h1', 'meta[name="title"]', "title"]),
        "description": meta_content(soup, name="description"),
        "synopsis": first(soup, ['[data-testid="dp-atf-synopsis"]']),
        "release_year": badge(soup, "release-year-badge", "Released"),
        "runtime": badge(soup, "runtime-badge", "Runtime"),
        "imdb_rating": badge(soup, "imdb-rating-badge", "IMDb Rating"),
        "content_rating": text_or_content(soup.select_one('[data-testid="rating-badge"]')),
        "genres": genres,
        "people": people,
        "images": images,
        "trailer_present": bool(soup.select_one('[data-testid="trailer-button"]')),
        "related_titles": extract_cards(soup, base_url),
    }
    return data


def scrape_episodes(path):
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    season_match = re.search(r"\bSeason\s+(\d+)\b", soup.get_text(" ", strip=True), re.I)
    season_number = int(season_match.group(1)) if season_match else None
    count_node = soup.select_one(".Lvobdt")
    count_match = re.search(r"(\d+)\s+episodes?", count_node.get_text(" ", strip=True), re.I) if count_node else None
    episodes = []
    for position, item in enumerate(soup.select('[data-testid="episode-list-item"]'), start=1):
        title_node = item.select_one('[data-automation-id^="ep-title-"] h3') or item.select_one("h3")
        raw_title = clean(title_node.get_text(" ", strip=True)) if title_node else None
        number_match = re.match(r"^(\d+)\.\s*(.*)$", raw_title or "")
        episode_number = int(number_match.group(1)) if number_match else position
        title = clean(number_match.group(2)) if number_match else raw_title
        synopsis_node = item.select_one('[data-testid^="synopsis-"]')
        image_node = item.select_one('[data-testid="episode-image"] img[src]') or item.select_one('img[src]')
        image_urls = []
        if image_node:
            image_urls.append(image_node.get("src"))
            parent_picture = image_node.find_parent("picture")
            if parent_picture:
                for source in parent_picture.select("source[srcset]"):
                    image_urls.extend(re.findall(r"https?://[^,\s]+", source.get("srcset", "")))
        rating_node = item.select_one('[data-testid="rating-badge"]')
        runtime_node = item.select_one('[data-testid="episode-runtime"]')
        date_node = item.select_one('[data-testid="episode-release-date"]')
        packshot = item.select_one('[data-testid="episode-packshot"]')
        episodes.append({
            "season_number": season_number,
            "episode_number": episode_number,
            "title": title,
            "episode_id": item.get("id"),
            "content_id": (item.select_one('input[id^="selector-"]') or {}).get("id", "").removeprefix("selector-") or None,
            "synopsis": text_or_content(synopsis_node),
            "runtime": text_or_content(runtime_node),
            "release_date": text_or_content(date_node),
            "content_rating": clean(rating_node.get("aria-label")) if rating_node else None,
            "image_url": image_urls[0] if image_urls else None,
            "image_urls": unique(image_urls),
            "watched": packshot.get("data-is-watched") == "true" if packshot else None,
            "purchase_options_present": bool(item.select_one('[aria-label="Purchase options"]')),
            "availability_text": unique(node.get_text(" ", strip=True) for node in item.select('[data-testid="text-component"], [data-testid="dp-btf-action-box"]')),
        })
    return {
        "source_file": str(Path(path).resolve()),
        "season_number": season_number,
        "episode_count": int(count_match.group(1)) if count_match else len(episodes),
        "episodes": episodes,
    }


def scrape_catalog(path):
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    base_url = (soup.select_one('link[rel="canonical"]') or {}).get("href") or "https://www.primevideo.com/"
    sections = []
    for heading in soup.select('[data-testid="carousel-title"], h2, h3'):
        title = clean(heading.get_text(" ", strip=True))
        if not title or title in {"Menu", "Search"}:
            continue
        parent = heading
        for _ in range(4):
            parent = parent.parent if parent else None
        cards = []
        if parent:
            for card in parent.select('[data-testid="card"], [data-testid="super-carousel-card"]'):
                card_title = clean(card.get("data-card-title")) or clean(card.get_text(" ", strip=True))
                link = card.select_one("a[href]")
                image = card.select_one("img[src]")
                if card_title:
                    cards.append({
                        "title": card_title,
                        "url": urljoin(base_url, link.get("href")) if link else None,
                        "image_url": image.get("src") if image else None,
                        "entity_type": card.get("data-card-entity-type"),
                        "entitlement": card.get("data-card-entitlement"),
                    })
        if cards:
            sections.append({"section_title": title, "items": cards})
    all_links = []
    for link in soup.select('a[href]'):
        text = clean(link.get_text(" ", strip=True))
        href = link.get("href")
        if text and href and not text.lower() in {"home", "menu", "search", "help", "categories remaster", "join prime"}:
            all_links.append({"text": text, "url": urljoin(base_url, href)})
    deduped, seen = [], set()
    for item in all_links:
        key = (item["text"], item["url"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return {
        "source_file": str(Path(path).resolve()),
        "source_url": base_url,
        "page_title": clean(soup.title.get_text(" ", strip=True)) if soup.title else None,
        "sections": sections,
        "links": deduped,
        "item_count": sum(len(section["items"]) for section in sections),
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape movie metadata from saved Prime Video HTML")
    parser.add_argument("html_file", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    result = scrape(args.html_file)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()

