import random

from backend.enums import NIGHT_ORDER, RoleType, WinTeam
from backend.models import Game, Player


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------

def assign_roles(game: Game, players: list[Player]) -> None:
    """
    Shuffle selected_roles, deal one to each player (in seat order),
    put the remaining 3 in center_cards. Build the active night_order.
    """
    roles = game.selected_roles.copy()
    random.shuffle(roles)

    for i, player in enumerate(players):
        player.original_role = roles[i]
        player.current_role = roles[i]

    game.center_cards = roles[len(players):]

    # Only include roles that at least one player holds
    active_original_roles = {p.original_role for p in players}
    game.night_order = [r for r in NIGHT_ORDER if r in active_original_roles]


# ---------------------------------------------------------------------------
# Night action processors
# Each returns a dict that is sent back to the acting player as revealed info.
# Side effects: may swap current_role fields on players / center_cards.
# ---------------------------------------------------------------------------

def process_night_action(
    game: Game,
    acting_player: Player,
    targets: list[str],  # player_ids or "center_0" / "center_1" / "center_2"
) -> dict:
    role = acting_player.original_role
    match role:
        case RoleType.WEREWOLF:
            return _werewolf_action(game, acting_player)
        case RoleType.MINION:
            return _minion_action(game)
        case RoleType.SEER:
            return _seer_action(game, targets)
        case RoleType.ROBBER:
            return _robber_action(game, acting_player, targets)
        case RoleType.TROUBLEMAKER:
            return _troublemaker_action(game, targets)
        case RoleType.DRUNK:
            return _drunk_action(game, acting_player)
        case RoleType.INSOMNIAC:
            return {"your_current_role": acting_player.current_role}
        case _:
            return {}


def build_action_prompt(game: Game, player: Player) -> dict:
    """
    Returns the payload for a night_action_prompt WS event.
    Describes which targets are selectable and what the action does.
    """
    role = player.original_role
    other_player_ids = [
        pid for pid in game.players if pid != player.player_id
    ]

    match role:
        case RoleType.WEREWOLF:
            werewolf_ids = [
                pid for pid, p in game.players.items()
                if p.original_role == RoleType.WEREWOLF and pid != player.player_id
            ]
            # Lone wolf may peek at one center card
            lone_wolf = len(werewolf_ids) == 0
            return {
                "action_type": "view_werewolves",
                "message": (
                    "You are alone. You may peek at one center card."
                    if lone_wolf
                    else "These are your fellow werewolves."
                ),
                "selectable_players": [] if not lone_wolf else [],
                "selectable_center": [0, 1, 2] if lone_wolf else [],
                "pick_count": 1 if lone_wolf else 0,
                "werewolf_ids": werewolf_ids,
                "lone_wolf": lone_wolf,
            }

        case RoleType.MINION:
            werewolf_ids = [
                pid for pid, p in game.players.items()
                if p.original_role == RoleType.WEREWOLF
            ]
            return {
                "action_type": "view_werewolves",
                "message": "You are the Minion. These players are werewolves.",
                "werewolf_ids": werewolf_ids,
                "selectable_players": [],
                "selectable_center": [],
                "pick_count": 0,
                "lone_wolf": False,
            }

        case RoleType.SEER:
            return {
                "action_type": "view_player_card",
                "message": "Look at one player's card, or two center cards.",
                "selectable_players": other_player_ids,
                "selectable_center": [0, 1, 2],
                "pick_count": 1,
                "allow_center_pair": True,
            }

        case RoleType.ROBBER:
            return {
                "action_type": "swap_with_player",
                "message": "Swap your card with another player's card and see your new role.",
                "selectable_players": other_player_ids,
                "selectable_center": [],
                "pick_count": 1,
            }

        case RoleType.TROUBLEMAKER:
            return {
                "action_type": "swap_two_players",
                "message": "Swap the cards of two other players (without looking).",
                "selectable_players": other_player_ids,
                "selectable_center": [],
                "pick_count": 2,
            }

        case RoleType.DRUNK:
            return {
                "action_type": "take_center_card",
                "message": "Swap your card with a center card. You won't know your new role.",
                "selectable_players": [],
                "selectable_center": [0, 1, 2],
                "pick_count": 1,
            }

        case RoleType.INSOMNIAC:
            return {
                "action_type": "view_own_card",
                "message": "Look at your card — it may have changed during the night.",
                "selectable_players": [],
                "selectable_center": [],
                "pick_count": 0,
            }

        case _:
            return {
                "action_type": "no_action",
                "message": "You have no night action. The village is counting on you.",
                "selectable_players": [],
                "selectable_center": [],
                "pick_count": 0,
            }


