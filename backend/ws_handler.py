import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.enums import GameState, NARRATOR_SCRIPTS, NO_ACTION_ROLES, RoleType
from backend.game_logic import (
    assign_roles,
    build_action_prompt,
    process_night_action,
    resolve_votes,
)
from backend.game_manager import game_manager
from backend.models import Player, PlayerInfo
from backend.websocket_manager import ws_manager

router = APIRouter(tags=["websocket"])

# Tracks the asyncio.Task running auto_end_day so the host can cancel it
_day_timer_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/{player_id}")
async def websocket_endpoint(ws: WebSocket, player_id: str):
    if not game_manager.player_exists(player_id):
        await ws.close(code=4004, reason="Player not found")
        return

    await ws_manager.connect(player_id, ws)
    player = game_manager.reconnect_player(player_id)

    # Announce to everyone else
    await ws_manager.broadcast_except(player_id, {
        "type": "player_connected",
        "player_id": player_id,
        "name": player.name,
    })

    # Send full state snapshot so reconnecting clients can restore their UI
    await _send_state_snapshot(player_id)

    try:
        while True:
            data = await ws.receive_json()
            await _handle_message(player_id, data)
    except WebSocketDisconnect:
        ws_manager.disconnect(player_id)
        game_manager.disconnect_player(player_id)
        await ws_manager.broadcast({
            "type": "player_disconnected",
            "player_id": player_id,
            "name": player.name,
        })


# ---------------------------------------------------------------------------
# Incoming message dispatch
# ---------------------------------------------------------------------------

async def _handle_message(player_id: str, data: dict) -> None:
    msg_type = data.get("type")

    match msg_type:
        case "ping":
            await ws_manager.send(player_id, {"type": "pong"})

        case "start_game":
            await _handle_start_game(player_id)

        case "configure_roles":
            await _handle_configure_roles(player_id, data.get("roles", []))

        case "kick_player":
            await _handle_kick(player_id, data.get("target_player_id"))

        case "reset":
            await _handle_reset()

        case "night_action":
            await _handle_night_action(player_id, data.get("targets", []))

        case "night_skip":
            await _handle_night_skip(player_id)

        case "end_day":
            await _handle_end_day(player_id)

        case "vote":
            await _handle_vote(player_id, data.get("target_player_id"))


# ---------------------------------------------------------------------------
# Game control handlers (any player may call these)
# ---------------------------------------------------------------------------

async def _handle_configure_roles(player_id: str, roles: list[str]) -> None:
    game = game_manager.game
    if game.state != GameState.LOBBY:
        await ws_manager.send(player_id, {"type": "error", "message": "Game already started"})
        return

    from backend.enums import RoleType as RT
    try:
        role_list = [RT(r) for r in roles]
    except ValueError as e:
        await ws_manager.send(player_id, {"type": "error", "message": str(e)})
        return

    num_players = len(game.players)
    required = num_players + 3
    if len(role_list) != required:
        await ws_manager.send(player_id, {
            "type": "error",
            "message": f"Need {required} roles ({num_players} players + 3 center). Got {len(role_list)}.",
        })
        return

    game.selected_roles = role_list
    await ws_manager.broadcast({
        "type": "roles_configured",
        "roles": [r.value for r in role_list],
    })


async def _handle_start_game(player_id: str) -> None:
    game = game_manager.game
    if game.state != GameState.LOBBY:
        await ws_manager.send(player_id, {"type": "error", "message": "Game already started"})
        return

    players = game_manager.ordered_players()
    if len(players) < 3:
        await ws_manager.send(player_id, {"type": "error", "message": "Need at least 3 players"})
        return

    required = len(players) + 3
    if len(game.selected_roles) != required:
        await ws_manager.send(player_id, {
            "type": "error",
            "message": f"Configure exactly {required} roles before starting.",
        })
        return

    game.state = GameState.NIGHT
    assign_roles(game, players)

    await ws_manager.broadcast({"type": "game_started"})

    # Send each player their secret role
    for p in players:
        await ws_manager.send(p.player_id, {
            "type": "role_assigned",
            "role": p.original_role.value,
        })

    asyncio.create_task(run_night_phase())


async def _handle_kick(player_id: str, target_id: str | None) -> None:
    if not target_id:
        return
    try:
        kicked = game_manager.kick(target_id)
    except KeyError:
        await ws_manager.send(player_id, {"type": "error", "message": "Player not found"})
        return

    ws_manager.disconnect(target_id)
    await ws_manager.broadcast({
        "type": "player_kicked",
        "player_id": target_id,
        "name": kicked.name,
        "players": _serialise_players(),
    })


