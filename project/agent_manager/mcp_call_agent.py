"""MCPサーバー — call_agent ツールを提供する"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kobito_call_agent")

DEFAULT_SERVER_URL = "http://localhost:8300"
MAX_CALL_DEPTH = 2


@mcp.tool()
def call_agent(agent_id: str, message: str) -> str:
    """他のエージェントを呼び出して会話する。

    自分自身を呼び出すことはできない。
    呼び出し先のエージェントがさらに別のエージェントを呼ぶことはできるが、2階層までに制限される。

    Args:
        agent_id: 呼び出し先のエージェントID（ディレクトリ名。例: adam, eden）
        message: 送信するメッセージ
    """
    caller_id = os.environ.get("KOBITO_CALLER_AGENT_ID", "")
    call_depth = int(os.environ.get("KOBITO_CALL_DEPTH", "0"))
    server_url = os.environ.get("KOBITO_SERVER_URL", DEFAULT_SERVER_URL)

    # 自分自身の呼び出しチェック
    if agent_id == caller_id:
        raise ValueError(f"自分自身（{agent_id}）を呼び出すことはできません")

    # 階層チェック
    if call_depth >= MAX_CALL_DEPTH:
        raise ValueError(
            f"呼び出し階層の上限（{MAX_CALL_DEPTH}）に達しました。"
            f"これ以上他のエージェントを呼び出すことはできません。"
        )

    url = f"{server_url}/api/agents/{caller_id}/call/{agent_id}"
    payload = {
        "message": message,
        "call_depth": call_depth + 1,
    }

    with httpx.Client(timeout=600) as client:
        resp = client.post(url, json=payload)

    if resp.status_code != 200:
        detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise RuntimeError(f"エージェント呼び出し失敗（{resp.status_code}）: {detail}")

    return resp.json().get("response", "")


if __name__ == "__main__":
    mcp.run()
