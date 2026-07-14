#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE = 'https://diavgeia.gov.gr'
SEARCH = BASE + '/luminapi/opendata/search'
DETAIL = BASE + '/luminapi/api/decisions/{ada}'
DOC = BASE + '/doc/{ada}'
OUT = Path('unit-price-probe-output')
TERMS = ('γραβάτες','γραβάτα','φουλάρια','φουλάρι','κλιματιστικά','κλιματιστικό','air condition','αναμνηστικά','τιμητικές πλακέτες')
DATE_FROM = '2020-01-01'
DATE_TO = '2026-07-14'

MONEY = re.compile(r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)', re.I)
QTY = re.compile(r'(?<!\d)(\d{1,5})\s*(?:τεμ\.?|τμχ\.?|τεμάχια|τεμάχιο|μονάδες|μονάδα)', re.I)
UNIT = re.compile(r'(?:τιμ(?:ή|ης)\s*(?:ανά\s*)?(?:μονάδ(?:α|ας)|τεμάχιο|τεμ\.?|τμχ\.?)|τιμή\s*μονάδος)[^\d]{0,80}(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)', re.I)
BTU = re.compile(r'(\d{4,5})\s*(?:btu|btu/h)', re.I)


def fold(value: str) -> str:
    value = unicodedata.normalize('NFD', str(value or '').casefold())
    return ''.join(ch for ch in value if unicodedata.category(ch) != 'Mn')


def compact(value: Any, limit: int = 500) -> str:
    return ' '.join(str(value or '').split())[:limit]


def eur(raw: Any) -> float | None:
    text = str(raw or '').strip().replace(' ', '')
    if not text:
        return None
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 <= value <= 10_000_000 else None


def get(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, timeout: int = 55) -> requests.Response:
    last = None
    for attempt in range(5):
        try:
            response = session.get(url, params=params, timeout=timeout, allow_redirects=True)
            if response.status_code in {429,500,502,503,504}:
                time.sleep(min(16,2**attempt)); continue
            return response
        except requests.RequestException as exc:
            last = exc; time.sleep(min(16,2**attempt))
    raise RuntimeError(last)


def extract_pdf(data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix='unit-price-') as tmp:
        pdf = Path(tmp)/'a.pdf'; txt = Path(tmp)/'a.txt'
        pdf.write_bytes(data)
        run = subprocess.run(['pdftotext','-enc','UTF-8','-layout',str(pdf),str(txt)],capture_output=True,timeout=55)
        if run.returncode or not txt.exists(): return ''
        return txt.read_text(encoding='utf-8',errors='replace')[:220000]


def structured_amount(detail: dict[str, Any]) -> float | None:
    extra = detail.get('extraFieldValues') if isinstance(detail.get('extraFieldValues'),dict) else {}
    for key in ('awardAmount','amount','expenseAmount','budgetAmount'):
        value = extra.get(key)
        if isinstance(value,dict): value=value.get('amount')
        parsed=eur(value)
        if parsed is not None: return parsed
    return None


def category(text: str) -> str:
    f=fold(text)
    if 'γραβατ' in f: return 'tie'
    if 'φουλαρ' in f: return 'scarf'
    if 'κλιματισ' in f or 'air condition' in f: return 'air_conditioner'
    if 'πλακετ' in f: return 'plaque'
    if 'αναμνηστικ' in f: return 'souvenir'
    return 'other'


def search(session: requests.Session, term: str) -> list[dict[str,Any]]:
    out=[]
    for page in range(8):
        r=get(session,SEARCH,params={'page':page,'size':100,'term':term,'from_issue_date':DATE_FROM,'to_issue_date':DATE_TO})
        if not r.ok: break
        payload=r.json(); rows=payload.get('decisions') if isinstance(payload,dict) else None
        if not isinstance(rows,list) or not rows: break
        out.extend(x for x in rows if isinstance(x,dict))
        if len(rows)<100: break
        time.sleep(.25)
    return out


def inspect(session: requests.Session, row: dict[str,Any], retrieved: list[str]) -> dict[str,Any]:
    ada=str(row.get('ada') or '')
    d=get(session,DETAIL.format(ada=quote(ada,safe='')))
    detail=d.json() if d.ok else row
    if not isinstance(detail,dict): detail=row
    url=str(detail.get('documentUrl') or DOC.format(ada=quote(ada,safe='')))
    p=get(session,url,timeout=70)
    text=extract_pdf(p.content) if p.ok and 'pdf' in p.headers.get('content-type','').casefold() else ''
    joined='\n'.join([str(detail.get('subject') or ''),json.dumps(detail.get('extraFieldValues') or {},ensure_ascii=False,default=str),text])
    amounts=sorted({v for v in (eur(m.group(1)) for m in MONEY.finditer(joined)) if v is not None})
    quantities=sorted({int(m.group(1)) for m in QTY.finditer(joined) if 0<int(m.group(1))<=100000})
    explicit=sorted({v for v in (eur(m.group(1)) for m in UNIT.finditer(joined)) if v is not None})
    total=structured_amount(detail)
    derived=[]
    if total is not None:
        for q in quantities:
            value=round(total/q,2)
            if 1<=value<=100000: derived.append(value)
    btu=sorted(set(m.group(1) for m in BTU.finditer(joined)))
    lines=[]
    for raw_line in text.splitlines():
        f=fold(raw_line)
        if any(fold(term) in f for term in retrieved) and (MONEY.search(raw_line) or QTY.search(raw_line) or UNIT.search(raw_line)):
            lines.append(compact(raw_line,900))
        if len(lines)>=20: break
    return {'ada':ada,'url':url,'status':detail.get('status'),'private':detail.get('privateData'),'corrected':detail.get('correctedVersionId'),'organization_id':detail.get('organizationId'),'subject':compact(detail.get('subject'),900),'category':category(joined),'retrieved_by':retrieved,'structured_total':total,'amounts':amounts[:80],'quantities':quantities[:40],'explicit_unit_prices':explicit[:40],'derived_unit_prices':sorted(set(derived))[:40],'btu':btu[:20],'evidence_lines':lines,'pdf_text_length':len(text)}


