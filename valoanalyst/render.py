"""Markdown report. Stats tables always render; AI sections only if the LLM output survived validation."""
from .llm import Feedback
from .metrics import Analysis
from .models import Match


def _table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(h for h, _ in cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(str(r[k]) for _, k in cols) + " |" for r in rows)


def _cite(ids: list[str]) -> str:
    return f" `[{', '.join(ids)}]`" if ids else ""


def render(match: Match, a: Analysis, mode: str, fb: Feedback | None, note: str, checked: tuple[int, int]) -> str:
    us, them = match.teams[a.my_team], match.teams[a.enemy_team]
    result = "Win" if us > them else "Loss" if us < them else "Draw"
    out = [f"# {match.map}: Your team {us} : {them} Enemy team ({result})",
           f"{match.mode.title()} · {match.started_at[:10]} · {match.length_ms // 60000} min · mode: {mode} · "
           f"source: {match.source}" + (f" · fact checks passed: {checked[0]}/{checked[1]}" if checked[1] else ""), ""]
    if note:
        out += [f"> {note}", ""]

    if fb and fb.summary:
        out += ["## Summary", fb.summary + _cite(fb.summary_evidence), ""]
    if fb and fb.improvements:
        out += ["## Top things to fix"]
        for i, imp in enumerate(sorted(fb.improvements, key=lambda x: x.priority), 1):
            out.append(f"{i}. **{imp.action}** {imp.why}{_cite(imp.evidence)}")
        out.append("")
    if fb and fb.key_findings:
        out += ["## Key findings"]
        out += [f"- **{f.title}.** {f.explanation}{_cite(f.evidence)}" for f in fb.key_findings]
        out.append("")

    out += ["## Teams", _table(a.team_rows, [("Team", "team"), ("Rounds", "rounds"), ("Attack", "attack"),
                                             ("Defense", "defense"), ("Pistols", "pistols"), ("Post-plant", "postplant"),
                                             ("Retakes", "retake"), ("FB → win", "fb_conversion")]), ""]
    for row in a.team_rows:
        out.append(f"- {row['team']} by buy: " + ", ".join(f"{k} {v}" for k, v in row["buys"].items()))
    out += ["", "## Players", _table(a.player_rows, [
        ("Player", "player"), ("Agent", "agent"), ("Team", "team"), ("ACS", "acs"), ("ADR", "adr"), ("K", "k"),
        ("D", "d"), ("A", "a"), ("HS%", "hs"), ("KAST%", "kast"), ("FK", "fk"), ("FD", "fd"), ("Trades", "trades"),
        ("Untraded deaths", "untraded"), ("Clutch W/A", "clutch"), ("Multi", "multi"), ("Ults", "ults")]), ""]

    if fb and fb.round_notes:
        out += ["## Round notes"]
        out += [f"- **R{r.round}**: {r.note}{_cite(r.evidence)}" for r in sorted(fb.round_notes, key=lambda r: r.round)]
        out.append("")

    out += ["## Limits of this data",
            "Kills, timings, weapons, economy, plants/defuses, damage totals and ability-cast counts only. No utility "
            "placement, positioning outside kill moments, crosshair placement or comms. Players are pseudonymised.", ""]

    if fb:
        cited = dict.fromkeys(fb.summary_evidence + [e for x in fb.key_findings + fb.improvements + fb.round_notes
                                                     for e in x.evidence])
        if cited:
            out += ["<details><summary>Evidence (cited facts)</summary>", ""]
            out += [f"- `{fid}` {a.facts[fid]}" for fid in cited if fid in a.facts]
            out += ["", "</details>", ""]
    return "\n".join(out)
