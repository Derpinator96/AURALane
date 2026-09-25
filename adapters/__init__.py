"""Model adapters. Each module exposes

    adapt(model_output, context) -> core.types.Findings
    finding_names(entry) -> list[str]     every finding adapt can emit

core/registry.py checks finding_names against the entry's urgency weights at
startup, so a finding with no weight is a load error, not a silent 0.15.
"""
