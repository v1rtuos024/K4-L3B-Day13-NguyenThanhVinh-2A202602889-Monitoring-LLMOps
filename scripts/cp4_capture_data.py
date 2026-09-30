"""Generate real local demonstration logs, without taking screenshots."""
import json
import sys
from pathlib import Path
from datetime import datetime
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.dashboard import render

evidence = ROOT / "submission/evidence"
for cid, message, filename in [
    ("req-d1300004", "Explain traces", "04-structured-log.json"),
    ("req-d1300005", "a@b.vn 0901234567 001099012345 4111 1111 1111 1111", "05-pii-redaction.txt"),
]:
    response = httpx.post("http://127.0.0.1:8000/chat", json={"user_id":"demo", "session_id":"demo-01", "feature":"qa", "message":message}, headers={"x-request-id":cid}, timeout=30)
    response.raise_for_status()
    rows = [json.loads(line) for line in (ROOT / "data/logs.jsonl").read_text(encoding="utf-8").splitlines() if cid in line]
    (evidence / filename).write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(cid, response.status_code, next(r["trace_id"] for r in rows if r["event"] == "response_sent"))
run = json.loads((evidence / "cp3-run.json").read_text(encoding="utf-8"))
for phase, name in [("incident", "12-incident-dashboard.html"), ("recovery", "11-dashboard-overview.html")]:
    page = render(datetime.fromisoformat(run["phases"][phase]["ended_at"].replace("Z", "+00:00")))
    assert page.count("<section>") == 6
    assert "2000" in page and "3000" in page and "<svg" in page
    (evidence / name).write_text(page, encoding="utf-8")
