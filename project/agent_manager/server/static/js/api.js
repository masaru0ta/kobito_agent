/**
 * API通信ユーティリティ
 */
const API = {
  async getAgents() {
    const resp = await fetch("/api/agents");
    return resp.json();
  },

  async getAgent(agentId) {
    const resp = await fetch(`/api/agents/${agentId}`);
    return resp.json();
  },

  async getConversations(agentId) {
    const resp = await fetch(`/api/agents/${agentId}/conversations`);
    return resp.json();
  },

  async getConversation(agentId, conversationId) {
    const resp = await fetch(`/api/agents/${agentId}/conversations/${conversationId}`);
    return resp.json();
  },

  async deleteConversation(agentId, conversationId) {
    await fetch(`/api/agents/${agentId}/conversations/${conversationId}`, { method: "DELETE" });
  },

  async saveSettings(agentId, { name, model, description, systemPrompt, triggerCron, triggerEnabled }) {
    const resp = await fetch(`/api/agents/${agentId}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name, model, description,
        system_prompt: systemPrompt,
        trigger_cron: triggerCron || null,
        trigger_enabled: triggerEnabled,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "設定の保存に失敗しました");
    }
    return resp.json();
  },


  async summarizeConversation(agentId, conversationId) {
    const resp = await fetch(`/api/agents/${agentId}/conversations/${conversationId}/summarize`, {
      method: "POST",
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "要約に失敗しました");
    }
    return resp.json();
  },

  async updateMission(agentId, content) {
    const resp = await fetch(`/api/agents/${agentId}/mission`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "ミッションの保存に失敗しました");
    }
    return resp.json();
  },

  async updateTask(agentId, content) {
    const resp = await fetch(`/api/agents/${agentId}/task`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "タスクの保存に失敗しました");
    }
    return resp.json();
  },

  async getThinkPrompt(agentId) {
    const resp = await fetch(`/api/agents/${agentId}/think-prompt`);
    return resp.json();
  },

  async updateThinkPrompt(agentId, content) {
    const resp = await fetch(`/api/agents/${agentId}/think-prompt`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "思考プロンプトの保存に失敗しました");
    }
    return resp.json();
  },

  async think(agentId, callbacks, { resume = false } = {}) {
    const url = `/api/agents/${agentId}/think` + (resume ? "?resume=true" : "");
    const resp = await fetch(url, { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "思考実行に失敗しました");
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      let eventType = null;
      let dataLines = [];
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
          dataLines = [];
        } else if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        } else if (line === "" && eventType) {
          const data = dataLines.join("\n");
          if (callbacks && callbacks[eventType]) callbacks[eventType](data);
          eventType = null;
          dataLines = [];
        }
      }
    }
  },

  async getLogs(agentId) {
    const resp = await fetch(`/api/agents/${agentId}/logs`);
    return resp.json();
  },

  async getLogDetail(agentId, filename) {
    const resp = await fetch(`/api/agents/${agentId}/logs/${filename}`);
    return resp.json();
  },

  async getOutputs(agentId) {
    const resp = await fetch(`/api/agents/${agentId}/outputs`);
    return resp.json();
  },

  async getOutputContent(agentId, filename) {
    const resp = await fetch(`/api/agents/${agentId}/outputs/${filename}`);
    return resp.json();
  },

  async getTriggers() {
    const resp = await fetch("/api/triggers");
    return resp.json();
  },


  async launchCLI(agentId, sessionId) {
    const resp = await fetch(`/api/agents/${agentId}/launch-cli`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    return resp.json();
  },

  /**
   * メッセージ送信（SSEストリーミング）
   * コールバック: onConversationId, onChunk, onDone
   */
  async sendMessage(agentId, message, conversationId, callbacks) {
    const resp = await fetch(`/api/agents/${agentId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });

    try {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        let eventType = null;
        let dataLines = [];
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
            dataLines = [];
          } else if (line.startsWith("data: ")) {
            dataLines.push(line.slice(6));
          } else if (line === "" && eventType) {
            const data = dataLines.join("\n");
            if (eventType === "conversation_id" && callbacks.onConversationId) {
              callbacks.onConversationId(data);
            } else if (eventType === "chunk" && callbacks.onChunk) {
              callbacks.onChunk(data);
            } else if (eventType === "done" && callbacks.onDone) {
              callbacks.onDone(data);
            } else if (eventType === "error" && callbacks.onError) {
              callbacks.onError(data);
            }
            eventType = null;
            dataLines = [];
          }
        }
      }
    } catch (e) {
      if (callbacks.onError) {
        callbacks.onError(e.message || "通信エラーが発生しました");
      }
    }
  },

};
