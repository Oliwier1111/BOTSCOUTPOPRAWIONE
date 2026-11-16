"""Czy firma nadal istnieje? Sprawdzenie każdego leada w kilku niezależnych źródłach, zanim trafi do listy i do maili.

Wynik zapisuje się w business.profile:
  istnieje         = "potwierdzona" | "niepewna" | "zamknieta"
  istnieje_dowody  = lista zdań „co i gdzie sprawdzono” (trafia do karty rozmowy)

Źródła (każde opcjonalne, brak odpowiedzi nie przesądza o niczym):
  - Google Maps (gdy firma przyszła z Google Places): status OPERATIONAL,
  - Biała Lista VAT i CEIDG (gdy znamy NIP): czynny / wykreślony / zawieszony,
  - Booksy: czy profil nadal działa i kiedy była ostatnia opinia,
  - OpenStreetMap (API): oznaczenia „zamknięte” (disused:, was:, opening_hours=closed, end_date) i data sprawdzenia w terenie,
  - własna strona: czy działa i czy jest aktualna (rok w stopce),
  - wyszukiwarka (gdy dostępna): wzmianki „zamknięte na stałe”, „firma zlikwidowana” przy tej firmie.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

import requests

import scout_config as config
from . import contacts

CACHE_PATH = config.DATA_DIR / "cache_istnienia.json"
CACHE_DAYS = 14
OSM_API = "https://api.openstreetmap.org/api/0.6"
UA = "SparkScaleScout/1.0 (lokalny audyt stron firm)"

CONFIRMED, UNSURE, CLOSED = "potwierdzona", "niepewna", "zamknieta"
LABEL = {CONFIRMED: "działa (potwierdzone)", UNSURE: "nie udało się potwierdzić", CLOSED: "zamknięta"}

BOOKSY_FRESH_DAYS = 180       # ostatnia opinia na Booksy nie starsza niż pół roku = firma działa
OSM_SURVEY_FRESH_DAYS = 730   # sprawdzenie w terenie (check_date) nie starsze niż 2 lata
CLOSED_RE = re.compile(
    r"zamkni[eę]t[ae]? na sta[łl]e|permanently closed|trwale zamkni[eę]t|firma (?:zosta[łl]a )?zlikwidowan|"
    r"zako[ńn]czy[łl]a dzia[łl]alno[sś][ćc]|zako[ńn]czyli[sś]my dzia[łl]alno[sś][ćc]|lokal do wynaj[eę]cia|"
    r"wykre[sś]lon[ay] z (?:ceidg|krs|rejestru)", re.I)
OSM_LIFECYCLE = ("disused:", "was:", "abandoned:", "closed:", "demolished:", "removed:")


def _days_ago(date: str) -> int | None:
    try:
        return (dt.date.today() - dt.date.fromisoformat(date[:10])).days
    except ValueError:
        return None


# ------------------------------------------------------------------ pojedyncze źródła
def check_osm(source_id: str, get=None) -> dict:
    """Stan obiektu w OpenStreetMap: {"closed": powód} / {"fresh": data sprawdzenia} / {"info": ...}."""
    if not re.fullmatch(r"(node|way|relation)/\d+", source_id or ""):
        return {}
    get = get or (lambda u: requests.get(u, headers={"User-Agent": UA}, timeout=config.REQUEST_TIMEOUT))
    r = get(f"{OSM_API}/{source_id}.json")
    if r.status_code == 410:
        return {"info": "obiekt usunięty z OpenStreetMap – możliwe, że firma zamknięta lub przeniesiona"}
    if r.status_code != 200:
        return {}
    el = (r.json().get("elements") or [{}])[0]
    t = el.get("tags") or {}
    out = {"info": f"ostatnia zmiana w OpenStreetMap: {el.get('timestamp', '')[:10]}"}
    biz = ("amenity", "shop", "office", "craft", "healthcare")
    if any(k.startswith(OSM_LIFECYCLE) and k.split(":", 1)[1] in biz for k in t) and not any(k in t for k in biz):
        out["closed"] = "OpenStreetMap: działalność oznaczona jako nieczynna"
    if (t.get("opening_hours") or "").strip().lower() in ("closed", "off"):
        out["closed"] = "OpenStreetMap: godziny otwarcia „zamknięte”"
    end = t.get("end_date", "")
    if end and (_days_ago(end) or -1) >= 0:
        out["closed"] = f"OpenStreetMap: działalność zakończona {end}"
    survey = max((t.get(k, "") for k in ("check_date", "survey:date", "check_date:opening_hours")), default="")
    if survey and (_days_ago(survey) or 99999) <= OSM_SURVEY_FRESH_DAYS:
        out["fresh"] = f"OpenStreetMap: sprawdzone w terenie {survey[:10]}"
    return out


def check_booksy(url: str, session: requests.Session | None = None) -> dict:
    """Profil Booksy: czy jeszcze istnieje i kiedy ostatnia opinia."""
    s = session
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"})
    r = s.get(url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True)
    if r.status_code == 404 or (r.status_code == 200 and not contacts._BIZ_RE.match(r.url.split("?")[0])):
        return {"closed": "profil na Booksy już nie istnieje"}
    if r.status_code != 200:
        return {}
    if '"PostalAddress"' not in r.text and '"ratingValue"' not in r.text:
        # Booksy dla nieistniejącego salonu zwraca pustą stronę z tytułem „Booksy”; inna pusta strona = nie wiemy
        title = re.search(r"<title>([^<]*)", r.text)
        return {"closed": "profil na Booksy już nie istnieje"} if title and title.group(1).strip() == "Booksy" else {}
    dates = sorted(re.findall(r'"datePublished":"(\d{4}-\d{2}-\d{2})', r.text))
    if not dates:
        return {"info": "profil na Booksy działa, ale bez opinii"}
    last = dates[-1]
    age = _days_ago(last) or 0
    if age <= BOOKSY_FRESH_DAYS:
        return {"fresh": f"Booksy: ostatnia opinia {last}"}
    return {"info": f"Booksy: ostatnia opinia dawno – {last}", "stale": True}


def check_search(b, search) -> dict:
    """Wzmianki o zamknięciu przy tej firmie w wynikach wyszukiwarki."""
    q = " ".join(x for x in [f'"{b.name}"', b.city] if x)
    for r in search(q)[:10]:
        ok, _ = contacts._matches(b, r)
        m = CLOSED_RE.search(f"{r['title']} {r['snippet']}")
        if ok and m:
            return {"closed": f"wyszukiwarka: „{m.group(0)}” ({contacts._host(r['url'])})"}
    return {"searched": True}


# ------------------------------------------------------------------ ocena jednej firmy
def assess(b, audit=None, osm=None, booksy=None, search=None) -> tuple[str, list[str]]:
    """Zbiera sygnały i zwraca (status, dowody). Funkcje sprawdzające można podmienić (testy)."""
    p = b.profile
    ok: list[str] = []
    bad: list[str] = []
    info: list[str] = []
    year = dt.date.today().year

    if b.source == "google_places":
        ok.append("Google Maps: firma oznaczona jako czynna")

    vat = (p.get("status_vat") or "").lower()
    if vat in ("czynny", "zwolniony"):
        ok.append(f"Biała Lista VAT: podatnik {vat} (NIP {p.get('nip', '')})")
    ceidg = (p.get("status_ceidg") or "").upper()
    if ceidg == "AKTYWNY":
        ok.append("CEIDG: działalność aktywna")
    elif ceidg in ("WYKRESLONY", "ZAWIESZONY"):
        bad.append(f"CEIDG: działalność {'wykreślona' if ceidg == 'WYKRESLONY' else 'zawieszona'}")

    if audit is not None and audit.url:
        if audit.reachable and not audit.is_parked:
            if audit.copyright_year and audit.copyright_year >= year - 1:
                ok.append(f"własna strona działa i jest aktualna (© {audit.copyright_year})")
            else:
                info.append("własna strona działa" + (f", ale stopka z {audit.copyright_year}" if audit.copyright_year else ""))
        else:
            info.append("własna strona nie działa – możliwe, że firma zamknięta")

    for name, fn in (("osm", osm), ("booksy", booksy), ("search", search)):
        if not fn:
            continue
        try:
            res = fn()
        except (requests.RequestException, ValueError, contacts.SearchBlocked):
            continue
        if res.get("closed"):
            bad.append(res["closed"])
        if res.get("fresh"):
            ok.append(res["fresh"])
        if res.get("info"):
            info.append(res["info"])

    if bad:
        return CLOSED, bad + ok + info
    if ok:
        return CONFIRMED, ok + info
    return UNSURE, info or ["żadne źródło nie potwierdziło, że firma działa"]


def _booksy_url(b) -> str:
    if b.source == "booksy" and b.source_id.startswith("http"):
        return b.source_id
    return next((c.split(": ", 1)[1] for c in b.other_contacts if c.startswith("Booksy: ")), "")


def verify(leads, log=lambda _: None, use_search: bool | None = None) -> None:
    """Sprawdza istnienie każdej firmy z listy leadów (wynik w l.business.profile)."""
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    now = dt.datetime.now()
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"})
    search, sname = contacts.default_search()
    search_ok = config.FIND_CONTACTS if use_search is None else use_search
    counts = {CONFIRMED: 0, UNSURE: 0, CLOSED: 0}
    log(f"Sprawdzam, czy {len(leads)} firm nadal działa (rejestry, Booksy, OpenStreetMap, strona"
        + (f", {sname})" if search_ok else ")"))

    def guarded_search(b):
        nonlocal search_ok
        if not search_ok:
            return {}
        try:
            time.sleep(2)
            return check_search(b, search)
        except (contacts.SearchBlocked, requests.RequestException) as e:
            search_ok = False
            log(f"Wyszukiwarka nie odpowiada ({e}) – sprawdzam istnienie bez niej")
            return {}

    for l in leads:
        b = l.business
        key = f"{b.source}|{b.source_id}|{b.name.lower()}|{b.city.lower()}"
        hit = cache.get(key)
        if hit and (now - dt.datetime.fromisoformat(hit["_t"])).days < CACHE_DAYS:
            status, proofs = hit["status"], hit["dowody"]
        else:
            burl = _booksy_url(b)
            status, proofs = assess(
                b, l.audit,
                osm=(lambda: (time.sleep(0.3), check_osm(b.source_id))[1]) if b.source == "openstreetmap" else None,
                booksy=(lambda: (time.sleep(0.4), check_booksy(burl, session))[1]) if burl else None,
                search=lambda: guarded_search(b),
            )
            if status != UNSURE or search_ok:  # bez wyszukiwarki „niepewna” sprawdzimy jeszcze raz następnym razem
                cache[key] = {"status": status, "dowody": proofs, "_t": now.isoformat()}
        b.profile["istnieje"], b.profile["istnieje_dowody"] = status, proofs
        counts[status] += 1
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log(f"Istnienie firm: {counts[CONFIRMED]} potwierdzonych, {counts[UNSURE]} niepewnych, {counts[CLOSED]} zamkniętych")


def status_of(lead) -> str:
    return lead.business.profile.get("istnieje", UNSURE)
