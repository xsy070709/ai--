const els = {
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#messageInput"),
  debug: document.querySelector("#debugMeta"),
  modelName: document.querySelector("#modelName"),
  modelStatus: document.querySelector("#modelStatus"),
  personaBox: document.querySelector("#personaBox"),
  backgroundInput: document.querySelector("#backgroundInput"),
  importPersonaButton: document.querySelector("#importPersonaButton"),
  memoryLayers: document.querySelector("#memoryLayers"),
};

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

async function refresh() {
  const [status, messages] = await Promise.all([api("/api/status"), api("/api/messages")]);
  els.modelName.textContent = status.llm.model;
  els.modelStatus.textContent = status.llm.configured ? "已配置" : "本地降级";
  renderPersona(status.persona);
  renderLayers(status.layers);
  renderMessages(messages);
}

els.importPersonaButton.addEventListener("click", async () => {
  const text = els.backgroundInput.value.trim();
  if (!text) return;
  els.importPersonaButton.disabled = true;
  els.importPersonaButton.textContent = "初始化中";
  try {
    await api("/api/persona/import", {
      method: "POST",
      body: JSON.stringify({ text, confirm: true }),
    });
    els.backgroundInput.value = "";
    await refresh();
  } finally {
    els.importPersonaButton.disabled = false;
    els.importPersonaButton.textContent = "导入并初始化";
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
  } catch (error) {
    els.debug.textContent = `发送失败：${error.message}`;
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
