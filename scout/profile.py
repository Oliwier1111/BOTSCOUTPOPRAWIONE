"""Profil firmy i „karta rozmowy" dla handlowca: czym się zajmuje, od kiedy jest na rynku, kontakty, godziny, usługi.

Źródła (każde opcjonalne, błąd jednego nie psuje reszty):
- strona firmy: NIP z stopki / kontaktu oraz deklaracje typu „działamy od 2008 roku",
- Biała Lista VAT (Ministerstwo Finansów, bez klucza): nazwa, REGON, KRS, data wpisu do rejestru VAT,
- KRS (Ministerstwo Sprawiedliwości, bez klucza): data rejestracji spółki, forma prawna, PKD, zarząd,
- CEIDG (klucz CEIDG_TOKEN – darmowy z dane.gov.pl): data rozpoczęcia działalności jednoosobowej firmy,
- Wayback Machine: najstarsza kopia strony (strona w sieci co najmniej od…),
- OpenStreetMap i Booksy: godziny otwarcia, usługi, ceny (zapisane wcześniej w Business.profile).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import scout_config as config
from .filters import domain_of, is_social

CACHE_PATH = config.DATA_DIR / "cache_profil.json"
CACHE_DAYS = 30
Log = type(lambda _: None)

NIP_RE = re.compile(r"(?:NIP|N\.I\.P\.?)\s*[:.]?\s*(?:PL)?\s*(\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\d{3}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{3})", re.I)
CLAIM_YEAR_RE = re.compile(
    r"(?:dzia[łl]amy|istniejemy|funkcjonujemy|na rynku|firma dzia[łl]a|za[łl]o[żz]on\w+|tradycj\w+)[^.\d]{0,25}?((?:19[5-9]|20[0-2])\d)", re.I)
CLAIM_YEARS_RE = re.compile(r"(\d{1,2})\s+lat\w*\s+(?:do[sś]wiadczenia|na rynku|tradycji|dzia[łl]alno[sś]ci)", re.I)
DAYS = {"Monday": "pn", "Tuesday": "wt", "Wednesday": "śr", "Thursday": "czw", "Friday": "pt", "Saturday": "sob", "Sunday": "ndz"}
HTTP_HEADERS = {"User-Agent": config.USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"}


# ------------------------------------------------------------------ OpenStreetMap / Booksy -> profil
def osm_profile(t: dict) -> dict:
    """Godziny otwarcia, opis i specjalizacje zapisane w tagach OpenStreetMap."""
    p = {}
    if t.get("opening_hours"):
        p["godziny"] = t["opening_hours"]
    if t.get("description"):
        p["opis"] = t["description"][:300]
    spec = t.get("healthcare:speciality") or t.get("speciality") or ""
    if spec:
        p["specjalizacje"] = spec.replace("_", " ").replace(";", ", ")
    if t.get("start_date"):
        p["osm_start"] = t["start_date"]
    return p


def hours_from_jsonld(specs) -> str:
    out = []
    for s in specs or []:
        days = s.get("dayOfWeek") or []
        days = [days] if isinstance(days, str) else days
        order = list(DAYS)
        idx = sorted(order.index(d.rsplit("/", 1)[-1]) for d in days if d.rsplit("/", 1)[-1] in order)
        names = [DAYS[order[i]] for i in idx]
        contiguous = idx and idx[-1] - idx[0] == len(idx) - 1
        label = names[0] if len(names) == 1 else f"{names[0]}–{names[-1]}" if len(names) > 2 and contiguous else ", ".join(names)
        out.append(f"{label} {s.get('opens', '')}–{s.get('closes', '')}".strip())
    return "; ".join(out)


# ------------------------------------------------------------------ strona firmy
def valid_nip(n: str) -> bool:
    d = re.sub(r"\D", "", n)
    if len(d) != 10:
        return False
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    c = sum(int(a) * b for a, b in zip(d, w)) % 11
    return c != 10 and c == int(d[9])


def facts_from_text(text: str) -> dict:
    out = {"nip": "", "deklaracje": []}
    for m in NIP_RE.finditer(text):
        if valid_nip(m.group(1)):
            out["nip"] = re.sub(r"\D", "", m.group(1))
            break
    for m in CLAIM_YEAR_RE.finditer(text):
        out["deklaracje"].append(f"na stronie: „{m.group(0).strip()}”")
        break
    m = CLAIM_YEARS_RE.search(text)
    if m:
        out["deklaracje"].append(f"na stronie: „{m.group(0).strip()}”")
    return out


LINK_RE = re.compile(r"kontakt|o[- ]?nas|about|polityk|prywatno|regulamin|stopka|impressum|rodo", re.I)


def _fetch(url: str) -> str:
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=config.REQUEST_TIMEOUT)
    except requests.exceptions.SSLError:  # wiele małych firm ma zepsuty certyfikat – dane i tak są publiczne
        r = requests.get(url, headers=HTTP_HEADERS, timeout=config.REQUEST_TIMEOUT, verify=False)
    return r.text if r.status_code < 400 else ""


def site_facts(url: str, get=None) -> dict:
    """NIP i deklaracje o wieku firmy ze strony głównej oraz z podstron kontakt / o nas / polityka prywatności / regulamin."""
    get = get or _fetch
    start = url if "://" in url else "http://" + url
    out = {"nip": "", "deklaracje": []}
    pages = [start]
    seen = set()
    while pages and len(seen) < 5:
        page = pages.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            html = get(page)
        except requests.RequestException:
            continue
        soup = BeautifulSoup(html, "html.parser")
        f = facts_from_text(soup.get_text(" "))
        out["nip"] = out["nip"] or f["nip"]
        out["deklaracje"] += [x for x in f["deklaracje"] if x not in out["deklaracje"]]
        if page == start:  # linki do podstron, na których zwykle jest NIP
            host = urlparse(page).netloc.removeprefix("www.")
            for a in soup.find_all("a", href=True):
                href = urljoin(page, a["href"]).split("#")[0]
                if urlparse(href).netloc.removeprefix("www.") == host and LINK_RE.search(href + " " + a.get_text(" ")):
                    pages.append(href)
        if out["nip"] and out["deklaracje"]:
            break
    return out


def wayback_year(url: str, get=None) -> int | None:
    get = get or (lambda u: requests.get(u, headers=HTTP_HEADERS, timeout=config.REQUEST_TIMEOUT).json())
    try:
        snap = get(f"http://archive.org/wayback/available?url={domain_of(url)}&timestamp=19950101")["archived_snapshots"].get("closest")
    except (requests.RequestException, ValueError, KeyError):
        return None
    return int(snap["timestamp"][:4]) if snap and snap.get("available") else None


# ------------------------------------------------------------------ rejestry
def _pl_date(s: str) -> str:
    """„11.06.2001” albo „2001-06-11” -> „2001-06-11”."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (s or "")[:10]


