/**
 * メインアプリケーション
 */
(async function () {
  // --- DOM要素 ---
  const agentListEl = document.getElementById("agent-list");
  const conversationListEl = document.getElementById("conversation-list");
  const headerNameEl = document.getElementById("header-name");
  const headerModelEl = document.getElementById("header-model");
  const chatMessagesEl = document.getElementById("chat-messages");
  const chatInputEl = document.getElementById("chat-input");
  const btnSendEl = document.getElementById("btn-send");
  const btnNewConvEl = document.getElementById("btn-new-conversation");
  const btnLaunchCliEl = document.getElementById("btn-launch-cli");
  const btnSettingsEl = document.getElementById("btn-settings");
  const btnBackChatEl = document.getElementById("btn-back-chat");
  const btnThinkEl = document.getElementById("btn-think");
  const chatViewEl = document.getElementById("chat-view");
  const settingsViewEl = document.getElementById("settings-view");
  const logsViewEl = document.getElementById("logs-view");
  const outputsViewEl = document.getElementById("outputs-view");
  const viewTabsEl = document.getElementById("view-tabs");

  // --- 状態 ---
  let agents = [];
  let currentAgentId = null;
  let currentConversationId = null;
  let currentSessionId = null;
  let isSending = false;
  let inSettingsView = false;
  let currentView = "chat";

  // --- 初期化 ---
  Chat.init(chatMessagesEl);
  Settings.init();
  Think.init();
  showView("chat");

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

  // --- 画面切り替え ---
  function showView(view) {
    if (inSettingsView && view !== "settings" && !Settings.confirmDiscard()) return;

    currentView = view;
    inSettingsView = view === "settings";

    chatViewEl.classList.toggle("hidden", view !== "chat");
    logsViewEl.classList.toggle("hidden", view !== "logs");
    outputsViewEl.classList.toggle("hidden", view !== "outputs");
    settingsViewEl.classList.toggle("hidden", view !== "settings");

    // タブのハイライト
    viewTabsEl.querySelectorAll(".view-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.view === view);
    });

    // ヘッダーボタンの表示制御
    btnSettingsEl.style.display = view === "settings" ? "none" : "";
    btnThinkEl.style.display = view === "settings" ? "none" : "";
    btnNewConvEl.style.display = view === "chat" ? "" : "none";
    btnLaunchCliEl.style.display = view === "chat" ? "" : "none";
    btnBackChatEl.style.display = view === "settings" ? "" : "none";
    viewTabsEl.style.display = view === "settings" ? "none" : "";

    if (view === "settings") {
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      if (agent) Settings.load(agent);
    } else if (view === "logs" && currentAgentId) {
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      if (agent) Think.showMissionTask(agent);
      Think.loadLogs(currentAgentId);
    } else if (view === "outputs" && currentAgentId) {
      Think.loadOutputs(currentAgentId);
    }
  }

  // タブクリック
  viewTabsEl.addEventListener("click", (e) => {
    const tab = e.target.closest(".view-tab");
    if (tab) showView(tab.dataset.view);
  });

  btnSettingsEl.addEventListener("click", () => showView("settings"));
  btnBackChatEl.addEventListener("click", () => showView("chat"));

  // 設定画面の保存ボタン
  document.getElementById("btn-save").addEventListener("click", async () => {
    const saved = await Settings.save(currentAgentId);
    if (saved) {
      // エージェント一覧を再取得して反映
      agents = await API.getAgents();
      renderAgentList();
      // ヘッダーも更新
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      if (agent) {
        headerNameEl.textContent = agent.config.name;
        headerModelEl.textContent = agent.config.model;
      }
    }
  });

  // --- エージェント選択 ---
  async function selectAgent(agentId) {
    // 設定画面で未保存の変更がある場合、確認ダイアログ
    if (inSettingsView && !Settings.confirmDiscard()) return;

    currentAgentId = agentId;
    currentConversationId = null;

    // ハイライト更新
    agentListEl.querySelectorAll(".agent-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.agentId === agentId);
    });

    // ヘッダー更新
    const agent = agents.find((a) => a.agent_id === agentId);
    headerNameEl.textContent = agent.config.name;
    headerModelEl.textContent = agent.config.model;
    Chat.setAgentName(agent.config.name);

    // 現在のビューに応じて更新
    if (inSettingsView) {
      Settings.load(agent);
    } else if (currentView === "logs") {
      Think.showMissionTask(agent);
      Think.loadLogs(agentId);
    } else if (currentView === "outputs") {
      Think.loadOutputs(agentId);
    }

    // 入力有効化
    chatInputEl.disabled = false;
    updateSendButton();

    // 会話一覧読み込み
    await loadConversations();

    // 最新の会話を自動で開く
    const conversations = await API.getConversations(agentId);
    if (conversations.length > 0) {
      await selectConversation(conversations[0].conversation_id);
    } else {
      Chat.clear();
    }
  }

  // --- 会話一覧描画 ---
  async function loadConversations() {
    const conversations = await API.getConversations(currentAgentId);
    conversationListEl.innerHTML = "";

    for (const conv of conversations) {
      const li = document.createElement("li");
      li.className = "conversation-item";
      if (conv.conversation_id === currentConversationId) {
        li.classList.add("active");
      }
      li.dataset.convId = conv.conversation_id;

      const date = document.createElement("div");
      date.className = "conversation-date";
      date.textContent = formatDate(conv.updated_at);

      const preview = document.createElement("div");
      preview.className = "conversation-preview";
      preview.textContent = conv.last_message;

      li.appendChild(date);
      li.appendChild(preview);
      li.addEventListener("click", () => selectConversation(conv.conversation_id));
      conversationListEl.appendChild(li);
    }
  }

  // --- 会話選択 ---
  async function selectConversation(conversationId) {
    currentConversationId = conversationId;

    // ハイライト更新
    conversationListEl.querySelectorAll(".conversation-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.convId === conversationId);
    });

    // 履歴読み込み
    const agent = agents.find((a) => a.agent_id === currentAgentId);
    const conv = await API.getConversation(currentAgentId, conversationId);
    Chat.renderHistory(conv.messages, agent.config.name);

    // セッションID表示
    updateSessionId(conv.session_id);
  }

  // --- 新規会話 ---
  btnNewConvEl.addEventListener("click", () => {
    currentConversationId = null;
    Chat.clear();
    chatInputEl.focus();
    updateSessionId(null);

    // 会話一覧のハイライトを解除
    conversationListEl.querySelectorAll(".conversation-item").forEach((el) => {
      el.classList.remove("active");
    });
  });

  // --- 思考実行 ---
  btnThinkEl.addEventListener("click", async () => {
    if (!currentAgentId) return;
    btnThinkEl.disabled = true;
    btnThinkEl.textContent = "思考中...";
    try {
      const result = await API.think(currentAgentId);
      if (!result.success) {
        alert(`思考失敗: ${result.error}`);
      }
      // エージェント情報を再取得（mission/taskが更新された可能性）
      agents = await API.getAgents();
      // ログタブに遷移して結果を見せる
      const agent = agents.find((a) => a.agent_id === currentAgentId);
      if (agent) Think.showMissionTask(agent);
      showView("logs");
      Think.loadLogs(currentAgentId);
    } catch (e) {
      alert("思考実行に失敗しました: " + e.message);
    }
    btnThinkEl.textContent = "思考実行";
    btnThinkEl.disabled = false;
  });

  // --- Claude CLI起動 ---
  btnLaunchCliEl.addEventListener("click", async () => {
    if (!currentAgentId) return;
    btnLaunchCliEl.disabled = true;
    btnLaunchCliEl.textContent = "起動中...";
    try {
      await API.launchCLI(currentAgentId, currentSessionId);
    } catch (e) {
      alert("CLI起動に失敗しました: " + e.message);
    }
    btnLaunchCliEl.textContent = "Claude起動";
    btnLaunchCliEl.disabled = false;
  });

  // --- メッセージ送信 ---
  async function sendMessage() {
    const message = chatInputEl.value.trim();
    if (!message || isSending) return;

    isSending = true;
    chatInputEl.value = "";
    setInputEnabled(false);

    // ユーザーメッセージ表示
    Chat.addMessage("user", message, "あなた");

    // ストリーミング応答
    const agent = agents.find((a) => a.agent_id === currentAgentId);
    const bubble = Chat.addStreamingMessage(agent.config.name);

    await API.sendMessage(currentAgentId, message, currentConversationId, {
      onConversationId(id) {
        currentConversationId = id;
      },
      onChunk(chunk) {
        Chat.appendChunk(bubble, chunk);
      },
      async onDone() {
        Chat.finishStreaming(bubble, bubble._rawText || "");
        isSending = false;
        setInputEnabled(true);
        chatInputEl.focus();
        await loadConversations();
      },
      onError(errorMsg) {
        Chat.finishStreaming(bubble, "エラー: " + errorMsg);
        isSending = false;
        setInputEnabled(true);
        chatInputEl.focus();
      },
    });
  }

  // --- 入力制御 ---
  function setInputEnabled(enabled) {
    chatInputEl.disabled = !enabled;
    btnSendEl.disabled = !enabled;
  }

  function updateSendButton() {
    if (isSending) return;
    btnSendEl.disabled = !chatInputEl.value.trim();
  }

  // --- イベントリスナー ---
  btnSendEl.addEventListener("click", sendMessage);

  chatInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  chatInputEl.addEventListener("input", updateSendButton);

  // --- セッションID表示 ---
  const headerSessionEl = document.getElementById("header-session");

  function updateSessionId(sessionId) {
    currentSessionId = sessionId;
    if (sessionId) {
      headerSessionEl.textContent = `claude --resume ${sessionId}`;
      headerSessionEl.style.cursor = "pointer";
      headerSessionEl.title = "クリックでコピー";
      headerSessionEl.onclick = () => {
        navigator.clipboard.writeText(`claude --resume ${sessionId}`);
        const original = headerSessionEl.textContent;
        headerSessionEl.textContent = "コピーしました";
        setTimeout(() => { headerSessionEl.textContent = original; }, 1000);
      };
    } else {
      headerSessionEl.textContent = "";
      headerSessionEl.onclick = null;
    }
  }

  // --- ユーティリティ ---
  function formatDate(isoStr) {
    const d = new Date(isoStr);
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${y}/${mo}/${day} ${h}:${mi}`;
  }
})();
