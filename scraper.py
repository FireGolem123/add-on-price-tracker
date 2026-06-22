import os
import requests
import re
import json
import html as htmllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

YELP_API_KEY = os.getenv("YELP_API_KEY", "")
YELP_HEADERS = {
    "Authorization": f"Bearer {YELP_API_KEY}",
    "Accept": "application/json",
}
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

CITY_LOCATIONS = {
    "philadelphia": "Philadelphia, PA",
    "new york":     "New York, NY",
    "chicago":      "Chicago, IL",
    "austin":       "Austin, TX",
    "denver":       "Denver, CO",
}

ADDON_SECTION_RE = re.compile(
    r'\b(add[\s\-]?on|extra|topping|modifier|modification|side order|supplement|add to)\b',
    re.IGNORECASE
)
AVOCADO_RE = re.compile(r'\bavocado\b', re.IGNORECASE)

CATEGORY_KEYWORDS = {
    "salad":    re.compile(r'\bsalad\b', re.IGNORECASE),
    "burger":   re.compile(r'\bburger\b|\bsmash\b', re.IGNORECASE),
    "sandwich": re.compile(r'\bsandwich\b|\bsub\b|\bhoagie\b|\bgrinder\b', re.IGNORECASE),
    "wrap":     re.compile(r'\bwrap\b|\bbowl\b', re.IGNORECASE),
    "toast":    re.compile(r'\btoast\b', re.IGNORECASE),
    "taco":     re.compile(r'\btaco\b|\bburrito\b|\bquesadilla\b', re.IGNORECASE),
    "pizza":    re.compile(r'\bpizza\b|\bflatbread\b', re.IGNORECASE),
    "eggs":     re.compile(r'\begg\b|\bomelet\b|\bscramble\b|\bbendict\b', re.IGNORECASE),
}


def classify_item(name: str) -> str:
    for category, pattern in CATEGORY_KEYWORDS.items():
        if pattern.search(name):
            return category
    return "other"


# ── Yelp API ──────────────────────────────────────────────────────────────────

