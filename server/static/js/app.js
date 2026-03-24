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

  // --- 状態 ---
  let agents = [];
  let currentAgentId = null;
  let currentConversationId = null;
  let isSending = false;

  // --- 初期化 ---
  Chat.init(chatMessagesEl);

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
  }

  // --- 新規会話 ---
  btnNewConvEl.addEventListener("click", () => {
    currentConversationId = null;
    Chat.clear();
    chatInputEl.focus();

    // 会話一覧のハイライトを解除
    conversationListEl.querySelectorAll(".conversation-item").forEach((el) => {
      el.classList.remove("active");
    });
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
