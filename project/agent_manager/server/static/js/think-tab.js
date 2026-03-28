/**
 * 思考タブのロジック
 * ヘルパー関数、ログ表示、ストリーミング実行を管理する
 */
const ThinkTab = (() => {
  // init() で受け取る依存
  let _deps = null; // { getAgentId, getAgents, logsListEl, showRightPane, loadMissionTask, formatTime, formatDateTime }

  // 思考ストリーミング状態（null=実行していない）
  let thinkState = null; // { events: [], finished: null, prompt: "" }

  // DOM要素（init で取得）
  let btnThinkRunEl;

  // ============================================================
  // 初期化
  // ============================================================

  function init(deps) {
    _deps = deps;
    btnThinkRunEl = document.getElementById("btn-think-run");

    btnThinkRunEl.addEventListener("click", () => startThink(false));

    // プロンプト表示
    document.getElementById("btn-think-prompt").addEventListener("click", async () => {
      const agentId = _deps.getAgentId();
      if (!agentId) return;
      try {
        const data = await API.getThinkPrompt(agentId);
        document.getElementById("edit-think-prompt").value = data.content || "";
      } catch (e) {
        document.getElementById("edit-think-prompt").value = "";
      }
      _deps.showRightPane("right-think-prompt");
    });

    // プロンプト保存
    document.getElementById("btn-save-think-prompt").addEventListener("click", async () => {
      const agentId = _deps.getAgentId();
      if (!agentId) return;
      const content = document.getElementById("edit-think-prompt").value;
      try {
        await API.updateThinkPrompt(agentId, content);
        const btn = document.getElementById("btn-save-think-prompt");
        const feedback = document.getElementById("think-prompt-feedback");
        btn.textContent = "保存しました";
        btn.classList.add("saved");
        feedback.classList.add("visible");
        setTimeout(() => {
          btn.textContent = "保存";
          btn.classList.remove("saved");
          feedback.classList.remove("visible");
        }, 2000);
      } catch (e) {
        alert("保存に失敗しました: " + e.message);
      }
    });
  }

  // ============================================================
  // ヘルパー
  // ============================================================

  /** 折りたたみ可能なプロンプトセクションを生成 */
  function createCollapsiblePrompt(promptText) {
    const section = document.createElement("div");
    section.className = "right-detail-section";
    const label = document.createElement("div");
    label.className = "right-detail-label right-detail-toggle";
    label.textContent = "▶ プロンプト";
    const pre = document.createElement("div");
    pre.className = "right-detail-pre";
    pre.textContent = promptText;
    pre.style.display = "none";
    label.addEventListener("click", () => {
      const hidden = pre.style.display === "none";
      pre.style.display = hidden ? "" : "none";
      label.textContent = (hidden ? "▼ " : "▶ ") + "プロンプト";
    });
    section.appendChild(label);
    section.appendChild(pre);
    return section;
  }

  /** ストリーミングイベント要素を生成 */
  function createStreamEventEl(ev) {
    const el = document.createElement("div");
    if (ev.type === "tool_use") {
      el.className = "think-stream-tool";
    } else if (ev.type === "error") {
      el.className = "think-stream-error";
    } else {
      el.className = "think-stream-text";
    }
    el.textContent = ev.content;
    return el;
  }

  // ============================================================
  // ログ一覧・詳細
  // ============================================================

  async function loadLogs() {
    const agentId = _deps.getAgentId();
    if (!agentId) return;
    const logs = await API.getLogs(agentId);
    const listEl = _deps.logsListEl;
    listEl.innerHTML = "";

    if (logs.length === 0) {
      listEl.innerHTML = '<li class="empty-state">思考履歴はありません</li>';
      return;
    }

    for (const log of logs) {
      const li = document.createElement("li");
      li.className = "mid-list-item" + (log.success ? "" : " log-error");
      li.dataset.filename = log.filename;

      const date = document.createElement("div");
      date.className = "mid-list-date";
      const badge = document.createElement("span");
      badge.className = "mid-list-badge " + (log.success ? "success" : "failure");
      badge.textContent = log.success ? "実行済" : "失敗";
      date.appendChild(badge);
      date.appendChild(document.createTextNode(" " + _deps.formatTime(log.timestamp)));

      const preview = document.createElement("div");
      preview.className = "mid-list-preview";
      preview.textContent = log.summary || "(応答なし)";

      li.appendChild(date);
      li.appendChild(preview);
      li.addEventListener("click", () => showLogDetail(log.filename, li));
      listEl.appendChild(li);
    }
  }

  async function showLogDetail(filename, listItem) {
    const listEl = _deps.logsListEl;
    listEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
    if (listItem) listItem.classList.add("active");

    const agentId = _deps.getAgentId();
    const data = await API.getLogDetail(agentId, filename);
    const container = document.getElementById("right-think-detail");
    container.innerHTML = "";

    const detail = document.createElement("div");
    detail.className = "right-detail";

    // ヘッダー
    const header = document.createElement("div");
    header.className = "right-detail-header";
    const badgeEl = document.createElement("span");
    badgeEl.className = "right-detail-badge " + (data.success ? "success" : "failure");
    badgeEl.textContent = data.success ? "実行済" : "失敗";
    const timeEl = document.createElement("span");
    timeEl.className = "right-detail-time";
    timeEl.textContent = _deps.formatDateTime(data.timestamp);
    header.appendChild(badgeEl);
    header.appendChild(timeEl);
    detail.appendChild(header);

    // プロンプト
    if (data.prompt) {
      detail.appendChild(createCollapsiblePrompt(data.prompt));
    }

    // イベントログ
    if (data.events && data.events.length > 0) {
      const evSection = document.createElement("div");
      evSection.className = "right-detail-section";
      const evLabel = document.createElement("div");
      evLabel.className = "right-detail-label";
      evLabel.textContent = "実行過程";
      evSection.appendChild(evLabel);

      const logArea = document.createElement("div");
      logArea.className = "think-stream-log";
      for (const ev of data.events) {
        logArea.appendChild(createStreamEventEl(ev));
      }
      evSection.appendChild(logArea);
      detail.appendChild(evSection);
    }

    // 結果・エラー
    const fields = [];
    if (data.response) fields.push({ label: "結果", value: data.response });
    if (data.error) fields.push({ label: "エラー", value: data.error });

    for (const field of fields) {
      if (!field.value) continue;
      const section = document.createElement("div");
      section.className = "right-detail-section";
      const label = document.createElement("div");
      label.className = "right-detail-label";
      label.textContent = field.label;
      const pre = document.createElement("div");
      pre.className = "right-detail-pre";
      pre.textContent = field.value;
      section.appendChild(label);
      section.appendChild(pre);
      detail.appendChild(section);
    }

    container.appendChild(detail);
    _deps.showRightPane("right-think-detail");
  }

  // ============================================================
  // ストリーミング実行
  // ============================================================

  function renderThinkView() {
    const container = document.getElementById("right-think-detail");
    container.innerHTML = "";

    const detail = document.createElement("div");
    detail.className = "right-detail";

    const header = document.createElement("div");
    header.className = "right-detail-header";
    const badge = document.createElement("span");
    badge.id = "think-stream-badge";
    badge.className = "right-detail-badge " + (
      thinkState.finished
        ? (thinkState.finished.success ? "success" : "failure")
        : "thinking"
    );
    badge.textContent = thinkState.finished
      ? (thinkState.finished.success ? "実行済" : "失敗")
      : "思考中";
    header.appendChild(badge);
    detail.appendChild(header);

    // プロンプト
    if (thinkState.prompt) {
      detail.appendChild(createCollapsiblePrompt(thinkState.prompt));
    }

    const logArea = document.createElement("div");
    logArea.className = "think-stream-log";
    logArea.id = "think-stream-active";
    for (const ev of thinkState.events) {
      logArea.appendChild(createStreamEventEl(ev));
    }

    // 完了時の結果
    if (thinkState.finished && thinkState.finished.content) {
      const section = document.createElement("div");
      section.className = "right-detail-section";
      const label = document.createElement("div");
      label.className = "right-detail-label";
      label.textContent = "結果";
      const pre = document.createElement("div");
      pre.className = "right-detail-pre";
      pre.textContent = thinkState.finished.content;
      section.appendChild(label);
      section.appendChild(pre);
      logArea.appendChild(section);
    }

    detail.appendChild(logArea);
    container.appendChild(detail);
    logArea.scrollTop = logArea.scrollHeight;
    _deps.showRightPane("right-think-detail");
  }

  function setThinkButtons(enabled) {
    btnThinkRunEl.disabled = !enabled;
    if (!enabled) {
      btnThinkRunEl.textContent = "作業中...";
    } else {
      btnThinkRunEl.textContent = "自律作業を１つ実行";
    }
  }

  /** 思考ストリーミングイベントを記録し、画面に追記する */
  function appendThinkEvent(ev) {
    thinkState.events.push(ev);
    const preview = document.getElementById("thinking-preview");
    if (preview) preview.textContent = ev.content.slice(0, 80);
    const logArea = document.getElementById("think-stream-active");
    if (logArea) {
      logArea.appendChild(createStreamEventEl(ev));
      logArea.scrollTop = logArea.scrollHeight;
    }
  }

  /** 思考中の仮アイテムを作成して思考履歴に追加する */
  function createThinkingItem(badgeText) {
    const listEl = _deps.logsListEl;
    const li = document.createElement("li");
    li.className = "mid-list-item active thinking-item";

    const date = document.createElement("div");
    date.className = "mid-list-date";
    const badge = document.createElement("span");
    badge.className = "mid-list-badge thinking";
    badge.textContent = badgeText;
    date.appendChild(badge);

    const preview = document.createElement("div");
    preview.className = "mid-list-preview";
    preview.id = "thinking-preview";
    preview.textContent = "実行中...";

    li.appendChild(date);
    li.appendChild(preview);
    li.addEventListener("click", () => {
      listEl.querySelectorAll(".mid-list-item").forEach((el) => el.classList.remove("active"));
      li.classList.add("active");
      renderThinkView();
    });

    listEl.prepend(li);
    return li;
  }

  async function startThink(unused, taskFile = null) {
    const agentId = _deps.getAgentId();
    if (thinkState || !agentId) return;

    thinkState = { events: [], finished: null, prompt: "" };
    setThinkButtons(false);
    renderThinkView();
    const badgeText = taskFile ? "タスク実行中" : "作業中";
    createThinkingItem(badgeText);

    try {
      await API.think(agentId, {
        prompt(data) {
          thinkState.prompt = data;
          renderThinkView();
        },
        text(data) {
          appendThinkEvent({ type: "text", content: data });
        },
        tool_use(data) {
          appendThinkEvent({ type: "tool_use", content: data });
          if (data.includes("task.md") || data.includes("mission.md")) {
            setTimeout(async () => {
              const agents = await API.getAgents();
              const agent = agents.find((a) => a.agent_id === agentId);
              if (agent) _deps.loadMissionTask(agent);
            }, 500);
          }
        },
        result(data) {
          const result = JSON.parse(data);
          thinkState.finished = result;
          const badge = document.getElementById("think-stream-badge");
          if (badge) {
            badge.className = "right-detail-badge " + (result.success ? "success" : "failure");
            badge.textContent = result.success ? "実行済" : "失敗";
          }
          if (result.content) {
            const logArea = document.getElementById("think-stream-active");
            if (logArea) {
              const section = document.createElement("div");
              section.className = "right-detail-section";
              const label = document.createElement("div");
              label.className = "right-detail-label";
              label.textContent = "結果";
              const pre = document.createElement("div");
              pre.className = "right-detail-pre";
              pre.textContent = result.content;
              section.appendChild(label);
              section.appendChild(pre);
              logArea.appendChild(section);
              logArea.scrollTop = logArea.scrollHeight;
            }
          }
        },
        error(data) {
          const result = JSON.parse(data);
          thinkState.finished = result;
          thinkState.events.push({ type: "error", content: result.content });
          const badge = document.getElementById("think-stream-badge");
          if (badge) {
            badge.className = "right-detail-badge failure";
            badge.textContent = "失敗";
          }
        },
      }, { task: taskFile });
    } catch (e) {
      alert("思考実行に失敗しました: " + e.message);
    }

    thinkState = null;

    const agents = await API.getAgents();
    const agent = agents.find((a) => a.agent_id === agentId);
    if (agent) _deps.loadMissionTask(agent);
    await loadLogs();

    setThinkButtons(true);
  }

  // ============================================================
  // 公開インターフェース
  // ============================================================

  return {
    init,
    loadLogs,
    startThinkForTask(taskFile) { return startThink(false, taskFile); },
    get isThinking() { return thinkState !== null; },
  };
})();
