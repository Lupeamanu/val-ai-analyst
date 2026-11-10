"""Synthetic HenrikDev v4-shaped match -> adapter -> metrics -> validator. Run: python -m unittest"""
import unittest

from valoanalyst import henrik
from valoanalyst.llm import Feedback, Finding, Improvement, RoundNote
from valoanalyst.metrics import analyze
from valoanalyst.validate import validate

RED = [f"r{i}" for i in range(1, 6)]
BLUE = [f"b{i}" for i in range(1, 6)]
ME = "b5"


def ref(pid):
    return {"puuid": pid, "name": pid.upper(), "tag": "TST", "team": "Red" if pid in RED else "Blue"}


def kill(rnd, t, killer, victim):
    return {"round": rnd, "time_in_round_in_ms": t, "time_in_match_in_ms": 0, "killer": ref(killer),
            "victim": ref(victim), "assistants": [], "location": {"x": 0, "y": 0},
            "weapon": {"id": "w", "name": "Vandal", "type": "Weapon"}, "player_locations": []}


def round_stats(loadout):
    return [{"player": ref(p), "ability_casts": {}, "damage_events": [{"player": ref("r1"), "damage": 50,
             "headshots": 0, "bodyshots": 1, "legshots": 0}], "stats": {},
             "economy": {"loadout_value": loadout, "remaining": 0, "weapon": None, "armor": None},
             "was_afk": False} for p in RED + BLUE]


def payload():
    kills = [
        kill(0, 10_000, "r1", "b1"),  # first blood
        kill(0, 12_000, "b2", "r1"),  # trade for kill 1
        kill(0, 30_000, "r2", "b2"),  # not traded
        kill(0, 31_000, "r2", "b3"),
        kill(0, 32_000, "r2", "b4"),  # b5 left 1v4
        kill(0, 50_000, "r3", "b5"),
    ] + [kill(1, 5_000 + i * 1000, "b1", r) for i, r in enumerate(RED)]  # b1 5K
    players = [{"puuid": p, "name": p.upper(), "tag": "TST", "team_id": "Red" if p in RED else "Blue",
                "agent": {"name": "Jett"}, "tier": {"name": "Gold 2"}, "party_id": "",
                "stats": {"score": 300, "kills": 1, "deaths": 1, "assists": 0, "headshots": 1, "bodyshots": 3,
                          "legshots": 0}, "ability_casts": {"ultimate": 1}} for p in RED + BLUE]
    return {"status": 200, "data": {
        "metadata": {"match_id": "m1", "map": {"name": "Ascent"}, "queue": {"id": "competitive"},
                     "game_length_in_ms": 120_000, "started_at": "2026-11-02T20:00:00Z", "region": "eu"},
        "players": players,
        "teams": [{"team_id": "Red", "won": False, "rounds": {"won": 1, "lost": 1}},
                  {"team_id": "Blue", "won": False, "rounds": {"won": 1, "lost": 1}}],
        "rounds": [
            {"id": 0, "result": "Elimination", "winning_team": "Red", "stats": round_stats(800),
             "plant": {"round_time_in_ms": 40_000, "site": "A", "player": ref("r3")}, "defuse": None},
            {"id": 1, "result": "Elimination", "winning_team": "Blue", "stats": round_stats(1500),
             "plant": None, "defuse": None},
        ],
        "kills": kills}}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.match = henrik.to_match(payload())
        self.a = analyze(self.match, ME)
        self.rows = {r["player"]: r for r in self.a.player_rows}

    def test_adapter(self):
        self.assertEqual([r.number for r in self.match.rounds], [1, 2])
        self.assertEqual([r.attacking_team for r in self.match.rounds], ["Red", "Red"])  # Red planted in first half
        self.assertEqual(len(self.match.rounds[0].kills), 6)

    def test_trades_and_first_blood(self):
        k = self.match.rounds[0].kills
        self.assertTrue(k[0].first_blood and k[0].traded)
        self.assertEqual(k[1].trade_of, 0)
        self.assertFalse(k[2].traded)

    def test_player_stats(self):
        you = self.rows["You"]
        self.assertEqual(you["clutch"], "0/1")  # b5 left 1v4, lost
        self.assertEqual(you["kast"], 50)  # died untraded in R1, survived R2
        self.assertEqual(you["adr"], 50)
        self.assertEqual(you["hs"], 25)
        b1 = next(r for r in self.a.player_rows if r["multi"] == "5K:1")
        self.assertEqual(b1["fd"], 1)
        self.assertIn("R01.CLUTCH.You", self.a.facts)

    def test_team_stats(self):
        us = next(r for r in self.a.team_rows if r["team"] == "Your team")
        self.assertEqual(us["pistols"], "0/1 (0%)")
        self.assertEqual(us["defense"], "1/2 (50%)")
        self.assertEqual(us["retake"], "0/1 (0%)")

    def test_validator(self):
        fb = Feedback(
            summary="You were left 1v4 in round 1 and lost.", summary_evidence=["R01.CLUTCH.You"],
            key_findings=[Finding(title="Fake", explanation="Ally9 won 7 clutches", evidence=["R01.CLUTCH.You"]),
                          Finding(title="Bad id", explanation="x", evidence=["R99.K1"])],
            improvements=[Improvement(priority=1, action="Trade faster", why="Your KAST was 50%.",
                                      evidence=["P:You"]),
                          Improvement(priority=2, action="Invented", why="You had 83% KAST", evidence=["P:You"])],
            round_notes=[RoundNote(round=1, note="First blood at 0:10 was traded at 0:12.",
                                   evidence=["R01.K1", "R01.K2"]),
                         RoundNote(round=40, note="no such round", evidence=["R01.K1"])])
        out, failures, total = validate(fb, self.a)
        self.assertEqual(total, 7)
        self.assertEqual(len(failures), 4, failures)
        self.assertTrue(out.summary)
        self.assertEqual(out.key_findings, [])
        self.assertEqual([i.action for i in out.improvements], ["Trade faster"])
        self.assertEqual([r.round for r in out.round_notes], [1])

    def test_unsupported_mode(self):
        p = payload()
        p["data"]["metadata"]["queue"]["id"] = "deathmatch"
        with self.assertRaises(henrik.FetchError):
            henrik.to_match(p)


if __name__ == "__main__":
    unittest.main()