def krs_lookup(krs: str, get=None) -> dict:
    get = get or (lambda u, **kw: requests.get(u, timeout=config.REQUEST_TIMEOUT, **kw).json())
    try:
        o = get(f"https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}", params={"rejestr": "P", "format": "json"})["odpis"]
    except (requests.RequestException, ValueError, KeyError):
        return {}
    d = o.get("dane", {})
    out = {"data_krs": _pl_date(o.get("naglowekA", {}).get("dataRejestracjiWKRS", ""))}
    out["forma"] = d.get("dzial1", {}).get("danePodmiotu", {}).get("formaPrawna", "").capitalize()
    pkd = d.get("dzial3", {}).get("przedmiotDzialalnosci", {}).get("przedmiotPrzewazajacejDzialalnosci") or []
    if pkd:
        out["pkd"] = pkd[0].get("opis", "").capitalize()
    people = []
    rep = d.get("dzial2", {}).get("reprezentacja")
    for org in rep if isinstance(rep, list) else [rep] if rep else []:
        for p in org.get("sklad") or []:
            name = " ".join(x for x in [(p.get("imiona") or {}).get("imie", ""), (p.get("nazwisko") or {}).get("nazwiskoI", "")] if x)
            if name and "*" not in name:  # KRS publicznie maskuje dane osobowe w odpisach
                people.append(f"{name.title()} ({(p.get('funkcjaWOrganie') or 'zarząd').lower()})")
    out["zarzad"] = people[:4]
    return out


def mf_lookup(nip: str, get=None) -> dict:
    """Biała Lista VAT: nazwa, REGON, KRS, data wpisu do rejestru VAT."""
    get = get or (lambda u, **kw: requests.get(u, timeout=config.REQUEST_TIMEOUT, **kw).json())
    try:
        s = get(f"https://wl-api.mf.gov.pl/api/search/nip/{nip}", params={"date": dt.date.today().isoformat()})["result"]["subject"]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {}
    if not s:
        return {}
    return {"nip": nip, "nazwa_prawna": s.get("name", ""), "regon": s.get("regon", ""), "krs": s.get("krs") or "",
            "status_vat": s.get("statusVat", ""), "vat_od": s.get("registrationLegalDate") or ""}