async def _handle_reset() -> None:
    global _day_timer_task
    if _day_timer_task and not _day_timer_task.done():
        _day_timer_task.cancel()
        _day_timer_task = None

    game_manager.reset()
    await ws_manager.broadcast({
        "type": "game_reset",
        "players": _serialise_players(),
    })


# ---------------------------------------------------------------------------
# Night phase
# ---------------------------------------------------------------------------

async def run_night_phase() -> None:
    game = game_manager.game

    for role in game.night_order:
        await ws_manager.broadcast({
            "type": "night_phase_begin",
            "active_role": role.value,
            "message": "🌙 Night is in progress... wait for your turn.",
        })

        acting = [p for p in game.players.values() if p.original_role == role]

        if not acting:
            await asyncio.sleep(2)
            await ws_manager.broadcast({
                "type": "night_role_done",
                "active_role": role.value,
                "message": NARRATOR_SCRIPTS[role]["sleep"],
            })
            continue

        # Villagers: auto-complete, no review needed
        if role in NO_ACTION_ROLES:
            for p in acting:
                p.night_action_done = True

        # Roles that are auto-computed (no card selection) but player must read and tap Continue
        elif role in {RoleType.MINION, RoleType.INSOMNIAC}:
            for p in acting:
                prompt = build_action_prompt(game, p)
                await ws_manager.send(p.player_id, {"type": "night_action_prompt", **prompt})
                result = process_night_action(game, p, [])
                game.night_results[p.player_id] = result
                await ws_manager.send(p.player_id, {
                    "type": "night_action_result",
                    "revealed": result,
                    "needs_ready": True,
                })

        # Werewolves: auto-reveal teammates; lone wolf picks a card
        elif role == RoleType.WEREWOLF:
            for p in acting:
                prompt = build_action_prompt(game, p)
                await ws_manager.send(p.player_id, {"type": "night_action_prompt", **prompt})
                if not prompt.get("lone_wolf", False):
                    result = process_night_action(game, p, [])
                    game.night_results[p.player_id] = result
                    await ws_manager.send(p.player_id, {
                        "type": "night_action_result",
                        "revealed": result,
                        "needs_ready": True,
                    })
                # Lone wolf: waits for _handle_night_action (card pick)

        # All other roles: player selects a target, then sees result and taps Continue
        else:
            for p in acting:
                prompt = build_action_prompt(game, p)
                await ws_manager.send(p.player_id, {"type": "night_action_prompt", **prompt})

        await _wait_for_actions(acting, timeout=60)

        await asyncio.sleep(1)
        await ws_manager.broadcast({
            "type": "night_role_done",
            "active_role": role.value,
            "message": "🌙 Night is in progress... wait for your turn.",
        })
        await asyncio.sleep(1)

    # Transition to DAY
    game.state = GameState.DAY
    end_time = time.time() + 300  # 5-minute discussion
    game.day_end_time = end_time
    await ws_manager.broadcast({
        "type": "day_phase_begin",
        "discussion_end_time": end_time,
        "players": _serialise_players(),
    })

    global _day_timer_task
    _day_timer_task = asyncio.create_task(_auto_end_day(end_time))


async def _wait_for_actions(players: list[Player], timeout: float = 45) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if all(p.night_action_done for p in players):
            return
        if asyncio.get_event_loop().time() >= deadline:
            for p in players:
                p.night_action_done = True
            return
        await asyncio.sleep(0.2)


async def _handle_night_action(player_id: str, targets: list[str]) -> None:
    game = game_manager.game
    if game.state != GameState.NIGHT:
        return

    player = game_manager.get_player(player_id)
    if player.night_action_done:
        return
    if not player.original_role:
        return
    # Already processed (auto-compute roles): ignore
    if player_id in game.night_results:
        return

    # Lone wolf skipping the peek: just show "lone wolf" message and wait for Continue
    if player.original_role == RoleType.WEREWOLF and not targets:
        result: dict = {"werewolf_teammates": [], "skipped_peek": True}
        game.night_results[player_id] = result
        await ws_manager.send(player_id, {
            "type": "night_action_result",
            "revealed": result,
            "needs_ready": True,
        })
        return

    result = process_night_action(game, player, targets)
    game.night_results[player_id] = result

    # Send result immediately; player taps Continue (night_skip) to proceed
    await ws_manager.send(player_id, {
        "type": "night_action_result",
        "revealed": result,
        "needs_ready": True,
    })
    # night_action_done is set by _handle_night_skip (the Continue tap)


