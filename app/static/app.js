const els = {
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#messageInput"),
  debug: document.querySelector("#debugMeta"),
  modelName: document.querySelector("#modelName"),
  modelStatus: document.querySelector("#modelStatus"),
  personaBox: document.querySelector("#personaBox"),
  entityList: document.querySelector("#entityList"),
  entityNameInput: document.querySelector("#entityNameInput"),
  createEntityButton: document.querySelector("#createEntityButton"),
  renameEntityInput: document.querySelector("#renameEntityInput"),
  renameEntityButton: document.querySelector("#renameEntityButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  deleteEntityButton: document.querySelector("#deleteEntityButton"),
  importSourceType: document.querySelector("#importSourceType"),
  backgroundInput: document.querySelector("#backgroundInput"),
  importPersonaButton: document.querySelector("#importPersonaButton"),
  memoryLayers: document.querySelector("#memoryLayers"),
  devToggle: document.querySelector("#devToggle"),
  devDrawer: document.querySelector("#devDrawer"),
  devBackdrop: document.querySelector("#devBackdrop"),
  devClose: document.querySelector("#devClose"),
  devRefresh: document.querySelector("#devRefresh"),
  devTidy: document.querySelector("#devTidy"),
  devContent: document.querySelector("#devContent"),
  devTabs: document.querySelectorAll(".dev-tab"),
  importModal: document.querySelector("#importModal"),
  importModalClose: document.querySelector("#importModalClose"),
  importTextarea: document.querySelector("#importTextarea"),
  importSourceTypeModal: document.querySelector("#importSourceTypeModal"),
  importAnalyzeButton: document.querySelector("#importAnalyzeButton"),
  importStep1: document.querySelector("#importStep1"),
  importStep2: document.querySelector("#importStep2"),
  importStep3: document.querySelector("#importStep3"),
  importChatMessages: document.querySelector("#importChatMessages"),
  importChatForm: document.querySelector("#importChatForm"),
  importChatInput: document.querySelector("#importChatInput"),
  importLiveProfile: document.querySelector("#importLiveProfile"),
  importEditButton: document.querySelector("#importEditButton"),
  importConfirmFromStep2: document.querySelector("#importConfirmFromStep2"),
  importEditableProfile: document.querySelector("#importEditableProfile"),
  importBackToStep2: document.querySelector("#importBackToStep2"),
  importConfirmFromStep3: document.querySelector("#importConfirmFromStep3"),
  eventList: document.querySelector("#eventList"),
  addEventButton: document.querySelector("#addEventButton"),
  eventModal: document.querySelector("#eventModal"),
  eventModalClose: document.querySelector("#eventModalClose"),
  eventContent: document.querySelector("#eventContent"),
  eventType: document.querySelector("#eventType"),
  eventImpactScope: document.querySelector("#eventImpactScope"),
  eventExpiryField: document.querySelector("#eventExpiryField"),
  eventDurationDays: document.querySelector("#eventDurationDays"),
  traitEffectsList: document.querySelector("#traitEffectsList"),
  addTraitEffect: document.querySelector("#addTraitEffect"),
  eventBecomesTopic: document.querySelector("#eventBecomesTopic"),
  eventTopicWords: document.querySelector("#eventTopicWords"),
  eventBecomesTaboo: document.querySelector("#eventBecomesTaboo"),
  eventTabooWords: document.querySelector("#eventTabooWords"),
  eventSaveButton: document.querySelector("#eventSaveButton"),
  eventCancelButton: document.querySelector("#eventCancelButton"),
};

let devState = null;
let activeDevTab = "memories";
let activePersonaEntityId = null;
let activePersonaEntityName = "";

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function renderMessages(messages) {
  els.messages.innerHTML = "";
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "message assistant";
    empty.textContent = "先导入背景设定，或者直接开始聊天。我会把这个窗口当作长期聊天来接续。";
    els.messages.appendChild(empty);
    return;
  }
  for (const message of messages) {
    if (!message.role || !message.content) continue;
    const node = document.createElement("div");
    node.className = `message ${message.role}`;
    node.textContent = message.content;
    if (message.meta) {
      const meta = document.createElement("div");
      meta.className = "message-meta";
      meta.textContent = `${message.meta.provider}/${message.meta.model}${message.meta.degraded ? " · 降级" : ""}`;
      node.appendChild(meta);
    }
    els.messages.appendChild(node);
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderLayers(layers) {
  els.memoryLayers.innerHTML = "";
  for (const key of ["work", "summary", "long_term", "persona", "shared", "open_loops", "relationship", "impression"]) {
    const layer = layers[key];
    const node = document.createElement("div");
    node.className = "layer";
    node.innerHTML = `<span>${layer.name}</span><strong>${layer.count}</strong>`;
    els.memoryLayers.appendChild(node);
  }
}

function renderEvents(events) {
  els.eventList.innerHTML = "";
  const activeEvents = (events || []).filter(e => e.status !== "resolved" && e.status !== "absorbed");
  if (!activeEvents.length) {
    const empty = document.createElement("div");
    empty.className = "event-empty";
    empty.textContent = "暂无活跃事件";
    els.eventList.appendChild(empty);
    return;
  }
  for (const event of activeEvents) {
    const card = document.createElement("div");
    card.className = "event-card";

    const typeLabel = { positive: "正面", negative: "负面", neutral: "中性", traumatic: "创伤" }[event.event_type] || event.event_type;
    const statusLabel = { active: "活跃", fading: "消退中", acknowledged: "已讨论", resolved: "已解决", absorbed: "已吸收" }[event.status] || event.status;

    let traitInfo = "";
    if (event.trait_effects && event.trait_effects.length) {
      traitInfo = event.trait_effects.map(e => {
        const dir = { add: "+", weaken: "↓", strengthen: "↑", remove: "×" }[e.direction] || e.direction;
        return `${dir}${e.trait}`;
      }).join(" ");
    }

    card.innerHTML = `
      <div class="event-card-head">
        <strong>${escapeHtml(event.content)}</strong>
      </div>
      <div class="event-card-meta">
        <span class="event-badge ${event.event_type}">${escapeHtml(typeLabel)}</span>
        <span class="event-badge ${event.status}">${escapeHtml(statusLabel)}</span>
        ${event.impact_scope ? `<span style="font-size:11px;color:var(--muted)">${escapeHtml({temporary:"暂时",permanent:"长期",fading:"消退"}[event.impact_scope]||event.impact_scope)}</span>` : ""}
        ${event.becomes_taboo ? '<span class="event-badge" style="background:rgba(200,50,50,0.1);color:#c83232">禁忌</span>' : ""}
      </div>
      ${traitInfo ? `<div class="event-card-meta"><span style="font-size:11px;color:var(--accent-dark)">性格影响：${escapeHtml(traitInfo)}</span></div>` : ""}
      <div class="event-card-actions">
        ${event.status === "active" || event.status === "fading" ? `<button class="secondary" data-action="resolve" data-id="${event.id}">标记解决</button>` : ""}
        <button class="secondary" data-action="delete" data-id="${event.id}">删除</button>
      </div>`;
    els.eventList.appendChild(card);
  }

  // attach action handlers
  els.eventList.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      btn.disabled = true;
      try {
        if (action === "resolve") {
          await api(`/api/persona-events/${encodeURIComponent(id)}/resolve`, { method: "POST", body: "{}" });
        } else if (action === "delete") {
          await api(`/api/persona-events/${encodeURIComponent(id)}`, { method: "DELETE" });
        }
        await refresh();
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function renderPersona(persona) {
  if (!persona) {
    els.personaBox.className = "persona-empty";
    els.personaBox.textContent = "尚未导入背景设定";
    return;
  }
  els.personaBox.className = "persona-card";
  const identity = persona.identity || {};
  const traits = persona.personality?.stable_traits || [];
  els.personaBox.textContent = `${identity.name || "未命名"} · ${identity.relationship_to_user || "虚拟好友"}\n核心性格：${traits.join("、")}`;
}

async function refreshDevIfOpen() {
  if (els.devDrawer.classList.contains("open")) await refreshDev();
}

function renderEntities(entities = []) {
  els.entityList.innerHTML = "";
  const activeEntity = entities.find((entity) => entity.active);
  activePersonaEntityName = activeEntity?.display_name || activeEntity?.name || activeEntity?.persona?.identity?.name || "";
  els.renameEntityInput.value = activePersonaEntityName;
  const hasActiveEntity = Boolean(activeEntity);
  els.renameEntityButton.disabled = !hasActiveEntity;
  els.clearChatButton.disabled = !hasActiveEntity;
  els.deleteEntityButton.disabled = !hasActiveEntity;
  if (!entities.length) {
    const empty = document.createElement("div");
    empty.className = "entity-empty";
    empty.textContent = "暂无人格实体";
    els.entityList.appendChild(empty);
    return;
  }
  for (const entity of entities) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `entity-item${entity.active ? " active" : ""}`;
    button.dataset.entityId = entity.id;
    const personaName = entity.display_name || entity.name || entity.persona?.identity?.name || "未命名";
    button.innerHTML = `<strong>${escapeHtml(personaName)}</strong><span>${escapeHtml(entity.message_count || 0)} 条消息</span>`;
    button.addEventListener("click", async () => {
      if (entity.active) return;
      await api(`/api/persona-entities/${encodeURIComponent(entity.id)}/activate`, { method: "POST", body: "{}" });
      await refresh();
      await refreshDevIfOpen();
    });
    els.entityList.appendChild(button);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function compactJson(value) {
  return JSON.stringify(value ?? null, null, 2);
}

function memoryTitle(memory) {
  const flags = [];
  if (memory.status && memory.status !== "active") flags.push(memory.status);
  if (memory.open) flags.push("open");
  if (memory.is_user_confirmed) flags.push("confirmed");
  return flags.length ? flags.join(" · ") : "active";
}

function renderDev() {
  if (!devState) {
    els.devContent.innerHTML = '<div class="dev-empty">还没有加载调试数据</div>';
    return;
  }
  if (activeDevTab === "memories") renderDevMemories();
  if (activeDevTab === "logs") renderDevLogs();
  if (activeDevTab === "api") renderDevApi();
  if (activeDevTab === "raw") renderDevRaw();
}

function renderDevMemories() {
  const groups = devState.memories_by_type || {};
  const keys = Object.keys(groups).sort();
  if (!keys.length) {
    els.devContent.innerHTML = '<div class="dev-empty">暂无长期记忆</div>';
    return;
  }
  els.devContent.innerHTML = keys
    .map((type) => {
      const items = groups[type] || [];
      return `
        <section class="dev-section">
          <h3>${escapeHtml(type)} <span>${items.length}</span></h3>
          ${items
            .map(
              (memory) => `
                <article class="dev-card">
                  <div class="dev-card-head">
                    <strong>${escapeHtml(memory.content)}</strong>
                    <span>${escapeHtml(memoryTitle(memory))}</span>
                  </div>
                  <div class="dev-kv">
                    <span>importance ${escapeHtml(memory.importance)}</span>
                    <span>confidence ${escapeHtml(memory.confidence)}</span>
                    <span>policy ${escapeHtml(memory.surface_policy)}</span>
                  </div>
                  <details>
                    <summary>完整 JSON</summary>
                    <pre>${escapeHtml(compactJson(memory))}</pre>
                  </details>
                </article>`
            )
            .join("")}
        </section>`;
    })
    .join("");
}

function renderDevLogs() {
  const logs = [...(devState.generation_logs || [])].reverse();
  if (!logs.length) {
    els.devContent.innerHTML = '<div class="dev-empty">暂无 generation logs</div>';
    return;
  }
  els.devContent.innerHTML = logs
    .map(
      (log) => `
        <article class="dev-card">
          <div class="dev-card-head">
            <strong>${escapeHtml(log.purpose)} · ${escapeHtml(log.model)}</strong>
            <span>${escapeHtml(log.elapsed_ms)}ms</span>
          </div>
          <div class="dev-kv">
            <span>${escapeHtml(log.created_at)}</span>
            <span>${escapeHtml(log.provider)}</span>
            <span>${log.degraded ? "degraded" : "ok"}</span>
            <span>audit ${escapeHtml(log.prompt_manifest?.memory_audit_status)}</span>
          </div>
          <details open>
            <summary>发给聊天 API 的 messages</summary>
            <pre>${escapeHtml(compactJson(log.api_messages || []))}</pre>
          </details>
          <details>
            <summary>prompt manifest</summary>
            <pre>${escapeHtml(compactJson(log.prompt_manifest))}</pre>
          </details>
          <details>
            <summary>usage / feedback</summary>
            <pre>${escapeHtml(compactJson({ usage: log.usage, feedback_signals: log.feedback_signals, error: log.error }))}</pre>
          </details>
        </article>`
    )
    .join("");
}

function renderDevApi() {
  const requests = [...(devState.api_requests || [])].reverse();
  if (!requests.length) {
    els.devContent.innerHTML = '<div class="dev-empty">本次进程暂无 DeepSeek 请求日志</div>';
    return;
  }
  els.devContent.innerHTML = requests
    .map(
      (request) => `
        <article class="dev-card">
          <div class="dev-card-head">
            <strong>${escapeHtml(request.purpose)} · ${escapeHtml(request.model)}</strong>
            <span>${escapeHtml(request.elapsed_ms)}ms</span>
          </div>
          <div class="dev-kv">
            <span>${escapeHtml(request.created_at)}</span>
            <span>${request.degraded ? "degraded" : "ok"}</span>
            <span>${request.client_cache_hit ? "client cache hit" : "network/local"}</span>
            <span>${escapeHtml(formatPromptStats(request.prompt_stats))}</span>
          </div>
          <details open>
            <summary>request messages</summary>
            <pre>${escapeHtml(compactJson(request.messages || []))}</pre>
          </details>
          <details>
            <summary>request options / usage</summary>
            <pre>${escapeHtml(compactJson({
              thinking: request.thinking,
              response_format: request.response_format,
              max_tokens: request.max_tokens,
              prompt_stats: request.prompt_stats,
              usage: request.usage,
              error: request.error,
            }))}</pre>
          </details>
        </article>`
    )
    .join("");
}

function formatPromptStats(stats) {
  if (!stats) return "prompt stats n/a";
  return `prompt ${stats.total_chars || 0} chars · stable ${stats.stable_system_chars || 0} · summary ${stats.summary_system_chars || 0} · memory ${stats.memory_system_chars || 0} · time ${stats.time_system_chars || 0}`;
}

function renderDevRaw() {
  const raw = devState.raw_flow || {};
  const latest = raw.latest_chat || {};
  els.devContent.innerHTML = `
    <section class="dev-section">
      <h3>最新聊天原始流 <span>${escapeHtml(latest.note || "暂无聊天")}</span></h3>
      <article class="dev-card">
        <div class="dev-card-head">
          <strong>真正发给 chat API 的 messages</strong>
          <span>${escapeHtml((latest.chat_api_messages || []).length)} messages</span>
        </div>
        <pre>${escapeHtml(compactJson(latest.chat_api_messages || []))}</pre>
      </article>
      <article class="dev-card">
        <div class="dev-card-head">
          <strong>同一服务进程最近 DeepSeek 请求/响应</strong>
          <span>${escapeHtml((latest.nearby_api_requests || []).length)} requests</span>
        </div>
        <pre>${escapeHtml(compactJson(latest.nearby_api_requests || []))}</pre>
      </article>
      <article class="dev-card">
        <div class="dev-card-head">
          <strong>持久化 generation log</strong>
          <span>prompt_manifest 是审计，不是完整 prompt</span>
        </div>
        <pre>${escapeHtml(compactJson(latest.chat_generation_log || {}))}</pre>
      </article>
    </section>
    <section class="dev-section">
      <h3>完整 raw_flow <span>debug JSON</span></h3>
      <article class="dev-card">
        <pre>${escapeHtml(compactJson(raw))}</pre>
      </article>
    </section>`;
}

async function refreshDev() {
  devState = await api("/api/debug");
  renderDev();
}

function openDev() {
  els.devDrawer.classList.add("open");
  els.devBackdrop.classList.add("open");
  els.devDrawer.setAttribute("aria-hidden", "false");
  refreshDev().catch((error) => {
    els.devContent.innerHTML = `<div class="dev-empty">加载失败：${escapeHtml(error.message)}</div>`;
  });
}

function closeDev() {
  els.devDrawer.classList.remove("open");
  els.devBackdrop.classList.remove("open");
  els.devDrawer.setAttribute("aria-hidden", "true");
}

async function refresh() {
  const [status, messages] = await Promise.all([api("/api/status"), api("/api/messages")]);
  activePersonaEntityId = status.active_persona_entity_id;
  els.modelName.textContent = status.llm.model;
  els.modelStatus.textContent = status.llm.configured ? "已配置" : "本地降级";
  renderEntities(status.persona_entities || []);
  renderPersona(status.persona);
  renderLayers(status.layers);
  renderEvents(status.persona_events || []);
  renderMessages(messages);
}

els.createEntityButton.addEventListener("click", async () => {
  const name = els.entityNameInput.value.trim();
  els.createEntityButton.disabled = true;
  try {
    await api("/api/persona-entities", {
      method: "POST",
      body: JSON.stringify({ name: name || null, activate: true }),
    });
    els.entityNameInput.value = "";
    await refresh();
  } finally {
    els.createEntityButton.disabled = false;
  }
});

els.renameEntityButton.addEventListener("click", async () => {
  const name = els.renameEntityInput.value.trim();
  if (!activePersonaEntityId || !name || name === activePersonaEntityName) return;
  els.renameEntityButton.disabled = true;
  try {
    await api(`/api/persona-entities/${encodeURIComponent(activePersonaEntityId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    await refresh();
    await refreshDevIfOpen();
  } finally {
    els.renameEntityButton.disabled = false;
  }
});

els.clearChatButton.addEventListener("click", async () => {
  if (!activePersonaEntityId) return;
  if (!window.confirm("清空当前好友的聊天记录？人格设定和长期记忆会保留。")) return;
  els.clearChatButton.disabled = true;
  try {
    const result = await api("/api/messages/clear", { method: "POST", body: "{}" });
    await refresh();
    await refreshDevIfOpen();
    els.debug.textContent = `已清空 ${result.removed_messages || 0} 条聊天记录`;
  } finally {
    els.clearChatButton.disabled = false;
  }
});

els.deleteEntityButton.addEventListener("click", async () => {
  if (!activePersonaEntityId) return;
  const name = activePersonaEntityName || "当前好友";
  if (!window.confirm(`删除好友「${name}」？该好友的聊天记录、人格设定和长期记忆都会删除。`)) return;
  els.deleteEntityButton.disabled = true;
  try {
    await api(`/api/persona-entities/${encodeURIComponent(activePersonaEntityId)}`, { method: "DELETE" });
    await refresh();
    await refreshDevIfOpen();
    els.debug.textContent = `已删除好友：${name}`;
  } finally {
    els.deleteEntityButton.disabled = false;
  }
});

els.importPersonaButton.addEventListener("click", () => {
  const text = els.backgroundInput.value.trim();
  if (text) {
    els.importTextarea.value = text;
    els.importSourceTypeModal.value = els.importSourceType.value;
  }
  openImportWizard();
});

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.input.value.trim();
  if (!message) return;
  els.input.value = "";
  els.debug.textContent = "生成中";
  const currentMessages = await api("/api/messages");
  renderMessages([...currentMessages, { role: "user", content: message }]);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    els.debug.textContent = `${result.llm.provider}/${result.llm.model} · ${result.llm.elapsed_ms}ms${result.degraded ? " · 降级" : ""}`;
    await refresh();
    await refreshDevIfOpen();
  } catch (error) {
    els.debug.textContent = `发送失败：${error.message}`;
  }
});

els.devToggle.addEventListener("click", openDev);
els.devClose.addEventListener("click", closeDev);
els.devBackdrop.addEventListener("click", closeDev);
els.devRefresh.addEventListener("click", () => refreshDev());
els.devTidy.addEventListener("click", async () => {
  els.devTidy.disabled = true;
  els.devTidy.textContent = "整理中";
  try {
    const report = await api("/api/memories/tidy", { method: "POST", body: "{}" });
    await refresh();
    await refreshDev();
    els.debug.textContent = `整理完成：规范 ${report.normalized.length}，合并 ${report.merged.length}，归档 ${report.archived.length}`;
  } finally {
    els.devTidy.disabled = false;
    els.devTidy.textContent = "整理记忆";
  }
});
for (const tab of els.devTabs) {
  tab.addEventListener("click", () => {
    activeDevTab = tab.dataset.tab;
    for (const item of els.devTabs) item.classList.toggle("active", item === tab);
    renderDev();
  });
}

// ── Import Wizard ──────────────────────────────────────────────────

let importSessionId = null;
let importCurrentProfile = {};

function openImportWizard() {
  importSessionId = null;
  importCurrentProfile = {};
  showImportStep(1);
  els.importChatMessages.innerHTML = "";
  els.importLiveProfile.innerHTML = "";
  els.importModal.classList.add("open");
  els.importModal.setAttribute("aria-hidden", "false");
}

function closeImportWizard() {
  els.importModal.classList.remove("open");
  els.importModal.setAttribute("aria-hidden", "true");
  if (importSessionId) {
    api(`/api/persona/import-session/${encodeURIComponent(importSessionId)}`, { method: "DELETE" }).catch(() => {});
    importSessionId = null;
  }
  importCurrentProfile = {};
}

function showImportStep(step) {
  els.importStep1.style.display = step === 1 ? "" : "none";
  els.importStep2.style.display = step === 2 ? "" : "none";
  els.importStep3.style.display = step === 3 ? "" : "none";
}

function renderImportChatMessages(messages) {
  els.importChatMessages.innerHTML = "";
  for (const msg of messages) {
    appendImportChatMessage(msg);
  }
}

function appendImportChatMessage(message) {
  const node = document.createElement("div");
  node.className = `iw-chat-msg ${message.role}`;
  node.textContent = message.content;
  els.importChatMessages.appendChild(node);
  els.importChatMessages.scrollTop = els.importChatMessages.scrollHeight;
}

function renderLiveProfile(profile) {
  const p = profile || importCurrentProfile;
  const sections = [
    { label: "名字", value: p.name || "未识别" },
    { label: "关系", value: p.relationship_to_user || "虚拟好友" },
    { label: "摘要", value: p.summary || "暂无摘要" },
  ];
  const tags = [
    { label: "性格特质", key: "traits" },
    { label: "说话风格", key: "speaking_style" },
    { label: "口癖", key: "catchphrases" },
    { label: "习惯", key: "habits" },
    { label: "情绪风格", key: "emotional_style" },
    { label: "聊天习惯", key: "conversation_habits" },
    { label: "禁忌用语", key: "taboo_phrases" },
  ];

  let html = "";
  for (const section of sections) {
    html += `<div class="iw-profile-field">
      <span class="iw-profile-field-label">${escapeHtml(section.label)}</span>
      <span class="iw-profile-field-value">${escapeHtml(section.value)}</span>
    </div>`;
  }
  for (const tag of tags) {
    const values = p[tag.key] || [];
    if (!values.length) continue;
    html += `<div class="iw-profile-field">
      <span class="iw-profile-field-label">${escapeHtml(tag.label)}</span>
      <div class="iw-tag-list">${values.map(v => `<span class="iw-tag">${escapeHtml(v)}</span>`).join("")}</div>
    </div>`;
  }
  els.importLiveProfile.innerHTML = html || '<span class="iw-profile-field-value">暂无数据</span>';
}

// ── Step 3: editable profile form ──────────────────────────────────

function renderEditableProfile(profile) {
  const p = profile || importCurrentProfile;
  const tagFields = ["traits", "speaking_style", "catchphrases", "habits", "emotional_style", "conversation_habits", "taboo_phrases"];
  const tagLabels = {
    traits: "性格特质", speaking_style: "说话风格", catchphrases: "口癖",
    habits: "习惯", emotional_style: "情绪风格", conversation_habits: "聊天习惯", taboo_phrases: "禁忌用语",
  };

  let html = "";

  // scalar fields
  html += `<div class="iw-edit-field">
    <label>名字</label>
    <input id="iwEditName" type="text" value="${escapeHtml(p.name || '')}" placeholder="未命名" />
  </div>`;
  html += `<div class="iw-edit-field">
    <label>关系</label>
    <input id="iwEditRelationship" type="text" value="${escapeHtml(p.relationship_to_user || '')}" placeholder="虚拟好友" />
  </div>`;
  html += `<div class="iw-edit-field">
    <label>摘要</label>
    <textarea id="iwEditSummary" placeholder="简短的人格摘要">${escapeHtml(p.summary || '')}</textarea>
  </div>`;

  // tag fields
  for (const key of tagFields) {
    const values = p[key] || [];
    html += `<div class="iw-edit-field">
      <label>${escapeHtml(tagLabels[key] || key)}</label>
      <div class="iw-edit-tags" id="iwEditTags_${key}">
        ${values.map((v, i) => `<span class="iw-tag">${escapeHtml(v)}<button class="iw-tag-remove" type="button" data-field="${key}" data-index="${i}" title="移除">&times;</button></span>`).join("")}
      </div>
      <div class="iw-tag-input-row">
        <input id="iwTagInput_${key}" type="text" placeholder="添加..." />
        <button class="secondary" type="button" data-add-field="${key}">+</button>
      </div>
    </div>`;
  }

  els.importEditableProfile.innerHTML = html;

  // attach event listeners
  for (const key of tagFields) {
    const container = document.getElementById(`iwEditTags_${key}`);
    if (!container) continue;
    container.addEventListener("click", (event) => {
      const btn = event.target.closest(".iw-tag-remove");
      if (!btn) return;
      const field = btn.dataset.field;
      const index = parseInt(btn.dataset.index, 10);
      const values = p[field] || [];
      values.splice(index, 1);
      p[field] = values;
      renderEditableProfile(p);
    });
    const addBtn = els.importEditableProfile.querySelector(`[data-add-field="${key}"]`);
    const input = document.getElementById(`iwTagInput_${key}`);
    if (addBtn && input) {
      addBtn.addEventListener("click", () => {
        const value = input.value.trim();
        if (!value) return;
        const values = p[key] || [];
        if (!values.includes(value)) {
          values.push(value);
          p[key] = values;
        }
        input.value = "";
        renderEditableProfile(p);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addBtn.click();
        }
      });
    }
  }
}

function collectEditableProfile() {
  const p = { ...importCurrentProfile };
  const nameInput = document.getElementById("iwEditName");
  const relInput = document.getElementById("iwEditRelationship");
  const summaryInput = document.getElementById("iwEditSummary");
  if (nameInput) p.name = nameInput.value.trim() || p.name;
  if (relInput) p.relationship_to_user = relInput.value.trim() || p.relationship_to_user;
  if (summaryInput) p.summary = summaryInput.value.trim() || p.summary;
  // tag fields are already mutated in-place on p via renderEditableProfile
  return p;
}

// ── Event Handlers ─────────────────────────────────────────────────

els.importModalClose.addEventListener("click", closeImportWizard);
els.importModal.addEventListener("click", (event) => {
  if (event.target === els.importModal) closeImportWizard();
});

els.importAnalyzeButton.addEventListener("click", async () => {
  const text = els.importTextarea.value.trim();
  if (!text) return;
  els.importAnalyzeButton.disabled = true;
  els.importAnalyzeButton.textContent = "分析中...";
  try {
    const result = await api("/api/persona/import-session", {
      method: "POST",
      body: JSON.stringify({
        text,
        source_type: els.importSourceTypeModal.value,
        persona_entity_id: activePersonaEntityId,
      }),
    });
    importSessionId = result.session_id;
    importCurrentProfile = result.current_profile;
    renderImportChatMessages(result.messages || []);
    renderLiveProfile(importCurrentProfile);
    showImportStep(2);
    els.importChatInput.focus();
  } catch (error) {
    els.debug.textContent = `分析失败：${error.message}`;
  } finally {
    els.importAnalyzeButton.disabled = false;
    els.importAnalyzeButton.textContent = "开始分析";
  }
});

els.importChatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.importChatInput.value.trim();
  if (!message || !importSessionId) return;
  els.importChatInput.value = "";
  appendImportChatMessage({ role: "user", content: message });
  try {
    const result = await api(`/api/persona/import-session/${encodeURIComponent(importSessionId)}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    appendImportChatMessage({ role: "assistant", content: result.reply });
    if (result.profile_diff && Object.keys(result.profile_diff).length > 0) {
      importCurrentProfile = result.current_profile;
      renderLiveProfile(importCurrentProfile);
    }
    if (result.is_complete) {
      els.importConfirmFromStep2.style.background = "var(--accent)";
    }
  } catch (error) {
    appendImportChatMessage({ role: "assistant", content: `出错了：${error.message}` });
  }
});

els.importEditButton.addEventListener("click", () => {
  renderEditableProfile(importCurrentProfile);
  showImportStep(3);
});

els.importBackToStep2.addEventListener("click", () => {
  importCurrentProfile = collectEditableProfile();
  renderLiveProfile(importCurrentProfile);
  showImportStep(2);
});

async function confirmImportWizard() {
  const finalProfile = collectEditableProfile();
  els.importConfirmFromStep2.disabled = true;
  els.importConfirmFromStep3.disabled = true;
  try {
    await api(`/api/persona/import-session/${encodeURIComponent(importSessionId)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ profile: finalProfile }),
    });
    importSessionId = null;
    closeImportWizard();
    els.backgroundInput.value = "";
    await refresh();
    await refreshDevIfOpen();
    els.debug.textContent = "人格导入完成";
  } catch (error) {
    els.debug.textContent = `导入失败：${error.message}`;
  } finally {
    els.importConfirmFromStep2.disabled = false;
    els.importConfirmFromStep3.disabled = false;
  }
}

els.importConfirmFromStep2.addEventListener("click", confirmImportWizard);
els.importConfirmFromStep3.addEventListener("click", () => {
  importCurrentProfile = collectEditableProfile();
  confirmImportWizard();
});

// ── Event Modal ────────────────────────────────────────────────────

let traitEffectCounter = 0;

function openEventModal() {
  els.eventContent.value = "";
  els.eventType.value = "neutral";
  els.eventImpactScope.value = "temporary";
  els.eventDurationDays.value = "7";
  els.traitEffectsList.innerHTML = "";
  els.eventBecomesTopic.checked = true;
  els.eventTopicWords.value = "";
  els.eventBecomesTaboo.checked = false;
  els.eventTabooWords.value = "";
  traitEffectCounter = 0;
  els.eventExpiryField.style.display = "";
  els.eventModal.classList.add("open");
  els.eventModal.setAttribute("aria-hidden", "false");
  els.eventContent.focus();
}

function closeEventModal() {
  els.eventModal.classList.remove("open");
  els.eventModal.setAttribute("aria-hidden", "true");
}

function addTraitEffectRow(trait = "", direction = "add") {
  const id = ++traitEffectCounter;
  const row = document.createElement("div");
  row.className = "trait-effect-row";
  row.dataset.traitId = id;
  row.innerHTML = `
    <input type="text" placeholder="特质名称" value="${escapeHtml(trait)}" data-field="trait" />
    <select data-field="direction">
      <option value="add" ${direction === "add" ? "selected" : ""}>新增</option>
      <option value="weaken" ${direction === "weaken" ? "selected" : ""}>减弱</option>
      <option value="strengthen" ${direction === "strengthen" ? "selected" : ""}>加强</option>
      <option value="remove" ${direction === "remove" ? "selected" : ""}>移除</option>
    </select>
    <button class="icon-button" type="button" data-remove="${id}" title="移除">&times;</button>`;
  row.querySelector("[data-remove]").addEventListener("click", () => row.remove());
  els.traitEffectsList.appendChild(row);
}

function collectTraitEffects() {
  const effects = [];
  els.traitEffectsList.querySelectorAll(".trait-effect-row").forEach(row => {
    const trait = row.querySelector("[data-field=trait]").value.trim();
    const direction = row.querySelector("[data-field=direction]").value;
    if (trait) effects.push({ trait, direction, strength: 0.6 });
  });
  return effects;
}

els.addEventButton.addEventListener("click", openEventModal);
els.eventModalClose.addEventListener("click", closeEventModal);
els.eventCancelButton.addEventListener("click", closeEventModal);
els.eventModal.addEventListener("click", (event) => {
  if (event.target === els.eventModal) closeEventModal();
});

els.eventImpactScope.addEventListener("change", () => {
  els.eventExpiryField.style.display = els.eventImpactScope.value === "permanent" ? "none" : "";
});

els.addTraitEffect.addEventListener("click", () => addTraitEffectRow());

els.eventSaveButton.addEventListener("click", async () => {
  const content = els.eventContent.value.trim();
  if (!content) return;
  const impactScope = els.eventImpactScope.value;
  let expiresAt = null;
  if (impactScope !== "permanent") {
    const days = parseInt(els.eventDurationDays.value, 10) || 7;
    const d = new Date();
    d.setDate(d.getDate() + days);
    expiresAt = d.toISOString();
  }
  const traitEffects = collectTraitEffects();
  const topicWords = els.eventTopicWords.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  const tabooWords = els.eventTabooWords.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);

  els.eventSaveButton.disabled = true;
  els.eventSaveButton.textContent = "保存中...";
  try {
    await api("/api/persona-events", {
      method: "POST",
      body: JSON.stringify({
        content,
        event_type: els.eventType.value,
        impact_scope: impactScope,
        expires_at: expiresAt,
        trait_effects: traitEffects,
        becomes_topic: els.eventBecomesTopic.checked,
        topic_trigger_words: topicWords,
        becomes_taboo: els.eventBecomesTaboo.checked,
        taboo_keywords: tabooWords,
      }),
    });
    closeEventModal();
    await refresh();
    await refreshDevIfOpen();
  } catch (error) {
    els.debug.textContent = `保存事件失败：${error.message}`;
  } finally {
    els.eventSaveButton.disabled = false;
    els.eventSaveButton.textContent = "保存事件";
  }
});

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    els.composer.requestSubmit();
  }
});

refresh().catch((error) => {
  els.debug.textContent = `初始化失败：${error.message}`;
});
