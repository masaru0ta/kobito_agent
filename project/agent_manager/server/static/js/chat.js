/**
 * チャット機能
 */
const Chat = {
  _messagesEl: null,
  _currentAgentName: "",

  init(messagesEl) {
    this._messagesEl = messagesEl;
  },

  clear() {
    this._messagesEl.innerHTML = "";
  },

  setAgentName(name) {
    this._currentAgentName = name;
  },

  /**
   * メッセージ要素を作成して追加
   */
  addMessage(role, content, senderName, timestamp) {
    const div = document.createElement("div");
    div.className = `message message-${role === "user" ? "user" : "agent"}`;

    const sender = document.createElement("div");
    sender.className = "message-sender";
    sender.textContent = senderName || (role === "user" ? "あなた" : this._currentAgentName);

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    if (role === "user") {
      bubble.textContent = content;
    } else {
      bubble.innerHTML = marked.parse(content);
    }

    const time = document.createElement("div");
    time.className = "message-time";
    time.textContent = timestamp || this._formatTime(new Date());

    div.appendChild(sender);
    div.appendChild(bubble);
    div.appendChild(time);
    this._messagesEl.appendChild(div);
    this._scrollToBottom();

    return bubble;
  },

  /**
   * ストリーミング用: 空のエージェントメッセージを追加
   */
  addStreamingMessage(senderName) {
    const div = document.createElement("div");
    div.className = "message message-agent";

    const sender = document.createElement("div");
    sender.className = "message-sender";
    sender.textContent = senderName || this._currentAgentName;

    const toolStatus = document.createElement("div");
    toolStatus.className = "message-tool-status";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble streaming-cursor";
    bubble._toolStatusEl = toolStatus;

    const time = document.createElement("div");
    time.className = "message-time";
    time.textContent = this._formatTime(new Date());

    div.appendChild(sender);
    div.appendChild(toolStatus);
    div.appendChild(bubble);
    div.appendChild(time);
    this._messagesEl.appendChild(div);
    this._scrollToBottom();

    return bubble;
  },

  /**
   * ストリーミングチャンクを追加
   */
  appendChunk(bubble, chunk) {
    bubble._rawText = (bubble._rawText || "") + chunk;
    bubble.innerHTML = marked.parse(bubble._rawText);
    // テキストが届いたらtool_use表示をクリア
    if (bubble._toolStatusEl) {
      bubble._toolStatusEl.textContent = "";
    }
    this._scrollToBottom();
  },

  /**
   * tool_use状況を表示（ストリーミング中）
   */
  showToolUse(bubble, description) {
    if (bubble._toolStatusEl) {
      bubble._toolStatusEl.textContent = description;
      this._scrollToBottom();
    }
  },

  /**
   * ストリーミング完了
   */
  finishStreaming(bubble, fullText) {
    bubble.classList.remove("streaming-cursor");
    bubble._rawText = fullText;
    bubble.innerHTML = marked.parse(fullText);
    if (bubble._toolStatusEl) {
      bubble._toolStatusEl.textContent = "";
    }
    this._scrollToBottom();
  },

  /**
   * 会話履歴を表示
   */
  renderHistory(messages, agentName) {
    this.clear();
    for (const msg of messages) {
      let name;
      if (msg.source && msg.source.startsWith("agent:")) {
        // エージェント間通信: 送信元エージェント名を表示
        name = msg.source.replace("agent:", "");
      } else {
        name = msg.role === "user" ? "あなた" : agentName;
      }
      const ts = this._formatTime(new Date(msg.timestamp));
      this.addMessage(msg.role, msg.content, name, ts);
    }
  },

  _scrollToBottom() {
    this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
  },

  _formatTime(date) {
    const h = String(date.getHours()).padStart(2, "0");
    const m = String(date.getMinutes()).padStart(2, "0");
    return `${h}:${m}`;
  },
};
