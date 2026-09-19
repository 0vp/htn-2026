"""Exercise the app-server wire with interleaved notifications, tools and failures."""

import asyncio
import sys

import pytest

from htn_backend.agent.protocol import AppServer
from htn_backend.agent.run import run_turn


class Tools:
    def __init__(self):
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        return {"success": True, "contentItems": [{"type": "inputText", "text": "blocked"}]}


def test_interleaved_tools_and_turn_completion(tmp_path):
    script = tmp_path / "server.py"
    script.write_text("""
import sys,json
def send(x): print(json.dumps(x),flush=True)
for line in sys.stdin:
 m=json.loads(line)
 if m.get('method')=='initialize': send({'id':m['id'],'result':{}})
 elif m.get('method')=='turn/start':
  send({'method':'turn/started','params':{'turn':{'id':'turn'}}})
  send({'id':m['id'],'result':{'turn':{'id':'turn'}}})
  send({'id':900,'method':'item/tool/call','params':{'tool':'read_scene','arguments':{}}})
 elif m.get('id')==900:
  assert m['result']['success']
  item={'type':'agentMessage','text':'No robot connected'}
  send({'method':'item/completed','params':{'item':item}})
  send({'method':'turn/completed','params':{'turn':{'id':'turn','status':'completed'}}})
""")

    async def exercise():
        tools = Tools()
        server = AppServer([sys.executable, str(script)], tools)
        try:
            await server.start()
            result = await run_turn(server, "thread", "inspect", emit=lambda _: None)
            assert result == "No robot connected"
            assert tools.calls == [("read_scene", {})]
        finally:
            await server.close()
        assert server.process.returncode is not None

    asyncio.run(exercise())


def test_app_server_crash_fails_pending_request(tmp_path):
    script = tmp_path / "exit.py"
    script.write_text("import sys\nsys.stdin.readline()\nsys.exit(2)\n")

    async def exercise():
        server = AppServer([sys.executable, str(script)], Tools())
        try:
            with pytest.raises(RuntimeError, match="closed"):
                await server.start()
        finally:
            await server.close()

    asyncio.run(exercise())
