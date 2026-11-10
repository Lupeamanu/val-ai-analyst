"""HenrikDev unofficial API adapter (v4 match details).

Unofficial, not endorsed by Riot: local prototype on your own matches only. See plan risk L1.
Schema: https://docs.henrikdev.xyz/api-reference/valorant/get-match-details-v4.md
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .models import BombEvent, Economy, Kill, Match, Player, Round

API = "https://api.henrikdev.xyz/valorant/v4/match/{region}/{match_id}"
REGIONS = {"na", "eu", "ap", "kr", "latam", "br"}
SUPPORTED_QUEUES = {"competitive", "unrated", "premier", "swiftplay", "custom"}
CACHE_DIR = Path("cache/henrik")


class FetchError(Exception):
    pass


def fetch(match_id: str, region: str) -> dict:
    """Raw v4 payload, cached on disk forever (finished matches never change)."""
    if region not in REGIONS:
        raise FetchError(f"Unknown region {region!r}; use one of {sorted(REGIONS)}")
    cached = CACHE_DIR / f"{match_id}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    key = os.environ.get("HENRIK_API_KEY")
    if not key:
        raise FetchError("HENRIK_API_KEY is not set (get a free Basic key at https://api.henrikdev.xyz/dashboard)")
    req = urllib.request.Request(API.format(region=region, match_id=match_id),
                                 headers={"Authorization": key, "User-Agent": "valoanalyst/0.1"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(min(int(e.headers.get("Retry-After") or 10), 60))
                continue
            msg = {401: "API key rejected", 403: "API key rejected or match not accessible",
                   404: "match not found (check the match ID and region)",
                   429: "rate limited by HenrikDev (Basic key: 30 requests/min)"}.get(e.code, f"HTTP {e.code}")
            raise FetchError(f"HenrikDev: {msg}") from e
        except urllib.error.URLError as e:
            raise FetchError(f"HenrikDev unreachable: {e.reason}") from e
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _side_schedule(numbers: list[int], planters: dict[int, str], teams: list[str], half: int) -> dict[int, str]:
    """Attacking team per 1-based round. v4 has no side field, so infer it from who planted.

    shortcut: assumes standard side swaps (swap after `half` rounds, then every round in overtime);
    if Riot changes overtime rules, read sides from Riot's API instead (v2 adapter).
    """
    same_as_first = lambda n: n <= half or (n > 2 * half and (n - 2 * half) % 2 == 1)
    votes = {t: 0 for t in teams}
    for n, team in planters.items():
        votes[team] += 1 if same_as_first(n) else -1
    first_attacker = max(teams, key=lambda t: votes[t])  # ties fall back to list order
    other = next(t for t in teams if t != first_attacker)
    return {n: first_attacker if same_as_first(n) else other for n in numbers}


def to_match(payload: dict) -> Match:
    d = payload["data"]
    meta = d["metadata"]
    queue = (meta.get("queue") or {}).get("id") or "unknown"
    if queue not in SUPPORTED_QUEUES:
        raise FetchError(f"Unsupported mode {queue!r}; supported: {sorted(SUPPORTED_QUEUES)}")
    if len(d["players"]) != 10 or not d["rounds"]:
        raise FetchError("Only completed 5v5 matches are supported")

    players = {}
    for p in d["players"]:
        s, casts = p["stats"], p.get("ability_casts") or {}
        players[p["puuid"]] = Player(
            puuid=p["puuid"], name=f'{p["name"]}#{p["tag"]}', team=p["team_id"], agent=p["agent"]["name"],
            tier=(p.get("tier") or {}).get("name") or "Unrated", party_id=p.get("party_id") or "",
            score=s["score"], kills=s["kills"], deaths=s["deaths"], assists=s["assists"],
            headshots=s["headshots"], bodyshots=s["bodyshots"], legshots=s["legshots"],
            ult_casts=casts.get("ultimate"))

    offset = 1 - min(r["id"] for r in d["rounds"])  # v4 round ids are 0-based; normalize to 1-based
    teams = sorted({p.team for p in players.values()})  # ["Blue", "Red"]
    half = 4 if queue == "swiftplay" else 12
    planters = {r["id"] + offset: r["plant"]["player"]["team"] for r in d["rounds"] if r.get("plant")}
    sides = _side_schedule([r["id"] + offset for r in d["rounds"]], planters, sorted(teams, reverse=True), half)

    rounds = []
    for r in d["rounds"]:
        n = r["id"] + offset
        econ, dmg, afk = {}, {}, set()
        for st in r["stats"]:
            pid = st["player"]["puuid"]
            e = st.get("economy") or {}
            econ[pid] = Economy(loadout_value=e.get("loadout_value") or 0, remaining=e.get("remaining") or 0,
                                weapon=(e.get("weapon") or {}).get("name"), armor=(e.get("armor") or {}).get("name"))
            dmg[pid] = sum(ev["damage"] for ev in st.get("damage_events") or [])
            if st.get("was_afk"):
                afk.add(pid)
        bomb = lambda b: b and BombEvent(player=b["player"]["puuid"], time_ms=b["round_time_in_ms"], site=b.get("site"))
        rounds.append(Round(number=n, winning_team=r["winning_team"], end_type=r["result"],
                            attacking_team=sides[n], plant=bomb(r.get("plant")), defuse=bomb(r.get("defuse")),
                            economy=econ, damage=dmg, afk=afk))

    by_number = {r.number: r for r in rounds}
    for k in sorted(d["kills"], key=lambda k: (k["round"], k["time_in_round_in_ms"])):
        rnd = by_number.get(k["round"] + offset)
        if rnd is None:
            continue
        rnd.kills.append(Kill(round=rnd.number, time_ms=k["time_in_round_in_ms"], killer=k["killer"]["puuid"],
                              victim=k["victim"]["puuid"], assistants=[a["puuid"] for a in k.get("assistants") or []],
                              weapon=(k.get("weapon") or {}).get("name")))

    return Match(match_id=meta["match_id"], map=meta["map"]["name"], mode=queue, started_at=meta.get("started_at", ""),
                 length_ms=meta.get("game_length_in_ms") or 0, region=meta.get("region") or "", source="henrik-v4",
                 teams={t["team_id"]: t["rounds"]["won"] for t in d["teams"]}, players=players, rounds=rounds)
