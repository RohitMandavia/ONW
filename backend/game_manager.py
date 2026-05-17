import secrets

from backend.enums import GameState
from backend.models import Game, Player


class GameManager:
    """
    Single in-memory game instance. Only one group plays at a time.
    Any player can kick others, configure roles, start, or reset.
    """

    def __init__(self) -> None:
        self._game: Game = Game()
        self._players: dict[str, Player] = {}  # player_id -> Player
        self._next_seat: int = 0

    # ------------------------------------------------------------------
    # Player lifecycle
    # ------------------------------------------------------------------

    def join(self, player_name: str) -> Player:
        """Add a player and return them. Creates a fresh game if none exists."""
        if self._game.state != GameState.LOBBY:
            raise ValueError("A game is already in progress. Ask someone to reset.")

        player = Player(
            player_id=secrets.token_hex(8),
            name=player_name.strip(),
            seat=self._next_seat,
        )
        self._next_seat += 1
        self._game.players[player.player_id] = player
        self._players[player.player_id] = player
        return player

    def kick(self, target_player_id: str) -> Player:
        """Remove a player. Any player may kick any other player."""
        player = self._require_player(target_player_id)
        del self._game.players[target_player_id]
        del self._players[target_player_id]
        # Re-assign seat indices to stay contiguous
        for i, p in enumerate(self.ordered_players()):
            p.seat = i
        self._next_seat = len(self._players)
        return player

    def reconnect_player(self, player_id: str) -> Player:
        player = self._players.get(player_id)
        if not player:
            raise KeyError(f"Player {player_id} not found")
        player.is_connected = True
        return player

    def disconnect_player(self, player_id: str) -> None:
        player = self._players.get(player_id)
        if player:
            player.is_connected = False

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Wipe the game entirely and return to an empty lobby."""
        self._game = Game()
        self._players = {}
        self._next_seat = 0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def game(self) -> Game:
        return self._game

    def get_player(self, player_id: str) -> Player:
        return self._require_player(player_id)

    def player_exists(self, player_id: str) -> bool:
        return player_id in self._players

    def ordered_players(self) -> list[Player]:
        """Players sorted by seat index — consistent order on all clients."""
        return sorted(self._game.players.values(), key=lambda p: p.seat)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_player(self, player_id: str) -> Player:
        player = self._players.get(player_id)
        if not player:
            raise KeyError(f"Player {player_id} not found")
        return player


# Module-level singleton
game_manager = GameManager()
