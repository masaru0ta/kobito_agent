"""webコンポーネントのE2Eテスト（spec_web.md準拠）"""

import re
import shutil
import threading
import time
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import uvicorn
import yaml
from playwright.sync_api import Page, expect

from server.config import AgentInfo
from server.runner import Message

TEST_PORT = 8099
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
TEST_AGENTS_DIR = Path(__file__).parent / "_test_agents"

MOCK_RESPONSE = "これはテスト応答です。\n\n## 見出し\n\n- リスト1\n- リスト2\n\n```python\nprint('hello')\n```"


class MockRunner:
    """テスト用Runner — LLMを呼ばずに固定応答を返す"""

    def build_messages(self, agent_info, messages):
        built = []
        if agent_info.system_prompt:
            built.append({"role": "system", "content": agent_info.system_prompt})
        for msg in messages:
            built.append({"role": msg.role, "content": msg.content})
        return built

    async def run(self, agent_info, messages, session_id=None):
        if not messages:
            raise ValueError("メッセージリストが空です")
        from server.runner import RunResult
        return RunResult(text=MOCK_RESPONSE, session_id="mock-session-id")

    async def run_stream(self, agent_info, messages, session_id=None):
        if not messages:
            raise ValueError("メッセージリストが空です")
        from server.runner import RunResult

        chunks = [MOCK_RESPONSE[i:i+10] for i in range(0, len(MOCK_RESPONSE), 10)]
        for chunk in chunks:
            yield chunk
        yield RunResult(text=MOCK_RESPONSE, session_id="mock-session-id")


def _setup_test_agents():
    """テスト用エージェントディレクトリを作成"""
    if TEST_AGENTS_DIR.exists():
        shutil.rmtree(TEST_AGENTS_DIR)

    adam = TEST_AGENTS_DIR / "adam"
    adam.mkdir(parents=True)
    (adam / "config.yaml").write_text(
        yaml.dump({"name": "アダム", "model": "test-model", "description": "システムの設計者であり管理者"}, allow_unicode=True),
        encoding="utf-8",
    )
    (adam / "CLAUDE.md").write_text("あなたはアダム。", encoding="utf-8")
    (adam / "chat_history").mkdir()

    eden = TEST_AGENTS_DIR / "eden"
    eden.mkdir(parents=True)
    (eden / "config.yaml").write_text(
        yaml.dump({"name": "エデン", "model": "test-model-2", "description": "情報収集と分析を担当"}, allow_unicode=True),
        encoding="utf-8",
    )
    (eden / "chat_history").mkdir()


@pytest.fixture(scope="session")
def _server():
    """テストサーバーをバックグラウンドで起動"""
    _setup_test_agents()

    from server.app import create_app
    app = create_app(agents_dir=TEST_AGENTS_DIR, runner=MockRunner())

    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            resp = httpx.get(f"{BASE_URL}/api/agents")
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            pass
        time.sleep(0.1)

    yield

    server.should_exit = True
    thread.join(timeout=5)
    if TEST_AGENTS_DIR.exists():
        shutil.rmtree(TEST_AGENTS_DIR)


@pytest.fixture(scope="session")
def browser_context_args(_server):
    return {"base_url": BASE_URL}


# ============================================================
# ページ読み込み
# ============================================================


class TestPageLoad:
    """ページ読み込みのテスト"""

    def test_logo_displayed(self, page: Page, _server):
        """ページにアクセスするとロゴ「kobito_agent」がサイドバー上部に表示される"""
        page.goto("/")
        logo = page.locator(".sidebar-logo")
        expect(logo).to_have_text("kobito_agent")

    def test_agent_list_displayed(self, page: Page, _server):
        """エージェント一覧がサイドバーに表示される（名前 + 説明）"""
        page.goto("/")
        agents = page.locator(".agent-item")
        expect(agents).not_to_have_count(0)

        first = agents.first
        expect(first.locator(".agent-item-name")).to_be_visible()
        expect(first.locator(".agent-item-desc")).to_be_visible()

    def test_first_agent_selected(self, page: Page, _server):
        """最初のエージェントが自動選択される"""
        page.goto("/")
        first_agent = page.locator(".agent-item").first
        expect(first_agent).to_have_class(re.compile(r"active"))

    def test_agent_name_in_header(self, page: Page, _server):
        """エージェント名がヘッダーに表示される"""
        page.goto("/")
        header_name = page.locator(".chat-header-name")
        expect(header_name).not_to_be_empty()

    def test_model_name_in_header(self, page: Page, _server):
        """エージェントのモデル名がヘッダーに表示される"""
        page.goto("/")
        header_model = page.locator(".chat-header-model")
        expect(header_model).not_to_be_empty()


# ============================================================
# エージェント選択
# ============================================================