def ceidg_lookup(token: str, nip: str = "", name: str = "", city: str = "", get=None) -> dict:
    """CEIDG v3 (wymaga darmowego tokenu). Zwraca datę rozpoczęcia działalności i właściciela jednoosobowej firmy."""
    if not token or not (nip or name):
        return {}
    get = get or (lambda u, **kw: requests.get(u, timeout=config.REQUEST_TIMEOUT, **kw).json())
    hdr = {"Authorization": f"Bearer {token}"}
    params = {"nip": nip} if nip else {"nazwa": name, "miasto": city}
    try:
        firms = get("https://dane.biznes.gov.pl/api/ceidg/v3/firmy", params=params, headers=hdr).get("firmy") or []
        if not firms:
            return {}
        f = firms[0]
        if not f.get("dataRozpoczecia") and f.get("link"):
            f = (get(f["link"], headers=hdr).get("firma") or [f])[0]
    except (requests.RequestException, ValueError, AttributeError, IndexError):
        return {}
    w = f.get("wlasciciel") or {}
    return {"ceidg_start": (f.get("dataRozpoczecia") or "")[:10], "status_ceidg": f.get("status", ""),
            "wlasciciel": " ".join(x for x in [w.get("imie", ""), w.get("nazwisko", "")] if x).title(),
            "nip": w.get("nip") or nip, "regon": w.get("regon", ""), "pkd_kod": f.get("pkdGlowny", "")}


# ------------------------------------------------------------------ składanie opisu
def _age(date: str) -> str:
    try:
        years = (dt.date.today() - dt.date.fromisoformat(date[:10])).days // 365
    except ValueError:
        return ""
    return f" (~{years} lat)" if years >= 1 else " (mniej niż rok)"


def na_rynku(p: dict) -> str:
    parts = []
    if p.get("ceidg_start"):
        parts.append(f"działalność w CEIDG od {p['ceidg_start']}{_age(p['ceidg_start'])}")
    if p.get("data_krs"):
        parts.append(f"spółka w KRS od {p['data_krs']}{_age(p['data_krs'])}")
    if p.get("osm_start"):
        parts.append(f"w OpenStreetMap: działa od {p['osm_start']}")
    if p.get("vat_od"):
        parts.append(f"w rejestrze VAT od {p['vat_od']}{_age(p['vat_od'])}")
    parts += p.get("deklaracje", [])
    if p.get("strona_od"):
        parts.append(f"strona internetowa istnieje od ok. {p['strona_od']}")
    return "; ".join(parts)


def czym(b) -> str:
    p = b.profile
    parts = [b.category]
    for k in ("specjalizacje", "pkd", "opis"):
        if p.get(k):
            parts.append(str(p[k]))
    if p.get("uslugi"):
        parts.append("usługi: " + ", ".join(p["uslugi"][:6]))
    return " · ".join(dict.fromkeys(x for x in parts if x))


def enrich_one(b, token: str = "", get_cache=None) -> None:
    p = b.profile
    own = b.website and not is_social(b.website) and "booksy" not in b.website
    if own and not p.get("nip"):
        f = site_facts(b.website)
        p["nip"] = p.get("nip") or f["nip"]
        p["deklaracje"] = f["deklaracje"]
    if own and not p.get("strona_od"):
        y = wayback_year(b.website)
        if y:
            p["strona_od"] = y
    if p.get("nip"):
        reg = mf_lookup(p["nip"])
        p.update({k: v for k, v in reg.items() if v})
        if reg.get("krs"):
            p.update({k: v for k, v in krs_lookup(reg["krs"]).items() if v})
        elif reg:
            p.setdefault("forma", "Działalność bez KRS (jednoosobowa firma lub spółka cywilna)")
    if token and not p.get("ceidg_start") and not p.get("krs"):
        p.update({k: v for k, v in ceidg_lookup(token, p.get("nip", ""), b.name, b.city).items() if v})
        if p.get("wlasciciel") and not b.owner_name:
            b.owner_name, b.owner_info = p["wlasciciel"], "właściciel firmy według CEIDG"
    if p.get("zarzad") and not b.owner_name:
        first = p["zarzad"][0]
        b.owner_name, b.owner_info = first.split(" (")[0], f"KRS: {first.split(' (')[-1].rstrip(')')}"
    p["na_rynku"] = na_rynku(p)
    p["czym"] = czym(b)


