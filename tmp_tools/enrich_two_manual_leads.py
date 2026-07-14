#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests

BASE='https://diavgeia.gov.gr'
SEARCH=BASE+'/luminapi/opendata/search'
DETAIL=BASE+'/luminapi/api/decisions/{ada}'
DOC=BASE+'/doc/{ada}'
OUT=Path('manual-diverse-output')
QUERIES={
 'oxygen':['Φαρμακευτικό Υγρό Οξυγόνο','Υγρό Οξυγόνο','SOL HELLAS'],
 'ekab_lodging':['υπηρεσιών διανυκτέρευσης','ΕΚΑΒ Κέρκυρας','ΞΕΝΟΔΟΧΕΙΟ ΑΡΙΩΝ'],
}
AFM=re.compile(r'(?:Α\.?Φ\.?Μ\.?|AFM)\s*[:#]?\s*(\d{9})',re.I)
MONEY=re.compile(r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)',re.I)

def req(s,u,**kw):
 for i in range(5):
  try:
   r=s.get(u,timeout=60,allow_redirects=True,**kw)
   if r.status_code in {429,502,503,504}: time.sleep(2**i); continue
   return r
  except requests.RequestException:
   time.sleep(2**i)
 raise RuntimeError(u)

def pdftotext(content):
 with tempfile.TemporaryDirectory() as d:
  p=Path(d)/'a.pdf'; t=Path(d)/'a.txt'; p.write_bytes(content)
  x=subprocess.run(['pdftotext','-enc','UTF-8','-layout',str(p),str(t)],capture_output=True,timeout=60)
  return t.read_text(errors='replace')[:220000] if x.returncode==0 and t.exists() else ''

def ms(v):
 try:return datetime.fromtimestamp(int(v)/1000,tz=timezone.utc).date().isoformat()
 except:return None

def excerpt(text,terms):
 low=text.casefold()
 positions=[low.find(t.casefold()) for t in terms if low.find(t.casefold())>=0]
 pos=min(positions) if positions else 0
 return ' '.join(text[max(0,pos-500):pos+6500].split())

def main():
 OUT.mkdir(exist_ok=True)
 s=requests.Session(); s.headers['User-Agent']='MizAI targeted official enrichment/1.0'
 found={k:{} for k in QUERIES}
 attempts=[]
 for lane,terms in QUERIES.items():
  for term in terms:
   for year_start,year_end in [('2023-01-01','2023-12-31'),('2024-01-01','2024-12-31'),('2025-01-01','2025-12-31'),('2026-01-01','2026-07-14')]:
    for page in range(5):
     r=req(s,SEARCH,params={'term':term,'page':page,'size':100,'from_issue_date':year_start,'to_issue_date':year_end})
     rows=(r.json().get('decisions') or []) if r.ok else []
     attempts.append({'lane':lane,'term':term,'year':year_start[:4],'page':page,'status':r.status_code,'count':len(rows)})
     for row in rows:
      ada=str(row.get('ada') or '').strip()
      if ada: found[lane][ada]=row
     if len(rows)<100: break
     time.sleep(.12)
 results={}
 for lane,rows in found.items():
  out=[]
  ranked=sorted(rows.items(),key=lambda kv:sum(t.casefold() in str(kv[1].get('subject') or '').casefold() for t in QUERIES[lane]),reverse=True)[:70]
  for ada,seed in ranked:
   d=req(s,DETAIL.format(ada=quote(ada,safe='')))
   if not d.ok: continue
   detail=d.json(); status=str(detail.get('status') or '')
   if status!='PUBLISHED' or detail.get('correctedVersionId') or detail.get('privateData') is True: continue
   url=str(detail.get('documentUrl') or DOC.format(ada=quote(ada,safe='')))
   p=req(s,url)
   text=pdftotext(p.content) if p.ok and 'pdf' in p.headers.get('content-type','').casefold() else ''
   subject=' '.join(str(detail.get('subject') or '').split())
   joined=subject+'\n'+text
   if lane=='oxygen' and not any(x in joined.casefold() for x in ('υγρό οξυγόνο','υγρου οξυγονου','sol hellas')): continue
   if lane=='ekab_lodging' and not ('διανυκτερευ' in joined.casefold() and ('κερκυρ' in joined.casefold() or 'αριων' in joined.casefold())): continue
   amounts=list(dict.fromkeys(m.group(1) for m in MONEY.finditer(joined)))[:20]
   afms=list(dict.fromkeys(AFM.findall(joined)))[:8]
   out.append({'ada':ada,'url':url,'subject':subject,'issue_date':ms(detail.get('issueDate')),'publish_date':ms(detail.get('publishTimestamp')),'organization_id':str(detail.get('organizationId') or ''),'amount_mentions':amounts,'afms':afms,'excerpt':excerpt(text,QUERIES[lane])})
   time.sleep(.12)
  results[lane]=out
 payload={'executed_at':datetime.now(timezone.utc).isoformat(),'attempts':attempts,'results':results}
 (OUT/'targeted-enrichment.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
 lines=['# Targeted enrichment','']
 for lane,rows in results.items():
  lines += [f'## {lane} ({len(rows)})','']
  for row in rows:
   lines += [f"### {row['ada']}",f"- URL: {row['url']}",f"- Subject: {row['subject']}",f"- Dates: {row['issue_date']} / {row['publish_date']}",f"- Amount mentions: {', '.join(row['amount_mentions'])}",f"- AFMs: {', '.join(row['afms'])}",f"- Excerpt: {row['excerpt']}",'']
 (OUT/'targeted-enrichment.md').write_text('\n'.join(lines),encoding='utf-8')
 print({k:len(v) for k,v in results.items()})
if __name__=='__main__':main()
# trigger 2026-07-14
