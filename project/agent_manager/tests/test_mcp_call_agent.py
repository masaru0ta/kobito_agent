"""MCPサーバー call_agent ツールのテスト"""

import os
from unittest.mock import patch, MagicMock

import pytest
import httpx

from mcp_call_agent import call_agent, MAX_CALL_DEPTH


class TestCallAgentValidation:
    """安全制約のテスト"""

    def test_自分自身を呼び出すとエラー(self):
        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "adam", "KOBITO_CALL_DEPTH": "0"}):
            with pytest.raises(ValueError, match="自分自身"):
                call_agent(agent_id="adam", message="テスト")

    def test_呼び出し階層が上限を超えるとエラー(self):
        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "adam", "KOBITO_CALL_DEPTH": "2"}):
            with pytest.raises(ValueError, match="呼び出し階層の上限"):
                call_agent(agent_id="eden", message="テスト")

    def test_呼び出し階層が上限ちょうどでエラー(self):
        with patch.dict(os.environ, {
            "KOBITO_CALLER_AGENT_ID": "adam",
            "KOBITO_CALL_DEPTH": str(MAX_CALL_DEPTH),
        }):
            with pytest.raises(ValueError, match="呼び出し階層の上限"):
                call_agent(agent_id="eden", message="テスト")

    def test_呼び出し階層1は許可(self):
        """depth=1のとき、まだ1回呼べる（上限2未満）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "OK"}
        mock_response.headers = {"content-type": "application/json"}

        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "adam", "KOBITO_CALL_DEPTH": "1"}):
            with patch("mcp_call_agent.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client
                result = call_agent(agent_id="eden", message="テスト")
                assert result == "OK"


class TestCallAgentRequest:
    """API呼び出しのテスト"""

    def test_正常な呼び出しでAPIにPOSTする(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "エデンの回答"}
        mock_response.headers = {"content-type": "application/json"}

        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "adam", "KOBITO_CALL_DEPTH": "0"}):
            with patch("mcp_call_agent.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                result = call_agent(agent_id="eden", message="こんにちは")

                assert result == "エデンの回答"
                mock_client.post.assert_called_once()
                call_args = mock_client.post.call_args
                assert "/api/agents/adam/call/eden" in call_args[0][0]
                assert call_args[1]["json"]["message"] == "こんにちは"
                assert call_args[1]["json"]["call_depth"] == 1

    def test_APIがエラーを返したらRuntimeError(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "エージェントが見つかりません"}
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"detail": "エージェントが見つかりません"}'

        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "adam", "KOBITO_CALL_DEPTH": "0"}):
            with patch("mcp_call_agent.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                with pytest.raises(RuntimeError, match="エージェント呼び出し失敗"):
                    call_agent(agent_id="eden", message="テスト")

    def test_call_depthがインクリメントされる(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "OK"}
        mock_response.headers = {"content-type": "application/json"}

        with patch.dict(os.environ, {"KOBITO_CALLER_AGENT_ID": "team", "KOBITO_CALL_DEPTH": "0"}):
            with patch("mcp_call_agent.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                call_agent(agent_id="adam", message="テスト")

                call_args = mock_client.post.call_args
                assert call_args[1]["json"]["call_depth"] == 1

    def test_KOBITO_SERVER_URLを使う(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "OK"}
        mock_response.headers = {"content-type": "application/json"}

        with patch.dict(os.environ, {
            "KOBITO_CALLER_AGENT_ID": "adam",
            "KOBITO_CALL_DEPTH": "0",
            "KOBITO_SERVER_URL": "http://localhost:9999",
        }):
            with patch("mcp_call_agent.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                call_agent(agent_id="eden", message="テスト")

                call_args = mock_client.post.call_args
                assert "localhost:9999" in call_args[0][0]
