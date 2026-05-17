from fastapi import APIRouter, HTTPException

from backend.game_manager import game_manager
from backend.models import (
    ConfigureRolesRequest,
    JoinRequest,
    JoinResponse,
    KickRequest,
    LobbyStateResponse,
    PlayerInfo,
)

router = APIRouter(prefix="/api/lobby", tags=["lobby"])


@router.post("/join", response_model=JoinResponse)
async def join(body: JoinRequest):
    if not body.player_name.strip():
        raise HTTPException(400, "player_name cannot be empty")
    try:
        player = game_manager.join(body.player_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JoinResponse(player_id=player.player_id)


@router.get("/state", response_model=LobbyStateResponse)
async def get_state():
    game = game_manager.game
    return LobbyStateResponse(
        state=game.state,
        players=_player_list(),
        selected_roles=game.selected_roles,
    )


@router.put("/roles")
async def configure_roles(body: ConfigureRolesRequest):
    game = game_manager.game
    num_players = len(game.players)
    required = num_players + 3
    if len(body.roles) != required:
        raise HTTPException(
            400,
            f"Need exactly {required} roles for {num_players} players "
            f"(players + 3 center cards). Got {len(body.roles)}.",
        )
    game.selected_roles = list(body.roles)
    return {"ok": True, "selected_roles": game.selected_roles}


@router.post("/kick")
async def kick_player(body: KickRequest):
    try:
        game_manager.kick(body.target_player_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/reset")
async def reset_game():
    game_manager.reset()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _player_list() -> list[PlayerInfo]:
    return [
        PlayerInfo(
            player_id=p.player_id,
            name=p.name,
            seat=p.seat,
            is_connected=p.is_connected,
        )
        for p in game_manager.ordered_players()
    ]
