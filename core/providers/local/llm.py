"""TemplateLLM: drafts a structured radiology report from stored findings. No model call.

This is the working implementation, not a stub. Bedrock is blocked at the
account level, and a language model writing clinical findings is not wanted
anyway: the draft is assembled from structured output (core/report_text.py) and
the radiologist confirms or replaces every statement.
"""
from __future__ import annotations

from typing import Any

from core import report_text
from core.ports import LLMPort


class TemplateLLM(LLMPort):
    def draft(self, context: dict[str, Any]) -> str:
        return report_text.build(context)
