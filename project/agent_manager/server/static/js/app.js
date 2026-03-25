/**
 * メインアプリケーション（3ペインレイアウト）
 */
(async function () {
  // --- DOM要素 ---
  const agentListEl = document.getElementById("agent-list");
  const conversationListEl = document.getElementById("conversation-list");
  const chatMessagesEl = document.getElementById("chat-messages");
  const chatInputEl = document.getElementById("chat-input");
  const btnSendEl = document.getElementById("btn-send");
  const btnNewConvEl = document.getElementById("btn-new-conversation");
  const logsListEl = document.getElementById("logs-list");
  const outputsListEl = document.getElementById("outputs-list");
  const missionContentEl = document.getElementById("mission-content");
  const taskContentEl = document.getElementById("task-content");

  // --- 状態 ---
  let agents = [];
  let currentAgentId = null;
  let viewingConversationId = null;  // 右ペインに表示中の会話
  let sendingConversationId = null;  // 送信中の会話（送信完了まで保持、null=送信していない）

  // --- 初期化 ---
  Chat.init(chatMessagesEl);
  Settings.init();
  ThinkTab.init({
    getAgentId: () => currentAgentId,
    getAgents: () => agents,
    logsListEl,
    showRightPane,
    loadMissionTask,
    formatTime,
    formatDateTime,
  });

  // --- エージェント一覧読み込み ---
  agents = await API.getAgents();
  renderAgentList();
  if (agents.length > 0) {
    selectAgent(agents[0].agent_id);
  }

  // --- エージェント一覧描画 ---
  function renderAgentList() {
    agentListEl.innerHTML = "";
    for (const agent of agents) {
      const li = document.createElement("li");
      li.className = "agent-item";
      li.dataset.agentId = agent.agent_id;

      const name = document.createElement("div");
      name.className = "agent-item-name";
      name.textContent = agent.config.name;

      const desc = document.createElement("div");
      desc.className = "agent-item-desc";
      desc.textContent = agent.config.description || "";

      li.appendChild(name);
      li.appendChild(desc);
      li.addEventListener("click", () => selectAgent(agent.agent_id));
      agentListEl.appendChild(li);
    }
  }

  // --- エージェント選択 ---
  async function selectAgent(agentId) {
    // 送信中チェック
    if (pendingChat && !confirm("応答待ちの会話があります。エージェントを切り替えますか？")) return;
    // 設定の未保存チェック
    if (Settings.hasUnsavedChanges && !Settings.confirmDiscard()) return;

    currentAgentId = agentId;
    viewingConversationId = null;
    sendingConversationId = null;

    // 左ペイン: ハイライト更新
    agentListEl.querySelectorAll(".agent-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.agentId === agentId);
    });

    const agent = agents.find((a) => a.agent_id === agentId);
    Chat.setAgentName(agent.config.name);

    // チャット入力有効化
    chatInputEl.disabled = false;
    updateSendButton();

    // 中ペイン: 各タブのデータを読み込み
    await loadConversations();
    loadLogs();
    loadMissionTask(agent);
    loadOutputs();
    Settings.load(agent);

    // 最新の会話を自動で開く
    const conversations = await API.getConversations(agentId);
    if (conversations.length > 0) {
      selectConversation(conversations[0].conversation_id);
    } else {
      showRightPane("right-empty");
    }
  }

  // ==============================
  // タブ切り替え（右ペインは維持）
  // ==============================
  document.getElementById("mid-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".mid-tab");
    if (!tab) return;

    // 設定タブから離れるとき未保存チェック
    const currentTab = document.querySelector(".mid-tab.active");
    if (currentTab && currentTab.dataset.view === "settings" && tab.dataset.view !== "settings") {
      if (Settings.hasUnsavedChanges && !Settings.confirmDiscard()) return;
    }

    // タブ切り替え
    document.querySelectorAll(".mid-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");

    // 中ペインのみ切り替え（右ペインは触らない）
    document.querySelectorAll(".mid-content").forEach((c) => c.classList.remove("active"));
    document.getElementById("mid-" + tab.dataset.view).classList.add("active");
  });

  // ==============================
  // チャットタブ
  // ==============================

  async function loadConversations() {
    const conversations = await API.getConversations(currentAgentId);
    conversationListEl.innerHTML = "";

    if (conversations.length === 0) {
      conversationListEl.innerHTML = '<li class="empty-state">会話はありません</li>';
      return;
    }

    for (const conv of conversations) {
      const li = document.createElement("li");
      li.className = "mid-list-item";
      if (conv.conversation_id === viewingConversationId || conv.conversation_id === sendingConversationId) li.classList.add("active");
      li.dataset.convId = conv.conversation_id;

      const date = document.createElement("div");
      date.className = "mid-list-date";
      date.textContent = formatDate(conv.updated_at);
      const count = document.createElement("span");
      count.className = "mid-list-count";
      count.textContent = conv.message_count + "件";
      date.appendChild(count);

      const preview = document.createElement("div");
      preview.className = "mid-list-preview";
      preview.textContent = conv.title || conv.last_message;

      li.appendChild(date);
      li.appendChild(preview);
      li.addEventListener("click", () => selectConversation(conv.conversation_id));
      conversationListEl.appendChild(li);
    }
  }

  // 送信中のチャット状態（null=送信していない）
  let pendingChat = null; // {userMessage, agentName, bubble}

  async function selectConversation(conversationId) {
    viewingConversationId = conversationId;

    // 中ペインのハイライト
    conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.convId === conversationId);
    });

    // 右ペイン: チャット表示
    const agent = agents.find((a) => a.agent_id === currentAgentId);
    const conv = await API.getConversation(currentAgentId, conversationId);
    Chat.renderHistory(conv.messages, agent.config.name);

    // チャットヘッダー表示
    const header = document.getElementById("right-chat-header");
    header.style.display = "";
    document.getElementById("right-chat-title").textContent = conv.title || formatDate(conv.updated_at) + " の会話";
    document.getElementById("right-chat-summary").textContent = conv.summary || "";

    showRightPane("right-chat");
  }

  // 要約する
  document.getElementById("btn-summarize").addEventListener("click", async () => {
    if (!viewingConversationId) return;
    const btn = document.getElementById("btn-summarize");
    btn.disabled = true;
    btn.textContent = "要約中...";
    try {
      const result = await API.summarizeConversation(currentAgentId, viewingConversationId);
      document.getElementById("right-chat-title").textContent = result.title || "";
      document.getElementById("right-chat-summary").textContent = result.summary || "";
      await loadConversations();
    } catch (e) {
      alert("要約に失敗しました: " + e.message);
    }
    btn.textContent = "要約する";
    btn.disabled = false;
  });

  // CLI起動
  document.getElementById("btn-launch-cli").addEventListener("click", async () => {
    if (!currentAgentId) return;
    try {
      const conv = viewingConversationId
        ? await API.getConversation(currentAgentId, viewingConversationId)
        : null;
      const sessionId = conv && conv.session_id ? conv.session_id : null;
      await API.launchCLI(currentAgentId, sessionId);
    } catch (e) {
      alert("CLI起動に失敗しました: " + e.message);
    }
  });

  // 会話削除
  document.getElementById("btn-delete-chat").addEventListener("click", async () => {
    if (!viewingConversationId) return;
    if (!confirm("この会話を削除しますか？")) return;
    await API.deleteConversation(currentAgentId, viewingConversationId);
    viewingConversationId = null;
    Chat.clear();
    document.getElementById("right-chat-header").style.display = "none";
    showRightPane("right-empty");
    await loadConversations();
  });

  // 新規会話
  btnNewConvEl.addEventListener("click", () => {
    viewingConversationId = null;
    Chat.clear();
    chatInputEl.focus();
    document.getElementById("right-chat-header").style.display = "none";

    // 中ペインのハイライト解除
    conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => {
      el.classList.remove("active");
    });

    showRightPane("right-chat");
  });

  // ミッションについて話す
  document.getElementById("btn-talk-mission").addEventListener("click", () => {
    const agent = agents.find((a) => a.agent_id === currentAgentId);
    const hasMission = agent && agent.mission;
    const hasTask = agent && agent.task;

    let message;
    if (hasMission) {
      message = "mission.md と task.md を読んで、現状の課題や次にやるべきことについて話そう";
    } else {
      message = "まだ mission.md がないので、一緒にミッションを考えよう。CLAUDE.md を読んで、自分の役割からミッションを提案して";
    }

    // 新規会話を開始（中ペインはミッションのまま）
    viewingConversationId = null;
    Chat.clear();
    showRightPane("right-chat");

    chatInputEl.value = message;
    sendMessage();
  });

  /** 新規会話の仮アイテムを作成して会話リストに追加する */
  function createPendingConvItem(previewText) {
    const li = document.createElement("li");
    li.className = "mid-list-item active";

    const date = document.createElement("div");
    date.className = "mid-list-date";
    date.textContent = formatDate(new Date().toISOString());

    const preview = document.createElement("div");
    preview.className = "mid-list-preview";
    preview.textContent = previewText.slice(0, 80);

    li.appendChild(date);
    li.appendChild(preview);
    li.addEventListener("click", () => {
      conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
      li.classList.add("active");
      if (pendingChat) {
        restorePendingChat();
      } else if (li.dataset.convId) {
        selectConversation(li.dataset.convId);
      } else {
        showRightPane("right-chat");
      }
    });

    conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
    conversationListEl.prepend(li);
    return li;
  }

  /** pendingChat のデータからチャット画面を再描画する */
  function restorePendingChat() {
    Chat.clear();
    Chat.addMessage("user", pendingChat.userMessage, "あなた");
    const newBubble = Chat.addStreamingMessage(pendingChat.agentName);
    newBubble._rawText = pendingChat.bubble._rawText || "";
    if (newBubble._rawText) {
      newBubble.innerHTML = marked.parse(newBubble._rawText);
    }
    pendingChat.bubble = newBubble;
    document.getElementById("right-chat-header").style.display = "none";
    showRightPane("right-chat");
  }

  /** 送信完了時の共通クリーンアップ */
  function finishSending() {
    if (!viewingConversationId || viewingConversationId === sendingConversationId) {
      viewingConversationId = sendingConversationId;
    }
    sendingConversationId = null;
    pendingChat = null;
    setInputEnabled(true);
    chatInputEl.focus();
  }

  // メッセージ送信
  async function sendMessage() {
    const message = chatInputEl.value.trim();
    if (!message || pendingChat) return;

    chatInputEl.value = "";
    setInputEnabled(false);
    sendingConversationId = viewingConversationId;

    const pendingConvItem = sendingConversationId ? null : createPendingConvItem(message);

    showRightPane("right-chat");
    Chat.addMessage("user", message, "あなた");
    const agent = agents.find((a) => a.agent_id === currentAgentId);
    const bubble = Chat.addStreamingMessage(agent.config.name);
    pendingChat = { userMessage: message, agentName: agent.config.name, bubble };

    await API.sendMessage(currentAgentId, message, sendingConversationId, {
      onConversationId(id) {
        sendingConversationId = id;
        if (pendingConvItem) pendingConvItem.dataset.convId = id;
      },
      onChunk(chunk) {
        Chat.appendChunk(pendingChat.bubble, chunk);
      },
      async onDone() {
        Chat.finishStreaming(pendingChat.bubble, pendingChat.bubble._rawText || "");
        finishSending();
        await loadConversations();
      },
      onError(errorMsg) {
        Chat.finishStreaming(pendingChat.bubble, "エラー: " + errorMsg);
        finishSending();
      },
    });
  }

  btnSendEl.addEventListener("click", sendMessage);
  chatInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  chatInputEl.addEventListener("input", updateSendButton);

  function setInputEnabled(enabled) {
    chatInputEl.disabled = !enabled;
    btnSendEl.disabled = !enabled;
  }

  function updateSendButton() {
    if (pendingChat) return;
    btnSendEl.disabled = !chatInputEl.value.trim();
  }

  // ==============================
  // 思考タブ（think-tab.js に委譲）
  // ==============================

  function loadLogs() { return ThinkTab.loadLogs(); }

  // ミッションタブ
  // ==============================

  function loadMissionTask(agent) {
    missionContentEl.innerHTML = agent.mission
      ? marked.parse(agent.mission)
      : '<span class="text-muted">未設定</span>';
    taskContentEl.innerHTML = agent.task
      ? marked.parse(agent.task)
      : '<span class="text-muted">未設定</span>';
    // 編集モードを閉じる
    document.getElementById("mission-view").style.display = "";
    document.getElementById("mission-edit").style.display = "none";
    document.getElementById("btn-edit-mission").textContent = "編集";
  }

  // 編集モード切り替え
  document.getElementById("btn-edit-mission").addEventListener("click", () => {
    const view = document.getElementById("mission-view");
    const edit = document.getElementById("mission-edit");
    const btn = document.getElementById("btn-edit-mission");

    if (edit.style.display === "none") {
      // 表示→編集
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      document.getElementById("edit-mission").value = agent.mission || "";
      document.getElementById("edit-task").value = agent.task || "";
      view.style.display = "none";
      edit.style.display = "";
      btn.textContent = "表示";
    } else {
      // 編集→表示
      view.style.display = "";
      edit.style.display = "none";
      btn.textContent = "編集";
    }
  });

  // キャンセル
  document.getElementById("btn-cancel-mission").addEventListener("click", () => {
    document.getElementById("mission-view").style.display = "";
    document.getElementById("mission-edit").style.display = "none";
    document.getElementById("btn-edit-mission").textContent = "編集";
  });

  // 保存
  document.getElementById("btn-save-mission").addEventListener("click", async () => {
    const mission = document.getElementById("edit-mission").value;
    const task = document.getElementById("edit-task").value;
    try {
      await API.updateMission(currentAgentId, mission);
      await API.updateTask(currentAgentId, task);
      // エージェント情報を再取得して表示を更新
      agents = await API.getAgents();
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      loadMissionTask(agent);
    } catch (e) {
      alert("保存に失敗しました: " + e.message);
    }
  });

  // ==============================
  // 成果物タブ
  // ==============================

  async function loadOutputs() {
    if (!currentAgentId) return;
    const outputs = await API.getOutputs(currentAgentId);
    outputsListEl.innerHTML = "";

    if (outputs.length === 0) {
      outputsListEl.innerHTML = '<li class="empty-state">成果物はありません</li>';
      return;
    }

    for (const output of outputs) {
      const li = document.createElement("li");
      li.className = "mid-list-item";

      const preview = document.createElement("div");
      preview.className = "mid-list-preview";
      preview.textContent = output.filename;

      const size = document.createElement("span");
      size.className = "mid-list-size";
      size.textContent = formatSize(output.size);
      preview.appendChild(size);

      li.appendChild(preview);
      li.addEventListener("click", () => showOutputDetail(output.filename, li));
      outputsListEl.appendChild(li);
    }
  }

  async function showOutputDetail(filename, listItem) {
    // 中ペインのハイライト
    outputsListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
    if (listItem) listItem.classList.add("active");

    const data = await API.getOutputContent(currentAgentId, filename);
    const container = document.getElementById("right-output-detail");
    container.innerHTML = "";

    const preview = document.createElement("div");
    preview.className = "right-preview";
    preview.innerHTML = marked.parse(data.content);
    container.appendChild(preview);

    showRightPane("right-output-detail");
  }

  // ==============================
  // 設定タブ（保存ボタン）
  // ==============================

  document.getElementById("btn-save").addEventListener("click", async () => {
    const saved = await Settings.save(currentAgentId);
    if (saved) {
      agents = await API.getAgents();
      renderAgentList();
    }
  });

  // ==============================
  // 右ペイン制御
  // ==============================

  function showRightPane(id) {
    document.getElementById("right-empty").style.display = "none";
    document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
    const el = document.getElementById(id);
    if (el) {
      if (el.classList.contains("right-content")) {
        el.classList.add("active");
      } else {
        el.style.display = "";
      }
    }
  }

  // ==============================
  // ユーティリティ
  // ==============================

  function formatDate(isoStr) {
    const d = new Date(isoStr);
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${y}/${mo}/${day} ${h}:${mi}`;
  }

  function formatTime(isoStr) {
    if (!isoStr) return "";
    const d = new Date(isoStr);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function formatDateTime(isoStr) {
    if (!isoStr) return "";
    const d = new Date(isoStr);
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    const s = String(d.getSeconds()).padStart(2, "0");
    return `${y}/${mo}/${day} ${h}:${mi}:${s}`;
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    return (bytes / 1024).toFixed(1) + " KB";
  }

  // ==============================
  // リサイズハンドル（中ペイン↔右ペイン）
  // ==============================
  (() => {
    const handle = document.getElementById("pane-resize-handle");
    const midPane = document.querySelector(".pane-mid");
    let dragging = false;

    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      dragging = true;
      handle.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const leftWidth = document.querySelector(".pane-left").offsetWidth;
      const newMidWidth = e.clientX - leftWidth;
      const minWidth = 200;
      const maxWidth = window.innerWidth - leftWidth - 300;
      if (newMidWidth >= minWidth && newMidWidth <= maxWidth) {
        midPane.style.width = newMidWidth + "px";
        midPane.style.minWidth = newMidWidth + "px";
      }
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    });
  })();
})();
