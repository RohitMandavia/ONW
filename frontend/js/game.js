import { api } from "./api.js";
import { saveSession, loadSession, clearSession } from "./session.js";
import * as socket from "./socket.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let myPlayerId = null;
let myPlayerName = null;
let myRole = null;
let mySeat = null;
let players = [];          // [{player_id, name, seat, is_connected}] sorted by seat
let selectedRoles = [];    // currently configured role list
let villagerCount = 0;

let nightSelections = [];  // player_ids or "center_X" selected this turn
let currentPrompt = null;  // last night_action_prompt payload
let dayTimerInterval = null;
let myVoteTarget = null;

const ROLE_DESCRIPTIONS = {
  werewolf: "🐺 Werewolf",
  villager: "👤 Villager",
  seer: "👁 Seer",
  robber: "🥷 Robber",
  troublemaker: "😈 Troublemaker",
  drunk: "🍺 Drunk",
  insomniac: "😴 Insomniac",
  minion: "🎭 Minion",
  hunter: "🏹 Hunter",
};

const ROLE_EMOJI = {
  werewolf: "🐺", villager: "👤", seer: "👁", robber: "🥷",
  troublemaker: "😈", drunk: "🍺", insomniac: "😴", minion: "🎭", hunter: "🏹",
};

// ---------------------------------------------------------------------------
// Screen management
// ---------------------------------------------------------------------------
function switchScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(`screen-${id}`).classList.add("active");
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function boot() {
  const session = loadSession();
  if (session) {
    try {
      const data = await api.reconnect(session.player_id);
      myPlayerId = session.player_id;
      myPlayerName = session.player_name;
      myRole = data.your_role;
      mySeat = data.seat;
      players = data.players;
      selectedRoles = data.selected_roles;
      socket.connect(myPlayerId);
      registerSocketHandlers();
      restoreScreen(data);
      return;
    } catch {
      clearSession();
    }
  }
  switchScreen("join");
}

function restoreScreen(data) {
  switch (data.state) {
    case "lobby":   renderLobby(); switchScreen("lobby"); break;
    case "night":
      switchScreen("night");
      renderNightBase();
      if (data.pending_prompt) applyNightPrompt(data.pending_prompt);
      else showWaiting();
      break;
    case "day":
      switchScreen("day");
      renderDayScreen(data.discussion_end_time, players);
      break;
    case "voting":
      switchScreen("voting");
      renderVotingScreen(players);
      break;
    case "results":
      switchScreen("results");
      renderResultsScreen(data);
      break;
  }
}

// ---------------------------------------------------------------------------
// Join screen
// ---------------------------------------------------------------------------
document.getElementById("join-btn").addEventListener("click", async () => {
  const nameInput = document.getElementById("name-input");
  const name = nameInput.value.trim();
  if (!name) return showToast("Enter your name first");

  try {
    const data = await api.join(name);
    myPlayerId = data.player_id;
    myPlayerName = name;
    saveSession(myPlayerId, myPlayerName);
    const lobby = await api.getLobby();
    players = lobby.players;
    selectedRoles = lobby.selected_roles;
    mySeat = players.find(p => p.player_id === myPlayerId)?.seat ?? 0;
    socket.connect(myPlayerId);
    registerSocketHandlers();
    renderLobby();
    switchScreen("lobby");
  } catch (e) {
    showToast(e.message);
  }
});

// ---------------------------------------------------------------------------
// Lobby screen
// ---------------------------------------------------------------------------
function renderLobby() {
  renderPlayerList();
  renderRolePicker();
  updateStartBtn();
}

function renderPlayerList() {
  const ul = document.getElementById("player-list");
  ul.innerHTML = "";
  players.forEach(p => {
    const li = document.createElement("li");
    const isMe = p.player_id === myPlayerId;
    li.innerHTML = `
      <span>${p.name}${isMe ? " <em>(you)</em>" : ""}</span>
      ${!isMe ? `<button class="kick-btn" title="Remove player" data-id="${p.player_id}">✕</button>` : ""}
    `;
    ul.appendChild(li);
  });

  ul.querySelectorAll(".kick-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        await api.kick(btn.dataset.id);
      } catch (e) { showToast(e.message); }
    });
  });
}

// Role picker — multi-select toggles for each role type + villager counter
const AVAILABLE_ROLES = ["werewolf", "seer", "robber", "troublemaker", "drunk", "insomniac", "minion", "hunter"];

