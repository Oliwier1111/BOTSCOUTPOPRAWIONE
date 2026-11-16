"""Tryb pracownika: SCOUT sam przechodzi po kolejce „miasto + branża", szuka tylko nowych firm
i przekazuje je do szkiców maili (wysyłkę dalej pilnuje scout/outreach.py z jej limitami)."""
from __future__ import annotations

import datetime as dt
import json
import re
import threading

import scout_config as config

PATH = config.DATA_DIR / "autopilot.json"
KNOWN = config.DATA_DIR / "znalezione.json"
_lock = threading.Lock()
DEFAULT = {"wlaczony": False, "dziennie": 12, "godziny": "7-20", "zadania": [], "historia": []}


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------- firmy już znalezione
def key(b) -> str:
    """Stały klucz firmy: telefon (same cyfry), a bez niego nazwa + miasto."""
    digits = re.sub(r"\D", "", b.phone or "")[-9:]
    if len(digits) >= 9:
        return "t" + digits
    return "n" + re.sub(r"\W+", "", f"{b.name}{b.city}".lower())


_BOOKSY_ID = re.compile(r"booksy\.com/pl-pl/(\d+)_")


def booksy_key(url: str) -> str:
    """Klucz profilu Booksy (numer salonu) – ten sam salon bywa na Booksy pod dwiema nazwami."""
    m = _BOOKSY_ID.search(url or "")
    return "b" + m.group(1) if m else ""


_GENERIC = re.compile(r"^(?:(?:salon|studio|gabinet|pracownia|zakład|fryzjerski|fryzjerskie|fryzjer|kosmetyczny|urody|beauty)\s+)+")


def keys(b) -> set[str]:
    """Klucz telefonu, klucz nazwy + miasta i numer profilu Booksy – ta sama firma z różnych źródeł to jedna firma."""
    out = {key(b), "n" + re.sub(r"\W+", "", f"{b.name}{b.city}".lower())}
    short = re.split(r"\s+[|•–-]\s+", b.name or "")[0]  # „J&S Studio | Fryzjer Bydgoszcz” = „J&S Studio”
    if short and short != b.name:
        out.add("n" + re.sub(r"\W+", "", f"{short}{b.city}".lower()))
    bare = _GENERIC.sub("", short.lower()).strip()  # „Salon Sekret Loli” = „Sekret LOLI”
    if len(bare) >= 5 and bare != short.lower() and _GENERIC.sub("", bare + " "):
        out.add("n" + re.sub(r"\W+", "", f"{bare}{b.city}".lower()))
    for u in [getattr(b, "source_id", "") or "", *(getattr(b, "other_contacts", None) or [])]:
        if k := booksy_key(str(u)):
            out.add(k)
    return out


def known() -> set[str]:
    return set(_read(KNOWN, []))


def remember(businesses) -> None:
    with _lock:
        _write(KNOWN, sorted(known() | {k for b in businesses for k in keys(b)}))


def only_new(businesses, log=lambda _: None):
    seen = known()
    fresh = [b for b in businesses if not (keys(b) & seen)]
    log(f"Autopilot: {len(businesses) - len(fresh)} firm już znanych pomijam, {len(fresh)} nowych")
    return fresh


# ----------------------------------------------------- ustawienia i kolejka
def load() -> dict:
    return {**DEFAULT, **_read(PATH, {})}


def save(cfg: dict) -> dict:
    with _lock:
        _write(PATH, cfg)
    return cfg


def set_config(wlaczony: bool, dziennie: int, zadania: list[dict]) -> dict:
    cfg = load()
    old = {(z["miasto"].lower(), z["branza"].lower()): z for z in cfg["zadania"]}
    jobs = []
    for z in zadania:
        m, br = (z.get("miasto") or "").strip(), (z.get("branza") or "").strip()
        if not m or not br or any((x["miasto"].lower(), x["branza"].lower()) == (m.lower(), br.lower()) for x in jobs):
            continue
        prev = old.get((m.lower(), br.lower()), {})
        jobs.append({"miasto": m, "branza": br, "ostatnio": prev.get("ostatnio"), "nowych": prev.get("nowych", 0)})
    cfg.update(wlaczony=bool(wlaczony), dziennie=max(1, min(int(dziennie), 20)), zadania=jobs)
    return save(cfg)


def _today() -> str:
    return dt.date.today().isoformat()


def runs_today(cfg: dict) -> int:
    return sum(1 for h in cfg["historia"] if h.get("data") == _today())


