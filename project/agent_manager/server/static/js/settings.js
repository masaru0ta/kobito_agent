/**
 * 設定画面の表示・保存処理
 */
const Settings = (() => {
  // 最後に保存された値（リセット用）
  let savedValues = { name: "", model: "", description: "", systemPrompt: "", triggerEnabled: false, triggerCron: "" };
  let dirty = false;

  const els = {};

  function init() {
    els.name = document.getElementById("setting-name");
    els.model = document.getElementById("setting-model");
    els.description = document.getElementById("setting-description");
    els.systemPrompt = document.getElementById("setting-system-prompt");
    els.errorName = document.getElementById("error-name");
    els.errorModel = document.getElementById("error-model");
    els.btnSave = document.getElementById("btn-save");
    els.btnReset = document.getElementById("btn-reset");
    els.saveFeedback = document.getElementById("save-feedback");
    els.triggerEnabled = document.getElementById("setting-trigger-enabled");
    els.triggerCron = document.getElementById("setting-trigger-cron");
    els.triggerCronGroup = document.getElementById("trigger-cron-group");
    els.errorTriggerCron = document.getElementById("error-trigger-cron");
    els.triggerStatus = document.getElementById("trigger-status");

    // 変更検知
    [els.name, els.model, els.description, els.systemPrompt, els.triggerCron].forEach((el) => {
      el.addEventListener("input", () => { dirty = true; });
    });
    els.triggerEnabled.addEventListener("change", () => {
      dirty = true;
      // 有効にしたときcron式が空ならデフォルト値を入れる
      if (els.triggerEnabled.checked && !els.triggerCron.value.trim()) {
        els.triggerCron.value = "*/10 * * * *";
      }
      toggleCronField();
    });

    els.btnReset.addEventListener("click", reset);
  }

  function toggleCronField() {
    els.triggerCronGroup.style.display = els.triggerEnabled.checked ? "" : "none";
  }

  function load(agent) {
    const trigger = agent.config.trigger;
    const values = {
      name: agent.config.name,
      model: agent.config.model,
      description: agent.config.description || "",
      systemPrompt: agent.system_prompt || "",
      triggerEnabled: trigger ? trigger.enabled : false,
      triggerCron: trigger ? trigger.cron : "",
    };
    savedValues = { ...values };
    els.name.value = values.name;
    els.model.value = values.model;
    els.description.value = values.description;
    els.systemPrompt.value = values.systemPrompt;
    els.triggerEnabled.checked = values.triggerEnabled;
    els.triggerCron.value = values.triggerCron;
    toggleCronField();
    loadTriggerStatus(agent.agent_id);
    dirty = false;
    clearErrors();
  }

  async function loadTriggerStatus(agentId) {
    try {
      const triggers = await API.getTriggers();
      const status = triggers.find(t => t.agent_id === agentId);
      if (status) {
        const next = status.next_run ? new Date(status.next_run).toLocaleString("ja-JP") : "-";
        const last = status.last_run ? new Date(status.last_run).toLocaleString("ja-JP") : "-";
        const running = status.running ? "実行中" : "待機中";
        els.triggerStatus.innerHTML =
          `<span class="trigger-status-item">状態: ${running}</span>` +
          `<span class="trigger-status-item">次回: ${next}</span>`;
      } else {
        els.triggerStatus.innerHTML = "";
      }
    } catch {
      els.triggerStatus.innerHTML = "";
    }
  }

  function reset() {
    els.name.value = savedValues.name;
    els.model.value = savedValues.model;
    els.description.value = savedValues.description;
    els.systemPrompt.value = savedValues.systemPrompt;
    els.triggerEnabled.checked = savedValues.triggerEnabled;
    els.triggerCron.value = savedValues.triggerCron;
    toggleCronField();
    dirty = false;
    clearErrors();
  }

  function clearErrors() {
    els.name.classList.remove("error");
    els.model.classList.remove("error");
    els.errorName.classList.remove("visible");
    els.errorModel.classList.remove("visible");
    els.triggerCron.classList.remove("error");
    els.errorTriggerCron.classList.remove("visible");
  }

  function validate() {
    let valid = true;
    clearErrors();

    if (!els.name.value.trim()) {
      els.name.classList.add("error");
      els.errorName.classList.add("visible");
      valid = false;
    }
    if (!els.model.value.trim()) {
      els.model.classList.add("error");
      els.errorModel.classList.add("visible");
      valid = false;
    }
    if (els.triggerEnabled.checked && !els.triggerCron.value.trim()) {
      els.triggerCron.classList.add("error");
      els.errorTriggerCron.classList.add("visible");
      valid = false;
    }
    return valid;
  }

  async function save(agentId) {
    if (!validate()) return false;

    try {
      const agent = await API.saveSettings(agentId, {
        name: els.name.value.trim(),
        model: els.model.value.trim(),
        description: els.description.value.trim(),
        systemPrompt: els.systemPrompt.value,
        triggerCron: els.triggerCron.value.trim(),
        triggerEnabled: els.triggerEnabled.checked,
      });
      load(agent);
    } catch (e) {
      els.btnSave.textContent = "保存失敗";
      els.btnSave.classList.add("saved");
      setTimeout(() => {
        els.btnSave.textContent = "保存";
        els.btnSave.classList.remove("saved");
      }, 3000);
      return false;
    }

    // 保存成功フィードバック
    els.btnSave.textContent = "保存しました";
    els.btnSave.classList.add("saved");
    els.saveFeedback.classList.add("visible");
    setTimeout(() => {
      els.btnSave.textContent = "保存";
      els.btnSave.classList.remove("saved");
      els.saveFeedback.classList.remove("visible");
    }, 2000);

    return true;
  }

  function isDirty() {
    return dirty;
  }

  function confirmDiscard() {
    if (!dirty) return true;
    return confirm("変更が保存されていません。破棄しますか？");
  }

  return {
    init, load, reset, save, isDirty, confirmDiscard,
    get hasUnsavedChanges() { return dirty; },
  };
})();
