#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADUM one-page scraper (parallel), tri par 'Dernière mise à jour le', sans org/loc.
Usage:
  python adum_onepage_parallel_min.py \
    --url "https://adum.fr/as/ed/propositionFR.pl" \
    --workers 50 \
    --out-json offres.json \
    --out-html index.html \
    --debug
"""
from __future__ import annotations
import argparse, json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
from html import escape

import requests
from bs4 import BeautifulSoup
import dateparser

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
BACKOFF_BASE = 0.6
UA = "Mozilla/5.0 (compatible; ADUMParallel/1.0)"

_tls = threading.local()
def get_session() -> requests.Session:
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA})
        _tls.session = sess
    return sess

# --- Ta méthode fournie : extrait après "Dernière mise à jour le"
def parse_fr_date(text: str):
    if not text:
        return None
    pos = text.find("Dernière mise à jour le")
    if pos == -1:
        return None
    text = text[pos + 23:]
    epos = text.find("MODALITÉS de CANDIDATURE")
    if epos != -1:
        text = text[:epos]
    dt = dateparser.parse(
        text,
        languages=["fr"],
        settings={
            "DATE_ORDER": "DMY",
            "PREFER_DAY_OF_MONTH": "first",
            "STRICT_PARSING": False,
        }
    )
    return dt

def fetch(url: str, timeout=DEFAULT_TIMEOUT, debug=False) -> str:
    sess = get_session()
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = sess.get(url, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if debug:
                print(f"[DEBUG] GET fail {url} (attempt {attempt}/{MAX_RETRIES}): {e}", file=sys.stderr)
            time.sleep(BACKOFF_BASE * attempt)
    raise last_err if last_err else RuntimeError("Unknown fetch error")

def extract_links(list_url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select('a[href*="proposition"]') or soup.select('a[href*="adum.fr"][href*="proposition"]')
    seen = set()
    out = []
    for a in anchors:
        href = a.get("href", "").strip()
        if not href:
            continue
        url = urljoin(list_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True) or (a.parent.get_text(" ", strip=True) if a.parent else "")
        title = " ".join(title.split())
        out.append((url, title))
    return out

def parse_detail(url: str, title_hint: str, debug=False):
    try:
        html = fetch(url, debug=debug)
        soup = BeautifulSoup(html, "html.parser")
        raw = soup.get_text(" ", strip=True)
        dt = parse_fr_date(raw)
        ts = int(dt.timestamp()) if dt else -1
        page_title = soup.find(["h1", "h2", "h3"])
        title = page_title.get_text(" ", strip=True) if page_title else title_hint
        if debug and dt:
            print(f"[DEBUG] {url} => {dt.date()} | {title[:60]}", file=sys.stderr)
        return {
            "title": title,
            "url": url,
            "posted_at": dt.isoformat() if dt else "",
            "posted_at_ts": ts,  # interne pour le tri
        }
    except Exception as e:
        if debug:
            print(f"[DEBUG] detail error {url}: {e}", file=sys.stderr)
        return {
            "title": title_hint or "",
            "url": url,
            "posted_at": "",
            "posted_at_ts": -1,
        }

def save_html(path: str, items: list[dict]):
    """Écrit un HTML 'tout beubeu' listant Date + Titre (lien)."""
    rows = []
    for it in items:
        date_txt = escape(it.get("posted_at") or "")
        title_txt = escape(it.get("title") or "")
        url_txt = escape(it.get("url") or "#")
        rows.append(f"<tr><td>{date_txt}</td><td><a href=\"{url_txt}\">{title_txt}</a></td></tr>")
    html = (
        "<!DOCTYPE html>\n<html lang=\"fr\">\n<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <title>Offres ADUM</title>\n"
        "</head>\n<body>\n"
        "  <h1>Offres ADUM</h1>\n"
        "  <table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">\n"
        "    <thead><tr><th>Date (ISO)</th><th>Titre</th></tr></thead>\n"
        "    <tbody>\n" + "\n".join(rows) + "\n"
        "    </tbody>\n"
        "  </table>\n"
        "</body>\n</html>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

def main():
    ap = argparse.ArgumentParser(description="ADUM one-page scraper (parallel, minimal fields).")
    ap.add_argument("--url", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-html", default="")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    list_html = fetch(args.url, debug=args.debug)
    links = extract_links(args.url, list_html)
    if args.debug:
        print(f"[DEBUG] {len(links)} liens d'offres détectés", file=sys.stderr)

    items = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {ex.submit(parse_detail, url, title, args.debug): (url, title) for url, title in links}
        for fut in as_completed(futures):
            items.append(fut.result())

    items.sort(key=lambda x: (x["posted_at_ts"], x["title"]), reverse=True)
    out = [{k: v for k, v in it.items() if k != "posted_at_ts"} for it in items]
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            f.write(text)

    if args.out_html:
        save_html(args.out_html, out)

    # Impression stdout = JSON (utile pour pipe)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