def in_hours(cfg: dict, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    try:
        a, b = (int(x) for x in cfg["godziny"].split("-"))
    except ValueError:
        a, b = 7, 22
    return a <= now.hour < b


def next_job(cfg: dict) -> dict | None:
    """Najpierw zadanie, w którym zostały jeszcze nowe firmy; potem to, które czekało najdłużej (nic dwa razy dziennie)."""
    left = [z for z in cfg["zadania"] if z.get("zostalo", 0) > 0]
    if left:
        return min(left, key=lambda z: z.get("ostatnio") or "")
    todo = [z for z in cfg["zadania"] if z.get("ostatnio") != _today()]
    return min(todo, key=lambda z: z.get("ostatnio") or "") if todo else None


def status() -> dict:
    cfg = load()
    nxt = next_job(cfg)
    return {**cfg, "dzisiaj": runs_today(cfg), "nastepne": nxt and f"{nxt['miasto']} – {nxt['branza']}",
            "historia": cfg["historia"][-15:][::-1]}


def _finish(job: dict, result, log, remaining: int = 0) -> None:
    ok = isinstance(result, list)
    with _lock:
        cfg = load()
        for z in cfg["zadania"]:
            if (z["miasto"], z["branza"]) == (job["miasto"], job["branza"]):
                z["ostatnio"] = _today()
                z["nowych"] = z.get("nowych", 0) + (len(result) if ok else 0)
                z["zostalo"] = remaining if ok and result else 0  # paczka bez potwierdzonych leadów → przejdź do następnej branży, ta wróci w swojej kolejce
        mails = sum(1 for l in result if l.business.emails) if ok else 0
        cfg["historia"] = (cfg["historia"] + [{
            "data": _today(), "czas": dt.datetime.now().strftime("%H:%M"), "miasto": job["miasto"],
            "branza": job["branza"], "nowych": len(result) if ok else 0, "z_mailem": mails,
            "blad": "" if ok else f"{type(result).__name__}: {result}"}])[-200:]
        _write(PATH, cfg)
    log(f"Autopilot: {job['miasto']} – {job['branza']}: " + (f"{len(result)} nowych leadów, {mails} z adresem e-mail" if ok else "błąd, idę dalej"))


def tick(agent, force: bool = False) -> bool:
    """Jedno sprawdzenie pętli. Zwraca True, gdy wystartowało wyszukiwanie."""
    cfg = seed(load())
    if not force and (not cfg["wlaczony"] or not in_hours(cfg) or runs_today(cfg) >= cfg["dziennie"]):
        return False
    job = next_job(cfg)
    if not job:
        return False
    agent.log(f"Autopilot: szukam – {job['miasto']}, {job['branza']}")
    from . import contacts

    def done(r):
        _finish(job, r, agent.log, agent.remaining if isinstance(r, list) else 0)
        if isinstance(r, list):
            add_to_preview(job, r + agent.unsure)

    contacts.SKIP_KEYS = known()
    return agent.start(cities=[job["miasto"]], categories=[job["branza"]], skip_known=True, expand=True,
                       max_new=config.AUTOPILOT_MAX_NEW, on_done=done)


# ----------------------------------------------------- tryb bez okna (harmonogram, chmura)
PREVIEW = config.OUTPUT_DIR / "podglad.json"


def segment_of(branza: str) -> str:
    """Branża z listy większych firm -> tryb „duze”, każda inna (dentysta, fryzjer…) -> „male”."""
    duze = {c.lower() for c in getattr(config, "DEFAULT_CATEGORIES_DUZE", [])}
    return "duze" if branza.lower() in duze else "male"


def seed(cfg: dict) -> dict:
    """Pusta kolejka -> miasta z SCOUT_AUTOPILOT_MIASTA (albo DEFAULT_CITIES) × branże z SCOUT_AUTOPILOT_BRANZE
    (albo DEFAULT_CATEGORIES). Dzięki temu automat działa od razu dla dowolnych miast i branż."""
    if cfg["zadania"]:
        return cfg
    import os

    cities = [c.strip() for c in os.getenv("SCOUT_AUTOPILOT_MIASTA", "").split(",") if c.strip()] or config.DEFAULT_CITIES
    cats = [c.strip() for c in os.getenv("SCOUT_AUTOPILOT_BRANZE", "").split(",") if c.strip()] or config.DEFAULT_CATEGORIES
    return set_config(cfg["wlaczony"], cfg["dziennie"], [{"miasto": m, "branza": b} for m in cities for b in cats])


def add_to_preview(job: dict, leads) -> None:
    """Dopisuje nowe leady do wyniki/podglad.json (wspólna lista ze wszystkich uruchomień automatu)."""
    data = _read(PREVIEW, {"leady": []})
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    have = {x.get("_klucz"): i for i, x in enumerate(data["leady"])}
    for l in leads:
        d = l.to_dict()
        d["_baza"] = l.key  # ten sam klucz co w bazie leadów panelu (statusy rozmów)
        k = key(l.business)
        if k in have:  # firma już jest (np. wcześniej niepewna) – odśwież dane, zostaw datę znalezienia
            old = data["leady"][have[k]]
            d.update(_klucz=k, _znaleziono=old.get("_znaleziono", stamp), _zadanie=old.get("_zadanie", ""))
            data["leady"][have[k]] = d
            continue
        d.update(_klucz=k, _znaleziono=stamp, _zadanie=f"{job['miasto']} – {job['branza']}")
        data["leady"].append(d)
    data["leady"] = sorted(data["leady"], key=lambda x: (x.get("_znaleziono", ""), x.get("score", 0)), reverse=True)[:2000]
    data["aktualizacja"] = stamp
    _write(PREVIEW, data)


def run_headless(agent, jobs: int = 1, log=print, max_new: int | None = None) -> list[dict]:
    """Uruchamia zadania z kolejki jedno po drugim (bez serwera), aż zbierze `max_new` nowych firm
    (domyślnie SCOUT_AUTOPILOT_FIRM) albo zrobi `jobs` zadań. Firm już znalezionych nigdy nie bierze drugi raz."""
    from . import contacts

    done = []
    seed(load())
    budget = config.AUTOPILOT_MAX_NEW if max_new is None else max_new
    for _ in range(jobs):
        if budget <= 0:
            break
        contacts.SKIP_KEYS = known()
        contacts.BOOKSY_MAX = max(10, budget * 2)  # 400 salonów w Poznaniu to 20 min – bierzemy porcję
        job = next_job(load())
        if not job:
            log("Autopilot: dziś wszystkie zadania z kolejki są już zrobione.")
            break
        agent.log(f"Autopilot: szukam – {job['miasto']}, {job['branza']}")
        try:
            result = agent.run(cities=[job["miasto"]], categories=[job["branza"]], skip_known=True, expand=True,
                               max_new=budget, segment=segment_of(job["branza"]))
        except Exception as e:  # noqa: BLE001 - błąd jednego zadania nie zatrzymuje reszty
            result = e
        _finish(job, result, agent.log, agent.remaining if isinstance(result, list) else 0)
        if isinstance(result, list):
            budget -= len(result) + len(agent.unsure)
        if isinstance(result, list):
            add_to_preview(job, result + agent.unsure)
        done.append({"zadanie": f"{job['miasto']} – {job['branza']}",
                     "nowych": len(result) if isinstance(result, list) else 0,
                     "blad": "" if isinstance(result, list) else str(result)})
    return done


def reverify_preview(log=print, use_search: bool | None = None) -> dict:
    """Sprawdza jeszcze raz, czy firmy z podglądu działają: zamknięte usuwa, resztę oznacza (potwierdzona / niepewna)."""
    from dataclasses import fields

    from . import verify
    from .models import Audit, Business, Lead

    data = _read(PREVIEW, {"leady": []})
    bf, af = {f.name for f in fields(Business)}, {f.name for f in fields(Audit)}
    leads = []
    for d in data["leady"]:
        b = Business(**{k: v for k, v in d["business"].items() if k in bf})
        a = Audit(**{k: v for k, v in d["audit"].items() if k in af}) if d.get("audit") else None
        leads.append(Lead(b, a, d.get("score", 0), d.get("tier", "C"), d.get("lead_type", ""), d.get("reasons", []), d.get("pitch", "")))
    verify.verify(leads, log, use_search=use_search)
    keep, removed = [], []
    for d, l in zip(data["leady"], leads):
        if verify.status_of(l) == verify.CLOSED:
            removed.append(f"{l.business.name}: {l.business.profile['istnieje_dowody'][0]}")
            continue
        nd = l.to_dict()
        nd.update({k: v for k, v in d.items() if k.startswith("_")})
        keep.append(nd)
    data["leady"] = keep
    data["aktualizacja"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    _write(PREVIEW, data)
    for r in removed:
        log(f"Usunięta z podglądu (zamknięta): {r}")
    st = [x["business"]["profile"].get("istnieje") for x in keep]
    return {"potwierdzone": st.count("potwierdzona"), "niepewne": st.count("niepewna"), "usuniete": len(removed)}