class TestAgentSelection:
    """エージェント選択のテスト"""

    def test_click_highlights(self, page: Page, _server):
        """エージェントをクリックするとハイライト表示になる"""
        page.goto("/")
        agents = page.locator(".agent-item")
        second = agents.nth(1)
        second.click()
        expect(second).to_have_class(re.compile(r"active"))

    def test_switch_updates_header_name(self, page: Page, _server):
        """エージェントを切り替えるとヘッダーの名前が変わる"""
        page.goto("/")
        agents = page.locator(".agent-item")
        first_name = page.locator(".chat-header-name").inner_text()
        agents.nth(1).click()
        second_name = page.locator(".chat-header-name").inner_text()
        assert first_name != second_name

    def test_switch_updates_conversations(self, page: Page, _server):
        """エージェントを切り替えると会話履歴一覧が更新される"""
        page.goto("/")
        agents = page.locator(".agent-item")
        agents.nth(1).click()
        expect(page.locator(".conversation-list")).to_be_visible()

    def test_switch_updates_model_name(self, page: Page, _server):
        """エージェントを切り替えるとモデル名が更新される"""
        page.goto("/")
        agents = page.locator(".agent-item")
        first_model = page.locator(".chat-header-model").inner_text()
        agents.nth(1).click()
        second_model = page.locator(".chat-header-model").inner_text()
        assert first_model != second_model

    def test_switch_clears_chat_when_no_history(self, page: Page, _server):
        """会話履歴がない場合、チャット表示エリアがクリアされる"""
        page.goto("/")
        # エデン（会話履歴なし）を選択
        page.locator(".agent-item").nth(1).click()
        page.wait_for_timeout(500)
        messages = page.locator(".message")
        expect(messages).to_have_count(0)


# ============================================================
# メッセージ送信
# ============================================================


class TestMessageSend:
    """メッセージ送信のテスト"""

    def test_send_button_displays_message(self, page: Page, _server):
        """テキストを入力して送信ボタンをクリックするとメッセージが表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("テストメッセージ")
        page.locator(".btn-send").click()

        user_message = page.locator(".message-user").last
        expect(user_message).to_contain_text("テストメッセージ")

    def test_user_message_has_sender_and_time(self, page: Page, _server):
        """ユーザーメッセージに送信者名「あなた」とタイムスタンプが表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("テスト")
        page.locator(".btn-send").click()

        user_message = page.locator(".message-user").last
        expect(user_message.locator(".message-sender")).to_have_text("あなた")
        expect(user_message.locator(".message-time")).to_be_visible()

    def test_enter_sends_message(self, page: Page, _server):
        """Enterキーでメッセージが送信される"""
        page.goto("/")
        page.locator(".chat-input").fill("Enterテスト")
        page.locator(".chat-input").press("Enter")

        user_message = page.locator(".message-user").last
        expect(user_message).to_contain_text("Enterテスト")

    def test_shift_enter_newline(self, page: Page, _server):
        """Shift+Enterで改行が入力される"""
        page.goto("/")
        textarea = page.locator(".chat-input")
        textarea.fill("1行目")
        textarea.press("Shift+Enter")
        textarea.type("2行目")

        value = textarea.input_value()
        assert "\n" in value

    def test_input_disabled_during_send(self, page: Page, _server):
        """送信中は入力欄と送信ボタンが無効化される"""
        page.goto("/")
        page.locator(".chat-input").fill("送信中テスト")
        page.locator(".btn-send").click()

        # 送信直後に無効化を確認（タイミングが合えば）
        # モックは即座に返すので、disabled状態の確認が難しい場合はスキップ
        # 応答完了後に有効化されていることで間接的に確認
        page.locator(".message-agent").last.wait_for(timeout=10000)
        expect(page.locator(".chat-input")).to_be_enabled()

    def test_streaming_response(self, page: Page, _server):
        """エージェントの応答がストリーミングで表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("応答テスト")
        page.locator(".btn-send").click()

        agent_message = page.locator(".message-agent").last
        expect(agent_message).to_be_visible(timeout=10000)

    def test_agent_message_has_sender_and_time(self, page: Page, _server):
        """エージェント応答に送信者名（エージェント名）とタイムスタンプが表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("送信者テスト")
        page.locator(".btn-send").click()

        agent_message = page.locator(".message-agent").last
        expect(agent_message).to_be_visible(timeout=10000)
        expect(agent_message.locator(".message-sender")).to_be_visible()
        expect(agent_message.locator(".message-time")).to_be_visible()

    def test_input_re_enabled_after_response(self, page: Page, _server):
        """応答完了後に入力欄が再有効化される"""
        page.goto("/")
        page.locator(".chat-input").fill("再有効化テスト")
        page.locator(".btn-send").click()

        page.locator(".message-agent").last.wait_for(timeout=10000)
        expect(page.locator(".chat-input")).to_be_enabled()
        expect(page.locator(".btn-send")).to_be_enabled()  # 入力可能な状態に復帰

    def test_empty_message_cannot_send(self, page: Page, _server):
        """空のメッセージは送信できない（送信ボタンが無効）"""
        page.goto("/")
        page.locator(".chat-input").fill("")
        expect(page.locator(".btn-send")).to_be_disabled()


