#!/usr/bin/env python3
import json
from pathlib import Path

source = Path('enriched-hunter-output/results.json')
out = Path('enriched-hunter-output/summary.txt')
if not source.exists():
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('STATUS|RESULTS_NOT_READY\n', encoding='utf-8')
else:
    payload = json.loads(source.read_text(encoding='utf-8'))
    lines = [
        f"STATUS|{payload.get('status')}",
        f"METADATA|{payload.get('coverage', {}).get('metadata_record_count')}",
        f"DEEP|{payload.get('coverage', {}).get('deep_record_count')}",
        f"PDFS|{payload.get('coverage', {}).get('readable_pdf_count')}",
        f"VALIDATED|{len(payload.get('validated') or [])}",
        f"LEADS|{len(payload.get('leads') or [])}",
    ]
    for index, item in enumerate([*(payload.get('validated') or []), *(payload.get('leads') or [])][:12], start=1):
        adas = ','.join(str(r.get('ada') or '') for r in item.get('records') or [])
        lines.append(f"TOP{index}|{item.get('review_priority')}|{item.get('kind')}|{item.get('category')}|{adas}")
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
