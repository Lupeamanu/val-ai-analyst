"""Normalized match representation. Every input source is converted to this; analysis never sees raw API JSON."""
from dataclasses import dataclass, field


@dataclass
class Player:
    puuid: str
    name: str  # Riot ID "Name#Tag"; never sent to the LLM
    team: str
    agent: str
    tier: str
    party_id: str
    score: int
    kills: int
    deaths: int
    assists: int
    headshots: int
    bodyshots: int
    legshots: int
    ult_casts: int | None


@dataclass
class Economy:
    loadout_value: int
    remaining: int
    weapon: str | None
    armor: str | None


@dataclass
class Kill:
    round: int  # 1-based
    time_ms: int  # since round start
    killer: str  # puuid
    victim: str
    assistants: list[str]
    weapon: str | None
    # derived by metrics.annotate()
    first_blood: bool = False
    trade_of: int | None = None  # index (within round) of the kill this one avenged
    traded: bool = False  # victim's death was avenged within TRADE_WINDOW_MS


@dataclass
class BombEvent:
    player: str
    time_ms: int
    site: str | None


@dataclass
class Round:
    number: int  # 1-based
    winning_team: str
    end_type: str  # Henrik "result", e.g. Elimination / Bomb detonated / Bomb defused / Round timer expired / Surrendered
    attacking_team: str
    plant: BombEvent | None
    defuse: BombEvent | None
    economy: dict[str, Economy]
    damage: dict[str, int]  # puuid -> damage dealt this round
    kills: list[Kill] = field(default_factory=list)
    afk: set[str] = field(default_factory=set)


@dataclass
class Match:
    match_id: str
    map: str
    mode: str
    started_at: str
    length_ms: int
    region: str
    source: str
    teams: dict[str, int]  # team_id -> rounds won
    players: dict[str, Player]
    rounds: list[Round]

    def team_of(self, puuid: str) -> str:
        return self.players[puuid].team
