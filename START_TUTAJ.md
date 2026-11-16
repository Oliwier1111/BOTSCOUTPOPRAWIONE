# SCOUT – zacznij tutaj

SCOUT to agent, który sam szuka lokalnych firm bez strony albo ze słabą stroną, sprawdza, czy firma nadal działa,
przygotowuje listę do obdzwonienia dla zespołu i wysyła maile z propozycją zrobienia lub poprawienia strony.

## Co robi w jednym przebiegu (np. co godzinę)

1. Bierze z kolejki parę „miasto + branża” (sam układa kolejkę z `SCOUT_AUTOPILOT_MIASTA` × `SCOUT_AUTOPILOT_BRANZE`).
2. Znajduje do 10 **nowych** firm (`SCOUT_AUTOPILOT_FIRM`); żadna firma nie wraca drugi raz (`data/znalezione.json`).
3. Audytuje stronę, szuka kontaktów, liczy wynik 0–100 i priorytet A/B/C.
4. Sprawdza, czy firma działa (VAT/CEIDG, Booksy, OpenStreetMap, strona). Zamknięte odpadają, niepewne idą do osobnego pliku.
5. Dodaje firmy do **listy do obdzwonienia** (`/podglad`) i przygotowuje maile.
6. Czyta odpowiedzi (STOP → lista „nie pisz”), potem wysyła maile: tylko potwierdzone firmy, jeden mail na adres,
   dni robocze 9–17, najwyżej 20 dziennie.

## Uruchomienie (5 minut)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: start.bat robi wszystko sam
pip install -r requirements.txt
cp .env.example .env                                    # uzupełnij poniższe
uvicorn server:app --host 0.0.0.0 --port 8010           # aplikacja + API + lista /podglad
```

Na serwerze bez aplikacji wystarczy harmonogram (cron), np. co godzinę w dni robocze:

```
47 7-19 * * 1-5  cd /sciezka/scout && TZ=Europe/Warsaw python main.py --autopilot 3 --wyslij
```

## Co trzeba wpisać w `.env`

| Zmienna | Po co |
|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | skrzynka, z której idą maile (zwykle „hasło aplikacji”) |
| `MAIL_FROM`, `MAIL_FROM_NAME`, `MAIL_COMPANY`, `MAIL_SIGNATURE` | nadawca i podpis w mailu |
| `SCOUT_AUTOWYSYLKA=1` | serwer sam wysyła maile (w trybie cron robi to `--wyslij`) |
| `SCOUT_AUTOPILOT_MIASTA`, `SCOUT_AUTOPILOT_BRANZE` | gdzie i jakich firm szukać (puste = Poznań i ok. 20 branż) |
| `CEIDG_TOKEN` (darmowy), `GOOGLE_PLACES_API_KEY` (opcjonalnie) | więcej firm z potwierdzeniem, że działają |
| `ANTHROPIC_API_KEY`, `PAGESPEED_API_KEY` (opcjonalnie) | ocena wyglądu strony przez AI i szybkość strony |

Bez `SMTP_HOST` SCOUT działa normalnie, tylko maile zostają jako szkice.

## Panel SparkScale i lista „Do dzwonienia”

- Główna lista dla handlowców to zakładka „Do dzwonienia” w aplikacji (`/`, baza `data/baza_leadow.json`, statusy, notatki,
  oddzwonienia, dziennik aktywności dla Prezesa). Automat dopisuje tam każdą potwierdzoną firmę.
- `/podglad` to lista firm znalezionych przez automat (zakładki Do zrobienia / Nowe / W toku / Zakończone). Statusy są
  zsynchronizowane z bazą „Do dzwonienia”: zmiana w jednym miejscu jest widoczna w drugim.
- API: `GET /api/scout/baza`, `POST /api/scout/crm`, `GET /api/scout/podglad`, `GET/POST /api/scout/statusy`,
  `GET /api/scout/state`, `POST /api/scout/run`, `GET /api/scout/outreach` – opis w `integracja/INTEGRACJA.md`.
- Automat wybiera tryb sam: branże z listy większych firm liczy jak „duże”, resztę (dentysta, fryzjer…) jak „małe”.

## Teksty maili

`data/szablon_maila.txt` (firma bez strony) i `data/szablon_maila_poprawa.txt` (słaba strona, z listą konkretnych problemów).
Można je dowolnie zmieniać; pola: `{nazwa}`, `{powod}`, `{problemy}`, `{podpis}`.

## Ważne

- Oferta mailem do firmy w Polsce wymaga zgody odbiorcy (Prawo komunikacji elektronicznej) i dotyczy jej RODO. Szablony pytają
  o zgodę na przesłanie propozycji, każdy mail ma „odpisz STOP” i List-Unsubscribe, ale decyzja o wysyłce należy do Was.
- Test bez internetu i kluczy: `python main.py --mock`.
- Pełna dokumentacja: `README.md`; hosting: `HOSTING.md`.
