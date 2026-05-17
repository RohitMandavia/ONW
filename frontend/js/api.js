async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return r.json();
}

async function put(path, body) {
  const r = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return r.json();
}

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return r.json();
}

export const api = {
  join: (playerName) => post("/api/lobby/join", { player_name: playerName }),
  getLobby: () => get("/api/lobby/state"),
  setRoles: (roles) => put("/api/lobby/roles", { roles }),
  kick: (targetPlayerId) => post("/api/lobby/kick", { target_player_id: targetPlayerId }),
  reset: () => post("/api/lobby/reset", {}),
  reconnect: (playerId) => get(`/api/game/reconnect?player_id=${playerId}`),
};