async def _handle_night_skip(player_id: str) -> None:
    game = game_manager.game
    if game.state != GameState.NIGHT:
        return
    player = game_manager.get_player(player_id)
    player.night_action_done = True


# ---------------------------------------------------------------------------
# Day / voting
# ---------------------------------------------------------------------------

async def _auto_end_day(end_time: float) -> None:
    delay = max(0.0, end_time - time.time())
    await asyncio.sleep(delay)
    game = game_manager.game
    if game.state == GameState.DAY:
        await _start_voting()


async def _handle_end_day(player_id: str) -> None:
    global _day_timer_task
    game = game_manager.game
    if game.state != GameState.DAY:
        return
    if _day_timer_task and not _day_timer_task.done():
        _day_timer_task.cancel()
    await _start_voting()


async def _start_voting() -> None:
    game = game_manager.game
    game.state = GameState.VOTING
    await ws_manager.broadcast({
        "type": "voting_begin",
        "players": _serialise_players(),
    })


async def _handle_vote(player_id: str, target_id: str | None) -> None:
    game = game_manager.game
    if game.state != GameState.VOTING or not target_id:
        return

    player = game_manager.get_player(player_id)
    if player.vote_target:
        return  # already voted

    player.vote_target = target_id

    votes_cast = sum(1 for p in game.players.values() if p.vote_target)
    total = len(game.players)
    await ws_manager.broadcast({
        "type": "vote_cast",
        "count": votes_cast,
        "total": total,
    })

    if votes_cast == total:
        await _finish_game()


async def _finish_game() -> None:
    game = game_manager.game
    eliminated, win_team = resolve_votes(game)
    game.state = GameState.RESULTS

    player_names = {pid: p.name for pid, p in game.players.items()}
    final_roles = {
        pid: p.current_role.value
        for pid, p in game.players.items()
        if p.current_role
    }
    votes = {
        pid: p.vote_target
        for pid, p in game.players.items()
        if p.vote_target
    }

    await ws_manager.broadcast({
        "type": "results",
        "eliminated": eliminated,
        "win_team": win_team.value,
        "final_roles": final_roles,
        "original_roles": {
            pid: p.original_role.value
            for pid, p in game.players.items()
            if p.original_role
        },
        "player_names": player_names,
        "votes": votes,
        "center_cards": [c.value for c in game.center_cards],
    })


# ---------------------------------------------------------------------------
# State snapshot (for reconnecting clients)
# ---------------------------------------------------------------------------

async def _send_state_snapshot(player_id: str) -> None:
    game = game_manager.game
    player = game_manager.get_player(player_id)

    snapshot: dict = {
        "type": "state_snapshot",
        "state": game.state.value,
        "players": _serialise_players(),
        "selected_roles": [r.value for r in game.selected_roles],
        "your_role": player.original_role.value if player.original_role else None,
        "seat": player.seat,
        "night_action_done": player.night_action_done,
    }

    # If it's night and it's currently their turn, resend the prompt
    if game.state == GameState.NIGHT and not player.night_action_done and player.original_role:
        prompt = build_action_prompt(game, player)
        snapshot["pending_prompt"] = prompt

    if game.state == GameState.DAY:
        snapshot["discussion_end_time"] = game.day_end_time

    if game.state == GameState.RESULTS:
        snapshot["eliminated"] = game.eliminated_players
        snapshot["win_team"] = game.win_team.value if game.win_team else None
        snapshot["final_roles"] = {
            pid: p.current_role.value for pid, p in game.players.items() if p.current_role
        }
        snapshot["original_roles"] = {
            pid: p.original_role.value for pid, p in game.players.items() if p.original_role
        }
        snapshot["votes"] = {pid: p.vote_target for pid, p in game.players.items() if p.vote_target}
        snapshot["center_cards"] = [c.value for c in game.center_cards]
        snapshot["player_names"] = {pid: p.name for pid, p in game.players.items()}

    await ws_manager.send(player_id, snapshot)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialise_players() -> list[dict]:
    return [
        {
            "player_id": p.player_id,
            "name": p.name,
            "seat": p.seat,
            "is_connected": p.is_connected,
        }
        for p in game_manager.ordered_players()
    ]
