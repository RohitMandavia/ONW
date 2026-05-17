from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from backend.enums import GameState, RoleType, WinTeam


# ---------------------------------------------------------------------------
# Runtime state (mutable dataclasses)
# ---------------------------------------------------------------------------

@dataclass
class Player:
    player_id: str
    name: str
    # Join order index — used to place player consistently around the table
    seat: int = 0
    original_role: Optional[RoleType] = None
    current_role: Optional[RoleType] = None
    is_connected: bool = True
    vote_target: Optional[str] = None
    night_action_done: bool = False


@dataclass
class Game:
    state: GameState = GameState.LOBBY
    # Ordered by join time (seat index)
    players: dict[str, Player] = field(default_factory=dict)
    selected_roles: list[RoleType] = field(default_factory=list)
    center_cards: list[RoleType] = field(default_factory=list)
    night_order: list[RoleType] = field(default_factory=list)
    current_night_role_index: int = 0
    day_end_time: Optional[float] = None
    eliminated_players: list[str] = field(default_factory=list)
    win_team: Optional[WinTeam] = None
    # player_id -> dict of revealed info from their night action
    night_results: dict[str, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class JoinRequest(BaseModel):
    player_name: str


class ConfigureRolesRequest(BaseModel):
    roles: list[RoleType]


class KickRequest(BaseModel):
    target_player_id: str


class VoteRequest(BaseModel):
    player_id: str
    target_player_id: str


class EndDayRequest(BaseModel):
    player_id: str


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class PlayerInfo(BaseModel):
    player_id: str
    name: str
    seat: int
    is_connected: bool


class LobbyStateResponse(BaseModel):
    state: GameState
    players: list[PlayerInfo]
    selected_roles: list[RoleType]


class JoinResponse(BaseModel):
    player_id: str


class ReconnectResponse(BaseModel):
    state: GameState
    your_role: Optional[RoleType]
    players: list[PlayerInfo]
    selected_roles: list[RoleType]
    night_action_done: bool
    seat: int
    pending_prompt: Optional[dict] = None


class ResultsResponse(BaseModel):
    eliminated: list[str]
    win_team: WinTeam
    final_roles: dict[str, str]     # player_id -> role name
    player_names: dict[str, str]    # player_id -> display name
    votes: dict[str, str]           # voter_id -> target_id
