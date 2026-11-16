"""Łączenie tej samej firmy znalezionej w kilku źródłach (OpenStreetMap, Google Maps, Booksy)."""
from __future__ import annotations

import re

from .filters import _norm, is_social
from .models import Business


def _phone9(b: Business) -> str:
    d = re.sub(r"\D", "", b.phone or "")
    return d[-9:] if len(d) >= 9 else ""


def _street(b: Business) -> str:
    """Ulica z numerem, np. „kosynierow gdynskich 12”."""
    first = _norm((b.address or "").split(",")[0])
    return re.sub(r"\b(ul|ulica|al|aleja|os|osiedle|pl|plac)\b\.?", "", first).strip()


def keys(b: Business) -> set[str]:
    out = set()
    if _phone9(b):
        out.add("t" + _phone9(b))
    name = re.sub(r"[^a-z0-9]+", "", _norm(b.name))
    st = _street(b)
    if name and re.search(r"\d", st):
        out.add(f"na:{name}|{st}")
    if name:
        out.add(f"nc:{name}|{_norm(b.city)}")
    return out


def _fill(a: Business, b: Business) -> None:
    """Uzupełnia puste pola firmy `a` danymi z `b` (a zostaje „głównym” rekordem)."""
    for f in ("address", "phone", "maps_url", "owner_name", "owner_info", "contacts_note"):
        if not getattr(a, f) and getattr(b, f):
            setattr(a, f, getattr(b, f))
    if (not a.website or is_social(a.website)) and b.website and not is_social(b.website):
        a.website = b.website
    elif not a.website and b.website:
        a.website = b.website
    if a.rating is None and b.rating is not None:
        a.rating, a.reviews = b.rating, b.reviews
    elif b.reviews and (a.reviews or 0) < b.reviews:
        a.rating, a.reviews = b.rating, b.reviews
    for f in ("emails", "socials", "other_contacts", "types"):
        setattr(a, f, list(dict.fromkeys(getattr(a, f) + getattr(b, f))))
    a.profile = {**b.profile, **a.profile}
    if b.source and b.source not in a.source.split("+"):
        a.source = "+".join(x for x in [a.source, b.source] if x)


def merge_duplicates(items: list[Business], log=lambda _: None) -> list[Business]:
    out: list[Business] = []
    index: dict[str, Business] = {}
    merged = 0
    for b in items:
        hit = next((index[k] for k in keys(b) if k in index), None)
        if hit is not None:
            if hit.source != b.source:
                merged += 1
            _fill(hit, b)
            for k in keys(hit):
                index.setdefault(k, hit)
            continue
        out.append(b)
        for k in keys(b):
            index[k] = b
    if merged:
        log(f"Połączono {merged} firm znalezionych w kilku źródłach naraz")
    return out
