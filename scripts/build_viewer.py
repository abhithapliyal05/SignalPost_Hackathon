#!/usr/bin/env python3
"""Build a single-file HTML viewer for a run: search, filter, compare and verify every fact.

Reads the profiles JSONL from scripts/run_competition_batch.py and writes one self-contained HTML
file (no external scripts, styles or fonts). Each fact links to its source and shows when it was
retrieved; missing families are shown as unknown with the reason. Works on desktop and mobile.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _src(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {"url": record.get("source_url"), "at": record.get("retrieved_at"), "status": record.get("status"), "note": record.get("note")}


def compact(profile: dict[str, Any]) -> dict[str, Any]:
    ev = profile.get("evidence", {})
    live = (ev.get("registry_live") or {}).get("value") or {}
    accounts = sorted(((ev.get("financials") or {}).get("value") or {}).get("records") or [], key=lambda row: str((row.get("period") or {}).get("tilDato")))
    site = ev.get("website") or {}
    site_value = site.get("value") or {}
    published_site = site.get("status") == "available" and (site_value.get("identity_assessment") or {}).get("publishable")
    roles = [row for row in ((ev.get("roles") or {}).get("value") or {}).get("roles") or [] if not row.get("inactive")]
    summary = (ev.get("summary") or {}).get("value") or {}
    return {
        "org": profile["organisation_number"],
        "name": profile.get("name"),
        "form": profile.get("legal_form"),
        "town": profile.get("municipality"),
        "industry": profile.get("industry_label") or (live.get("industry") or {}).get("beskrivelse"),
        "employees": live.get("employees", profile.get("employees")),
        "summary": summary.get("sentences") or [],
        "unknowns": summary.get("unknowns") or [],
        "accounts": [{"end": (row.get("period") or {}).get("tilDato"), "revenue": row.get("revenue"), "result": row.get("annual_result"), "equity": row.get("equity")} for row in accounts],
        "accounts_src": _src(ev.get("financials")),
        "years": ((ev.get("financial_history") or {}).get("value") or {}).get("pdfs") or [],
        "years_src": _src(ev.get("financial_history")),
        "roles": [{"name": row.get("name"), "role": row.get("role")} for row in roles][:30],
        "roles_src": _src(ev.get("roles")),
        "workplaces": [{"name": row.get("name"), "town": (row.get("address") or {}).get("kommune"), "org": row.get("organisation_number")} for row in ((ev.get("locations") or {}).get("value") or {}).get("locations") or []][:30],
        "workplaces_src": _src(ev.get("locations")),
        "website": site_value.get("final_url") if published_site else None,
        "website_why": (site_value.get("identity_assessment") or {}).get("reasons") if published_site else None,
        "website_src": _src(site),
        "social": site_value.get("social_links") if published_site else [],
        "jobs": [{"title": ad.get("title"), "url": ad.get("ad_url") or ad.get("detail_url"), "published": ad.get("published")} for ad in ((ev.get("jobs") or {}).get("value") or {}).get("active_ads") or []],
        "jobs_src": _src(ev.get("jobs")),
        "posts": ((ev.get("company_posts") or {}).get("value") or {}).get("posts") or [],
        "posts_src": _src(ev.get("company_posts")),
        "events": (((ev.get("official_timeline") or {}).get("value") or {}).get("events") or [])[:25],
    }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fjordlight company profiles</title>
<style>
:root{--bg:#fbfaf7;--fg:#1c1f23;--muted:#5f6670;--line:#e3e0d8;--card:#fff;--accent:#1d5f8a;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#e8e6e1;--muted:#9aa1aa;--line:#2c3137;--card:#1b1f23;--accent:#7cb8e0;--warn:#e0b45c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2}
h1{font-size:18px;margin:0 0 8px}input,select,button{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.controls{display:flex;flex-wrap:wrap;gap:8px}.controls input{flex:1 1 220px}.controls select{max-width:100%;min-width:0}
main{display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:0;min-height:calc(100vh - 100px)}
#list{border-right:1px solid var(--line);overflow:auto;max-height:calc(100vh - 100px)}
.row{padding:10px 16px;border-bottom:1px solid var(--line);cursor:pointer}.row:hover,.row.sel{background:var(--card)}
.row b{display:block}.row small{color:var(--muted)}
#detail{padding:16px 20px;overflow:auto;max-height:calc(100vh - 100px)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 12px}
section h3{margin:0 0 6px;font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.src{font-size:12px;color:var(--muted)}a{color:var(--accent)}.unk{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:999px;padding:0 8px;margin:2px 4px 2px 0}
@media (max-width:760px){main{grid-template-columns:1fr;min-height:0}.controls select{flex:1 1 100%}#list{max-height:40vh;border-right:0;border-bottom:1px solid var(--line)}#detail{max-height:none}}
</style></head><body>
<header><h1>Fjordlight · __COUNT__ company profiles</h1>
<div class="controls"><input id="q" type="search" placeholder="Search name, org. number, town or industry" aria-label="Search">
<select id="f" aria-label="Filter"><option value="">All companies</option><option value="website">With verified website</option><option value="jobs">With job ads</option><option value="posts">With dated posts</option><option value="social">With social profiles</option></select>
<select id="cmp" aria-label="Compare with"><option value="">Compare with…</option></select></div></header>
<main><nav id="list" aria-label="Companies"></nav><div id="detail"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nok=v=>v==null?'—':new Intl.NumberFormat('nb-NO',{maximumFractionDigits:0}).format(v);
const src=s=>s&&s.url?`<div class="src">Source: <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url.replace(/^https?:\\/\\//,'').slice(0,70))}</a>${s.at?' · retrieved '+esc(s.at.slice(0,16).replace('T',' ')):''}</div>`:'';
const link=(u,t)=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t||u)}</a>`;
let sel=null,cmp=null;
function card(c){
 const unk=f=>c.unknowns.filter(u=>u.field===f).map(u=>`<p class="unk">Unknown: ${esc(u.text)}</p>`).join('');
 let h=`<h2 style="margin:0">${esc(c.name)}</h2><p class="src">Org. no. ${esc(c.org)} · ${esc(c.form)} · ${esc(c.town||'')} · ${esc(c.industry||'')}${c.employees!=null?' · '+esc(c.employees)+' employees':''}</p>`;
 h+=`<section><h3>Summary</h3>${c.summary.map(s=>`<p>${esc(s.text)} ${s.sources.map((u,i)=>`<a class="src" href="${esc(u)}" target="_blank" rel="noopener">[${i+1}]</a>`).join(' ')}</p>`).join('')}${c.unknowns.length?'<p class="unk">'+c.unknowns.map(u=>esc(u.text)).join(' ')+'</p>':''}</section>`;
 h+=`<section><h3>Annual accounts (NOK)</h3>${c.accounts.length?`<table><tr><th>Period end</th><th>Revenue</th><th>Result</th><th>Equity</th></tr>${c.accounts.map(a=>`<tr><td>${esc(a.end)}</td><td class="n">${nok(a.revenue)}</td><td class="n">${nok(a.result)}</td><td class="n">${nok(a.equity)}</td></tr>`).join('')}</table>`:'<p class="unk">No normalized accounts returned.</p>'}${src(c.accounts_src)}
 ${c.years.length?`<p>Filed copies: ${c.years.slice(0,12).map(y=>link(y.url,y.year)).join(' ')}</p>${src(c.years_src)}`:''}</section>`;
 h+=`<section><h3>People and workplaces</h3>${c.roles.map(r=>`<span class="badge">${esc(r.role)}: ${esc(r.name)}</span>`).join('')}${src(c.roles_src)}
 ${c.workplaces.length?`<p>${c.workplaces.map(w=>`<span class="badge">${esc(w.name)} · ${esc(w.town||'')}</span>`).join('')}</p>${src(c.workplaces_src)}`:''}</section>`;
 h+=`<section><h3>Website and profiles</h3>${c.website?`<p>${link(c.website)}</p><p class="src">Why verified: ${esc((c.website_why||[]).join('; '))}</p>${src(c.website_src)}${c.social.length?'<p>'+c.social.map(s=>`<span class="badge">${link(s.url,s.platform)}</span>`).join('')+'</p>':''}`:unk('official_website')||'<p class="unk">Not verified.</p>'}</section>`;
 h+=`<section><h3>Hiring and dated activity</h3>${c.jobs.length?'<p><b>Job ads (NAV)</b></p><ul>'+c.jobs.map(j=>`<li>${esc((j.published||'').slice(0,10))} ${link(j.url,j.title)}</li>`).join('')+'</ul>'+src(c.jobs_src):unk('hiring')}
 ${c.posts.length?'<p><b>Website posts</b></p><ul>'+c.posts.slice(0,10).map(p=>`<li>${esc(p.published_at.slice(0,10))} ${link(p.url,p.title)}</li>`).join('')+'</ul>'+src(c.posts_src):''}
 ${c.events.length?'<details><summary>Official register timeline ('+c.events.length+')</summary><ul>'+c.events.map(e=>`<li>${esc(e.date)} · ${esc(e.event)} <a class="src" href="${esc(e.source_url)}" target="_blank" rel="noopener">source</a></li>`).join('')+'</ul></details>':''}</section>`;
 return h}
function show(){const a=D.find(c=>c.org===sel),b=D.find(c=>c.org===cmp);if(!a){$('#detail').innerHTML='<p>Select a company.</p>';return}
 $('#detail').innerHTML=b&&b!==a?`<div class="cols"><div>${card(a)}</div><div>${card(b)}</div></div>`:card(a);
 document.querySelectorAll('.row').forEach(r=>r.classList.toggle('sel',r.dataset.org===sel));history.replaceState(null,'','#'+sel+(cmp?','+cmp:''))}
function list(){const q=$('#q').value.trim().toLowerCase(),f=$('#f').value;
 const rows=D.filter(c=>(!q||[c.name,c.org,c.town,c.industry].join(' ').toLowerCase().includes(q))&&(!f||(f==='website'?c.website:f==='jobs'?c.jobs.length:f==='posts'?c.posts.length:c.social.length)));
 $('#list').innerHTML=rows.slice(0,400).map(c=>`<div class="row" tabindex="0" data-org="${c.org}"><b>${esc(c.name)}</b><small>${esc(c.org)} · ${esc(c.town||'')}${c.website?' · web':''}${c.jobs.length?' · jobs':''}</small></div>`).join('')+(rows.length>400?`<p class="src" style="padding:8px 16px">${rows.length-400} more, refine the search</p>`:'');
 document.querySelectorAll('.row').forEach(r=>{r.onclick=()=>{sel=r.dataset.org;show()};r.onkeydown=e=>{if(e.key==='Enter'){sel=r.dataset.org;show()}}})}
$('#cmp').innerHTML+=D.map(c=>`<option value="${c.org}">${esc(c.name)}</option>`).join('');
$('#q').oninput=list;$('#f').onchange=list;$('#cmp').onchange=e=>{cmp=e.target.value||null;show()};
const h=location.hash.slice(1).split(',');sel=D.some(c=>c.org===h[0])?h[0]:D[0]?.org;cmp=D.some(c=>c.org===h[1])?h[1]:null;list();show();
</script></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    profiles = [json.loads(line) for line in Path(args.profiles).read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.dumps([compact(profile) for profile in profiles], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(PAGE.replace("__COUNT__", html.escape(str(len(profiles)))).replace("__DATA__", data), encoding="utf-8")
    print(f"viewer: {args.output} ({len(profiles)} companies)")


if __name__ == "__main__":
    main()
