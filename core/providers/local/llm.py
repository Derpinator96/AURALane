"""TemplateLLM: drafts a structured note from triage output. No model call.

This is the working implementation, not a stub. Bedrock is blocked at the
account level, and a language model writing clinical findings is not wanted
anyway: the draft restates structured output, and the impression is left for
the radiologist.
"""
from __future__ import annotations

from typing import Any

from core.ports import LLMPort

TEMPLATE = """NON-DIAGNOSTIC; DECISION SUPPORT ONLY
Study: {study}
Model: {model}
Queue lane: {lane}{sla}
{driver_line}
Signals (0 to 1, relative to the model's operating point, not a probability of disease):
{signals}
Impression: to be written by the reading radiologist."""


class TemplateLLM(LLMPort):
    def draft(self, context: dict[str, Any]) -> str:
        t = context.get("triage", {})
        findings = context.get("findings", {})
        if t.get("abstained") or context.get("lane") == "ABSTAIN":
            driver = "Model abstained: no lane assigned, a human picks the lane."
        elif t.get("driver"):
            driver = f"Driving finding: {t['driver']} (signal {t.get('signal')})"
        else:
            driver = "No driving finding."
        signals = "\n".join(f"  {k}: {v:.3f}" for k, v in
                            sorted(findings.items(), key=lambda kv: -kv[1])) or "  none"
        return TEMPLATE.format(
            study=context.get("study", "unknown"), model=context.get("model_id", "unknown"),
            lane=context.get("lane", "unknown"),
            sla=f" ({t['sla']})" if t.get("sla") else "",
            driver_line=driver, signals=signals)
