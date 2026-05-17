const SESSION_KEY = "onw_session";

export function saveSession(playerId, playerName) {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ player_id: playerId, player_name: playerName }));
}

export function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}
