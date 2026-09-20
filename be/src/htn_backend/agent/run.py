"""Run Astra through Codex's actual app-server, using the server's room tools."""

import argparse
import asyncio
import os
import shutil
import tempfile

import httpx

from .embodied.prompt import INSTRUCTIONS as EMBODIED_INSTRUCTIONS
from .embodied.tools import EmbodiedTools
from .embodied.tools import definitions as embodied_definitions
from .feedback.stream import stream
from .motion.link import RobotLink
from .motion.skills import Motion
from .motion.tools import INSTRUCTIONS as MOTION_INSTRUCTIONS
from .profile import MODEL, server_command, thread_params
from .protocol import AppServer
from .tools import RobotTools, definitions

TURN_TIMEOUT_S = 600  # Exploration takes minutes; the embodied agent is meant to persist.


async def run_turn(
    server, thread_id, text, emit=print, feedback_backend=None, prefix=None, final_only=False
):
    turn = await server.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
            "model": MODEL,
            "effort": "medium",
        },
    )
    turn_id = turn["turn"]["id"]
    final = []
    monitor = (
        asyncio.create_task(stream(server, thread_id, turn_id, feedback_backend, prefix, emit))
        if feedback_backend and prefix
        else None
    )
    try:
        async with asyncio.timeout(TURN_TIMEOUT_S):
            while True:
                event = await server.events.get()
                method, params = event["method"], event.get("params", {})
                if method == "connection/closed":
                    raise RuntimeError("Codex connection closed before task completed")
                if params.get("threadId", thread_id) != thread_id:
                    continue
                if params.get("turnId", turn_id) != turn_id:
                    continue
                if method == "model/rerouted":
                    raise RuntimeError(
                        "Requested Astra model was rerouted; refusing silent substitution"
                    )
                if method == "item/started" and params["item"]["type"] == "dynamicToolCall":
                    emit(f"[tool: {params['item']['tool']} — started]")
                if method == "item/completed":
                    item = params["item"]
                    if item["type"] == "agentMessage":
                        emit(item["text"])
                        if not final_only or item.get("phase") != "commentary":
                            final.append(item["text"])
                    elif item["type"] == "dynamicToolCall":
                        emit(f"[tool: {item['tool']} — {item['status']}]")
                if method == "turn/completed" and params["turn"]["id"] == turn_id:
                    if params["turn"]["status"] != "completed":
                        raise RuntimeError(f"Codex turn {params['turn']['status']}")
                    return "\n".join(final)
    except BaseException:
        try:
            await server.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        except Exception:
            pass
        raise
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


async def run(room_id, prompt, backend, binary, motion=None, embodied=False, emit=print):
    # Empty workspace avoids inheriting repository instructions or editing source files.
    with tempfile.TemporaryDirectory(prefix="room-agent-") as workspace:
        with httpx.Client(base_url=backend, timeout=15, follow_redirects=False) as client:
            if embodied and motion:
                # The robot's own loop: six sense-returning verbs and an explorer's prompt.
                tools = EmbodiedTools(client, room_id, motion.link)
            else:
                tools = RobotTools(client, room_id, motion)
            server = AppServer(server_command(binary), tools)
            try:
                await server.start()
                inherited = await server.request(
                    "config/read", {"cwd": workspace, "includeLayers": False}
                )
                if isinstance(tools, EmbodiedTools):
                    params = thread_params(workspace, embodied_definitions(), inherited["config"])
                    params["baseInstructions"] = EMBODIED_INSTRUCTIONS
                    params["developerInstructions"] = (
                        "Act through your tools until the task is done."
                    )
                else:
                    params = thread_params(
                        workspace, definitions(motion=motion is not None), inherited["config"]
                    )
                    if motion:
                        params["developerInstructions"] += MOTION_INSTRUCTIONS
                thread = await server.request("thread/start", params)
                if thread.get("model", MODEL) != MODEL:
                    raise RuntimeError("App-server did not select the requested Astra model")
                return await run_turn(
                    server,
                    thread["thread"]["id"],
                    prompt,
                    emit=emit,
                    feedback_backend=backend,
                    prefix=tools.prefix,
                )
            finally:
                await server.close()


def main():
    parser = argparse.ArgumentParser(
        description="Astra room agent using the official Codex harness"
    )
    parser.add_argument(
        "room_id", nargs="?", default="A0000001", help="Defaults to the single shared room"
    )
    parser.add_argument("command", help="User command or finalized speech transcript")
    args = parser.parse_args()
    binary = os.environ.get("CODEX_BINARY") or shutil.which("codex")
    if not binary:
        parser.error("Build agent/codex or install the official Codex CLI, then run codex login")
    backend = os.environ.get("HTN_SERVER_URL", "https://qasim-test.35-253-10-71.sslip.io")
    # Motion tools are only offered when the laptop can reach the robot base directly.
    link = None
    robot_url, robot_token = os.environ.get("HTN_ROBOT_URL"), os.environ.get("HTN_ROBOT_TOKEN")
    if robot_url:
        link = RobotLink(robot_url, robot_token or "")
        link.start()
    try:
        motion = Motion(link) if link else None
        asyncio.run(run(args.room_id.upper(), args.command, backend, binary, motion))
    except (RuntimeError, TimeoutError, httpx.HTTPError) as error:
        parser.exit(1, f"Agent task failed: {error}\n")
    finally:
        if link:
            link.close()


if __name__ == "__main__":
    main()
