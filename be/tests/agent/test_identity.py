"""The voice and the agent are one character built from one identity."""

from htn_backend.agent.embodied import identity
from htn_backend.agent.embodied.prompt import INSTRUCTIONS
from htn_backend.agent.embodied.tools import TOOLS
from htn_backend.voice.persona import LIVE_INSTRUCTIONS, OFFLINE_INSTRUCTIONS


def test_both_prompts_share_name_character_and_language():
    for prompt in (INSTRUCTIONS, LIVE_INSTRUCTIONS, OFFLINE_INSTRUCTIONS):
        assert f"You are {identity.NAME}" in prompt
        assert identity.CHARACTER in prompt and f"{identity.LANGUAGE} only" in prompt
        assert "$" not in prompt  # Every placeholder was filled.


def test_agent_prompt_only_names_tools_that_exist():
    assert set(TOOLS) == {
        "look",
        "turn",
        "forward",
        "path",
        "scan",
        "room_map",
        "surroundings",
        "recall",
        "stop",
    }
    for name in TOOLS:
        assert name in TOOLS and name in INSTRUCTIONS
