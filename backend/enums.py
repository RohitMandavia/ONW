from enum import Enum


class GameState(str, Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    RESULTS = "results"


class RoleType(str, Enum):
    WEREWOLF = "werewolf"
    VILLAGER = "villager"
    SEER = "seer"
    ROBBER = "robber"
    TROUBLEMAKER = "troublemaker"
    DRUNK = "drunk"
    INSOMNIAC = "insomniac"
    MINION = "minion"
    HUNTER = "hunter"


class NightActionType(str, Enum):
    VIEW_PLAYER_CARD = "view_player_card"
    VIEW_CENTER_CARDS = "view_center_cards"
    SWAP_WITH_PLAYER = "swap_with_player"
    SWAP_TWO_PLAYERS = "swap_two_players"
    TAKE_CENTER_CARD = "take_center_card"
    VIEW_OWN_CARD = "view_own_card"
    VIEW_WEREWOLVES = "view_werewolves"
    NO_ACTION = "no_action"


class WinTeam(str, Enum):
    VILLAGE = "village"
    WEREWOLF = "werewolf"


# Fixed canonical night order; filtered to roles present in a given game
NIGHT_ORDER: list[RoleType] = [
    RoleType.WEREWOLF,
    RoleType.MINION,
    RoleType.SEER,
    RoleType.ROBBER,
    RoleType.TROUBLEMAKER,
    RoleType.DRUNK,
    RoleType.INSOMNIAC,
]

# Roles that require no player input during the night phase
NO_ACTION_ROLES: set[RoleType] = {RoleType.VILLAGER}

NARRATOR_SCRIPTS: dict[RoleType, dict[str, str]] = {
    RoleType.WEREWOLF: {
        "wake": "Werewolves, open your eyes and look for other werewolves.",
        "sleep": "Werewolves, close your eyes.",
    },
    RoleType.MINION: {
        "wake": "Minion, open your eyes. Werewolves, put your thumbs up so the Minion can see you.",
        "sleep": "Minion, close your eyes. Werewolves, put your thumbs down.",
    },
    RoleType.SEER: {
        "wake": "Seer, open your eyes. You may look at one player's card, or two of the center cards.",
        "sleep": "Seer, close your eyes.",
    },
    RoleType.ROBBER: {
        "wake": "Robber, open your eyes. You may exchange your card with another player's card, then look at your new card.",
        "sleep": "Robber, close your eyes.",
    },
    RoleType.TROUBLEMAKER: {
        "wake": "Troublemaker, open your eyes. You may exchange cards between two other players.",
        "sleep": "Troublemaker, close your eyes.",
    },
    RoleType.DRUNK: {
        "wake": "Drunk, open your eyes. You must exchange your card with one of the center cards.",
        "sleep": "Drunk, close your eyes.",
    },
    RoleType.INSOMNIAC: {
        "wake": "Insomniac, open your eyes and look at your card.",
        "sleep": "Insomniac, close your eyes.",
    },
    RoleType.VILLAGER: {
        "wake": "Everyone is sleeping peacefully...",
        "sleep": "",
    },
    RoleType.HUNTER: {
        "wake": "",
        "sleep": "",
    },
}
