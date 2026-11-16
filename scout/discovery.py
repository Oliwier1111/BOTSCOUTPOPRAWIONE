"""Wyszukiwanie lokalnych firm.

1. Google Places API (New) - najlepsze dane (telefon, strona, opinie).
2. OpenStreetMap (Nominatim + Overpass) - darmowy fallback bez klucza.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, Iterable

import requests

import scout_config as config
from . import contacts, merge, profile
from .models import Business

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.types",
        "places.primaryType",
        "places.googleMapsUri",
        "places.businessStatus",
        "nextPageToken",
    ]
)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
# Overpass odrzuca (HTTP 406) nagłówki udające przeglądarkę – przedstawiamy się uczciwie, jak każe regulamin OSM.
OSM_UA = "SparkScaleScout/1.1 (+https://spark-scale.pl)"
OSM_CACHE = config.DATA_DIR / "cache_osm.json"
OSM_CACHE_H = 24
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim wymaga, by aplikacja przedstawiała się własną nazwą (zasady: operations.osmfoundation.org/policies/nominatim)
NOMINATIM_UA = "SparkScaleScout/1.0 (lokalny audyt stron firm)"

# Polska nazwa branży -> tagi OpenStreetMap
OSM_TAGS = {
    "dentysta": ['"amenity"="dentist"', '"healthcare"="dentist"'],
    "gabinet stomatologiczny": ['"amenity"="dentist"'],
    "fizjoterapeuta": ['"healthcare"="physiotherapist"'],
    "weterynarz": ['"amenity"="veterinary"'],
    "kancelaria prawna": ['"office"="lawyer"'],
    "prawnik": ['"office"="lawyer"'],
    "notariusz": ['"office"="notary"'],
    "komornik": ['"office"="bailiff"', '"office"="government"]["name"~"[Kk]omornik"'],
    "biuro rachunkowe": ['"office"="accountant"', '"office"="tax_advisor"'],
    "mechanik samochodowy": ['"shop"="car_repair"'],
    "hydraulik": ['"craft"="plumber"'],
    "elektryk": ['"craft"="electrician"'],
    "fryzjer": ['"shop"="hairdresser"'],
    "salon kosmetyczny": ['"shop"="beauty"'],
    "restauracja": ['"amenity"="restaurant"'],
    "piekarnia": ['"shop"="bakery"'],
    "kwiaciarnia": ['"shop"="florist"'],
    "szkoła językowa": ['"amenity"="language_school"'],
    "psycholog": ['"healthcare"="psychotherapist"', '"healthcare"="psychologist"'],
    "optyk": ['"shop"="optician"'],
    "firma remontowa": ['"craft"="builder"', '"office"="construction_company"'],
    # --- segment: większe firmy
    # biura firm (office=company) – najliczniejsza darmowa grupa firm B2B w OpenStreetMap
    "biura firm": ['"office"="company"'],
    "producent": ['"office"="company"]["industrial"', '"man_made"="works"]["name"', '"industrial"="factory"]["name"'],
    "zakład produkcyjny": ['"man_made"="works"]["name"', '"industrial"="factory"]["name"', '"building"="industrial"]["name"'],
    "hurtownia": ['"shop"="wholesale"', '"wholesale"', '"office"="company"]["name"~"[Hh]urtowni"'],
    "firma budowlana": ['"office"="construction_company"', '"craft"="builder"]["name"~"[Ss]p[.] |S[.]A[.]"'],
    "deweloper": ['"office"="property_developer"', '"office"="company"]["name"~"[Dd]evelop|[Dd]ewelop"'],
    "firma transportowa": ['"office"="logistics"', '"office"="company"]["name"~"[Tt]rans"'],
    "spedycja": ['"office"="logistics"', '"office"="company"]["name"~"[Ss]pedy|[Ll]ogist"'],
    "firma logistyczna": ['"office"="logistics"', '"industrial"="warehouse"]["name"', '"building"="warehouse"]["name"'],
    "salon samochodowy": ['"shop"="car"'],
    "hotel": ['"tourism"="hotel"'],
    "centrum medyczne": ['"amenity"="clinic"', '"healthcare"="clinic"', '"healthcare"="centre"'],
    "klinika": ['"amenity"="clinic"', '"amenity"="hospital"]["operator:type"="private"'],
    "biuro nieruchomości": ['"office"="estate_agent"'],
    "firma IT": ['"office"="it"', '"office"="telecommunication"'],
    "agencja pracy": ['"office"="employment_agency"'],
    "producent mebli": ['"craft"="carpenter"', '"shop"="furniture"]["craft"', '"office"="company"]["name"~"[Mm]eb"'],
    "okna i drzwi": ['"shop"="doors"', '"shop"="windows"', '"craft"="window_construction"'],
    "firma instalacyjna": ['"craft"="hvac"', '"craft"="plumber"]["name"~"[Ss]p[.] |S[.]A[.]"', '"craft"="electrician"]["name"~"[Ss]p[.] |S[.]A[.]"'],
    "maszyny i urządzenia": ['"shop"="trade"', '"office"="company"]["name"~"[Mm]aszyn|[Tt]echni"'],
    "szkoła prywatna": ['"amenity"="school"]["operator:type"="private"', '"amenity"="school"]["name"~"[Pp]rywatn|[Nn]iepubliczn|[Ss]połeczn"'],
    "biuro projektowe": ['"office"="architect"', '"office"="engineer"'],
    "firma ochroniarska": ['"office"="security"'],
    "agencja reklamowa": ['"office"="advertising_agency"'],
    "ubezpieczenia": ['"office"="insurance"'],
}

# Inne nazwy tej samej branży: po nich szukamy w Google, a w OpenStreetMap po fragmencie nazwy firmy
# (wiele gabinetów jest w OSM tylko z nazwą, bez tagu branży).
SYNONYMS = {
    "dentysta": ["stomatolog", "gabinet stomatologiczny", "ortodonta", "implantologia"],
    "gabinet stomatologiczny": ["stomatolog", "dentysta", "ortodonta"],
    "fizjoterapeuta": ["fizjoterapia", "rehabilitacja", "gabinet fizjoterapii"],
    "weterynarz": ["lecznica weterynaryjna", "klinika weterynaryjna", "gabinet weterynaryjny"],
    "kancelaria prawna": ["adwokat", "radca prawny", "kancelaria adwokacka"],
    "biuro rachunkowe": ["księgowa", "usługi księgowe", "doradca podatkowy"],
    "mechanik samochodowy": ["warsztat samochodowy", "serwis samochodowy", "wulkanizacja"],
    "fryzjer": ["salon fryzjerski", "fryzjer męski", "barber"],
    "salon kosmetyczny": ["kosmetyczka", "gabinet kosmetyczny", "stylizacja paznokci", "medycyna estetyczna"],
    "psycholog": ["psychoterapeuta", "poradnia psychologiczna", "psychoterapia"],
    "firma remontowa": ["usługi remontowe", "wykończenia wnętrz", "usługi budowlane"],
    "hydraulik": ["instalacje sanitarne", "usługi hydrauliczne"],
    "elektryk": ["instalacje elektryczne", "usługi elektryczne"],
    "notariusz": ["kancelaria notarialna"],
    "komornik": ["kancelaria komornicza"],
    "restauracja": ["bistro", "pizzeria", "kuchnia domowa"],
    "piekarnia": ["cukiernia", "piekarnia rzemieślnicza"],
    "kwiaciarnia": ["kwiaty", "pracownia florystyczna"],
    "szkoła językowa": ["kursy językowe", "nauka angielskiego", "korepetycje językowe"],
    "optyk": ["salon optyczny", "zakład optyczny", "okulary"],
}
OSM_NAME_RX = {
    "dentysta": "stomatolog|dentyst|ortodont|implantolog|protetyk",
    "gabinet stomatologiczny": "stomatolog|dentyst|ortodont",
    "fizjoterapeuta": "fizjoterap|rehabilitac|kinezyterap",
    "weterynarz": "weterynar|lecznica zwierz",
    "kancelaria prawna": "kancelaria|adwokat|radca prawn",
    "biuro rachunkowe": "ksi[eę]gow|biuro rachunk|doradc[ay] podatk",
    "mechanik samochodowy": "warsztat samochod|serwis samochod|wulkanizac|mechanik",
    "fryzjer": "fryzjer|barber",
    "salon kosmetyczny": "kosmetyczn|kosmetolog|stylizacja paznokci|paznokci",
    "psycholog": "psycholog|psychoterap",
    "notariusz": "notariu|notarialn",
    "komornik": "komorni",
    "hydraulik": "hydraulik|instalacje sanitarn",
    "elektryk": "elektryk|instalacje elektryczn",
    "piekarnia": "piekarni|cukierni",
    "kwiaciarnia": "kwiaciarni|kwiaty|florysty",
    "szkoła językowa": "szkoła językow|język|english|kursy językow",
    "optyk": "optyk|optyczn",
    "firma remontowa": "remont|wykończen|budowlan",
}

# Branża -> fraza po angielsku dla Nominatim („dentist in Gniezno”), z tagu OSM
def _nominatim_phrases(category: str) -> list[str]:
    out = []
    for t in OSM_TAGS.get(category.lower(), []):
        if "][" in t:  # złożony warunek (np. komornik) – Nominatim go nie rozumie
            continue
        out.append(t.split("=")[1].strip('"').replace("_", " "))
    return list(dict.fromkeys(out))


def name_rx(category: str) -> str:
    """Regex nazwy firmy dla dowolnej branży: gotowy z OSM_NAME_RX albo zbudowany z rdzeni słów branży i synonimów."""
    if category.lower() in OSM_NAME_RX:
        return OSM_NAME_RX[category.lower()]
    stems = []
    for term in category_terms(category):
        for w in re.findall(r"\w+", term.lower()):
            if len(w) >= 4 and w not in {"firma", "usługi", "gabinet", "salon", "sklep", "studio", "biuro"}:
                stems.append(re.escape(w[: max(4, len(w) - 2)]))
    return "|".join(dict.fromkeys(stems))

Log = Callable[[str], None]


def category_terms(category: str) -> list[str]:
    """Branża + jej synonimy (do zapytań w Google)."""
    return [category] + SYNONYMS.get(category.lower(), [])


AREA_PATH = config.DATA_DIR / "okolice.json"
NEAR_KM = float(__import__("os").getenv("SCOUT_OKOLICE_KM", "15"))


def area_info(city: str, log: Log = None) -> dict:
    """Sąsiednie gminy i dzielnice miasta z data/okolice.json.

    Miasta, którego nie ma w pliku, agent sam ustala w OpenStreetMap (gminy w promieniu SCOUT_OKOLICE_KM km)
    i dopisuje do pliku – działa dla każdego miasta w Polsce.
    """
    try:
        data = json.loads(AREA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    hit = next((v for k, v in data.items() if k.lower() == city.lower() and isinstance(v, dict)), None)
    if hit is not None:
        return hit
    info = _auto_area(city)
    if info is None:
        return {}
    data[city] = info
    try:
        AREA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    if log:
        log(f"Okolice „{city}” ustalone automatycznie: {', '.join(info['gminy']) or 'brak'} (zapisane w data/okolice.json)")
    return info


def _nominatim(params: dict) -> list[dict]:
    time.sleep(1.1)  # zasady Nominatim: maks. 1 zapytanie na sekundę
    r = requests.get(NOMINATIM_URL, params={"format": "jsonv2", "countrycodes": "pl", **params},
                     headers={"User-Agent": NOMINATIM_UA, "Accept-Language": "pl"}, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _auto_area(city: str) -> dict | None:
    """Gminy wokół miasta (Nominatim, bez Overpass). None = nie udało się zapytać (spróbujemy następnym razem)."""
    try:
        place = _nominatim({"q": city, "limit": 1})
        if not place:
            return {"gminy": [], "dzielnice": [], "_auto": True}
        lat, lon = float(place[0]["lat"]), float(place[0]["lon"])
        dlat, dlon = NEAR_KM / 111, NEAR_KM / 68
        box = f"{lon - dlon},{lat + dlat},{lon + dlon},{lat - dlat}"
        names = []
        for q in ("gmina", "miasto"):
            for x in _nominatim({"q": q, "limit": 50, "viewbox": box, "bounded": 1}):
                n = re.sub(r"^(gmina|miasto)\s+", "", x.get("name", ""), flags=re.I).strip()
                if n and n.lower() != city.lower() and x.get("type") in ("administrative", "town", "city"):
                    names.append(n)
        return {"gminy": list(dict.fromkeys(names))[:15], "dzielnice": [], "_auto": True}
    except (requests.RequestException, ValueError, KeyError):
        return None


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------- Google
PLACES_COUNTER = config.DATA_DIR / "places_licznik.json"


def places_budget_left(n: int = 1) -> bool:
    """Liczy zapytania do Places w ciągu doby; zwraca False, gdy przekroczono SCOUT_PLACES_DZIENNIE."""
    import datetime as dt
    import json

    today = dt.date.today().isoformat()
    try:
        d = json.loads(PLACES_COUNTER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if d.get("dzien") != today:
        d = {"dzien": today, "zapytan": 0}
    if d["zapytan"] + n > config.PLACES_DAILY_LIMIT:
        return False
    d["zapytan"] += n
    try:
        PLACES_COUNTER.parent.mkdir(parents=True, exist_ok=True)
        PLACES_COUNTER.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass
    return True

def search_google_places(query: str, city: str, category: str, max_results: int, log: Log = _noop) -> list[Business]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": PLACES_FIELDS,
    }
    body = {"textQuery": query, "languageCode": "pl", "regionCode": "PL", "pageSize": 20}
    out: list[Business] = []
    while len(out) < max_results:
        if not places_budget_left():
            log(f"Dzienny limit zapytań do Google Places ({config.PLACES_DAILY_LIMIT}) wyczerpany – kończę na tym, co jest. Zwiększ SCOUT_PLACES_DZIENNIE w .env, jeśli to zamierzone.")
            break
        r = requests.post(PLACES_URL, json=body, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if r.status_code != 200:
            log(f"Google Places błąd {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        for p in data.get("places", []):
            if p.get("businessStatus") and p["businessStatus"] != "OPERATIONAL":
                continue
            out.append(
                Business(
                    name=(p.get("displayName") or {}).get("text", ""),
                    address=p.get("formattedAddress", ""),
                    city=city,
                    category=category,
                    phone=p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber", ""),
                    website=p.get("websiteUri", ""),
                    maps_url=p.get("googleMapsUri", ""),
                    rating=p.get("rating"),
                    reviews=p.get("userRatingCount"),
                    source="google_places",
                    source_id=p.get("id", ""),
                    types=p.get("types", []),
                )
            )
        token = data.get("nextPageToken")
        if not token:
            break
        body["pageToken"] = token
        time.sleep(1.5)  # token potrzebuje chwili, zanim zadziała
    return out[:max_results]


# ---------------------------------------------------------------- OSM
def _overpass_query(city: str, tags: Iterable[str], name_rx: str = "") -> str:
    parts = "".join(f"nwr(area.a)[{t}];" for t in tags)
    if name_rx:  # nazwa pasuje do branży, a firma ma jakikolwiek tag działalności
        parts += "".join(f'nwr(area.a)["name"~"{name_rx}",i]["{k}"];' for k in ("healthcare", "amenity", "office", "shop", "craft"))
    return (
        f'[out:json][timeout:110];area["name"="{city}"]["boundary"="administrative"]->.a;'
        f"({parts});out center tags;"
    )


_OVERPASS_DOWN = False
# Ile sekund w jednym uruchomieniu wolno stracić na nieudanych zapytaniach do Overpass, zanim przejdziemy na Nominatim
# (przeciążone serwery potrafią odpowiadać po 2 min – bez limitu jeden przebieg automatu trwałby godzinę).
OVERPASS_LIMIT_S = int(os.getenv("SCOUT_OSM_LIMIT_S", "300"))
_OVERPASS_LOST = 0.0
_OVERPASS_GOOD = ""  # serwer, który ostatnio odpowiedział – pytamy go najpierw


def osm_contacts(t: dict) -> dict:
    """E-mail i profile social zapisane w tagach OpenStreetMap."""
    emails = [e.strip() for k in ("email", "contact:email") for e in t.get(k, "").split(";") if "@" in e]
    socials = []
    for k, base in (("facebook", "https://www.facebook.com/"), ("instagram", "https://www.instagram.com/")):
        for v in (t.get(f"contact:{k}"), t.get(k)):
            if v:
                socials.append(v if v.startswith("http") else base + v.lstrip("@/"))
    return {"emails": list(dict.fromkeys(emails)), "socials": list(dict.fromkeys(socials)),
            "contacts_note": "kontakty z OpenStreetMap" if emails or socials else ""}


def _overpass_fetch(city: str, category: str, tags, log: Log, name_rx: str = "") -> dict | None:
    """Zapytanie do Overpass z pamięcią na dobę i ponawianiem po kolejnych serwerach (3 rundy)."""
    import datetime as dt
    import json

    key = f"{city.lower()}|{category.lower()}"
    try:
        cache = json.loads(OSM_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(key)
    if hit and (dt.datetime.now() - dt.datetime.fromisoformat(hit["_t"])).total_seconds() < OSM_CACHE_H * 3600:
        log(f"OpenStreetMap: {category} / {city} z pamięci (do {OSM_CACHE_H} h)")
        return hit["data"]
    global _OVERPASS_LOST, _OVERPASS_GOOD
    q = _overpass_query(city, tags, name_rx)
    rounds = 1 if _OVERPASS_DOWN else 3
    urls = sorted(OVERPASS_URLS, key=lambda u: u != _OVERPASS_GOOD)
    for rnd in range(rounds):
        for url in urls:
            host = url.split("/")[2]
            if _OVERPASS_LOST >= OVERPASS_LIMIT_S:
                log(f"OpenStreetMap: serwery Overpass za wolne (straciliśmy {int(_OVERPASS_LOST)} s) – dalej przez Nominatim")
                return None
            t0 = time.monotonic()
            try:
                r = requests.post(url, data={"data": q}, headers={"User-Agent": OSM_UA}, timeout=(10, 120))
            except requests.RequestException as e:
                _OVERPASS_LOST += time.monotonic() - t0
                log(f"OpenStreetMap ({host}) nie odpowiada: {type(e).__name__}")
                continue
            if r.status_code != 200:
                _OVERPASS_LOST += time.monotonic() - t0
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    log(f"OpenStreetMap ({host}) zwrócił nieczytelną odpowiedź")
                    continue
                remark = str(data.get("remark") or "")
                if "error" in remark.lower() or "timed out" in remark.lower():
                    log(f"OpenStreetMap ({host}) przerwał zapytanie: {remark[:80]}")
                    continue  # pusty wynik z błędem – nie zapisujemy go w pamięci
                _OVERPASS_GOOD = url
                cache[key] = {"_t": dt.datetime.now().isoformat(), "data": data}
                try:
                    OSM_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    OSM_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
                return data
            log(f"OpenStreetMap ({host}) błąd {r.status_code}, próbuję inny serwer")
        if rnd < rounds - 1:
            _OVERPASS_LOST += 15 * (rnd + 1)
            log(f"Wszystkie serwery OpenStreetMap zajęte – czekam {15 * (rnd + 1)} s i próbuję ponownie")
            time.sleep(15 * (rnd + 1))
    return None


def search_osm(city: str, category: str, max_results: int, log: Log = _noop) -> list[Business]:
    tags = {k.lower(): v for k, v in OSM_TAGS.items()}.get(category.lower(), [])
    rx = name_rx(category)
    if not tags and not rx:
        log(f"OSM: nie umiem szukać branży „{category}” – dopisz ją do OSM_TAGS w scout/discovery.py")
        return []
    if not tags:
        log(f"OSM: „{category}” bez tagu branży – szukam po nazwie firmy ({rx})")
    global _OVERPASS_DOWN
    if _OVERPASS_DOWN:  # w tym uruchomieniu Overpass już nie odpowiadał – od razu Nominatim
        return search_nominatim(city, category, max_results, log)
    data = _overpass_fetch(city, category, tags, log, rx)
    if data is None:
        _OVERPASS_DOWN = True  # wszystkie serwery zawiodły – w tym uruchomieniu od razu Nominatim
        log("Overpass nie odpowiada – szukam w OpenStreetMap przez Nominatim (mniej firm).")
        return search_nominatim(city, category, max_results, log)
    return [b for b in (_osm_business(el, city, category) for el in data.get("elements", [])) if b][:max_results]


def _osm_business(el: dict, city: str, category: str) -> Business | None:
    """Element z Overpass (tags) albo wynik Nominatim (extratags, address, category/type) -> Business."""
    nominatim = "place_id" in el
    t = dict(el.get("extratags") or {}) if nominatim else dict(el.get("tags") or {})
    if nominatim:
        addr = el.get("address") or {}
        t.setdefault("name", el.get("name", ""))
        for k, v in (("street", addr.get("road")), ("housenumber", addr.get("house_number")),
                     ("postcode", addr.get("postcode")), ("city", addr.get("city") or addr.get("town") or addr.get("village"))):
            if v:
                t.setdefault(f"addr:{k}", v)
        if el.get("category"):
            t.setdefault(el["category"], el.get("type", ""))
    name = t.get("name")
    if not name:
        return None
    street = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x)
    address = ", ".join(x for x in [street, t.get("addr:postcode", ""), t.get("addr:city", city)] if x)
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    sid = f"{el.get('osm_type')}/{el.get('osm_id')}" if nominatim else f"{el.get('type')}/{el.get('id')}"
    return Business(
        name=name,
        address=address,
        city=city,
        category=category,
        phone=t.get("phone") or t.get("contact:phone", ""),
        website=t.get("website") or t.get("contact:website") or t.get("url", ""),
        maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}" if lat else "",
        source="openstreetmap",
        source_id=sid,
        types=[k + "=" + v for k, v in t.items() if k in ("amenity", "shop", "office", "craft", "healthcare", "industrial", "man_made", "tourism")],
        profile=profile.osm_profile(t),
        **osm_contacts(t),
    )


def search_nominatim(city: str, category: str, max_results: int, log: Log = _noop) -> list[Business]:
    """Zapasowe źródło OSM (gdy Overpass jest zablokowany): frazy „dentist in Gniezno” + polskie nazwy branży."""
    queries = [f"{p} in {city}" for p in _nominatim_phrases(category)] + [f"{t} {city}" for t in category_terms(category)[:3]]
    seen: dict[int, dict] = {}
    for q in queries:
        exclude: list[str] = []
        for _ in range(4):  # do 200 wyników na frazę
            try:
                res = _nominatim({"q": q, "limit": 50, "extratags": 1, "addressdetails": 1,
                                  **({"exclude_place_ids": ",".join(exclude)} if exclude else {})})
            except requests.RequestException as e:
                log(f"Nominatim: „{q}” – {type(e).__name__} {getattr(e.response, 'status_code', '')}".rstrip())
                break
            exclude += [str(x["place_id"]) for x in res]
            for x in res:
                if x.get("category") not in ("boundary", "place", "highway", "landuse"):
                    seen.setdefault(x["place_id"], x)
            if len(res) < 50 or len(seen) >= max_results:
                break
    out = [b for b in (_osm_business(x, city, category) for x in seen.values()) if b]
    log(f"Nominatim: {len(out)} firm „{category}” w {city}")
    return out[:max_results]


# ---------------------------------------------------------------- API
GOOGLE_MAX_QUERIES = 60  # na jedną branżę – pilnuje kosztów przy szukaniu po dzielnicach


def discover(cities: list[str], categories: list[str], max_per_query: int, log: Log = _noop, expand: bool = False) -> list[Business]:
    """Szuka we wszystkich źródłach naraz i łączy duplikaty.

    expand=True: dodatkowo okoliczne gminy (OpenStreetMap) i dzielnice miasta (Google Maps), z data/okolice.json.
    """
    use_google = bool(config.GOOGLE_PLACES_API_KEY) and not config.FREE_ONLY
    if config.FREE_ONLY:
        log("Tryb darmowy: OpenStreetMap + Booksy (bez Google Maps).")
    elif not use_google:
        log("Brak GOOGLE_PLACES_API_KEY – szukam w OpenStreetMap + Booksy (Google Maps da więcej firm i opinii).")
    found: list[Business] = []
    for city in cities:
        info = area_info(city, log) if expand else {}
        areas = [city] + info.get("gminy", [])
        if expand and not info.get("gminy"):
            log(f"Nie znalazłem gmin wokół „{city}” – szukam tylko w samym mieście.")
        for cat in categories:
            batch: list[Business] = []
            for area in areas:
                part: list[Business] = []
                try:
                    if use_google:
                        queries = [f"{t} {area}" for t in category_terms(cat)[:3]]
                        if area == city:
                            queries += [f"{cat} {d} {city}" for d in info.get("dzielnice", [])]
                        queries = queries[:GOOGLE_MAX_QUERIES]
                        for q in queries:
                            part += search_google_places(q, area, cat, max_per_query, log)
                    part += search_osm(area, cat, 1000, log)
                    if not use_google:
                        time.sleep(1)  # grzecznie wobec darmowego serwera
                except requests.RequestException as e:
                    log(f"Błąd wyszukiwania „{cat} {area}”: {e}")
                part = merge.merge_duplicates(part)
                part += contacts.booksy_businesses(area, cat, part, log)
                if len(areas) > 1:
                    log(f"  {cat} / {area}: {len(part)} firm")
                batch += part
            log(f"Znaleziono {len(batch)} firm: {cat} / {city}" + (f" (+{len(areas) - 1} okolicznych gmin)" if len(areas) > 1 else ""))
            found.extend(batch)
    return merge.merge_duplicates(found, log)
