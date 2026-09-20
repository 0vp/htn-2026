import asyncio

from htn_backend.agent.run import run_turn


class Server:
    def __init__(self):
        self.events = asyncio.Queue()

    async def request(self, method, params):
        assert method == "turn/start"
        for turn, phase, text in [
            ("old", "final_answer", "Stale completed task"),
            ("current", "commentary", "I will pick it up"),
            ("current", "final_answer", "Pick failed; no delivery confirmed"),
        ]:
            await self.events.put(
                {
                    "method": "item/completed",
                    "params": {
                        "turnId": turn,
                        "item": {
                            "type": "agentMessage",
                            "phase": phase,
                            "text": text,
                        },
                    },
                }
            )
        await self.events.put(
            {
                "method": "turn/completed",
                "params": {
                    "turn": {"id": "current", "status": "completed"},
                },
            }
        )
        return {"turn": {"id": "current"}}


def test_only_current_final_result_is_spoken():
    result = asyncio.run(
        run_turn(Server(), "thread", "Pick it", emit=lambda _: None, final_only=True)
    )
    assert result == "Pick failed; no delivery confirmed"