function renderRolePicker() {
  const grid = document.getElementById("role-grid");
  grid.innerHTML = "";

  AVAILABLE_ROLES.forEach(role => {
    const btn = document.createElement("button");
    btn.dataset.role = role;
    btn.addEventListener("click", () => toggleRole(role, btn));
    _updateWerewolfBtn(btn, role);
    grid.appendChild(btn);
  });

  updateVillagerCount();
  updateRoleCountMsg();
}

function isRoleSelected(role) {
  return selectedRoles.includes(role);
}

function _updateWerewolfBtn(btn, role) {
  if (role !== "werewolf") {
    btn.className = "role-toggle" + (isRoleSelected(role) ? " selected" : "");
    btn.textContent = ROLE_DESCRIPTIONS[role];
    return;
  }
  const count = selectedRoles.filter(r => r === "werewolf").length;
  btn.className = "role-toggle" + (count > 0 ? " selected" : "");
  if (count === 0)      btn.textContent = "🐺 Werewolf";
  else if (count === 1) btn.textContent = "🐺 Werewolf ×1 → tap for ×2";
  else                  btn.textContent = "🐺 Werewolf ×2 → tap to remove";
}

function toggleRole(role, btn) {
  if (role === "werewolf") {
    // Cycle: 0 werewolves → 1 → 2 → 0
    const count = selectedRoles.filter(r => r === "werewolf").length;
    selectedRoles = selectedRoles.filter(r => r !== "werewolf" && r !== "villager");
    const newCount = (count + 1) % 3;
    for (let i = 0; i < newCount; i++) selectedRoles.push("werewolf");
    _updateWerewolfBtn(btn, "werewolf");
  } else {
    if (isRoleSelected(role)) {
      selectedRoles = selectedRoles.filter(r => r !== role && r !== "villager");
      btn.classList.remove("selected");
    } else {
      selectedRoles = selectedRoles.filter(r => r !== "villager");
      selectedRoles.push(role);
      btn.classList.add("selected");
    }
  }
  autoFillVillagers();
}

// Recalculate villager count to fill remaining slots, update selectedRoles, then sync UI.
function autoFillVillagers() {
  const nonVillager = selectedRoles.filter(r => r !== "villager").length;
  const total = players.length + 3;
  villagerCount = Math.max(0, total - nonVillager);
  selectedRoles = selectedRoles.filter(r => r !== "villager");
  for (let i = 0; i < villagerCount; i++) selectedRoles.push("villager");
  document.getElementById("villager-count-label").textContent = villagerCount;
  updateRoleCountMsg();
  updateStartBtn();
  pushRoles();
}

function updateVillagerCount() {
  villagerCount = selectedRoles.filter(r => r === "villager").length;
  document.getElementById("villager-count-label").textContent = villagerCount;
}

function updateRoleCountMsg() {
  const total = players.length + 3;
  const current = selectedRoles.length;
  const msg = document.getElementById("role-count-msg");
  msg.textContent = `${current} / ${total} roles selected`;
  msg.style.color = current === total ? "#4caf50" : "var(--accent)";
}

document.getElementById("villager-minus").addEventListener("click", () => {
  if (villagerCount > 0) { villagerCount--; syncVillagerRoles(); }
});
document.getElementById("villager-plus").addEventListener("click", () => {
  villagerCount++;
  syncVillagerRoles();
});

function syncVillagerRoles() {
  selectedRoles = selectedRoles.filter(r => r !== "villager");
  for (let i = 0; i < villagerCount; i++) selectedRoles.push("villager");
  document.getElementById("villager-count-label").textContent = villagerCount;
  updateRoleCountMsg();
  updateStartBtn();
  pushRoles();
}

function pushRoles() {
  // Send via WebSocket so all players see the updated roles instantly
  socket.send({ type: "configure_roles", roles: selectedRoles });
}

function updateStartBtn() {
  const total = players.length + 3;
  const current = selectedRoles.length;
  const ok = players.length >= 3 && current === total;
  document.getElementById("start-btn").disabled = !ok;
}

document.getElementById("start-btn").addEventListener("click", () => {
  socket.send({ type: "start_game" });
});

document.getElementById("reset-btn-lobby").addEventListener("click", () => {
  if (!confirm("Reset the game? Players will stay in the lobby.")) return;
  socket.send({ type: "reset" });
});

