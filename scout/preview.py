"""Podgląd wyników Autopilota: jedna strona HTML ze wszystkimi zebranymi leadami (filtry, kontakty, karta rozmowy).

Plik wyniki/podglad.html otwiera się w przeglądarce. Ten sam widok (bez nagłówka dokumentu) trafia do
wyniki/podglad_fragment.html – z niego publikowany jest podgląd w projekcie.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import scout_config as config

TYPE_LABEL = {
    "BRAK_STRONY": "Brak strony",
    "TYLKO_SOCIAL": "Tylko social/portal",
    "STRONA_NIE_DZIALA": "Strona nie działa",
    "SLABA_STRONA": "Słaba strona",
    "OK": "Strona OK",
}


def _slim(d: dict, sent: dict | None = None, replies: dict | None = None) -> dict:
    """Tylko to, co potrzebne na stronie (pełne dane zostają w podglad.json)."""
    b, a = d.get("business") or {}, d.get("audit") or {}
    emails = list(dict.fromkeys((b.get("emails") or []) + (a.get("emails") or [])))
    low = [e.lower() for e in emails]
    wys = next((sent[e] for e in low if sent and e in sent), "")
    odp = next((replies[e] for e in low if replies and e in replies), None)
    return {
        "s": d.get("score", 0), "t": d.get("tier", "C"), "typ": d.get("lead_type", ""),
        "n": b.get("name", ""), "br": b.get("category", ""), "m": b.get("city", ""), "adr": b.get("address", ""),
        "tel": b.get("phone", ""), "www": b.get("website", ""), "mapa": b.get("maps_url", ""),
        "mail": emails[:3], "soc": (b.get("socials") or [])[:4], "inne": (b.get("other_contacts") or [])[:4],
        "ocena": b.get("rating"), "opinie": b.get("reviews"), "wl": b.get("owner_name", ""),
        "pow": (d.get("reasons") or [])[:6], "zd": d.get("pitch", ""), "karta": d.get("karta", ""),
        "k": d.get("_klucz", ""), "kiedy": d.get("_znaleziono", ""), "zad": d.get("_zadanie", ""),
        "wys": wys, "odp": odp,
        "ist": (b.get("profile") or {}).get("istnieje", ""), "dow": ((b.get("profile") or {}).get("istnieje_dowody") or [])[:3],
    }


def build(data: dict, queue: dict, sent: dict | None = None, replies: dict | None = None) -> str:
    """Fragment strony (bez <html>/<head>/<body>). sent: e-mail -> data wysyłki, replies: e-mail -> odpowiedź."""
    leads = [_slim(x, sent, replies) for x in data.get("leady", [])]
    jobs = [{"m": z["miasto"], "b": z["branza"], "o": z.get("ostatnio") or "", "n": z.get("nowych", 0)}
            for z in queue.get("zadania", [])]
    payload = json.dumps({"leady": leads, "zadania": jobs, "akt": data.get("aktualizacja", ""),
                          "nast": queue.get("nastepne") or "", "typy": TYPE_LABEL,
                          "hist": queue.get("historia", [])[:15]},
                         ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload).replace("__AKT__", html.escape(data.get("aktualizacja", "") or "—"))


def write(out_dir: Path | None = None) -> Path:
    from . import autopilot

    out_dir = out_dir or config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    data = autopilot._read(autopilot.PREVIEW, {"leady": []})
    from . import outreach

    sent = {x["email"].lower(): x.get("t", "")[:10] for x in outreach._read(outreach.SENT, []) if x.get("status") == "sent"}
    replies = {r["email"].lower(): {"data": r.get("data", ""), "stop": r.get("stop", False), "tresc": r.get("tresc", "")[:200]}
               for r in outreach.replies()}
    frag = build(data, autopilot.status(), sent, replies)
    (out_dir / "podglad_fragment.html").write_text(frag, encoding="utf-8")
    page = out_dir / "podglad.html"
    page.write_text("<!doctype html><html lang=pl><head><meta charset=utf-8>"
                    "<meta name=viewport content=\"width=device-width,initial-scale=1,viewport-fit=cover\"></head><body>"
                    + frag + "</body></html>", encoding="utf-8")
    return page


TEMPLATE = r"""<title>SCOUT Leady</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Układ: styl „Biura agentów AI” – nagłówek sekcji RESEARCH / ANALIZA, liczniki jak w górnym pasku panelu, zakładki, karty firm. Jeden ciemny motyw, jak panel. */
:root{
  color-scheme:dark;
  --bg:#060b0a;--panel:#0b1412;--panel-2:#0f1b18;--line:#18302a;--ink:#d5e6df;--muted:#7a948b;
  --accent:#3ee08f;--accent-soft:#0f3324;--a:#3ee08f;--b:#f0b13c;--c:#7f938c;--warn:#ff7b62;--info:#5cc8ff;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Consolas,monospace;
  --disp:"Chakra Petch","Segoe UI",system-ui,sans-serif;
}
body{background:var(--bg);background-image:linear-gradient(rgba(62,224,143,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(62,224,143,.025) 1px,transparent 1px);background-size:28px 28px;color:var(--ink);font:14px/1.5 var(--sans);margin:0}
.wrap{max-width:1180px;margin:0 auto;padding-block:18px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 24px;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 18px;background-image:linear-gradient(90deg,rgba(62,224,143,.12),transparent 60%)}
.brand{display:flex;align-items:center;gap:14px;min-width:0}
.hex{width:34px;height:38px;flex:none;background:var(--accent-soft);clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%);display:grid;place-items:center}
.hex::after{content:"";width:12px;height:12px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
h1{font:600 20px/1.2 var(--disp);letter-spacing:.32em;text-transform:uppercase;margin:0;text-wrap:balance}
h1 span{color:var(--accent)}
.kicker{font:500 11px var(--mono);letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.meta{color:var(--muted);font:500 12px var(--mono);letter-spacing:.06em}
header .meta b{color:var(--accent)}
.filters{display:grid;grid-template-columns:2fr 1fr 1fr 1.4fr;gap:8px;margin-bottom:8px}
.filters input,.filters select{font:500 13px var(--mono);letter-spacing:.04em;padding:9px 10px;border:1px solid var(--line);border-radius:3px;background:var(--panel);color:var(--ink);min-width:0}
.filters input::placeholder{color:var(--muted)}
.count{color:var(--muted);font:500 12px var(--mono);letter-spacing:.08em;text-transform:uppercase;margin:6px 0 12px}
.list{display:flex;flex-direction:column;gap:10px}
.lead{overflow-wrap:anywhere;display:grid;grid-template-columns:64px minmax(0,1fr) minmax(0,280px);gap:16px;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
.lead:hover{border-color:#24493d}
.score{font:700 26px/1 var(--disp);text-align:center;font-variant-numeric:tabular-nums}
.score small{display:block;font:600 11px var(--mono);letter-spacing:.2em;margin-top:6px}
.tA{color:var(--a);text-shadow:0 0 12px rgba(62,224,143,.35)}.tB{color:var(--b)}.tC{color:var(--c)}
.name{font:600 15px var(--disp);letter-spacing:.14em;text-transform:uppercase}
.sub{color:var(--muted);font-size:13px}
.chip{display:inline-block;font:600 11px var(--mono);letter-spacing:.12em;text-transform:uppercase;padding:2px 8px;border-radius:2px;background:var(--accent-soft);color:var(--accent);border:1px solid #1d5a40;margin:8px 6px 0 0}
.chip.BRAK_STRONY,.chip.STRONA_NIE_DZIALA{background:rgba(255,123,98,.08);border-color:rgba(255,123,98,.5);color:var(--warn)}
ul{margin:8px 0 0;padding-left:18px;font-size:13.5px}
.pitch{font-style:italic;color:var(--muted);margin:8px 0 0;font-size:13.5px}
.contact{font-size:13.5px;display:flex;flex-direction:column;gap:4px;min-width:0}
.contact a{color:var(--info);overflow-wrap:anywhere}
.tel{font:600 15px var(--mono);user-select:all;color:var(--accent)}
.mail{font-family:var(--mono);font-size:13px;overflow-wrap:anywhere;user-select:all}
.none{color:var(--muted);font:500 12px var(--mono);text-transform:uppercase;letter-spacing:.08em}
details{margin-top:8px}
summary{cursor:pointer;color:var(--accent);font:600 12px var(--mono);letter-spacing:.12em;text-transform:uppercase}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12.5px/1.55 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:3px;padding:10px;margin:8px 0 0;overflow-x:auto}
button.copy{font:600 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--line);background:var(--panel-2);color:var(--ink);border-radius:2px;padding:4px 9px;cursor:pointer;margin-top:6px}
button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.alive{font-size:13px;margin-top:8px;color:var(--muted)}.alive b{font:600 11px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--a);border:1px solid #1d5a40;background:var(--accent-soft);padding:1px 7px;border-radius:2px;margin-right:6px}
.alive.unsure b{color:var(--b);border-color:rgba(240,177,60,.45);background:rgba(240,177,60,.08)}
.toggle{display:flex;align-items:center;gap:8px;font:500 12px var(--mono);letter-spacing:.06em;color:var(--muted);margin:4px 0 8px;cursor:pointer;width:fit-content}
.toggle input{accent-color:var(--accent)}
.work{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0 16px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:10px 14px;display:flex;flex-direction:column;min-width:0}
.tile span{font:500 10.5px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.2em}
.tile b{font:600 30px/1.15 var(--disp);font-variant-numeric:tabular-nums;color:var(--ink)}
.tile:first-child b{color:var(--accent);text-shadow:0 0 14px rgba(62,224,143,.35)}.tile:nth-child(3) b{color:var(--b)}
.tile small{color:var(--muted);font:500 11px var(--mono);letter-spacing:.04em}
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 12px;border-bottom:1px solid var(--line)}
.tab{font:600 12px var(--disp);letter-spacing:.2em;text-transform:uppercase;background:none;border:0;border-bottom:2px solid transparent;color:var(--muted);padding:9px 12px;cursor:pointer}
.tab b{font:600 11px var(--mono);margin-left:6px;padding:1px 6px;border:1px solid var(--line);border-radius:2px}
.tab[aria-pressed="true"]{color:var(--accent);border-bottom-color:var(--accent)}.tab[aria-pressed="true"] b{border-color:#1d5a40;background:var(--accent-soft)}
.new{display:inline-block;font:700 10px var(--mono);text-transform:uppercase;letter-spacing:.14em;background:var(--accent);color:#04120b;border-radius:2px;padding:1px 6px;vertical-align:2px;box-shadow:0 0 8px rgba(62,224,143,.45)}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.act{font:600 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--line);background:var(--panel-2);color:var(--ink);border-radius:2px;padding:5px 9px;cursor:pointer}
.act:hover{border-color:var(--accent);color:var(--accent)}.act.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}.act.undo{color:var(--muted)}
.mailinfo{margin-top:8px;font:600 12px var(--mono);letter-spacing:.04em;color:var(--info)}.mailinfo.reply{color:var(--a)}.mailinfo.stop{color:var(--warn)}
.who{display:flex;align-items:center;gap:8px;font:500 12px var(--mono);color:var(--muted);margin:0 0 10px}.who input{font:500 13px var(--mono);padding:6px 8px;border:1px solid var(--line);border-radius:3px;background:var(--panel);color:var(--ink);width:160px}
.status{margin-top:8px;font:600 12px var(--mono);letter-spacing:.06em;color:var(--b)}
.note{font:500 12px var(--mono);color:var(--warn);margin:0 0 8px}
details.legend{font-size:13px;color:var(--muted);margin:2px 0 8px;max-width:95ch}details.legend p{margin:6px 0}details.legend b{color:var(--ink)}details.legend b.tA{color:var(--a)}details.legend b.tB{color:var(--b)}details.legend b.tC{color:var(--c)}
.found{font:500 11px var(--mono);letter-spacing:.04em;color:var(--muted);margin-top:8px}
.queue{margin-top:28px;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
.queue h2{font:600 13px var(--disp);letter-spacing:.28em;text-transform:uppercase;margin:0 0 6px;color:var(--accent)}
.qwrap{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;width:100%;font:500 12px var(--mono)}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:10.5px;letter-spacing:.18em}
td.num{font-variant-numeric:tabular-nums;color:var(--accent)}
.empty{background:var(--panel);border:1px dashed var(--line);border-radius:4px;padding:24px;color:var(--muted);font:500 12px var(--mono);letter-spacing:.12em;text-transform:uppercase;text-align:center}
@media (max-width:760px){
  h1{font-size:16px;letter-spacing:.22em}
  .work{grid-template-columns:1fr 1fr}
  .filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}
  .lead{grid-template-columns:52px minmax(0,1fr)}.contact{grid-column:1/-1}
}
@media (prefers-reduced-motion:no-preference){.lead,.act,.tab{transition:border-color .15s,color .15s}}
</style>
<div class="wrap">
<header><div class="brand"><div class="hex" aria-hidden="true"></div><div><h1><span>SCOUT</span> · łowca klientów</h1>
<div class="kicker">Research / analiza // lista do obdzwonienia</div></div></div><div class="meta"><b>● Autopilot</b> · ostatnia praca: __AKT__</div></header>
<section class="work" id="work"></section>
<nav class="tabs" id="tabs" aria-label="Widok"></nav>
<div class="filters">
  <input id="q" type="search" placeholder="Szukaj: nazwa, ulica, telefon…" aria-label="Szukaj">
  <select id="fm" aria-label="Miasto"></select>
  <select id="fb" aria-label="Branża"></select>
  <select id="ft" aria-label="Priorytet"><option value="">Priorytet: wszystkie</option><option value="A">A – najlepsze, dzwoń najpierw</option><option value="B">B – dobre, czegoś brakuje</option><option value="C">C – słabsze, na koniec</option></select>
</div>
<details class="legend"><summary>Jak czytać kartę i jak pracować z listą</summary>
<p>Liczba po lewej to wynik 0–100: jak bardzo firmie przyda się nowa strona i jak łatwo się z nią skontaktować. Litera to priorytet:
<b class="tA">A</b> (75–100) brak strony lub martwa strona, jest telefon – dzwoń najpierw; <b class="tB">B</b> (55–74) dobra okazja, ale czegoś brakuje, najczęściej telefonu;
<b class="tC">C</b> (poniżej 55) strona jest, tylko słabsza.</p>
<p>Po rozmowie kliknij przy firmie, jak poszło. Firma znika z „Do zrobienia” i trafia do „W toku” albo „Zakończone” – u wszystkich, którzy mają ten link.
„Nowe” to firmy, które bot znalazł od Twojej ostatniej wizyty.</p></details>
<label class="toggle"><input type="checkbox" id="fu"> <span id="fu-label">Pokaż też firmy bez potwierdzenia, że działają</span></label>
<div class="count" id="count"></div>
<div class="note" id="dbnote" hidden></div>
<label class="who" id="who" hidden>Twoje imię (widoczne przy statusach): <input id="whoname" maxlength="40" placeholder="np. Kuba"></label>
<div class="list" id="list"></div>
<section class="queue"><h2>Co bot robi</h2><div class="meta" id="next"></div><div class="qwrap"><table id="hist"></table></div></section>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById("data").textContent);
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ACT={oddzwonic:["Oddzwonić","W toku"],nie_odbiera:["Nie odbiera","W toku"],spotkanie:["Umówione spotkanie","W toku"],
  klient:["Nowy klient!","Zakończone"],nie:["Nie zainteresowani","Zakończone"],zamknieta:["Firma nie działa","Zakończone"]};
let tab="todo", st={}, db=null, user=null, names={};
let lastVisit="";
try{lastVisit=localStorage.getItem("scout_ost_wizyta")||""}catch(e){}
try{localStorage.setItem("scout_ost_wizyta",D.akt)}catch(e){}
const isNew=l=>lastVisit?l.kiedy>lastVisit:l.kiedy.slice(0,10)===D.akt.slice(0,10);
const ok=l=>l.ist==="potwierdzona";
const docId=k=>String(k||"").toLowerCase().replace(/[^a-z0-9]/g,"").slice(0,120)||"x";
const stOf=l=>st[docId(l.k)];
const group=l=>{const s=stOf(l);return s?ACT[s.s]?.[1]||"W toku":"Do zrobienia"};
const TABS=[["todo","Do zrobienia"],["new","Nowe"],["doing","W toku"],["done","Zakończone"]];
const inTab=(l,t)=>t==="todo"?group(l)==="Do zrobienia":t==="new"?group(l)==="Do zrobienia"&&isNew(l):t==="doing"?group(l)==="W toku":group(l)==="Zakończone";
const pool=()=>$("fu").checked?D.leady:D.leady.filter(ok);
const opts=(el,label,vals)=>{el.innerHTML=`<option value="">${label}</option>`+[...new Set(vals)].filter(Boolean).sort((a,b)=>a.localeCompare(b,"pl")).map(v=>`<option>${esc(v)}</option>`).join("")};
opts($("fm"),"Każde miasto",D.leady.map(l=>l.m));
opts($("fb"),"Każda branża",D.leady.map(l=>l.br));
function work(){
  const P=pool(),today=D.akt.slice(0,10),h=D.hist[0];
  const foundToday=D.leady.filter(l=>l.kiedy.slice(0,10)===today&&ok(l)).length;
  const d0=new Date(),loc=`${d0.getFullYear()}-${String(d0.getMonth()+1).padStart(2,"0")}-${String(d0.getDate()).padStart(2,"0")}`;
  const handledToday=Object.values(st).filter(s=>{try{const d=new Date(s.t);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`===loc}catch(e){return false}}).length;
  $("work").innerHTML=[
    ["Do zrobienia",P.filter(l=>inTab(l,"todo")).length,"firm czeka na telefon"],
    ["Nowe",P.filter(l=>inTab(l,"new")).length,lastVisit?"od Twojej ostatniej wizyty":"z ostatniego przebiegu"],
    ["Bot dziś",foundToday,`nowych firm (${today})`],
    ["Obdzwonione dziś",handledToday,db?"przez zespół":"zapis statusów niedostępny"]
  ].map(([a,b,c])=>`<div class="tile"><span>${a}</span><b>${b}</b><small>${esc(c)}</small></div>`).join("");
}
function tabs(){
  const P=pool();
  $("tabs").innerHTML=TABS.map(([k,l])=>`<button class="tab" data-k="${k}" aria-pressed="${tab===k}">${l} <b>${P.filter(x=>inTab(x,k)).length}</b></button>`).join("");
  $("tabs").querySelectorAll("button").forEach(b=>b.onclick=()=>{tab=b.dataset.k;tabs();render()});
}
function link(u,label){return `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(label)}</a>`}
function host(u){try{return new URL(u).hostname.replace(/^www\./,"")}catch(e){return u}}
function when(t){try{return new Date(t).toLocaleString("pl-PL",{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}catch(e){return t}}
function card(l,i){
  const c=[];
  c.push(l.tel?`<span class="tel">${esc(l.tel)}</span>`:`<span class="none">brak telefonu</span>`);
  l.mail.forEach(m=>c.push(`<span class="mail">${esc(m)}</span>`));
  if(l.www)c.push(link(l.www,host(l.www)));
  l.soc.forEach(u=>c.push(link(u,host(u))));
  l.inne.forEach(x=>{const [n,u]=x.split(": ");if(u&&u.startsWith("http"))c.push(link(u,n));});
  if(l.mapa)c.push(link(l.mapa,"Mapa"));
  if(l.wl)c.push(`<span class="sub">Właściciel: ${esc(l.wl)}</span>`);
  const rating=l.ocena?` · ${l.ocena}★${l.opinie?` (${l.opinie})`:""}`:"";
  const s=stOf(l);
  const status=s?`<div class="status">${esc(ACT[s.s]?.[0]||s.s)} · ${esc(names[s.kto]||"ktoś z zespołu")} · ${esc(when(s.t))}</div>`:"";
  const acts=db?`<div class="acts">${Object.entries(ACT).map(([k,[lab]])=>`<button class="act${s&&s.s===k?" on":""}" data-i="${i}" data-a="${k}">${lab}</button>`).join("")}${s?`<button class="act undo" data-i="${i}" data-a="">Cofnij do „Do zrobienia”</button>`:""}</div>`:"";
  return `<article class="lead"><div class="score t${esc(l.t)}">${l.s}<small>${esc(l.t)}</small></div>
  <div style="min-width:0"><div class="name">${isNew(l)?'<span class="new">Nowe</span> ':''}${esc(l.n)}</div><div class="sub">${esc(l.br)} · ${esc(l.adr||l.m)}${rating}</div>
  <span class="chip ${esc(l.typ)}">${esc(D.typy[l.typ]||l.typ)}</span>
  ${l.ist?`<div class="alive ${ok(l)?"":"unsure"}"><b>${ok(l)?"Firma działa":"Nie potwierdzono, że działa"}</b> · ${esc(l.dow.join(" · "))}</div>`:`<div class="alive unsure"><b>Jeszcze nie sprawdzono, czy działa</b></div>`}
  <ul>${l.pow.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>${l.zd?`<p class="pitch">${esc(l.zd)}</p>`:""}
  ${l.karta?`<details><summary>Karta rozmowy</summary><pre id="k${i}">${esc(l.karta)}</pre><button class="copy" data-k="k${i}">Kopiuj kartę</button></details>`:""}
  ${l.wys?`<div class="mailinfo">Bot wysłał maila ${esc(l.wys)}</div>`:""}
  ${l.odp?`<div class="mailinfo ${l.odp.stop?"stop":"reply"}">${l.odp.stop?"Firma odpisała STOP – bot już nie napisze":"Firma odpisała! Sprawdź skrzynkę"}${l.odp.tresc?` · „${esc(l.odp.tresc.slice(0,120))}”`:""}</div>`:""}
  ${status}${acts}
  <div class="found">Znaleziono ${esc(l.kiedy)} · ${esc(l.zad)}</div></div>
  <div class="contact">${c.join("")}</div></article>`;
}
let shown=[];
function render(){
  const q=$("q").value.trim().toLowerCase(),m=$("fm").value,b=$("fb").value,t=$("ft").value;
  shown=pool().filter(l=>inTab(l,tab)&&(!m||l.m===m)&&(!b||l.br===b)&&(!t||l.t===t)&&
    (!q||[l.n,l.adr,l.tel,l.mail.join(" "),l.br,l.m].join(" ").toLowerCase().includes(q)));
  if(tab==="todo"||tab==="new")shown.sort((x,y)=>(isNew(y)-isNew(x))||(y.s-x.s));
  else shown.sort((x,y)=>(stOf(y)?.t||"").localeCompare(stOf(x)?.t||""));
  $("count").textContent=`${shown.length} firm`+(shown.length>200?" (pokazuję pierwsze 200)":"");
  const empty={todo:"Wszystko obdzwonione. Bot dorzuci nowe firmy przy kolejnym przebiegu.",new:"Nic nowego od ostatniej wizyty. Bot pracuje 3 razy dziennie.",
    doing:"Tu trafią firmy oznaczone jako „Oddzwonić”, „Nie odbiera” albo „Umówione spotkanie”.",done:"Tu trafią firmy zamknięte: nowi klienci, odmowy i firmy, które nie działają."}[tab];
  $("list").innerHTML=shown.slice(0,200).map(l=>card(l,D.leady.indexOf(l))).join("")||`<div class="empty">${D.leady.length?empty:"Bot jeszcze nic nie znalazł."}</div>`;
  $("list").querySelectorAll("button.copy").forEach(btn=>btn.onclick=()=>{
    const el=$(btn.dataset.k),txt=el.textContent;
    try{navigator.clipboard.writeText(txt).then(()=>{btn.textContent="Skopiowano"},()=>{sel(el);btn.textContent="Zaznaczono, Ctrl+C"})}catch(e){sel(el)}
  });
  $("list").querySelectorAll("button.act").forEach(btn=>btn.onclick=()=>mark(D.leady[+btn.dataset.i],btn.dataset.a,btn));
}
async function mark(l,a,btn){
  if(!db)return;
  btn.disabled=true;
  try{
    if(db.server){
      const kto=($("whoname").value||"").trim();
      const r=a?await fetch("/api/scout/statusy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({klucz:l.k,status:a,kto,firma:l.n,miasto:l.m})})
               :await fetch("/api/scout/statusy/"+encodeURIComponent(docId(l.k)),{method:"DELETE"});
      if(!r.ok)throw new Error(r.status);
      setServer(await r.json());return;
    }
    const ref=db.collection("statusy").doc(docId(l.k));
    if(!a)await ref.delete();
    else await ref.set({s:a,t:new Date().toISOString(),kto:user?await user.id():"",firma:l.n,miasto:l.m});
  }catch(e){
    btn.disabled=false;
    $("dbnote").hidden=false;
    $("dbnote").textContent=e&&e.code==="not_granted"?"Nie możesz zapisywać statusów – poproś właściciela o dostęp „może edytować”.":"Nie udało się zapisać statusu. Spróbuj ponownie.";
  }
}
function sel(el){const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r)}
function all(){work();tabs();render()}
["q","fm","fb","ft"].forEach(id=>$(id).addEventListener("input",render));
$("fu").addEventListener("change",all);
$("fu-label").textContent=`Pokaż też firmy bez potwierdzenia, że działają (${D.leady.filter(l=>!ok(l)).length})`;
$("next").textContent=(D.nast?`Następne zadanie: ${D.nast}. `:"")+"Bot szuka nowych firm 3 razy dziennie (7:47, 12:47, 17:47) i sprawdza, czy działają.";
$("hist").innerHTML=`<tr><th>Kiedy</th><th>Miasto</th><th>Branża</th><th>Nowych firm</th></tr>`+
  (D.hist.map(h=>`<tr><td>${esc(h.data)} ${esc(h.czas)}</td><td>${esc(h.miasto)}</td><td>${esc(h.branza)}</td><td class="num">${h.blad?"błąd":h.nowych}</td></tr>`).join("")||`<tr><td colspan="4">Jeszcze bez przebiegów.</td></tr>`);
all();
function setServer(data){st={};Object.entries(data||{}).forEach(([k,v])=>{st[k]=v;if(v.kto)names[v.kto]=v.kto});all()}
async function serverMode(){
  // SCOUT na własnym serwerze (server.py / panel): statusy w data/statusy.json, odświeżane co 30 s
  try{const r=await fetch("/api/scout/statusy");if(!r.ok)return false;db={server:true};setServer(await r.json())}catch(e){return false}
  $("who").hidden=false;
  try{$("whoname").value=localStorage.getItem("scout_imie")||""}catch(e){}
  $("whoname").addEventListener("change",()=>{try{localStorage.setItem("scout_imie",$("whoname").value.trim())}catch(e){}});
  setInterval(async()=>{try{const r=await fetch("/api/scout/statusy");if(r.ok)setServer(await r.json())}catch(e){}},30000);
  return true;
}
(async()=>{
  if(location.protocol.startsWith("http")&&!(window.claude&&window.claude.use)){if(await serverMode())return}
  if(!window.claude||!window.claude.use){$("dbnote").hidden=false;$("dbnote").textContent="Statusy rozmów działają w podglądzie w claude.ai albo po uruchomieniu SCOUT-a na serwerze (python server.py, adres /podglad).";return}
  try{db=await window.claude.use("db");user=await window.claude.use("user")}catch(e){db=null}
  if(!db){if(await serverMode())return;$("dbnote").hidden=false;$("dbnote").textContent="Statusy rozmów są dostępne po zalogowaniu w claude.ai.";return}
  db.collection("statusy").onSnapshot(async snap=>{
    st={};snap.docs.forEach(d=>{st[d.id]=d.data()||{}});
    const ids=[...new Set(Object.values(st).map(s=>s.kto).filter(Boolean))];
    if(user&&ids.length){try{const ps=await user.profiles(ids);ids.forEach(id=>{names[id]=(ps[id]&&ps[id].name)||""})}catch(e){}}
    all();
  },e=>{$("dbnote").hidden=false;$("dbnote").textContent="Nie udało się wczytać statusów rozmów."});
})();
})();
</script>
"""
