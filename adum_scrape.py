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

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Iterable, List, Optional, Sequence, Tuple

from urllib.parse import urljoin
import argparse
import json
import sys
import threading
import time

import requests
from bs4 import BeautifulSoup
import dateparser

DEFAULT_TIMEOUT: int = 20
MAX_RETRIES: int = 3
BACKOFF_BASE: float = 0.6
UA: str = "Mozilla/5.0 (compatible; ADUMParallel/1.0)"

_tls = threading.local()


def get_session() -> requests.Session:
    """Return a thread-local requests.Session with appropriate headers."""
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA})
        _tls.session = sess
    return sess


@dataclass(frozen=True)
class Offer:
    """Representation d'une offre ADUM."""
    title: str
    url: str
    posted_at: Optional[datetime]

    @property
    def posted_at_ts(self) -> int:
        """Timestamp entier pour tri (ou -1 si date inconnue)."""
        return int(self.posted_at.timestamp()) if self.posted_at else -1

    def to_json_dict(self) -> dict:
        """Dict prêt pour json.dumps()."""
        return {
            "title": self.title,
            "url": self.url,
            "posted_at": self.posted_at.isoformat() if self.posted_at else "",
        }


# --- Ta méthode fournie : extrait après "Dernière mise à jour le"
def parse_fr_date(text: str) -> Optional[datetime]:
    """Extrait une date FR à partir d'un bloc de texte contenant
    'Dernière mise à jour le ...'.
    """
    if not text:
        return None

    needle = "Dernière mise à jour le"
    pos = text.find(needle)
    if pos == -1:
        return None

    text = text[pos + len(needle) :]
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
        },
    )
    return dt


def fetch(url: str, timeout: float = DEFAULT_TIMEOUT, debug: bool = False) -> str:
    """HTTP GET avec retries simples et backoff."""
    sess = get_session()
    last_err: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = sess.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # requests.RequestException | Timeout | ...
            last_err = exc
            if debug:
                print(
                    f"[DEBUG] GET fail {url} (attempt {attempt}/{MAX_RETRIES}): {exc}",
                    file=sys.stderr,
                )
            time.sleep(BACKOFF_BASE * attempt)

    if last_err is None:
        raise RuntimeError("Unknown fetch error")

    raise last_err


def extract_links(list_url: str, html: str) -> List[Tuple[str, str]]:
    """Extrait les liens d'offres depuis la page de liste.

    Retourne une liste de tuples (url_absolue, titre).
    """
    soup = BeautifulSoup(html, "html.parser")

    anchors: Sequence = (
        soup.select('a[href*="proposition"]')
        or soup.select('a[href*="adum.fr"][href*="proposition"]')
    )

    seen: set[str] = set()
    out: List[Tuple[str, str]] = []

    for a in anchors:
        href = a.get("href", "").strip()
        if not href:
            continue

        url = urljoin(list_url, href)
        if url in seen:
            continue
        seen.add(url)

        title = a.get_text(" ", strip=True) or (
            a.parent.get_text(" ", strip=True) if a.parent else ""
        )
        title = " ".join(title.split())
        out.append((url, title))

    return out


def parse_detail(url: str, title_hint: str, debug: bool = False) -> Offer:
    """Récupère une page détail d'offre et renvoie un objet Offer."""
    try:
        html = fetch(url, debug=debug)
        soup = BeautifulSoup(html, "html.parser")
        raw = soup.get_text(" ", strip=True)

        dt = parse_fr_date(raw)
        # On pourrait récupérer un titre plus fiable ici si besoin :
        # page_title = soup.find(["h1", "h2", "h3"])
        # title = page_title.get_text(" ", strip=True) if page_title else title_hint
        title = title_hint or ""

        if debug and dt:
            print(
                f"[DEBUG] {url} => {dt.date()} | {title[:60]}",
                file=sys.stderr,
            )

        return Offer(title=title, url=url, posted_at=dt)
    except Exception as exc:
        if debug:
            print(f"[DEBUG] detail error {url}: {exc}", file=sys.stderr)
        return Offer(title=title_hint or "", url=url, posted_at=None)


def save_html(path: str, items: Iterable[Offer]) -> None:
    """Écrit un HTML 'tout beubeu' listant Date + Titre (lien)."""
    rows: List[str] = []
    for it in items:
        date_txt = escape(it.posted_at.isoformat() if it.posted_at else "")
        title_txt = escape(it.title)
        url_txt = escape(it.url or "#")
        rows.append(
            f'<tr><td>{date_txt}</td>'
            f'<td><a href="{url_txt}">{title_txt}</a></td></tr>'
        )

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ADUM one-page scraper (parallel, minimal fields)."
    )
    parser.add_argument("--url", default="https://adum.fr/as/ed/propositionFR.pl")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-html", default="")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    list_html = fetch(args.url, debug=args.debug)
    links = extract_links(args.url, list_html)

    if args.debug:
        print(
            f"[DEBUG] {len(links)} liens d'offres détectés",
            file=sys.stderr,
        )

    items: List[Offer] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(parse_detail, url, title, args.debug): (url, title)
            for url, title in links
        }
        for future in as_completed(futures):
            items.append(future.result())

    # tri par date desc, puis titre
    items.sort(key=lambda o: (o.posted_at_ts, o.title), reverse=True)

    json_ready = [offer.to_json_dict() for offer in items]
    text = json.dumps(json_ready, ensure_ascii=False, indent=2)

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            f.write(text)

    if args.out_html:
        save_html(args.out_html, items)

    # Impression stdout = JSON (utile pour pipe)
    print(json.dumps(json_ready, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
