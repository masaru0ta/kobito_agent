/**
 * 自律思考のUI管理（ログ・成果物の表示、手動トリガー）
 */
const Think = (() => {
  const els = {};

  function init() {
    els.logsView = document.getElementById("logs-view");
    els.logsList = document.getElementById("logs-list");
    els.logDetail = document.getElementById("log-detail");
    els.logDetailContent = document.getElementById("log-detail-content");
    els.btnBackLogs = document.getElementById("btn-back-logs");
    els.missionContent = document.getElementById("mission-content");
    els.taskContent = document.getElementById("task-content");

    els.outputsView = document.getElementById("outputs-view");
    els.outputsList = document.getElementById("outputs-list");
    els.outputDetail = document.getElementById("output-detail");
    els.outputDetailContent = document.getElementById("output-detail-content");
    els.btnBackOutputs = document.getElementById("btn-back-outputs");

    els.btnBackLogs.addEventListener("click", showLogsList);
    els.btnBackOutputs.addEventListener("click", showOutputsList);
  }

  // --- ログ ---

  async function loadLogs(agentId) {
    const logs = await API.getLogs(agentId);
    els.logsList.innerHTML = "";
    els.logDetail.classList.add("hidden");
    els.logsList.classList.remove("hidden");

    if (logs.length === 0) {
      els.logsList.innerHTML = '<div class="empty-state">ログはありません</div>';
      return;
    }

    for (const log of logs) {
      const item = document.createElement("div");
      item.className = "log-item" + (log.success ? "" : " log-error");
      item.dataset.filename = log.filename;

      const header = document.createElement("div");
      header.className = "log-item-header";

      const status = document.createElement("span");
      status.className = "log-status " + (log.success ? "log-success" : "log-failure");
      status.textContent = log.success ? "成功" : "失敗";

      const time = document.createElement("span");
      time.className = "log-time";
      time.textContent = formatTimestamp(log.timestamp);

      header.appendChild(status);
      header.appendChild(time);

      const action = document.createElement("div");
      action.className = "log-action";
      action.textContent = log.summary || "(応答なし)";

      item.appendChild(header);
      item.appendChild(action);
      item.addEventListener("click", () => showLogDetail(agentId, log.filename));
      els.logsList.appendChild(item);
    }
  }

  async function showLogDetail(agentId, filename) {
    const data = await API.getLogDetail(agentId, filename);
    els.logsList.classList.add("hidden");
    els.logDetail.classList.remove("hidden");

    els.logDetailContent.innerHTML = "";

    const fields = [
      { label: "タイムスタンプ", value: formatTimestamp(data.timestamp) },
      { label: "状態", value: data.success ? "成功" : "失敗" },
      { label: "エラー", value: data.error || "なし" },
      { label: "プロンプト", value: data.prompt, code: true },
      { label: "応答", value: data.response, code: true },
    ];

    for (const field of fields) {
      const section = document.createElement("div");
      section.className = "log-field";

      const label = document.createElement("div");
      label.className = "log-field-label";
      label.textContent = field.label;

      const value = document.createElement("div");
      value.className = "log-field-value";
      if (field.code) {
        const pre = document.createElement("pre");
        pre.textContent = field.value || "";
        value.appendChild(pre);
      } else {
        value.textContent = field.value || "";
      }

      section.appendChild(label);
      section.appendChild(value);
      els.logDetailContent.appendChild(section);
    }
  }

  function showLogsList() {
    els.logDetail.classList.add("hidden");
    els.logsList.classList.remove("hidden");
  }

  // --- 成果物 ---

  async function loadOutputs(agentId) {
    const outputs = await API.getOutputs(agentId);
    els.outputsList.innerHTML = "";
    els.outputDetail.classList.add("hidden");
    els.outputsList.classList.remove("hidden");

    if (outputs.length === 0) {
      els.outputsList.innerHTML = '<div class="empty-state">成果物はありません</div>';
      return;
    }

    for (const output of outputs) {
      const item = document.createElement("div");
      item.className = "output-item";

      const name = document.createElement("div");
      name.className = "output-name";
      name.textContent = output.filename;

      const size = document.createElement("div");
      size.className = "output-size";
      size.textContent = formatSize(output.size);

      item.appendChild(name);
      item.appendChild(size);
      item.addEventListener("click", () => showOutputDetail(agentId, output.filename));
      els.outputsList.appendChild(item);
    }
  }

  async function showOutputDetail(agentId, filename) {
    const data = await API.getOutputContent(agentId, filename);
    els.outputsList.classList.add("hidden");
    els.outputDetail.classList.remove("hidden");

    els.outputDetailContent.innerHTML = "";

    const title = document.createElement("h3");
    title.textContent = filename;
    els.outputDetailContent.appendChild(title);

    const content = document.createElement("div");
    content.className = "output-rendered";
    content.innerHTML = marked.parse(data.content);
    els.outputDetailContent.appendChild(content);
  }

  function showOutputsList() {
    els.outputDetail.classList.add("hidden");
    els.outputsList.classList.remove("hidden");
  }

  // --- mission/task 表示 ---

  function showMissionTask(agent) {
    els.missionContent.innerHTML = agent.mission
      ? marked.parse(agent.mission)
      : '<span class="text-muted">未設定</span>';
    els.taskContent.innerHTML = agent.task
      ? marked.parse(agent.task)
      : '<span class="text-muted">未設定</span>';
  }

  // --- ユーティリティ ---

  function formatTimestamp(ts) {
    if (!ts) return "";
    const d = new Date(ts);
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

  return { init, loadLogs, loadOutputs, showMissionTask };
})();