def yelp_search(location: str, term: str = "avocado", limit: int = 50, offset: int = 0) -> list[dict]:
    resp = requests.get(
        "https://api.yelp.com/v3/businesses/search",
        headers=YELP_HEADERS,
        params={
            "location": location,
            "term":     term,
            "limit":    limit,
            "offset":   offset,
            "sort_by":  "review_count",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("businesses", [])


def get_all_yelp_businesses(city: str, keyword: str = "avocado", max_results: int = 500) -> list[dict]:
    location = CITY_LOCATIONS.get(city.lower(), city)
    print(f"[yelp] Searching for '{keyword}' restaurants in {location}...")

    all_biz = []
    offset = 0
    while len(all_biz) < max_results:
        batch = yelp_search(location, term=keyword, limit=50, offset=offset)
        if not batch:
            break
        all_biz.extend(batch)
        print(f"  Fetched {len(all_biz)} businesses so far...")
        if len(batch) < 50:
            break
        offset += 50

    print(f"[yelp] Found {len(all_biz)} businesses total.")
    return all_biz[:max_results]


# ── allmenus.com menu scraper ─────────────────────────────────────────────────

ALLMENUS_CITY_URLS = {
    "philadelphia": "https://www.allmenus.com/pa/philadelphia/-/",
    "new york":     "https://www.allmenus.com/ny/new-york/-/",
    "chicago":      "https://www.allmenus.com/il/chicago/-/",
    "austin":       "https://www.allmenus.com/tx/austin/-/",
    "denver":       "https://www.allmenus.com/co/denver/-/",
}

_allmenus_link_cache: dict[str, list[str]] = {}


def get_allmenus_links(city: str) -> list[str]:
    if city in _allmenus_link_cache:
        return _allmenus_link_cache[city]
    url = ALLMENUS_CITY_URLS.get(city.lower())
    if not url:
        return []
    resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=30)
    links = list(dict.fromkeys(re.findall(r'href="(/[a-z]{2}/[^/]+/\d+-[^"]+)"', resp.text)))
    full = []
    for l in links:
        if not l.endswith("/menu/"):
            l = l.rstrip("/") + "/menu/"
        full.append("https://www.allmenus.com" + l)
    _allmenus_link_cache[city] = full
    return full


def _iter_key(obj, key):
    val = obj.get(key, [])
    if isinstance(val, dict):
        return [val]
    return val if isinstance(val, list) else []


def parse_jsonld_menu(raw_html: str, keyword: str = "avocado") -> list[dict]:
    """Parse JSON-LD structured menu data and return matching items with section context."""
    keyword_re = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
    hits = []
    for blob in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', raw_html, re.DOTALL):
        try:
            data = json.loads(blob)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for obj in items:
            all_sections = []
            for menu in _iter_key(obj, "hasMenu"):
                for sec in _iter_key(menu, "hasMenuSection"):
                    all_sections.append(sec)
            for sec in _iter_key(obj, "hasMenuSection"):
                all_sections.append(sec)

            for section in all_sections:
                section_name = section.get("name", "")
                is_addon = bool(ADDON_SECTION_RE.search(section_name))

                for item in _iter_key(section, "hasMenuItem"):
                    item_name = htmllib.unescape(str(item.get("name", "")).strip())
                    if not item_name:
                        continue
                    price_usd = None
                    for offer in _iter_key(item, "offers"):
                        raw_price = offer.get("Price") or offer.get("price")
                        try:
                            price_usd = float(raw_price)
                            break
                        except (TypeError, ValueError):
                            continue
                    if price_usd is None:
                        continue
                    if keyword_re.search(item_name):
                        hits.append({
                            "item":     item_name,
                            "price":    price_usd,
                            "section":  section_name,
                            "is_addon": is_addon,
                        })
    return hits


def find_menu_for_restaurant(restaurant_name: str, city: str, keyword: str = "avocado") -> list[dict]:
    """Try to find a matching allmenus.com page for a Yelp business by name similarity."""
    links = get_allmenus_links(city)
    name_slug = re.sub(r'[^a-z0-9]', '-', restaurant_name.lower())
    name_words = [w for w in name_slug.split('-') if len(w) > 3]

    # Score each link by how many significant words match
    def score(link):
        return sum(1 for w in name_words if w in link)

    candidates = sorted(links, key=score, reverse=True)
    top = candidates[:3]

    for link in top:
        if score(link) == 0:
            break
        try:
            resp = requests.get(link, headers=SCRAPE_HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            hits = parse_jsonld_menu(resp.text, keyword)
            if hits:
                return hits
        except Exception:
            continue
    return []


# ── Main scrape entry point ───────────────────────────────────────────────────

def build_record(biz: dict, menu_hit: dict, keyword: str) -> dict:
    price_tier = biz.get("price", "")
    location   = biz.get("location", {})
    categories = [c["title"] for c in biz.get("categories", [])]
    return {
        "restaurant":    biz.get("name", ""),
        "yelp_id":       biz.get("id", ""),
        "yelp_rating":   biz.get("rating"),
        "yelp_reviews":  biz.get("review_count"),
        "price_tier":    price_tier,
        "neighborhood":  location.get("city", "") or location.get("address1", ""),
        "categories":    ", ".join(categories),
        "item":          menu_hit["item"],
        "section":       menu_hit["section"],
        "price_usd":     menu_hit["price"],
        "price_cents":   int(menu_hit["price"] * 100),
        "type":          "add_on" if menu_hit["is_addon"] else "menu_item",
        "category":      classify_item(menu_hit["item"]),
        "modifier":      f"in section: {menu_hit['section']}" if menu_hit["is_addon"] else "",
    }


def scrape_city(city: str = "philadelphia", max_restaurants: int = 500, keyword: str = "avocado") -> list[dict]:
    if not YELP_API_KEY or YELP_API_KEY == "your_api_key_here":
        raise ValueError("YELP_API_KEY not set in .env file")

    businesses = get_all_yelp_businesses(city, keyword=keyword, max_results=max_restaurants)

    # Pre-load allmenus links for the city (single fetch, cached)
    print(f"[allmenus] Loading menu index for {city}...")
    get_allmenus_links(city)

    all_records = []
    completed   = 0
    total       = len(businesses)

    print(f"\n[scraper] Matching {total} Yelp businesses to menu data (20 workers)...\n")

    def process(biz):
        hits = find_menu_for_restaurant(biz.get("name", ""), city, keyword)
        return biz, hits

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(process, biz): biz for biz in businesses}
        for future in as_completed(futures):
            biz, hits = future.result()
            completed += 1
            if hits:
                records = [build_record(biz, h, keyword) for h in hits]
                all_records.extend(records)
                addons = sum(1 for r in records if r["type"] == "add_on")
                items  = sum(1 for r in records if r["type"] == "menu_item")
                tag    = f"{addons} add-on(s), {items} dish(es)" if addons else f"{items} dish(es)"
                print(f"  [{completed}/{total}] {biz.get('name','')}: {tag}  (total: {len(all_records)})")
            else:
                print(f"  [{completed}/{total}] scanning...   ", end="\r")

    addon_count = sum(1 for r in all_records if r["type"] == "add_on")
    item_count  = sum(1 for r in all_records if r["type"] == "menu_item")
    print(f"\n\n[scraper] Done. {len(all_records)} records — {addon_count} add-on charges, {item_count} avocado dishes.")
    return all_records


if __name__ == "__main__":
    results = scrape_city("philadelphia")
    with open("data_raw.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved to data_raw.json")