def main() -> None:
    OUT.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers.update({'User-Agent':'MizAI official unit-price validation/1.0'})
    by_ada={}; terms_by_ada=defaultdict(set)
    for term in TERMS:
        for row in search(s,term):
            ada=str(row.get('ada') or '')
            if ada:
                by_ada.setdefault(ada,row); terms_by_ada[ada].add(term)
        time.sleep(.3)
    ranked=[]
    for ada,row in by_ada.items():
        subject=fold(str(row.get('subject') or ''))
        score=sum(15 for term in terms_by_ada[ada] if fold(term) in subject)
        if structured_amount(row) is not None: score+=10
        ranked.append((score,ada,row))
    ranked.sort(reverse=True)
    records=[]
    per_category=defaultdict(int)
    for _score,ada,row in ranked:
        cat=category(str(row.get('subject') or ''))
        if per_category[cat]>=45: continue
        try: records.append(inspect(s,row,sorted(terms_by_ada[ada])))
        except Exception as exc: records.append({'ada':ada,'error':type(exc).__name__,'message':str(exc)[:300]})
        per_category[cat]+=1
        if len(records)>=160: break
        time.sleep(.3)
    valid=[r for r in records if not r.get('error') and r.get('status')=='PUBLISHED' and not r.get('private') and not r.get('corrected')]
    facts=[]
    for r in valid:
        prices=r.get('explicit_unit_prices') or r.get('derived_unit_prices')
        if prices:
            spec=f"{r.get('category')}:{','.join(r.get('btu') or []) or 'unknown-spec'}"
            facts.append({'spec':spec,'unit_price':max(prices),'explicit':bool(r.get('explicit_unit_prices')),'record':r})
    cohorts=defaultdict(list)
    for f in facts: cohorts[f['spec']].append(f)
    findings=[]
    for spec,cohort in cohorts.items():
        for fact in cohort:
            peers=[x['unit_price'] for x in cohort if x is not fact]
            med=sorted(peers)[len(peers)//2] if peers else None
            ratio=fact['unit_price']/med if med else None
            score=35+(12 if fact['explicit'] else 0)
            reasons=[f"unit price €{fact['unit_price']:.2f}"]
            if len(cohort)>=4 and ratio and ratio>=3:
                score+=32; reasons.append(f"{ratio:.1f}x peer median across {len(peers)} peers")
            elif len(cohort)>=4 and ratio and ratio>=2:
                score+=20; reasons.append(f"{ratio:.1f}x peer median across {len(peers)} peers")
            else:
                score=min(score,59); reasons.append('insufficient same-spec comparator cohort')
            if spec.startswith('air_conditioner:unknown'):
                score=min(score,59); reasons.append('BTU/model/installation scope not confirmed')
            findings.append({'score':score,'spec':spec,'ratio':ratio,'peer_count':len(peers),'reasons':reasons,'record':fact['record']})
    findings.sort(key=lambda x:x['score'],reverse=True)
    result={'status':'completed','executed_at':datetime.now(timezone.utc).isoformat(),'coverage':{'search_records':len(by_ada),'deep_records':len(records),'readable_pdfs':sum(r.get('pdf_text_length',0)>500 for r in valid)},'validated':[x for x in findings if x['score']>=80],'leads':[x for x in findings if x['score']<80][:30]}
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Official Diavgeia unit-price probe','',f"Search records: {len(by_ada)}",f"Deep records: {len(records)}",f"Validated >=80: {len(result['validated'])}",'', '> A high total is not overpricing. Missing quantity/specification caps the case below delivery.','']
    for label,items in [('Validated',result['validated']),('Leads',result['leads'][:15])]:
        lines += [f'## {label}','']
        for item in items:
            r=item['record']; lines += [f"### {item['score']}/100 — {r.get('category')}",f"- [{r.get('ada')}]({r.get('url')}) — {r.get('subject')}",f"- Spec: {item['spec']}",f"- Reasons: {'; '.join(item['reasons'])}",f"- Quantities: {r.get('quantities')}",f"- Explicit unit prices: {r.get('explicit_unit_prices')}",f"- Derived unit prices: {r.get('derived_unit_prices')}",'']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    summary=[f"SEARCH|{len(by_ada)}",f"DEEP|{len(records)}",f"PDFS|{result['coverage']['readable_pdfs']}",f"VALIDATED|{len(result['validated'])}",f"LEADS|{len(result['leads'])}"]
    for i,x in enumerate([*result['validated'],*result['leads']][:10],1): summary.append(f"TOP{i}|{x['score']}|{x['spec']}|{x['record'].get('ada')}")
    (OUT/'summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    print('\n'.join(summary))

if __name__=='__main__': main()