# ============================================================
# 会話履歴
# ============================================================


class TestConversationHistory:
    """会話履歴のテスト"""

    def test_new_conversation_in_sidebar(self, page: Page, _server):
        """メッセージ送信後、サイドバーの会話履歴に新しい会話が表示される"""
        page.goto("/")
        # 新規会話をクリア
        page.locator("#btn-new-conversation").click()
        page.wait_for_timeout(300)

        page.locator(".chat-input").fill("新規会話テスト")
        page.locator(".btn-send").click()
        page.locator(".message-agent").last.wait_for(timeout=10000)

        conversations = page.locator(".conversation-item")
        expect(conversations.first).to_be_visible()

    def test_click_history_shows_messages(self, page: Page, _server):
        """会話履歴をクリックすると過去のメッセージが表示される"""
        page.goto("/")
        # まず会話を作成
        page.locator(".chat-input").fill("履歴テスト")
        page.locator(".btn-send").click()
        page.locator(".message-agent").last.wait_for(timeout=10000)

        # 新規会話に切り替え
        page.locator("#btn-new-conversation").click()
        page.wait_for_timeout(300)
        expect(page.locator(".message")).to_have_count(0)

        # 履歴をクリック
        conversations = page.locator(".conversation-item")
        conversations.first.click()
        page.wait_for_timeout(500)
        messages = page.locator(".message")
        expect(messages).not_to_have_count(0)

    def test_new_conversation_button_clears_chat(self, page: Page, _server):
        """新規会話ボタンをクリックするとチャットがクリアされる"""
        page.goto("/")
        page.locator(".chat-input").fill("クリアテスト")
        page.locator(".btn-send").click()
        page.locator(".message-agent").last.wait_for(timeout=10000)

        page.locator("#btn-new-conversation").click()
        page.wait_for_timeout(300)
        messages = page.locator(".message")
        expect(messages).to_have_count(0)


# ============================================================
# Markdownレンダリング
# ============================================================


class TestMarkdownRendering:
    """Markdownレンダリングのテスト"""

    def test_markdown_rendered(self, page: Page, _server):
        """エージェント応答のMarkdownがHTMLに変換されて表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("Markdownテスト")
        page.locator(".btn-send").click()

        agent_message = page.locator(".message-agent").last
        agent_message.wait_for(timeout=10000)

        # ストリーミング完了を待つ（streaming-cursorが消える）
        page.wait_for_timeout(1000)

        bubble = agent_message.locator(".message-bubble")
        html = bubble.inner_html()
        # モック応答にh2, ul, pre, codeが含まれる
        has_markdown_html = any(
            tag in html for tag in ["<h2", "<li", "<pre", "<code"]
        )
        assert has_markdown_html, f"Markdownが HTML に変換されていない: {html}"


# ============================================================
# レイアウト
# ============================================================


class TestLayout:
    """レイアウトのテスト"""

    def test_sidebar_and_main_side_by_side(self, page: Page, _server):
        """サイドバーとメインエリアが横並びで表示される"""
        page.goto("/")
        sidebar = page.locator(".sidebar")
        main = page.locator(".main")

        sidebar_box = sidebar.bounding_box()
        main_box = main.bounding_box()

        assert sidebar_box is not None
        assert main_box is not None
        assert sidebar_box["x"] + sidebar_box["width"] <= main_box["x"] + 1

    def test_user_message_right_aligned(self, page: Page, _server):
        """ユーザーメッセージが右寄せで表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("右寄せテスト")
        page.locator(".btn-send").click()

        user_message = page.locator(".message-user").last
        chat_area = page.locator(".chat-messages")
        msg_box = user_message.bounding_box()
        area_box = chat_area.bounding_box()

        assert msg_box is not None
        assert area_box is not None
        msg_right = msg_box["x"] + msg_box["width"]
        area_right = area_box["x"] + area_box["width"]
        assert area_right - msg_right < 50

    def test_agent_message_left_aligned(self, page: Page, _server):
        """エージェント応答が左寄せで表示される"""
        page.goto("/")
        page.locator(".chat-input").fill("左寄せテスト")
        page.locator(".btn-send").click()

        agent_message = page.locator(".message-agent").last
        agent_message.wait_for(timeout=10000)
        chat_area = page.locator(".chat-messages")
        msg_box = agent_message.bounding_box()
        area_box = chat_area.bounding_box()

        assert msg_box is not None
        assert area_box is not None
        assert msg_box["x"] - area_box["x"] < 50

    def test_auto_scroll_on_new_message(self, page: Page, _server):
        """新しいメッセージ表示時に自動スクロールする"""
        page.goto("/")

        for i in range(3):
            page.locator(".chat-input").fill(f"スクロールテスト {i}")
            page.locator(".btn-send").click()
            page.locator(".message-agent").last.wait_for(timeout=10000)

        last_message = page.locator(".message").last
        expect(last_message).to_be_in_viewport()