// ---------------------------------------------------------------------------
// Night screen
// ---------------------------------------------------------------------------
function renderNightBase() {
  document.getElementById("narrator-text").textContent = "Night has fallen... Everyone close your eyes.";
  const roleBanner = document.getElementById("your-role-banner");
  if (myRole) {
    roleBanner.innerHTML = `Your role: <span class="role-label">${ROLE_DESCRIPTIONS[myRole] || myRole}</span>`;
  }
  renderTable();
}

function showWaiting() {
  document.getElementById("action-panel").style.display = "none";
  document.getElementById("action-waiting").style.display = "block";
}

function applyNightPrompt(prompt) {
  currentPrompt = prompt;
  nightSelections = [];

  document.getElementById("action-waiting").style.display = "none";
  const panel = document.getElementById("action-panel");
  panel.style.display = "block";
  document.getElementById("action-message").textContent = prompt.message;
  document.getElementById("action-submit").style.display =
    prompt.pick_count > 0 ? "block" : "none";

  // If no selection needed (e.g., minion just reads info), auto-resolve display
  if (prompt.pick_count === 0) {
    renderRevealInfo(prompt);
  }

  // Highlight selectable cards on the table
  renderTable(prompt);
}

function renderTable(prompt = null) {
  const area = document.getElementById("table-area");
  area.innerHTML = "";

  const selectable = new Set(prompt?.selectable_players || []);
  const selectableCenter = new Set((prompt?.selectable_center || []).map(i => `center_${i}`));

  // Place players around a circle
  const N = players.length;
  players.forEach((p, i) => {
    const isMe = p.player_id === myPlayerId;
    const angle = (2 * Math.PI * i) / N - Math.PI / 2;
    // Radius as fraction of container — 42% keeps cards inside
    const rx = 42, ry = 40;
    const cx = 50 + rx * Math.cos(angle);
    const cy = 50 + ry * Math.sin(angle);

    const seat = document.createElement("div");
    seat.className = "seat";
    seat.style.left = `${cx}%`;
    seat.style.top = `${cy}%`;

    const card = document.createElement("div");
    card.className = "playing-card" + (isMe ? " your-card" : "");
    card.textContent = "🂠";
    card.dataset.targetId = p.player_id;

    if (!isMe && selectable.has(p.player_id)) {
      card.classList.add("selectable");
      card.addEventListener("click", () => handleCardClick(p.player_id, card));
    }

    const name = document.createElement("div");
    name.className = "seat-name" + (isMe ? " you" : "");
    name.textContent = isMe ? `${p.name} (you)` : p.name;

    seat.appendChild(card);
    seat.appendChild(name);
    area.appendChild(seat);
  });
}

function renderCenterCards(prompt = null) {
  const area = document.getElementById("center-cards-area");
  area.innerHTML = "";
  const selectableCenter = new Set((prompt?.selectable_center || []).map(i => `center_${i}`));

  ["center_0", "center_1", "center_2"].forEach((cid, i) => {
    const wrap = document.createElement("div");
    wrap.className = "center-card-wrap";

    const card = document.createElement("div");
    card.className = "playing-card";
    card.textContent = "🂠";
    card.dataset.targetId = cid;

    if (selectableCenter.has(cid)) {
      card.classList.add("selectable");
      card.addEventListener("click", () => handleCardClick(cid, card));
    }

    const label = document.createElement("div");
    label.className = "center-label";
    label.textContent = `Center ${i + 1}`;

    wrap.appendChild(card);
    wrap.appendChild(label);
    area.appendChild(wrap);
  });
}

function handleCardClick(targetId, cardEl) {
  if (!currentPrompt) return;

  const isSeer = myRole === "seer";
  const maxPick = currentPrompt.pick_count;

  // Seer center-pair mode: if selecting center cards, need exactly 2
  const isCenter = targetId.startsWith("center_");
  const hadCenterSelection = nightSelections.some(t => t.startsWith("center_"));
  const hadPlayerSelection = nightSelections.some(t => !t.startsWith("center_"));

  // Seer switching between player and center resets selection
  if (isSeer) {
    if ((isCenter && hadPlayerSelection) || (!isCenter && hadCenterSelection)) {
      nightSelections = [];
      document.querySelectorAll(".playing-card.selected-card").forEach(c => c.classList.remove("selected-card"));
    }
  }

  // Toggle selection
  if (nightSelections.includes(targetId)) {
    nightSelections = nightSelections.filter(t => t !== targetId);
    cardEl.classList.remove("selected-card");
  } else {
    if (nightSelections.length >= maxPick && !(isSeer && isCenter && maxPick === 1)) {
      // Deselect oldest
      const old = nightSelections.shift();
      document.querySelectorAll(`[data-target-id="${old}"]`).forEach(c => c.classList.remove("selected-card"));
    }
    nightSelections.push(targetId);
    cardEl.classList.add("selected-card");
  }

  document.getElementById("action-submit").disabled = nightSelections.length === 0;
}

