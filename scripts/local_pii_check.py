"""Exercise synthetic PII samples without configuring Langfuse or network I/O."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ.pop(key, None)

from app.main import app  # noqa: E402
from app.pii import PII_PATTERNS
import re

EVIDENCE = ROOT / "submission/evidence/05-pii-redaction.txt"


async def main() -> None:
    samples = [json.loads(line) for line in (ROOT / "data/sample_queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    kinds = set()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        for payload in samples:
            matched = [name for name, pattern in PII_PATTERNS.items() if re.search(pattern, payload["message"])]
            if not matched:
                continue
            kinds.update(matched)
            response = await client.post("/chat", json=payload)
            response.raise_for_status()
    logs = (ROOT / "data/logs.jsonl").read_text(encoding="utf-8")
    for payload in samples:
        for pattern in PII_PATTERNS.values():
            for hit in re.findall(pattern, payload["message"]):
                if hit in logs:
                    raise AssertionError("Raw synthetic PII appeared in logs")
    EVIDENCE.write_text(
        "Offline PII exercise (Langfuse disabled; no external requests)\n"
        f"Synthetic sample categories exercised: {', '.join(sorted(kinds))}\n"
        f"Log redaction markers present: {', '.join(sorted(marker for marker in ('[REDACTED_EMAIL]', '[REDACTED_PHONE_VN]', '[REDACTED_CREDIT_CARD]') if marker in logs))}\n"
        "Raw synthetic sample values in log: 0\n",
        encoding="utf-8",
    )
    print(EVIDENCE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
