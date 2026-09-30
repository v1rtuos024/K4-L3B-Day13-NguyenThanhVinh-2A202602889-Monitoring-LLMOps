"""Verify CP2 trace IDs through Langfuse Observations API v2."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "submission/evidence"
load_dotenv(ROOT / ".env")


def write(name: str, lines: list[str]) -> None:
    (EVIDENCE / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_metadata(value: dict | None) -> dict:
    allowed = {"correlation_id", "feature", "model", "prompt_name", "prompt_label", "prompt_version", "prompt_source", "doc_count", "query_preview", "ttft_ms", "cost_usd"}
    return {key: item for key, item in (value or {}).items() if key in allowed}


def main() -> None:
    entries = []
    for line in (EVIDENCE / "06-trace-list.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"(.+): correlation_id=(req-[0-9a-f]{8}) trace_id=([0-9a-f]{32})(?: .*)?$", line)
        if match:
            entries.append(match.groups())
    if len(entries) < 10:
        raise RuntimeError("Fewer than ten trace IDs were recorded")

    client = get_client()
    project = client.api.projects.get().data[0]
    response = client.api.observations.get_many(
        fields="core,basic,metadata,model,usage,prompt,metrics,trace_context",
        from_start_time=datetime.now(timezone.utc) - timedelta(days=1),
        to_start_time=datetime.now(timezone.utc) + timedelta(minutes=1),
        limit=1000,
    )
    by_trace = defaultdict(list)
    for observation in response.data:
        by_trace[observation.trace_id].append(observation)
    checked = []
    transition = []
    expected_versions = {"baseline": 1, "candidate": 2, "production-promoted": 2, "production-rolled-back": 1}
    for label, cid, trace_id in entries:
        observations = by_trace[trace_id]
        names = {o.name for o in observations}
        if names != {"lab-agent-run", "retrieval", "generation"}:
            raise RuntimeError(f"Missing child observations for {trace_id}: {names}")
        root = next(o for o in observations if o.name == "lab-agent-run")
        if any(o.parent_observation_id != root.id for o in observations if o is not root):
            raise RuntimeError(f"Invalid parent linkage for {trace_id}")
        generation = next(o for o in observations if o.name == "generation")
        version = (generation.metadata or {}).get("prompt_version")
        if (generation.metadata or {}).get("correlation_id") != cid:
            raise RuntimeError(f"Correlation mismatch for {trace_id}")
        if label in expected_versions and int(version) != expected_versions[label]:
            raise RuntimeError(f"Prompt version mismatch for {trace_id}")
        checked.append(f"{label}: correlation_id={cid} trace_id={trace_id} observations=3 prompt_version={version}")
        if label in expected_versions:
            transition.append(f"{label}: trace_id={trace_id} prompt_version={version} prompt_label={(generation.metadata or {}).get('prompt_label')}")
    write("06-trace-list.txt", [
        f"Project: {project.name} ({project.id})",
        f"Verified trace count: {len(checked)}",
        "Source: Langfuse Observations API v2, matched to local response logs.",
        *checked,
    ])
    rollback_path = EVIDENCE / "10-prompt-rollback.txt"
    rollback_lines = rollback_path.read_text(encoding="utf-8").splitlines()
    if "Verified trace prompt metadata:" in rollback_lines:
        rollback_lines = rollback_lines[:rollback_lines.index("Verified trace prompt metadata:")]
    write("10-prompt-rollback.txt", [*rollback_lines, "Verified trace prompt metadata:", *transition])

    label, cid, trace_id = entries[0]
    observations = by_trace[trace_id]
    root = next(o for o in observations if o.name == "lab-agent-run")
    children = [o for o in observations if o is not root]
    write("07-trace-waterfall.txt", [
        f"Project: {project.name} ({project.id})",
        f"correlation_id={cid} trace_id={trace_id}",
        f"root: {root.name} type={root.type} id={root.id} start={root.start_time} end={root.end_time}",
        *[f"child: {o.name} type={o.type} id={o.id} parent={o.parent_observation_id} start={o.start_time} end={o.end_time}" for o in sorted(children, key=lambda x: x.start_time)],
        "Source: Langfuse Observations API v2.",
    ])
    generation = next(o for o in children if o.name == "generation")
    write("08-trace-metadata.txt", [
        f"Project: {project.name} ({project.id})",
        f"correlation_id={cid} trace_id={trace_id}",
        f"root_metadata={json.dumps(safe_metadata(root.metadata), ensure_ascii=False, default=str)}",
        f"generation_model={generation.model}",
        f"generation_prompt_name={generation.prompt_name}",
        f"generation_prompt_version={generation.prompt_version}",
        f"generation_metadata={json.dumps(safe_metadata(generation.metadata), ensure_ascii=False, default=str)}",
        f"usage_details={json.dumps(generation.usage_details, default=str)}",
        f"cost_details={json.dumps(generation.cost_details, default=str)}",
        "Source: Langfuse Observations API v2; no raw prompt or output is captured.",
    ])
    print(f"Verified {len(checked)} Langfuse traces with root/retrieval/generation in {project.name}")


if __name__ == "__main__":
    main()
