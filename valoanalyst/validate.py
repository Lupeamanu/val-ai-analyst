"""Drop any LLM claim that is not grounded in the computed facts."""
import re

from .llm import Feedback
from .metrics import Analysis

FACT_ID = re.compile(r"\b(?:R\d{2}\.[A-Z]+\d*(?:\.\w+)?|[PT]:\w+)")
NAME = re.compile(r"\b(?:You|Ally\d|Enemy\d)\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(NAME.sub(" ", FACT_ID.sub(" ", text)))]


def check(text: str, evidence: list[str], a: Analysis) -> str | None:
    """Return the reason a claim fails, or None if it is grounded."""
    if not evidence:
        return "no evidence cited"
    missing = [e for e in evidence if e not in a.facts]
    if missing:
        return f"unknown fact ids {missing}"
    unknown = set(NAME.findall(text)) - set(a.names.values())
    if unknown:
        return f"unknown players {sorted(unknown)}"
    allowed = {n for e in evidence for n in _numbers(a.facts[e])} | set(range(len(evidence) + 1))
    bad = [n for n in _numbers(text) if not any(abs(n - x) <= 0.5 for x in allowed)]
    if bad:
        return f"numbers not in cited facts: {bad}"
    return None


def validate(fb: Feedback, a: Analysis) -> tuple[Feedback, list[str], int]:
    """Returns (feedback with failing items removed, failure descriptions, total items checked)."""
    failures, total = [], 0

    def keep(label, text, evidence):
        nonlocal total
        total += 1
        reason = check(text, evidence, a)
        if reason:
            failures.append(f"{label}: {reason} -- {text[:120]!r}")
        return reason is None

    out = fb.model_copy(deep=True)
    if not keep("summary", out.summary, out.summary_evidence):
        out.summary = ""
    out.key_findings = [f for f in out.key_findings if keep("finding", f"{f.title} {f.explanation}", f.evidence)]
    out.improvements = [i for i in out.improvements if keep("improvement", f"{i.action} {i.why}", i.evidence)]
    # the round's own RESULT fact is implicitly cited; a nonexistent round fails as an unknown fact id
    out.round_notes = [r for r in out.round_notes
                       if keep("round note", f"Round {r.round}: {r.note}", r.evidence + [f"R{r.round:02d}.RESULT"])]
    return out, failures, total
