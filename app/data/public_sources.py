from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Public, free-to-use and open web sources that can be queried without paid APIs.
# Sources are grouped by domain and used to build site-scoped search queries.
POLAND_PUBLIC_SOURCES: dict[str, list[dict[str, Any]]] = {
    "flood": [
        {"name": "IMGW Meteo", "url": "https://meteo.imgw.pl/", "type": "official"},
        {"name": "IMGW X profile", "url": "https://x.com/IMGWmeteo", "type": "social"},
        {"name": "RCB", "url": "https://www.gov.pl/web/rcb", "type": "official"},
        {"name": "Hydroportal", "url": "https://wody.isok.gov.pl/imap_kzgw/", "type": "official"},
    ],
    "cyber": [
        {"name": "CERT Polska", "url": "https://cert.pl/", "type": "official"},
        {"name": "CSIRT GOV", "url": "https://csirt.gov.pl/", "type": "official"},
        {"name": "NASK", "url": "https://www.nask.pl/", "type": "official"},
        {"name": "Zaufana Trzecia Strona", "url": "https://zaufanatrzeciastrona.pl/", "type": "media"},
    ],
    "terror": [
        {"name": "RCB", "url": "https://www.gov.pl/web/rcb", "type": "official"},
        {"name": "ABW", "url": "https://www.gov.pl/web/abw", "type": "official"},
        {"name": "RSO", "url": "https://www.gov.pl/web/rcb/rzadowe-centrum-bezpieczenstwa", "type": "official"},
        {"name": "Policja", "url": "https://www.policja.pl/", "type": "official"},
    ],
    "infrastructure": [
        {"name": "GDDKiA", "url": "https://www.gddkia.gov.pl/", "type": "official"},
        {"name": "PKP PLK", "url": "https://www.plk-sa.pl/", "type": "official"},
        {"name": "PSE", "url": "https://www.pse.pl/", "type": "official"},
        {"name": "dane.gov.pl", "url": "https://dane.gov.pl/", "type": "open_data"},
    ],
    "traffic": [
        {"name": "GDDKiA traffic", "url": "https://www.gddkia.gov.pl/pl/a/mapa-stanu-drog", "type": "official"},
        {"name": "Warsaw Open Data", "url": "https://api.um.warszawa.pl/", "type": "open_data"},
        {"name": "Jakdojade", "url": "https://jakdojade.pl/", "type": "transport"},
        {"name": "Google Crisis Map", "url": "https://google.org/crisismap", "type": "map"},
    ],
}

X_TAGS: dict[str, list[str]] = {
    "flood": ["#powodz", "#alertRCB", "#IMGW", "#stanalarmowy"],
    "cyber": ["#cyberbezpieczenstwo", "#CERTPolska", "#phishing", "#cyberatak"],
    "terror": ["#alert", "#bezpieczenstwo", "#terror", "#RCB"],
    "infrastructure": ["#awaria", "#prad", "#wodociagi", "#PKP"],
    "traffic": ["#wypadek", "#korek", "#utrudnienia", "#A2", "#S8"],
}


def get_sources_for_category(category: str) -> list[dict[str, Any]]:
    return POLAND_PUBLIC_SOURCES.get(category, [])


def build_queries(category: str, location: str, date_str: str, description: str) -> list[str]:
    sources = get_sources_for_category(category)
    site_queries = [f"site:{s['url'].split('/')[2]}" for s in sources if "//" in s["url"]]

    base = [
        f"{category} {location} {date_str}",
        f"{description[:120]} {location}",
    ]

    scoped = [f"{category} {location} {sq}" for sq in site_queries[:4]]
    return base + scoped


def source_urls(category: str) -> list[str]:
    return [item["url"] for item in get_sources_for_category(category)]


def social_tags(category: str) -> list[str]:
    return X_TAGS.get(category, [])


def source_digest(category: str) -> str:
    sources = get_sources_for_category(category)
    if not sources:
        return "No curated sources."
    return "; ".join(f"{s['name']} ({s['url']})" for s in sources)


def now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
