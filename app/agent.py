from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, scrub_text, summarize_text
from .prompt_management import resolve_prompt
from .tracing import child_observation, get_langfuse_client, observe, propagate_attributes, tracing_enabled


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    trace_id: str | None = None


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(name="lab-agent-run", as_type="agent", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str,
    ) -> AgentResult:
        langfuse_client = get_langfuse_client()
        with propagate_attributes(
            user_id=hash_user_id(user_id),
            session_id=hash_user_id(session_id),
            tags=["lab", scrub_text(feature), self.model],
            trace_name="day13-agent-request",
            environment=os.getenv("APP_ENV", "dev"),
            metadata={
                "feature": scrub_text(feature),
                "model": self.model,
                "correlation_id": correlation_id,
            },
        ):
            get_trace_id = getattr(langfuse_client, "get_current_trace_id", None)
            trace_id = get_trace_id() if tracing_enabled() and get_trace_id else None
            started = time.perf_counter()
            with child_observation(
                langfuse_client,
                enabled=tracing_enabled(),
                name="retrieval",
                as_type="retriever",
                metadata={"correlation_id": correlation_id, "query_preview": summarize_text(message)},
            ) as retrieval_span:
                docs = retrieve(message)
                retrieval_span.update(metadata={"doc_count": len(docs), "success": True})
            prompt = resolve_prompt(
                langfuse_client,
                feature=feature,
                docs=docs,
                message=message,
                enabled=tracing_enabled(),
            )
            if tracing_enabled():
                langfuse_client.update_current_span(
                    metadata={
                        "doc_count": len(docs),
                        "query_preview": summarize_text(message),
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                        "prompt_source": prompt.source,
                        "prompt_fetch_error": prompt.fetch_error or "",
                    },
                    version=prompt.version,
                )
            with propagate_attributes(prompt=prompt.managed_prompt):
                with child_observation(
                    langfuse_client,
                    enabled=tracing_enabled(),
                    name="generation",
                    as_type="generation",
                    model=self.model,
                    metadata={
                        "correlation_id": correlation_id,
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                        "prompt_source": prompt.source,
                        "prompt_preview": summarize_text(prompt.text),
                    },
                ) as generation:
                    response = self.llm.generate(prompt.text)
                    input_cost = round(response.usage.input_tokens * 3 / 1_000_000, 8)
                    output_cost = round(response.usage.output_tokens * 15 / 1_000_000, 8)
                    generation.update(
                        usage_details={
                            "input": response.usage.input_tokens,
                            "output": response.usage.output_tokens,
                        },
                        cost_details={"input": input_cost, "output": output_cost},
                        metadata={"ttft_ms": response.ttft_ms, "cost_usd": round(input_cost + output_cost, 6), "answer_preview": summarize_text(response.text)},
                    )
            quality_score = self._heuristic_quality(message, response.text, docs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            cost_usd = self._estimate_cost(response.usage.input_tokens, response.usage.output_tokens)

        metrics.record_request(
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
            trace_id=trace_id,
        )

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost + output_cost, 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
