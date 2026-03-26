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
  const tasksListEl = document.getElementById("tasks-list");
  const missionContentEl = document.getElementById("mission-content");
  const taskContentEl = document.getElementById("task-content");

  // --- 状態 ---
  let agents = [];
  let currentAgentId = null;
  let viewingConversationId = null;  // 右ペインに表示中の会話

  // 送信中の会話（複数同時対応）
  // Map<pendingId, {agentId, userMessage, agentName, rawText, bubble, convId, finished}>
  const pendingChats = new Map();
  let activePendingId = null;  // 右ペインに表示中のpending（null=表示していない）
  let nextPendingId = 1;

  /** 右ペインに表示中のpendingを返す */
  function currentPending() {
    return activePendingId ? pendingChats.get(activePendingId) : null;
  }

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

  // --- 定期ポーリング開始 ---
  startAutoRefresh();

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

  // --- 定期ポーリング ---
  function hasAgentsChanged(oldAgents, newAgents) {
    if (oldAgents.length !== newAgents.length) {
      console.log('[Auto Refresh] エージェント数が変更されました');
      return true;
    }

    // agent_idでマッピングして比較
    for (const newAgent of newAgents) {
      const oldAgent = oldAgents.find(a => a.agent_id === newAgent.agent_id);

      if (!oldAgent) {
        console.log(`[Auto Refresh] 新しいエージェント発見: ${newAgent.agent_id}`);
        return true;
      }

      // mission、task、configの変更をチェック
      if (oldAgent.mission !== newAgent.mission) {
        console.log(`[Auto Refresh] ${newAgent.agent_id} の mission が変更されました`);
        return true;
      }

      if (oldAgent.task !== newAgent.task) {
        console.log(`[Auto Refresh] ${newAgent.agent_id} の task が変更されました`);
        return true;
      }

      if (JSON.stringify(oldAgent.config) !== JSON.stringify(newAgent.config)) {
        console.log(`[Auto Refresh] ${newAgent.agent_id} の config が変更されました`);
        return true;
      }
    }

    return false;
  }

  function startAutoRefresh() {
    console.log('[Auto Refresh] 定期ポーリング開始 (5秒間隔)');
    setInterval(async () => {
      try {
        console.log('[Auto Refresh] ポーリング実行中...');
        const latestAgents = await API.getAgents();

        const changed = hasAgentsChanged(agents, latestAgents);
        console.log(`[Auto Refresh] 変更チェック結果: ${changed}`);

        if (changed) {
          console.log('[Auto Refresh] エージェント情報が更新されました');

          const previousAgentId = currentAgentId;
          agents = latestAgents;

          // 現在選択中のエージェントのみ、静かに更新
          if (previousAgentId && agents.find(a => a.agent_id === previousAgentId)) {
            const currentAgent = agents.find(a => a.agent_id === previousAgentId);

            // mission/taskのみ更新（スクロール位置を保持）
            const missionEl = document.getElementById("mission-content");
            const taskEl = document.getElementById("task-content");

            if (missionEl) {
              missionEl.innerHTML = currentAgent.mission
                ? marked.parse(currentAgent.mission)
                : '<span class="text-muted">未設定</span>';
            }

            if (taskEl) {
              taskEl.innerHTML = currentAgent.task
                ? marked.parse(currentAgent.task)
                : '<span class="text-muted">未設定</span>';
            }

            // 設定画面が開いている場合は更新
            if (typeof Settings !== 'undefined' && Settings.refreshCurrentAgent) {
              Settings.refreshCurrentAgent(currentAgent);
            }
          }
        }
      } catch (error) {
        console.error('[Auto Refresh] エラー:', error);
      }
    }, 5000); // 5秒間隔
  }

  // --- エージェント選択 ---
  async function selectAgent(agentId) {
    // 設定の未保存チェック
    if (Settings.hasUnsavedChanges && !Settings.confirmDiscard()) return;

    currentAgentId = agentId;
    viewingConversationId = null;
    activePendingId = null;

    // 左ペイン: ハイライト更新
    agentListEl.querySelectorAll(".agent-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.agentId === agentId);
    });

    const agent = agents.find((a) => a.agent_id === agentId);
    Chat.setAgentName(agent.config.name);

    // 中ペイン: 各タブのデータを読み込み
    await loadConversations();
    loadLogs();
    loadMissionTask(agent);
    loadOutputs();
    loadTasks();
    Settings.load(agent);

    // このエージェントにストリーミング中のpendingがあれば最初の1つを復元
    const agentPending = findAgentPending(agentId);
    if (agentPending) {
      activePendingId = agentPending.id;
      restorePendingChat(agentPending.pending);
      setInputEnabled(false);
    } else {
      chatInputEl.disabled = false;
      updateSendButton();
      const conversations = await API.getConversations(agentId);
      if (conversations.length > 0) {
        selectConversation(conversations[0].conversation_id);
      } else {
        showRightPane("right-empty");
      }
    }
  }

  /** 指定エージェントの未完了pendingを1つ探す */
  function findAgentPending(agentId) {
    for (const [id, p] of pendingChats) {
      if (p.agentId === agentId && !p.finished) {
        return { id, pending: p };
      }
    }
    return null;
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

    // このエージェントの未完了pendingを先頭に表示
    for (const [id, p] of pendingChats) {
      if (p.agentId === currentAgentId && !p.finished) {
        const li = createPendingListItem(id, p);
        if (id === activePendingId) li.classList.add("active");
        conversationListEl.appendChild(li);
      }
    }

    if (conversations.length === 0 && conversationListEl.children.length === 0) {
      conversationListEl.innerHTML = '<li class="empty-state">会話はありません</li>';
      return;
    }

    for (const conv of conversations) {
      const li = document.createElement("li");
      li.className = "mid-list-item";
      if (conv.conversation_id === viewingConversationId) li.classList.add("active");
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

  /** pendingのリストアイテムを作成する */
  function createPendingListItem(pendingId, pending) {
    const li = document.createElement("li");
    li.className = "mid-list-item";
    li.dataset.pendingId = pendingId;

    const date = document.createElement("div");
    date.className = "mid-list-date";
    date.textContent = "応答中...";

    const preview = document.createElement("div");
    preview.className = "mid-list-preview";
    preview.textContent = pending.userMessage.slice(0, 80);

    li.appendChild(date);
    li.appendChild(preview);
    li.addEventListener("click", () => {
      viewingConversationId = null;
      activePendingId = pendingId;
      highlightListItem(li);
      restorePendingChat(pending);
      setInputEnabled(false);
    });
    return li;
  }

  function highlightListItem(activeLi) {
    conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
    if (activeLi) activeLi.classList.add("active");
  }

  async function selectConversation(conversationId) {
    viewingConversationId = conversationId;
    activePendingId = null;

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

    setInputEnabled(true);
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
    activePendingId = null;
    Chat.clear();
    setInputEnabled(true);
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

    let message;
    if (hasMission) {
      message = "mission.md と task.md を読んで、現状の課題や次にやるべきことについて話そう";
    } else {
      message = "まだ mission.md がないので、一緒にミッションを考えよう。CLAUDE.md を読んで、自分の役割からミッションを提案して";
    }

    // 新規会話を開始
    viewingConversationId = null;
    activePendingId = null;
    Chat.clear();
    showRightPane("right-chat");

    chatInputEl.value = message;
    sendMessage();
  });

  /** pending のデータからチャット画面を再描画する */
  function restorePendingChat(pending) {
    Chat.clear();
    Chat.addMessage("user", pending.userMessage, "あなた");
    const newBubble = Chat.addStreamingMessage(pending.agentName);
    newBubble._rawText = pending.rawText;
    if (pending.rawText) {
      newBubble.innerHTML = marked.parse(pending.rawText);
    }
    pending.bubble = newBubble;
    document.getElementById("right-chat-header").style.display = "none";
    showRightPane("right-chat");
  }

  /** 送信完了時のクリーンアップ */
  function finishSending(pendingId) {
    const pending = pendingChats.get(pendingId);
    if (!pending) return;
    pending.finished = true;
    pendingChats.delete(pendingId);

    // 完了したpendingを今見ている場合 → 入力有効化
    if (activePendingId === pendingId) {
      activePendingId = null;
      if (pending.convId) viewingConversationId = pending.convId;
      setInputEnabled(true);
      chatInputEl.focus();
    }

    // 同じエージェントを見ている場合 → 会話一覧更新
    if (currentAgentId === pending.agentId) {
      loadConversations();
    }
  }

  // メッセージ送信
  async function sendMessage() {
    const message = chatInputEl.value.trim();
    // activePendingIdがある＝今ストリーミング中の画面を見てるので送信不可
    if (!message || activePendingId) return;

    const sendAgentId = currentAgentId;
    const sendConvId = viewingConversationId;
    const pendingId = nextPendingId++;

    chatInputEl.value = "";
    setInputEnabled(false);

    showRightPane("right-chat");
    Chat.addMessage("user", message, "あなた");
    const agent = agents.find((a) => a.agent_id === sendAgentId);
    const bubble = Chat.addStreamingMessage(agent.config.name);

    const pending = {
      agentId: sendAgentId,
      userMessage: message,
      agentName: agent.config.name,
      bubble,
      rawText: "",
      convId: sendConvId,
      finished: false,
    };
    pendingChats.set(pendingId, pending);
    activePendingId = pendingId;

    // 中ペインにpendingアイテムを追加（新規会話の場合）
    if (!sendConvId) {
      const li = createPendingListItem(pendingId, pending);
      li.classList.add("active");
      conversationListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
      conversationListEl.prepend(li);
    }

    await API.sendMessage(sendAgentId, message, sendConvId, {
      onConversationId(id) {
        pending.convId = id;
      },
      onChunk(chunk) {
        pending.rawText += chunk;
        // 今このpendingを見ている場合のみDOMを更新
        if (activePendingId === pendingId) {
          Chat.appendChunk(pending.bubble, chunk);
        }
      },
      onToolUse(description) {
        pending.lastToolUse = description;
        if (activePendingId === pendingId) {
          Chat.showToolUse(pending.bubble, description);
        }
      },
      async onDone() {
        if (activePendingId === pendingId) {
          Chat.finishStreaming(pending.bubble, pending.rawText);
        }
        finishSending(pendingId);
      },
      onError(errorMsg) {
        pending.rawText += "\n\nエラー: " + errorMsg;
        if (activePendingId === pendingId) {
          Chat.finishStreaming(pending.bubble, "エラー: " + errorMsg);
        }
        finishSending(pendingId);
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
    if (activePendingId) return;
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

      const date = document.createElement("span");
      date.className = "mid-list-date";
      date.textContent = output.date || "";

      const title = document.createElement("span");
      title.className = "mid-list-title";
      title.textContent = output.title || output.filename;

      preview.appendChild(date);
      preview.appendChild(title);

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
  // タスクタブ
  // ==============================

  async function loadTasks() {
    if (!currentAgentId) return;
    const tasks = await API.getTasks(currentAgentId);
    tasksListEl.innerHTML = "";

    if (tasks.length === 0) {
      tasksListEl.innerHTML = '<li class="empty-state">タスクはありません</li>';
      return;
    }

    for (const task of tasks) {
      const li = document.createElement("li");
      li.className = "mid-list-item task-item";

      // 1行目: タイトル + ステータス
      const titleRow = document.createElement("div");
      titleRow.className = "task-title-row";

      const title = document.createElement("span");
      title.className = "task-title";
      title.textContent = task.title;

      const statusBadge = document.createElement("span");
      statusBadge.className = "task-status-badge task-status-" + (task.status === "未承認" ? "pending" : task.status === "承認済" ? "approved" : "done");
      statusBadge.textContent = task.status;

      // 2行目: プログレスバー + 進捗率
      const progressRow = document.createElement("div");
      progressRow.className = "task-progress-row";

      const progressBar = document.createElement("div");
      progressBar.className = "task-progress-bar";
      const progressFill = document.createElement("div");
      progressFill.className = "task-progress-fill";
      if (task.progress >= 100) progressFill.classList.add("task-progress-done");
      progressFill.style.width = task.progress + "%";
      progressBar.appendChild(progressFill);

      const progressText = document.createElement("span");
      progressText.className = "task-progress-text";
      progressText.textContent = task.progress + "% (" + task.completed_tasks + "/" + task.total_tasks + ")";

      progressRow.appendChild(progressBar);
      progressRow.appendChild(progressText);

      titleRow.appendChild(title);
      titleRow.appendChild(statusBadge);
      li.appendChild(titleRow);
      li.appendChild(progressRow);
      li.addEventListener("click", () => showTaskDetail(task.filename, li));
      tasksListEl.appendChild(li);
    }
  }

  async function showTaskDetail(filename, listItem) {
    tasksListEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
    if (listItem) listItem.classList.add("active");

    const data = await API.getTaskContent(currentAgentId, filename);
    const container = document.getElementById("right-task-detail");
    container.innerHTML = "";

    const preview = document.createElement("div");
    preview.className = "right-preview";
    preview.innerHTML = marked.parse(data.content);
    container.appendChild(preview);

    showRightPane("right-task-detail");
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