def enrich(businesses, log=lambda _: None, limit: int = 150) -> None:
    """Uzupełnia profil firm (zwykle tylko leadów). Wynik trzyma w pamięci podręcznej 30 dni."""
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    now = dt.datetime.now()
    done = got = 0
    own = lambda b: bool(b.website and not is_social(b.website) and 'booksy' not in b.website)  # tylko firmy ze stroną mają NIP do sprawdzenia
    for b in sorted(businesses, key=lambda b: not own(b))[:limit]:
        key = f"{domain_of(b.website) if b.website and not is_social(b.website) else ''}|{b.name.lower()}|{b.city.lower()}"
        hit = cache.get(key)
        if hit and (now - dt.datetime.fromisoformat(hit["_t"])).days < CACHE_DAYS:
            b.profile = {**b.profile, **{k: v for k, v in hit.items() if k != "_t" and not b.profile.get(k)}}
            b.profile["na_rynku"], b.profile["czym"] = na_rynku(b.profile), czym(b)
        else:
            try:
                enrich_one(b, getattr(config, "CEIDG_TOKEN", ""))
            except Exception as e:  # noqa: BLE001 - brak profilu nie może zatrzymać wyszukiwania
                log(f"Profil „{b.name}”: {type(e).__name__}: {e}")
                continue
            cache[key] = {**b.profile, "_t": now.isoformat()}
        done += 1
        got += bool(b.profile.get("na_rynku"))
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log(f"Profile firm: {done} sprawdzonych, wiek firmy znany dla {got}")


# ------------------------------------------------------------------ karta rozmowy
def call_sheet(lead) -> str:
    """Gotowa ściąga dla handlowca dzwoniącego do firmy."""
    from .models import _uniq

    b, a = lead.business, lead.audit
    p = b.profile
    emails = _uniq(b.emails + (a.emails if a else []))
    socials = _uniq(b.socials + (a.socials if a else []))
    L = [f"FIRMA: {b.name} – {b.category}, {b.address or b.city}"]
    if p.get("istnieje"):
        head = {"potwierdzona": "TAK", "niepewna": "NIE POTWIERDZONO – sprawdź przed telefonem", "zamknieta": "ZAMKNIĘTA"}[p["istnieje"]]
        L.append(f"CZY FIRMA DZIAŁA: {head} ({'; '.join(p.get('istnieje_dowody', [])[:3])})")
    if czy := p.get("czym") or czym(b):
        L.append(f"CZYM SIĘ ZAJMUJE: {czy}")
    L.append("OD KIEDY NA RYNKU: " + (p.get("na_rynku") or na_rynku(p) or "brak danych w rejestrach – zapytaj w rozmowie"))
    if p.get("forma") or p.get("nip"):
        L.append("DANE FIRMY: " + ", ".join(x for x in [p.get("nazwa_prawna"), p.get("forma"), f"NIP {p['nip']}" if p.get("nip") else "",
                                                         f"REGON {p['regon']}" if p.get("regon") else "",
                                                         f"VAT: {p['status_vat']}" if p.get("status_vat") else ""] if x))
    if b.owner_name:
        L.append(f"OSOBA DO ROZMOWY: {b.owner_name}" + (f" ({b.owner_info})" if b.owner_info else ""))
    elif p.get("zarzad"):
        L.append("ZARZĄD (KRS): " + ", ".join(p["zarzad"]))
    contact = [f"tel. {b.phone}" if b.phone else "brak telefonu w źródłach – napisz przez wizytówkę/social"]
    contact += [f"e-mail {e}" for e in emails[:3]] + socials[:3] + b.other_contacts[:3]
    L.append("KONTAKT: " + " · ".join(contact))
    if b.rating is not None:
        L.append(f"OPINIE: {b.rating} ({b.reviews or 0} opinii)")
    if p.get("godziny"):
        L.append(f"GODZINY OTWARCIA (dzwoń, gdy otwarte): {p['godziny']}")
    if p.get("uslugi"):
        L.append("USŁUGI I CENY: " + ", ".join(p["uslugi"][:8]) + (f" (zakres cen {p['cennik']})" if p.get("cennik") else ""))
    L.append("STRONA: " + (b.website or "brak własnej strony") + (f" – {p['weryfikacja_strony']}" if p.get("weryfikacja_strony") else ""))
    L.append("O CO ZAHACZYĆ: " + " | ".join(lead.reasons[:4]))
    if lead.pitch:
        L.append(f"NA POCZĄTEK: {lead.pitch}")
    if b.contacts_note:
        L.append(f"UWAGI: {b.contacts_note}")
    return "\n".join(L)
