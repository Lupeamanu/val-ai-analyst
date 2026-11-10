"""One structured Claude call: interpret computed facts, never invent new ones."""
import anthropic
from pydantic import BaseModel

from .metrics import Analysis

MODEL = "claude-opus-5-5"


class Finding(BaseModel):
    title: str
    explanation: str
    evidence: list[str]


class Improvement(BaseModel):
    priority: int  # 1 = most important
    action: str
    why: str
    evidence: list[str]


class RoundNote(BaseModel):
    round: int
    note: str
    evidence: list[str]


class Feedback(BaseModel):
    summary: str
    summary_evidence: list[str]
    key_findings: list[Finding]
    improvements: list[Improvement]
    round_notes: list[RoundNote]


SYSTEM = """You are a VALORANT coach reviewing one finished match from computed data.

Rules:
- Use ONLY the facts provided. Every item must list the fact IDs that support it in its evidence field.
- Every number you write must appear in the facts you cite (you may count cited items). Do not compute new percentages or averages.
- Refer to players only by the names in the facts (You, Ally2..Ally5, Enemy1..Enemy5).
- The data has kills, timings, weapons, economy, plants/defuses, damage totals and ability-cast counts. It has NO utility
  placement, positioning outside kills, crosshair placement or communication. Never claim anything about those.
- Prefer specific, practicable advice tied to rounds over generic tips. Do not write fact IDs inside prose text.
- Give 3-5 key findings, 3 improvements (priority 1 = biggest impact on winning rounds), and 3-8 round notes on the
  rounds that best illustrate the findings."""

MODES = {
    "team": "Review the match from Your team's perspective: what decided rounds, economy, trading, openings, post-plant.",
    "player": "Focus on the player 'You': their impact, openings, trades, deaths, clutches, and what they personally should change. "
              "Mention teammates only where it explains You's results.",
}


def facts_block(a: Analysis) -> str:
    return "\n".join(f"{fid} | {text}" for fid, text in a.facts.items())


def ask(a: Analysis, mode: str, retry_note: str = "") -> Feedback:
    """Raises anthropic.APIError on API failure, RuntimeError on refusal or truncated output."""
    content = f"Mode: {MODES[mode]}\n\nFacts (ID | text):\n{facts_block(a)}"
    if retry_note:
        content += f"\n\nYour previous answer had claims that failed fact-checking:\n{retry_note}\nFix or omit them."
    resp = anthropic.Anthropic().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": content}],
        output_format=Feedback,
    )
    if resp.stop_reason != "end_turn" or resp.parsed_output is None:
        raise RuntimeError(f"LLM returned no usable output (stop_reason={resp.stop_reason})")
    return resp.parsed_output
