"""Deterministic stats. Everything the LLM may cite is produced here as a fact: {fact_id: text}."""
from collections import Counter
from dataclasses import dataclass, field

from .models import Match, Round

TRADE_WINDOW_MS = 5000
# Team average loadout value thresholds (credits). shortcut: untuned guesses, calibrate on hand-labelled fixtures.
ECO_BELOW, FULL_FROM = 2000, 3900


def half_length(match: Match) -> int:
    return 4 if match.mode == "swiftplay" else 12


def mmss(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}"


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({round(100 * a / b)}%)" if b else f"{a}/0"


def annotate(match: Match) -> None:
    """Mark first bloods and trades on every kill (idempotent)."""
    for rnd in match.rounds:
        for i, k in enumerate(rnd.kills):
            k.first_blood, k.trade_of, k.traded = i == 0, None, False
        for j, k in enumerate(rnd.kills):
            avenging_team = match.team_of(k.victim)
            for i in range(j + 1, len(rnd.kills)):
                later = rnd.kills[i]
                if later.time_ms - k.time_ms > TRADE_WINDOW_MS:
                    break
                if later.victim == k.killer and match.team_of(later.killer) == avenging_team:
                    later.trade_of, k.traded = j, True
                    break


def buy_type(match: Match, rnd: Round, team: str) -> tuple[str, int]:
    vals = [e.loadout_value for pid, e in rnd.economy.items() if match.team_of(pid) == team]
    avg = round(sum(vals) / len(vals)) if vals else 0
    if rnd.number in (1, half_length(match) + 1):
        return "pistol", avg
    return ("eco" if avg < ECO_BELOW else "full" if avg >= FULL_FROM else "force"), avg


def clutches(match: Match, rnd: Round) -> dict[str, int]:
    """puuid -> X for every player left alone against X enemies (first time it happens this round)."""
    alive = {t: {p for p in match.players if match.team_of(p) == t} for t in match.teams}
    out = {}
    for k in rnd.kills:
        alive[match.team_of(k.victim)].discard(k.victim)
        for team, members in alive.items():
            enemies = sum(len(m) for t, m in alive.items() if t != team)
            if len(members) == 1 and enemies >= 1 and not any(p in out for p in members):
                out[next(iter(members))] = enemies
    return out


def aliases(match: Match, me: str) -> dict[str, str]:
    """Pseudonyms used everywhere (prompt and report): You, Ally2-5, Enemy1-5. Riot IDs never leave this machine."""
    mine = match.team_of(me)
    by_score = sorted(match.players.values(), key=lambda p: -p.score)
    allies = [p for p in by_score if p.team == mine and p.puuid != me]
    enemies = [p for p in by_score if p.team != mine]
    out = {me: "You"}
    out |= {p.puuid: f"Ally{i}" for i, p in enumerate(allies, 2)}
    out |= {p.puuid: f"Enemy{i}" for i, p in enumerate(enemies, 1)}
    return out


@dataclass
class Analysis:
    my_team: str
    enemy_team: str
    names: dict[str, str]
    player_rows: list[dict]
    team_rows: list[dict]
    facts: dict[str, str] = field(default_factory=dict)
    round_cards: list[list[str]] = field(default_factory=list)  # fact ids per round, in order


