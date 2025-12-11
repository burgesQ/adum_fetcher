# ADUM Thesis Offer Scraper

Tired of scrolling endlessly through unsorted thesis offers on ADUM? This tool fetches all available "propositions de sujets de thèse" from ADUM and sorts them chronologically—so you can find the freshest opportunities first!

## TLDR

https://burgesq.github.io/adum_fetcher/ (updated every day @ 8:00am)

## Features
- Scrapes all offers from https://adum.fr/as/ed/propositionFR.pl
- Sorts by last update date ("Dernière mise à jour le")
- Outputs results in JSON and HTML formats
- Fast parallel scraping with configurable worker count

## Usage
Run the scraper with:

```console
$ uv run adum_scrape.py --url "https://adum.fr/as/ed/propositionFR.pl" --workers 100 --out-json adum_offres_para.json --debug                                               ─╯
```

## Why?
ADUM doesn’t let you sort offers by date. This project fixes that—making your search for a thesis subject much easier!

---

## IT & Requirements

This tool is written in Python. To run it and fetch dependencies, you need:

- Python 3.8+
- [`uv`](https://github.com/astral-sh/uv) — a fast Python package manager and runner

Install `uv` by following instructions on its GitHub page. All dependencies are managed via `pyproject.toml` and `uv.lock`.

---

*JSON and HTML files are ignored from git by default (see .gitignore).*
