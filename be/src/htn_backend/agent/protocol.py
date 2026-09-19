"""JSON-lines client for the official Codex app-server, with bounded turn lifetime."""

import asyncio
import contextlib
import json


class AppServer:
    def __init__(self, command, tools):
        self.command, self.tools = command, tools
        self.pending, self.calls = {}, set()
        self.events = asyncio.Queue()
        self.next_id = 0
        self.process = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8_000_000,
        )
        self.reader = asyncio.create_task(self.read())
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "room_robot", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.send({"method": "initialized", "params": {}})

    async def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params):
        self.next_id += 1
        ident = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.send({"id": ident, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout=30)
        finally:
            self.pending.pop(ident, None)

    async def respond(self, message):
        if message["method"] == "item/tool/call":
            params = message["params"]
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self.tools.call, params["tool"], params["arguments"]),
                    timeout=25,
                )
            except Exception:
                result = {
                    "success": False,
                    "contentItems": [
                        {"type": "inputText", "text": "Robot tool failed; execution not confirmed"}
                    ],
                }
            await self.send({"id": message["id"], "result": result})
        else:
            await self.send(
                {
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "Only the room robot tool interface is supported",
                    },
                }
            )

    async def read(self):
        failure = RuntimeError("Codex app-server closed the connection")
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "id" in message and "method" in message:
                    call = asyncio.create_task(self.respond(message))
                    self.calls.add(call)
                    call.add_done_callback(self.calls.discard)
                elif "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(message["error"]["message"]))
                        else:
                            future.set_result(message.get("result"))
                else:
                    await self.events.put(message)
        except Exception as error:
            failure = error
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(failure)
            await self.events.put({"method": "connection/closed", "params": {}})

    async def close(self):
        if self.process is None:
            return
        for call in tuple(self.calls):
            call.cancel()
        await asyncio.gather(*self.calls, return_exceptions=True)
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader
