"""Run the local simulator; the physical robot link is never instantiated."""

import argparse
import asyncio
import shutil

import httpx
import uvicorn

from ..agent.run import run
from .service import ROOM, create_app


def main():
    parser = argparse.ArgumentParser(description="Local MuJoCo robot simulation")
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument(
        "--command", help="Ask Codex to control an already running local simulation"
    )
    args = parser.parse_args()
    if args.command:
        backend = f"http://127.0.0.1:{args.port}"
        health = httpx.get(backend + "/health", timeout=5)
        health.raise_for_status()
        if health.json().get("execution_domain") != "simulation":
            parser.error("Selected server is not a simulation")
        binary = shutil.which("codex")
        if not binary:
            parser.error("Install the official Codex CLI and authenticate first")
        asyncio.run(run(ROOM, args.command, backend, binary, motion=None))
        return
    print(f"Simulation room {ROOM}: http://127.0.0.1:{args.port}")
    print(
        "Use simulation.evaluate for an isolated Codex test; do not attach hardware motion tools."
    )
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