document.getElementById("action-submit").addEventListener("click", () => {
  const submitBtn = document.getElementById("action-submit");
  // If the button has been repurposed as a Ready/Continue button by night_action_result, skip default logic
  if (submitBtn.dataset.mode === "ready") return;

  if (!currentPrompt) return;

  const isSeer = myRole === "seer";
  const isCenter = nightSelections.every(t => t.startsWith("center_"));

  // Seer needs 1 player OR 2 center cards
  if (isSeer && isCenter && nightSelections.length < 2) {
    showToast("Pick 2 center cards, or switch to a player card");
    return;
  }
  if (nightSelections.length === 0) {
    showToast("Select a card first");
    return;
  }

  socket.send({ type: "night_action", targets: nightSelections });
  submitBtn.disabled = true;
  document.getElementById("action-message").textContent = "Waiting for result...";
});

function renderRevealInfo(data) {
  // Show inline in action panel for no-pick roles (werewolf team reveal, minion, insomniac)
  const msg = document.getElementById("action-message");
  if (data.werewolf_teammates !== undefined) {
    const names = data.werewolf_teammates.map(w => w.name);
    msg.textContent = names.length
      ? `Your pack: ${names.join(", ")}`
      : "You are the only werewolf.";
  } else if (data.werewolves !== undefined) {
    const names = data.werewolves.map(w => w.name);
    msg.textContent = names.length ? `Werewolves: ${names.join(", ")}` : "No werewolves!";
  } else if (data.lone_wolf) {
    msg.textContent = data.message || "You are alone. You may peek at a center card.";
  }
}

// ---------------------------------------------------------------------------
// Day screen
// ---------------------------------------------------------------------------
function renderDayScreen(endTime, playerList) {
  if (dayTimerInterval) clearInterval(dayTimerInterval);
  renderDayPlayers(playerList);
  dayTimerInterval = setInterval(() => {
    const remaining = Math.max(0, Math.ceil(endTime - Date.now() / 1000));
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    document.getElementById("timer-display").textContent = `${m}:${s}`;
    if (remaining === 0) clearInterval(dayTimerInterval);
  }, 500);
}

function renderDayPlayers(playerList) {
  const ul = document.getElementById("day-players");
  ul.innerHTML = "";
  playerList.forEach(p => {
    const li = document.createElement("li");
    li.innerHTML = `
      <div class="connected-dot${p.is_connected ? "" : " off"}"></div>
      <span>${p.name}${p.player_id === myPlayerId ? " (you)" : ""}</span>
    `;
    ul.appendChild(li);
  });
}

document.getElementById("end-day-btn").addEventListener("click", () => {
  socket.send({ type: "end_day" });
});

// ---------------------------------------------------------------------------
// Voting screen
// ---------------------------------------------------------------------------
function renderVotingScreen(playerList) {
  const grid = document.getElementById("vote-grid");
  grid.innerHTML = "";
  playerList.forEach(p => {
    if (p.player_id === myPlayerId) return;
    const btn = document.createElement("button");
    btn.className = "vote-btn";
    btn.textContent = p.name;
    btn.addEventListener("click", () => castVote(p.player_id, btn));
    grid.appendChild(btn);
  });
  document.getElementById("vote-progress").textContent = "Waiting for votes...";
}

function castVote(targetId, btn) {
  if (myVoteTarget) return;
  myVoteTarget = targetId;
  document.querySelectorAll(".vote-btn").forEach(b => { b.disabled = true; });
  btn.classList.add("chosen");
  socket.send({ type: "vote", target_player_id: targetId });
}

