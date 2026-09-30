"""Generate the student's CP2 workload and capture API-backed evidence.

Run only with a personal Langfuse project and valid .env credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langfuse import get_client
from langfuse.api.commons.errors.not_found_error import NotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.main import app  # noqa: E402 - environment must load first
from app.pii import scrub_text

EVIDENCE = ROOT / "submission/evidence"
LOG_PATH = ROOT / "data/logs.jsonl"
PROMPT_NAME = "day13-chat"


def write(name: str, lines: list[str]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


async def send(payload: dict, label: str) -> tuple[str, str | None]:
    os.environ["LANGFUSE_PROMPT_LABEL"] = label
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab") as api:
        response = await api.post("/chat", json=payload)
    response.raise_for_status()
    cid = response.json()["correlation_id"]
    for line in reversed(LOG_PATH.read_text(encoding="utf-8").splitlines()):
        event = json.loads(line)
        if event.get("event") == "response_sent" and event.get("correlation_id") == cid:
            return cid, event.get("trace_id")
    raise RuntimeError(f"No response log for {cid}")


async def main() -> None:
    client = get_client()
    if not client.auth_check():
        raise RuntimeError("Configured Langfuse keys are not valid")
    projects = client.api.projects.get().data
    if len(projects) != 1:
        raise RuntimeError("Expected exactly one project for the configured API key")
    project = projects[0]
    # Project API keys cannot rename a project. Keep the actual project name in
    # evidence; the owner can rename it from the Langfuse UI if desired.

    try:
        baseline = client.get_prompt(PROMPT_NAME, label="baseline", cache_ttl_seconds=0)
    except NotFoundError:
        baseline = client.create_prompt(
            name=PROMPT_NAME,
            type="text",
            prompt="Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}",
            labels=["baseline", "production"],
            commit_message="CP2 baseline prompt",
        )
    try:
        candidate = client.get_prompt(PROMPT_NAME, label="candidate", cache_ttl_seconds=0)
    except NotFoundError:
        candidate = client.create_prompt(
            name=PROMPT_NAME,
            type="text",
            prompt="Answer concisely using the relevant context.\nFeature={{feature}}\nDocs={{docs}}\nQuestion={{message}}",
            labels=["candidate"],
            commit_message="CP2 concise candidate",
        )
    baseline_version = int(baseline.version)
    candidate_version = int(candidate.version)
    write("09-prompt-versions.txt", [
        f"Project: {project.name} ({project.id})",
        f"Prompt: {PROMPT_NAME}",
        f"baseline: version {baseline_version}",
        f"candidate: version {candidate_version}",
        f"production before promotion: version {client.get_prompt(PROMPT_NAME, label='production', cache_ttl_seconds=0).version}",
        "Source: Langfuse prompt API; templates preserve feature/docs/message variables.",
    ])

    same_payload = {"user_id": "u-demo", "session_id": "s-demo", "feature": "qa", "message": "How do metrics, logs and traces help monitoring?"}
    links = []
    for label in ("baseline", "candidate"):
        cid, trace_id = await send(same_payload, label)
        links.append((label, cid, trace_id))
    client.update_prompt(name=PROMPT_NAME, version=candidate_version, new_labels=["candidate", "production"])
    promoted_version = client.get_prompt(PROMPT_NAME, label="production", cache_ttl_seconds=0).version
    links.append(("production-promoted", *(await send(same_payload, "production"))))
    client.update_prompt(name=PROMPT_NAME, version=baseline_version, new_labels=["baseline", "production"])
    rolled_back_version = client.get_prompt(PROMPT_NAME, label="production", cache_ttl_seconds=0).version
    links.append(("production-rolled-back", *(await send(same_payload, "production"))))
    if int(promoted_version) != candidate_version or int(rolled_back_version) != baseline_version:
        raise RuntimeError("Prompt label transition did not resolve to expected versions")
    write("10-prompt-rollback.txt", [
        f"Project: {project.name}",
        f"production promoted to version {promoted_version}",
        f"production rolled back to version {rolled_back_version}",
        *[f"{label}: correlation_id={cid} trace_id={trace_id}" for label, cid, trace_id in links],
        "Source: Langfuse prompt API reads after each label update.",
    ])

    payloads = [json.loads(line) for line in (ROOT / "data/sample_queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for payload in payloads:
        # The repository's sample file includes synthetic PII. The cloud workload
        # uses only redacted inputs; raw-value redaction is tested offline.
        payload["message"] = scrub_text(payload["message"])
        cid, trace_id = await send(payload, "production")
        links.append(("production", cid, trace_id))
    client.flush()
    time.sleep(10)
    write("06-trace-list.txt", [
        f"Project: {project.name} ({project.id})",
        "Trace IDs generated by this CP2 workload:",
        *[f"{label}: correlation_id={cid} trace_id={trace_id}" for label, cid, trace_id in links],
    ])

    from scripts.capture_cp2_evidence import main as capture_evidence
    capture_evidence()
    print(f"Project {project.name}: {len(links)} traced requests; production v{rolled_back_version}")


if __name__ == "__main__":
    asyncio.run(main())
