const handlers = {};
let ws = null;
let reconnectTimer = null;
let currentPlayerId = null;

export function on(type, handler) {
  handlers[type] = handler;
}

export function connect(playerId) {
  currentPlayerId = playerId;
  _open();
}

export function send(event) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(event));
  }
}

export function disconnect() {
  currentPlayerId = null;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (ws) ws.close();
  ws = null;
}

function _open() {
  if (!currentPlayerId) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocol}://${location.host}/ws/${currentPlayerId}`);

  ws.onopen = () => {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  };

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      const handler = handlers[data.type];
      if (handler) handler(data);
    } catch (e) {
      console.error("WS parse error", e);
    }
  };

  ws.onclose = () => {
    if (currentPlayerId) {
      // Auto-reconnect with backoff
      reconnectTimer = setTimeout(_open, 2000);
    }
  };

  ws.onerror = () => ws.close();
}