// ---------------------------------------------------------------------------
// Results screen
// ---------------------------------------------------------------------------
function renderResultsScreen(data) {
  const banner = document.getElementById("win-banner");
  const myFinalRole = data.final_roles?.[myPlayerId];
  const iAmWerewolf = myFinalRole === "werewolf";
  const iWon = (data.win_team === "werewolf" && iAmWerewolf) ||
               (data.win_team === "village" && !iAmWerewolf);

  if (iWon) {
    banner.textContent = "🎉 You Win!";
    banner.className = "village";
  } else {
    banner.textContent = "💀 You Lose";
    banner.className = "werewolf";
  }

  const teamLabel = data.win_team === "werewolf" ? "Werewolves win" : "Village wins";
  const eliminatedNames = (data.eliminated || []).map(id => data.player_names?.[id] || id);
  const eliminatedText = eliminatedNames.length ? `Eliminated: ${eliminatedNames.join(", ")}` : "No one was eliminated.";
  document.getElementById("eliminated-text").textContent = `${teamLabel} — ${eliminatedText}`;

  const tbody = document.getElementById("results-tbody");
  tbody.innerHTML = "";
  players.forEach(p => {
    const orig = data.original_roles?.[p.player_id] || "?";
    const final = data.final_roles?.[p.player_id] || "?";
    const votedFor = data.votes?.[p.player_id];
    const votedName = votedFor ? (data.player_names?.[votedFor] || votedFor) : "—";
    const changed = orig !== final;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.name}${p.player_id === myPlayerId ? " ★" : ""}</td>
      <td>${ROLE_EMOJI[orig] || ""} ${orig}</td>
      <td class="${changed ? "role-changed" : ""}">${ROLE_EMOJI[final] || ""} ${final}</td>
      <td>${votedName}</td>
    `;
    tbody.appendChild(tr);
  });

  // Show center cards
  const centerRow = document.getElementById("center-results");
  if (data.center_cards) {
    centerRow.textContent = "Center cards: " + data.center_cards.map(r => `${ROLE_EMOJI[r] || ""} ${r}`).join(", ");
  }
}

document.getElementById("play-again-btn").addEventListener("click", () => {
  socket.send({ type: "reset" });
});

// ---------------------------------------------------------------------------
// Socket event handlers
// ---------------------------------------------------------------------------
function registerSocketHandlers() {
  socket.on("state_snapshot", (data) => {
    players = data.players || players;
    selectedRoles = data.selected_roles || selectedRoles;
    if (data.your_role) myRole = data.your_role;
    if (data.seat !== undefined) mySeat = data.seat;
    restoreScreen(data);
  });

  socket.on("player_connected", (data) => {
    const p = players.find(p => p.player_id === data.player_id);
    if (p) p.is_connected = true;
    else players.push({ player_id: data.player_id, name: data.name, seat: players.length, is_connected: true });
    if (currentScreen() === "lobby") renderLobby();
    if (currentScreen() === "day") renderDayPlayers(players);
  });

  socket.on("player_disconnected", (data) => {
    const p = players.find(p => p.player_id === data.player_id);
    if (p) p.is_connected = false;
    if (currentScreen() === "day") renderDayPlayers(players);
  });

  socket.on("player_kicked", (data) => {
    if (data.player_id === myPlayerId) {
      clearSession();
      location.reload();
      return;
    }
    players = data.players || players.filter(p => p.player_id !== data.player_id);
    if (currentScreen() === "lobby") renderLobby();
    showToast(`${data.name} was removed`);
  });

  socket.on("roles_configured", (data) => {
    selectedRoles = data.roles;
    if (currentScreen() === "lobby") renderRolePicker();
    updateStartBtn();
  });

  socket.on("game_started", () => {
    switchScreen("night");
  });

  socket.on("role_assigned", (data) => {
    myRole = data.role;
    renderNightBase();
    showWaiting();
  });

  socket.on("night_phase_begin", (data) => {
    document.getElementById("narrator-text").textContent = data.message || "";
    document.getElementById("action-panel").style.display = "none";
    document.getElementById("action-waiting").style.display = "block";
    const submitBtn = document.getElementById("action-submit");
    submitBtn.dataset.mode = "";
    submitBtn.textContent = "Confirm";
    submitBtn.onclick = null;
    document.getElementById("skip-peek-btn")?.remove();
    nightSelections = [];
    currentPrompt = null;
  });

  socket.on("night_action_prompt", (data) => {
    applyNightPrompt(data);
    renderTable(data);
    renderCenterCards(data);
  });

  socket.on("night_action_result", (data) => {
    const panel = document.getElementById("action-panel");
    panel.style.display = "block";
    document.getElementById("action-waiting").style.display = "none";
    const msg = document.getElementById("action-message");
    const submitBtn = document.getElementById("action-submit");

    const r = data.revealed || {};
    if (r.werewolf_teammates !== undefined) {
      const names = r.werewolf_teammates.map(w => w.name);
      if (names.length) {
        msg.textContent = `Your fellow werewolf: ${names.join(", ")}`;
      } else if (r.peeked_center) {
        const role = r.peeked_center.role;
        msg.textContent = `You are the lone wolf. Center card: ${ROLE_DESCRIPTIONS[role] || role}`;
      } else {
        msg.textContent = "You are the lone wolf.";
      }
      // Lone wolf: add a Skip peek button alongside the card picker
      if (r.lone_wolf === false && !r.peeked_center) {
        addSkipPeekButton();
      }
    } else if (r.werewolves !== undefined) {
      const names = r.werewolves.map(w => w.name);
      msg.textContent = names.length ? `Werewolves: ${names.join(", ")}` : "No werewolves in play!";
    } else if (r.player_card) {
      const c = r.player_card;
      msg.textContent = `${c.name}'s card: ${ROLE_DESCRIPTIONS[c.role] || c.role}`;
    } else if (r.center_cards) {
      const parts = Object.entries(r.center_cards).map(([k, v]) => `${k.replace("_", " ")}: ${ROLE_DESCRIPTIONS[v] || v}`);
      msg.textContent = parts.join(", ");
    } else if (r.center_card) {
      const [[k, v]] = Object.entries(r.center_card);
      msg.textContent = `${k.replace("_", " ")}: ${ROLE_DESCRIPTIONS[v] || v}`;
    } else if (r.your_new_role) {
      msg.textContent = `You stole ${r.swapped_with}'s card. You are now: ${ROLE_DESCRIPTIONS[r.your_new_role] || r.your_new_role}`;
      myRole = r.your_new_role;
      document.querySelector(".role-label").textContent = ROLE_DESCRIPTIONS[myRole] || myRole;
    } else if (r.swapped) {
      msg.textContent = `You swapped ${r.swapped[0]} and ${r.swapped[1]}.`;
    } else if (r.your_current_role) {
      msg.textContent = `Your card is now: ${ROLE_DESCRIPTIONS[r.your_current_role] || r.your_current_role}`;
    } else if (r.message) {
      msg.textContent = r.message;
    }

    // Show Continue button for all results that need acknowledgement
    if (data.needs_ready) {
      showContinueButton(submitBtn);
    } else {
      submitBtn.style.display = "none";
    }
  });

  socket.on("night_role_done", (data) => {
    document.getElementById("narrator-text").textContent = data.message || "...";
  });

  socket.on("day_phase_begin", (data) => {
    if (dayTimerInterval) clearInterval(dayTimerInterval);
    players = data.players || players;
    switchScreen("day");
    renderDayScreen(data.discussion_end_time, players);
  });

  socket.on("voting_begin", (data) => {
    players = data.players || players;
    myVoteTarget = null;
    switchScreen("voting");
    renderVotingScreen(players);
  });

  socket.on("vote_cast", (data) => {
    document.getElementById("vote-progress").textContent = `${data.count} / ${data.total} voted`;
  });

  socket.on("results", (data) => {
    switchScreen("results");
    renderResultsScreen(data);
  });

  socket.on("game_reset", (data) => {
    myRole = null;
    nightSelections = [];
    currentPrompt = null;
    myVoteTarget = null;
    selectedRoles = [];
    if (dayTimerInterval) clearInterval(dayTimerInterval);

    // Players are kept — just go back to lobby
    players = data.players || players;
    renderLobby();
    switchScreen("lobby");
  });

  socket.on("error", (data) => {
    showToast(data.message || "An error occurred");
  });
}

function currentScreen() {
  const active = document.querySelector(".screen.active");
  return active ? active.id.replace("screen-", "") : null;
}

// ---------------------------------------------------------------------------
// Night UI helpers
// ---------------------------------------------------------------------------
function showContinueButton(btn) {
  btn.dataset.mode = "ready";
  btn.textContent = "Continue";
  btn.style.display = "block";
  btn.disabled = false;
  btn.onclick = () => {
    socket.send({ type: "night_skip" });
    btn.disabled = true;
    btn.textContent = "Waiting...";
  };
}

function addSkipPeekButton() {
  if (document.getElementById("skip-peek-btn")) return;
  const btn = document.createElement("button");
  btn.id = "skip-peek-btn";
  btn.className = "btn-secondary mt8";
  btn.textContent = "Skip peek";
  btn.addEventListener("click", () => {
    socket.send({ type: "night_skip" });
    btn.disabled = true;
    btn.textContent = "Waiting...";
  });
  document.getElementById("action-panel").appendChild(btn);
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
let toastTimer = null;
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3000);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
boot();