# ---------------------------------------------------------------------------
# Individual role action helpers
# ---------------------------------------------------------------------------

def _werewolf_action(game: Game, acting_player: Player) -> dict:
    teammates = [
        {"player_id": pid, "name": p.name}
        for pid, p in game.players.items()
        if p.original_role == RoleType.WEREWOLF and pid != acting_player.player_id
    ]
    return {"werewolf_teammates": teammates}


def _minion_action(game: Game) -> dict:
    werewolves = [
        {"player_id": pid, "name": p.name}
        for pid, p in game.players.items()
        if p.original_role == RoleType.WEREWOLF
    ]
    return {"werewolves": werewolves}


def _seer_action(game: Game, targets: list[str]) -> dict:
    if len(targets) == 1:
        t = targets[0]
        if t.startswith("center_"):
            idx = int(t.split("_")[1])
            return {"center_card": {t: game.center_cards[idx]}}
        player = game.players[t]
        return {"player_card": {"player_id": t, "name": player.name, "role": player.current_role}}

    # Two center cards
    result = {}
    for t in targets[:2]:
        idx = int(t.split("_")[1])
        result[t] = game.center_cards[idx]
    return {"center_cards": result}


def _robber_action(game: Game, acting_player: Player, targets: list[str]) -> dict:
    target_id = targets[0]
    target = game.players[target_id]
    acting_player.current_role, target.current_role = target.current_role, acting_player.current_role
    return {"your_new_role": acting_player.current_role, "swapped_with": target.name}


def _troublemaker_action(game: Game, targets: list[str]) -> dict:
    a, b = game.players[targets[0]], game.players[targets[1]]
    a.current_role, b.current_role = b.current_role, a.current_role
    return {"swapped": [a.name, b.name]}


def _drunk_action(game: Game, acting_player: Player) -> dict:
    idx = random.randrange(len(game.center_cards))
    game.center_cards[idx], acting_player.current_role = (
        acting_player.current_role,
        game.center_cards[idx],
    )
    # Drunk does not learn what they got
    return {"message": f"You swapped with center card {idx + 1}. You don't know your new role."}


# ---------------------------------------------------------------------------
# Voting and win condition
# ---------------------------------------------------------------------------

def resolve_votes(game: Game) -> tuple[list[str], WinTeam]:
    """
    Tally votes, eliminate the most-voted player(s).
    Hunter special: if Hunter is eliminated, their vote target also dies.
    Returns (eliminated_player_ids, win_team).
    """
    vote_counts: dict[str, int] = {}
    for player in game.players.values():
        if player.vote_target:
            vote_counts[player.vote_target] = vote_counts.get(player.vote_target, 0) + 1

    if not vote_counts:
        eliminated: list[str] = []
    else:
        max_votes = max(vote_counts.values())
        eliminated = [pid for pid, count in vote_counts.items() if count == max_votes]

    # Hunter: if eliminated, drag their vote target along
    for pid in list(eliminated):
        player = game.players.get(pid)
        if player and player.current_role == RoleType.HUNTER and player.vote_target:
            if player.vote_target not in eliminated:
                eliminated.append(player.vote_target)

    game.eliminated_players = eliminated
    game.win_team = determine_winner(game, eliminated)
    return eliminated, game.win_team


def determine_winner(game: Game, eliminated: list[str]) -> WinTeam:
    werewolf_ids = [
        pid for pid, p in game.players.items()
        if p.current_role == RoleType.WEREWOLF
    ]
    if not werewolf_ids:
        # No werewolves in game: village wins only if at least one person is eliminated
        return WinTeam.VILLAGE if eliminated else WinTeam.WEREWOLF

    werewolf_eliminated = any(pid in eliminated for pid in werewolf_ids)
    return WinTeam.VILLAGE if werewolf_eliminated else WinTeam.WEREWOLF
