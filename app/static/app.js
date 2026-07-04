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
  activePersonaEntityName = activeEntity?.persona?.identity?.name || activeEntity?.name || "";
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
    const personaName = entity.persona?.identity?.name || entity.name || "未命名";
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

els.importPersonaButton.addEventListener("click", async () => {
  const text = els.backgroundInput.value.trim();
  if (!text) return;
  els.importPersonaButton.disabled = true;
  els.importPersonaButton.textContent = "学习中";
  try {
    await api("/api/persona/import-materials", {
      method: "POST",
      body: JSON.stringify({
        text,
        source_type: els.importSourceType.value,
        persona_entity_id: activePersonaEntityId,
        confirm: true,
      }),
    });
    els.backgroundInput.value = "";
    await refresh();
  } finally {
    els.importPersonaButton.disabled = false;
    els.importPersonaButton.textContent = "导入并学习";
  }
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

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    els.composer.requestSubmit();
  }
});

refresh().catch((error) => {
  els.debug.textContent = `初始化失败：${error.message}`;
});
