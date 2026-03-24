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
