"""Shared fixtures: fake OpenAI Realtime server, fake Mattermost, fresh app per test."""
import asyncio
import importlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------- fake OpenAI
class FakeOpenAI:
    """Websocket server. `script(event) -> list[dict]` decides what to send back."""

    def __init__(self, script):
        self.script = script
        self.seen: list[dict] = []
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    async def _handler(self, ws):
        try:
            async for raw in ws:
                event = json.loads(raw)
                self.seen.append(event)
                for reply in self.script(event, self.seen):
                    await ws.send(json.dumps(reply))
        except websockets.ConnectionClosed:
            pass

    def _run(self):
        asyncio.set_event_loop(self._loop)

        async def main():
            server = await websockets.serve(self._handler, "127.0.0.1", 0)
            self.port = server.sockets[0].getsockname()[1]
            self._ready.set()
            await asyncio.Future()

        try:
            self._loop.run_until_complete(main())
        except Exception:  # noqa: BLE001
            pass

    def start(self):
        self._thread.start()
        assert self._ready.wait(5)
        return self

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}"

    def types(self):
        return [e["type"] for e in self.seen]


# ------------------------------------------------------------- fake Mattermost
class FakeMattermost:
    def __init__(self, fail_first_post_with_401=False, down=False):
        self.log: list[tuple] = []
        outer = self
        self.fail_401 = fail_first_post_with_401
        self.down = down

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/v4/users/login":
                    outer.log.append(("login", body["login_id"]))
                    token = f"tok{sum(1 for x in outer.log if x[0] == 'login')}"
                    self._send(200, {"id": "u1"}, {"Token": token})
                elif self.path == "/api/v4/posts":
                    if outer.fail_401:
                        outer.fail_401 = False
                        outer.log.append(("post-401",))
                        self._send(401, {"message": "expired"})
                        return
                    outer.log.append(("post", self.headers.get("Authorization"), body))
                    self._send(201, {"id": "p1"})
                elif self.path == "/hook":
                    outer.log.append(("webhook", body))
                    self._send(200, {})

            def do_GET(self):
                if self.path == "/api/v4/teams/name/myteam/channels/name/movecall-leads":
                    outer.log.append(("channel-lookup",))
                    self._send(200, {"id": "chan42"})
                else:
                    self._send(404, {})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self):
        return [x for x in self.log if x[0] == "post"]

    def stop(self):
        self.server.shutdown()


@pytest.fixture
def mm():
    m = FakeMattermost()
    yield m
    m.stop()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVECALL_DB", str(tmp_path / "t.db"))
    import leads

    importlib.reload(leads)
    return leads


@pytest.fixture
def mm_env(monkeypatch, mm):
    monkeypatch.setenv("SWITCH_POST_MODE", "mattermost_api")
    monkeypatch.setenv("MATTERMOST_URL", mm.url)
    monkeypatch.setenv("MATTERMOST_LOGIN", "owner")
    monkeypatch.setenv("MATTERMOST_PASSWORD", "pw")
    monkeypatch.setenv("MATTERMOST_TEAM", "myteam")
    monkeypatch.setenv("MATTERMOST_CHANNEL", "movecall-leads")
    monkeypatch.delenv("MATTERMOST_CHANNEL_ID", raising=False)
    import switch_handoff

    switch_handoff._token_cache.clear()
    return mm


def make_app(monkeypatch, tmp_path, fake_url, api_key="sk-test"):
    monkeypatch.setenv("MOVECALL_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("OPENAI_REALTIME_URL", fake_url)
    if api_key:
        monkeypatch.setenv("OPENAI_API_KEY", api_key)
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_HOST", "demo.ngrok.app")
    for mod in ("server", "leads"):
        sys.modules.pop(mod, None)
    import server  # noqa: WPS433

    return server


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def tool_call(args, name="save_lead", call_id="c1"):
    return {
        "type": "response.function_call_arguments.done",
        "name": name,
        "call_id": call_id,
        "arguments": args if isinstance(args, str) else json.dumps(args),
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts from a known state, whatever is in the developer's .env."""
    monkeypatch.setenv("SWITCH_POST_MODE", "console")
    for var in (
        "MATTERMOST_URL", "MATTERMOST_LOGIN", "MATTERMOST_PASSWORD", "MATTERMOST_TEAM",
        "MATTERMOST_CHANNEL", "MATTERMOST_CHANNEL_ID", "MATTERMOST_WEBHOOK_URL",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SWITCH_REVIEWER_HANDLE",
    ):
        monkeypatch.delenv(var, raising=False)
