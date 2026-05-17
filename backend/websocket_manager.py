from fastapi import WebSocket


class WebSocketManager:
    """Registry of active WebSocket connections keyed by player_id."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, player_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[player_id] = ws

    def disconnect(self, player_id: str) -> None:
        self._connections.pop(player_id, None)

    async def send(self, player_id: str, event: dict) -> None:
        ws = self._connections.get(player_id)
        if ws:
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(player_id)

    async def broadcast(self, event: dict) -> None:
        dead: list[str] = []
        for pid, ws in self._connections.items():
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(pid)
        for pid in dead:
            self.disconnect(pid)

    async def broadcast_except(self, exclude_id: str, event: dict) -> None:
        dead: list[str] = []
        for pid, ws in self._connections.items():
            if pid == exclude_id:
                continue
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(pid)
        for pid in dead:
            self.disconnect(pid)


ws_manager = WebSocketManager()
