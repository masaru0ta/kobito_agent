/**
 * 設定画面の表示・保存処理
 */
const Settings = (() => {
  // 最後に保存された値（リセット用）
  let savedValues = { name: "", model: "", description: "", systemPrompt: "" };
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

    // 変更検知
    [els.name, els.model, els.description, els.systemPrompt].forEach((el) => {
      el.addEventListener("input", () => { dirty = true; });
    });

    els.btnReset.addEventListener("click", reset);
  }

  function load(agent) {
    const values = {
      name: agent.config.name,
      model: agent.config.model,
      description: agent.config.description || "",
      systemPrompt: agent.system_prompt || "",
    };
    savedValues = { ...values };
    els.name.value = values.name;
    els.model.value = values.model;
    els.description.value = values.description;
    els.systemPrompt.value = values.systemPrompt;
    dirty = false;
    clearErrors();
  }

  function reset() {
    els.name.value = savedValues.name;
    els.model.value = savedValues.model;
    els.description.value = savedValues.description;
    els.systemPrompt.value = savedValues.systemPrompt;
    dirty = false;
    clearErrors();
  }

  function clearErrors() {
    els.name.classList.remove("error");
    els.model.classList.remove("error");
    els.errorName.classList.remove("visible");
    els.errorModel.classList.remove("visible");
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
    return valid;
  }

  async function save(agentId) {
    if (!validate()) return false;

    const name = els.name.value.trim();
    const model = els.model.value.trim();
    const description = els.description.value.trim();
    const systemPrompt = els.systemPrompt.value;

    await API.updateConfig(agentId, name, model, description);
    await API.updateSystemPrompt(agentId, systemPrompt);

    savedValues = { name, model, description, systemPrompt };
    dirty = false;

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

  return { init, load, reset, save, isDirty, confirmDiscard };
})();