def analyze(match: Match, me: str) -> Analysis:
    annotate(match)
    names = aliases(match, me)
    my_team = match.team_of(me)
    enemy_team = next(t for t in match.teams if t != my_team)
    side = {my_team: "Your team", enemy_team: "Enemy team"}
    n_rounds = len(match.rounds)
    a = Analysis(my_team, enemy_team, names, [], [])

    # --- per-player accumulation ---
    st = {pid: Counter() for pid in match.players}
    for rnd in match.rounds:
        kills_in_round, died, contributed = Counter(), set(), set()
        for k in rnd.kills:
            kills_in_round[k.killer] += 1
            died.add(k.victim)
            contributed.add(k.killer)
            contributed.update(k.assistants)
            if k.traded:
                contributed.add(k.victim)
                st[k.victim]["traded_deaths"] += 1
            else:
                st[k.victim]["untraded_deaths"] += 1
            if k.trade_of is not None:
                st[k.killer]["trades"] += 1
            if k.first_blood:
                st[k.killer]["fk"] += 1
                st[k.victim]["fd"] += 1
        for pid in match.players:
            st[pid]["damage"] += rnd.damage.get(pid, 0)
            if pid in contributed or pid not in died:
                st[pid]["kast"] += 1
            if kills_in_round[pid] >= 2:
                st[pid][f"{min(kills_in_round[pid], 5)}k"] += 1
        for pid, x in clutches(match, rnd).items():
            st[pid]["clutch_att"] += 1
            st[pid]["clutch_won"] += match.team_of(pid) == rnd.winning_team

    for pid, p in sorted(match.players.items(), key=lambda kv: (kv[1].team != my_team, -kv[1].score)):
        s, alias = st[pid], names[pid]
        shots = p.headshots + p.bodyshots + p.legshots
        row = dict(player=alias, agent=p.agent, team=side[p.team], acs=round(p.score / n_rounds),
                   adr=round(s["damage"] / n_rounds), k=p.kills, d=p.deaths, a=p.assists,
                   hs=round(100 * p.headshots / shots) if shots else 0, kast=round(100 * s["kast"] / n_rounds),
                   fk=s["fk"], fd=s["fd"], trades=s["trades"], untraded=s["untraded_deaths"],
                   clutch=f'{s["clutch_won"]}/{s["clutch_att"]}',
                   multi=" ".join(f"{n}K:{s[f'{n}k']}" for n in range(2, 6) if s[f"{n}k"]) or "-",
                   ults=p.ult_casts if p.ult_casts is not None else "n/a")
        a.player_rows.append(row)
        a.facts[f"P:{alias}"] = (
            f"{alias} ({p.agent}, {side[p.team]}): ACS {row['acs']}, ADR {row['adr']}, K/D/A {p.kills}/{p.deaths}/{p.assists}, "
            f"HS {row['hs']}%, KAST {row['kast']}%, first kills {row['fk']}, first deaths {row['fd']}, "
            f"trade kills {row['trades']}, deaths traded {s['traded_deaths']}, untraded deaths {row['untraded']}, "
            f"clutches won/attempted {row['clutch']}, multi-kills {row['multi']}, ult casts {row['ults']}")

    # --- per-team ---
    half = half_length(match)
    for team in (my_team, enemy_team):
        c = Counter()
        buys = {"pistol": [0, 0], "eco": [0, 0], "force": [0, 0], "full": [0, 0]}
        streak = best_streak = 0
        for rnd in match.rounds:
            won = rnd.winning_team == team
            atk = rnd.attacking_team == team
            c["atk_played" if atk else "def_played"] += 1
            c["atk_won" if atk else "def_won"] += won
            if rnd.number in (1, half + 1):
                c["pistol_won"] += won
                c["pistol_played"] += 1
            bt, _ = buy_type(match, rnd, team)
            buys[bt][0] += won
            buys[bt][1] += 1
            if rnd.plant and atk:
                c["postplant_played"] += 1
                c["postplant_won"] += won
            if rnd.plant and not atk:
                c["retake_played"] += 1
                c["retake_won"] += won
            if rnd.kills and match.team_of(rnd.kills[0].killer) == team:
                c["fb_rounds"] += 1
                c["fb_won"] += won
            streak = 0 if won else streak + 1
            best_streak = max(best_streak, streak)
        row = dict(team=side[team], rounds=match.teams[team], attack=pct(c["atk_won"], c["atk_played"]),
                   defense=pct(c["def_won"], c["def_played"]), pistols=pct(c["pistol_won"], c["pistol_played"]),
                   buys={k: pct(*v) for k, v in buys.items() if v[1]},
                   postplant=pct(c["postplant_won"], c["postplant_played"]),
                   retake=pct(c["retake_won"], c["retake_played"]),
                   fb_conversion=pct(c["fb_won"], c["fb_rounds"]), loss_streak=best_streak)
        a.team_rows.append(row)
        key = "T:Us" if team == my_team else "T:Them"
        a.facts[key] = (
            f"{side[team]}: rounds won {row['rounds']}; attack rounds won {row['attack']}; defense rounds won {row['defense']}; "
            f"pistol rounds won {row['pistols']}; rounds won by buy type: "
            + ", ".join(f"{k} {v}" for k, v in row["buys"].items())
            + f"; post-plant rounds won {row['postplant']}; retakes won {row['retake']}; "
            f"rounds won after taking first blood {row['fb_conversion']}; longest losing streak {best_streak}")

    a.facts["M"] = (f"Map {match.map}, mode {match.mode}, {n_rounds} rounds, final score Your team {match.teams[my_team]} "
                    f"- Enemy team {match.teams[enemy_team]}. Trade window {TRADE_WINDOW_MS // 1000}s. "
                    f"Buy types from team average loadout value: eco under {ECO_BELOW}, full from {FULL_FROM}, force between.")

    # --- round cards ---
    score = Counter()
    for rnd in match.rounds:
        r, ids = f"R{rnd.number:02d}", []
        score[rnd.winning_team] += 1

        def add(fid, text):
            a.facts[fid] = text
            ids.append(fid)

        add(f"{r}.RESULT", f"Round {rnd.number}: {side[rnd.winning_team]} won ({rnd.end_type}); "
                           f"{side[rnd.attacking_team]} attacking; score after round {score[my_team]}-{score[enemy_team]}")
        mine, theirs = buy_type(match, rnd, my_team), buy_type(match, rnd, enemy_team)
        add(f"{r}.ECON", f"Round {rnd.number} buys: Your team {mine[0]} (avg loadout {mine[1]}), "
                         f"Enemy team {theirs[0]} (avg loadout {theirs[1]})")
        for i, k in enumerate(rnd.kills, 1):
            tags = []
            if k.first_blood:
                tags.append("first blood")
            if k.trade_of is not None:
                tags.append(f"trade for kill {k.trade_of + 1}")
            if not k.traded:
                tags.append("death not traded")
            assist = f", assisted by {', '.join(names[x] for x in k.assistants)}" if k.assistants else ""
            add(f"{r}.K{i}", f"Round {rnd.number} kill {i} at {mmss(k.time_ms)}: {names[k.killer]} killed {names[k.victim]} "
                             f"with {k.weapon or 'unknown'}{assist}" + (f" [{'; '.join(tags)}]" if tags else ""))
        if rnd.plant:
            add(f"{r}.PLANT", f"Round {rnd.number}: spike planted on {rnd.plant.site or '?'} by {names[rnd.plant.player]} "
                              f"at {mmss(rnd.plant.time_ms)}")
        if rnd.defuse:
            add(f"{r}.DEFUSE", f"Round {rnd.number}: spike defused by {names[rnd.defuse.player]} at {mmss(rnd.defuse.time_ms)}")
        for pid, x in clutches(match, rnd).items():
            result = "won" if match.team_of(pid) == rnd.winning_team else "lost"
            add(f"{r}.CLUTCH.{names[pid]}", f"Round {rnd.number}: {names[pid]} was left 1v{x} and {result} the round")
        if rnd.afk:
            add(f"{r}.AFK", f"Round {rnd.number}: AFK players: {', '.join(names[p] for p in rnd.afk)}")
        a.round_cards.append(ids)
    return a
