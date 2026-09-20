"""A sighting from the fast eye cuts a scan short and hands the planner where to look."""

from concurrent.futures import Future
from types import SimpleNamespace

from htn_backend.agent.embodied.senses.watcher import first_sighting
from htn_backend.agent.embodied.tools import EmbodiedTools, Scan


def done(value):
    future = Future()
    future.set_result(value)
    return future


def test_first_sighting_skips_misses_and_keeps_unfinished_checks():
    waiting = Future()
    pending = [done(None), waiting, done(dict(x=0.4, y=0.5))]
    assert first_sighting(pending) == dict(x=0.4, y=0.5)
    assert pending == [waiting]


def test_scan_stops_at_the_view_where_the_target_appears():
    tools = EmbodiedTools.__new__(EmbodiedTools)
    heading, turns = [0.0], []

    def read(render=True):
        return SimpleNamespace(
            sequence=len(turns) + 1,
            heading_deg=heading[0],
            position=(0.0, 0.0),
            fresh=True,
            rgb_jpeg=JPEG,
            map_png=b"",
            summary=lambda: dict(clear_ahead_m=3.0),
            obstacles_world=None,
        )

    def turn(degrees):
        heading[0] += degrees
        turns.append(degrees)
        return dict(moved=True)

    tools.senses = SimpleNamespace(read=read)
    tools.navigator = SimpleNamespace(
        remember=lambda s: None,
        turn=turn,
        settle_and_sense=lambda s: None,
        face=lambda h: turns.append(("face", h)),
    )
    # The eye sees the target in the third view (heading 120).
    tools.watcher = SimpleNamespace(
        submit=lambda target, sense: done(
            dict(x=0.7, y=0.4, confidence=0.9, note="there", heading_deg=sense.heading_deg)
            if sense.heading_deg == 120
            else None
        )
    )
    tools.moves, tools.speak = 0, None
    items = tools._scan(Scan(views=6, watch_for="red box"))
    assert [t for t in turns if not isinstance(t, tuple)] == [60.0, 60.0]  # Not all six.
    assert ("face", 120.0) in turns
    assert '"spotted"' in items[0]["text"] and '"x": 0.7' in items[0]["text"]


JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c"
    "1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0"
    "000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc4"
    "00b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1"
    "c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a"
    "636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5"
    "b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda00"
    "08010100003f00fbfcffd9"
)
