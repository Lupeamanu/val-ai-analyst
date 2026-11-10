"""CLI: python -m valoanalyst MATCH_ID --region eu --player "Name#Tag" [--mode team|player] [--no-llm]"""
import argparse
import json
import sys
from pathlib import Path

from . import henrik, llm
from .metrics import analyze
from .render import render
from .validate import validate

RETRY_IF_FAILED_OVER = 0.2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="valoanalyst", description="AI review of one VALORANT match")
    ap.add_argument("match_id")
    ap.add_argument("--region", default="na", help="na, eu, ap, kr, latam, br")
    ap.add_argument("--player", required=True, help='your Riot ID, e.g. "Name#Tag" (the report is from your side)')
    ap.add_argument("--mode", choices=sorted(llm.MODES), default="team")
    ap.add_argument("--file", type=Path, help="analyze a saved HenrikDev v4 JSON payload instead of fetching")
    ap.add_argument("--no-llm", action="store_true", help="stats only, no API call")
    ap.add_argument("--out", type=Path, default=Path("reports"))
    args = ap.parse_args(argv)

    try:
        payload = json.loads(args.file.read_text(encoding="utf-8")) if args.file else henrik.fetch(args.match_id, args.region)
        match = henrik.to_match(payload)
    except henrik.FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    me = next((p.puuid for p in match.players.values() if p.name.casefold() == args.player.casefold()), None)
    if me is None:
        print(f"error: {args.player!r} is not in this match. Players: "
              f"{', '.join(sorted(p.name for p in match.players.values()))}", file=sys.stderr)
        return 2

    a = analyze(match, me)
    fb, note, checked = None, "", (0, 0)
    if args.no_llm:
        note = "Stats only (--no-llm)."
    else:
        try:
            raw = llm.ask(a, args.mode)
            fb, failures, total = validate(raw, a)
            if total and len(failures) / total > RETRY_IF_FAILED_OVER:
                raw2 = llm.ask(a, args.mode, retry_note="\n".join(failures))
                fb2, failures2, total2 = validate(raw2, a)
                if len(failures2) <= len(failures):
                    fb, failures, total = fb2, failures2, total2
            checked = (total - len(failures), total)
            for f in failures:
                print(f"dropped ungrounded claim: {f}", file=sys.stderr)
            if checked[0] == 0:
                fb, note = None, "AI feedback failed fact-checking entirely; showing stats only."
        except Exception as e:  # any LLM failure still yields the stats report
            fb, note = None, f"AI feedback unavailable ({type(e).__name__}: {e}); showing stats only."

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{match.match_id}-{args.mode}.md"
    path.write_text(render(match, a, args.mode, fb, note, checked), encoding="utf-8")
    print(f"report written to {path}" + (f" ({checked[0]}/{checked[1]} claims passed fact-check)" if checked[1] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
