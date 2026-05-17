from fastapi import APIRouter, HTTPException, Query

from backend.enums import GameState
from backend.game_manager import game_manager
from backend.models import EndDayRequest, PlayerInfo, ReconnectResponse, VoteRequest

router = APIRouter(prefix="/api/game", tags=["game"])


@router.get("/reconnect", response_model=ReconnectResponse)
async def reconnect(player_id: str = Query(...)):
    """Called on page load to restore session from localStorage."""
    if not game_manager.player_exists(player_id):
        raise HTTPException(404, "Player not found — session expired")

    game = game_manager.game
    player = game_manager.get_player(player_id)

    return ReconnectResponse(
        state=game.state,
        your_role=player.original_role,
        players=[
            PlayerInfo(
                player_id=p.player_id,
                name=p.name,
                seat=p.seat,
                is_connected=p.is_connected,
            )
            for p in game_manager.ordered_players()
        ],
        selected_roles=game.selected_roles,
        night_action_done=player.night_action_done,
        seat=player.seat,
    )


@router.post("/vote")
async def vote(body: VoteRequest):
    game = game_manager.game
    if game.state != GameState.VOTING:
        raise HTTPException(400, "Not in voting phase")

    if not game_manager.player_exists(body.player_id):
        raise HTTPException(404, "Player not found")
    if not game_manager.player_exists(body.target_player_id):
        raise HTTPException(404, "Target player not found")

    player = game_manager.get_player(body.player_id)
    if player.vote_target:
        raise HTTPException(400, "Already voted")

    player.vote_target = body.target_player_id
    return {"ok": True}
