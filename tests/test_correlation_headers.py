from __future__ import annotations

import asyncio
import json
import re

import httpx

from app import logging_config, main
from app.agent import AgentResult


def test_request_id_headers_and_log_context_do_not_leak(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    monkeypatch.setattr(
        main.agent,
        "run",
        lambda **_: AgentResult("safe answer", 12, 4, 10, 8, 0.00015, 0.8),
    )

    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            first = await client.post("/chat", headers={"x-request-id": "req-a1b2c3d4"}, json={"user_id": "one", "session_id": "session-one", "feature": "qa", "message": "hello"})
            second = await client.post("/chat", headers={"x-request-id": "invalid"}, json={"user_id": "two", "session_id": "session-two", "feature": "summary", "message": "hello"})
            return first, second

    first, second = asyncio.run(requests())
    assert first.headers["x-request-id"] == "req-a1b2c3d4"
    assert re.fullmatch(r"req-[0-9a-f]{8}", second.headers["x-request-id"])
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert float(first.headers["x-response-time-ms"]) >= 0
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    received = [record for record in records if record["event"] == "request_received"]
    assert [r["correlation_id"] for r in received] == [first.headers["x-request-id"], second.headers["x-request-id"]]
    assert received[0]["user_id_hash"] != received[1]["user_id_hash"]
    assert received[0]["feature"] == "qa"
    assert received[1]["feature"] == "summary"
    assert all(record["model"] == main.agent.model and record["env"] for record in received)
