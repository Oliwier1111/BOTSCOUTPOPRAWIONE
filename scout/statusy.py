"""Statusy rozmów z firmami (Do zrobienia / W toku / Zakończone) – wspólne dla zespołu, gdy SCOUT działa na serwerze.

Na stronie podglądu w claude.ai statusy trzyma baza strony; na własnym serwerze (server.py, panel) – ten plik:
data/statusy.json  ->  {klucz_firmy: {"s": status, "t": czas ISO, "kto": imię, "firma": ..., "miasto": ...}}

Statusy są zsynchronizowane z bazą leadów panelu (scout/baza.py, zakładka „Do dzwonienia”): zmiana na liście /podglad
trafia do bazy, a zmiana w panelu widoczna jest na liście /podglad (wygrywa nowsza).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading

import scout_config as config

PATH = config.DATA_DIR / "statusy.json"
ALLOWED = {"oddzwonic", "nie_odbiera", "spotkanie", "klient", "nie", "zamknieta"}
_lock = threading.Lock()


def doc_id(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").lower())[:120] or "x"


# lista /podglad  <->  baza leadów panelu
TO_BAZA = {"oddzwonic": "oddzwonic", "nie_odbiera": "nie_odebral", "spotkanie": "spotkanie",
           "klient": "zainteresowany", "nie": "odmowa", "zamknieta": "zly_numer"}
FROM_BAZA = {"oddzwonic": "oddzwonic", "nie_odebral": "nie_odbiera", "wyslac_oferte": "oddzwonic",
             "spotkanie": "spotkanie", "zainteresowany": "klient", "odmowa": "nie", "zly_numer": "zamknieta",
             "nie_dzwonic": "nie"}


def _own() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _baza_keys() -> dict:
    """doc_id leada z podglądu -> klucz w bazie leadów panelu."""
    from . import autopilot

    data = autopilot._read(autopilot.PREVIEW, {"leady": []})
    return {doc_id(x.get("_klucz", "")): x["_baza"] for x in data.get("leady", []) if x.get("_baza")}


def _ts(s: str) -> float:
    try:
        d = dt.datetime.fromisoformat(s)
        return (d if d.tzinfo else d.astimezone()).timestamp()
    except (TypeError, ValueError):
        return 0.0


def all_() -> dict:
    data = _own()
    try:
        from . import baza

        recs = {r["key"]: r for r in baza.all_records()}
    except Exception:  # noqa: BLE001 - brak bazy nie może zepsuć listy
        return data
    for did, bkey in _baza_keys().items():
        rec = recs.get(bkey)
        if not rec:
            continue
        c = rec.get("crm") or {}
        mine = data.get(did)
        if mine and _ts(mine.get("t", "")) >= _ts(c.get("czas", "")):
            continue  # nowsza zmiana jest na liście /podglad
        if c.get("status") in FROM_BAZA:
            b = (rec.get("lead") or {}).get("business") or {}
            data[did] = {"s": FROM_BAZA[c["status"]], "t": c.get("czas", ""), "kto": c.get("kto", ""),
                         "firma": b.get("name", ""), "miasto": b.get("city", "")}
        elif c.get("status") == "nowy" and mine:
            data.pop(did, None)  # w panelu cofnięto do „Do zadzwonienia”
    return data


def _to_baza(key: str, status: str, kto: str) -> None:
    try:
        from . import baza

        bkey = _baza_keys().get(doc_id(key))
        if bkey:
            baza.update(bkey, kto or "lista /podglad", status=status)
    except Exception:  # noqa: BLE001 - firma spoza bazy / stara baza: status zostaje na liście
        pass


def set_(key: str, status: str, kto: str = "", firma: str = "", miasto: str = "") -> dict:
    if status not in ALLOWED:
        raise ValueError(f"nieznany status: {status}")
    with _lock:
        data = _own()
        data[doc_id(key)] = {"s": status, "t": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                             "kto": kto[:60], "firma": firma[:200], "miasto": miasto[:100]}
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _to_baza(key, TO_BAZA[status], kto)
    return all_()


def delete(key: str, kto: str = "") -> dict:
    with _lock:
        data = _own()
        data.pop(doc_id(key), None)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _to_baza(key, "nowy", kto)
    return all_()
