import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from htn_backend.voice.lab.live import read_audio


def test_reject_wrong_sample_rate_and_long_audio(tmp_path):
    path = tmp_path / "input.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48000)
        target.writeframes(bytes(960))
    with pytest.raises(ValueError, match="24000"):
        read_audio(path)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(bytes(24000 * 2 * 61))
    with pytest.raises(ValueError, match="60 seconds"):
        read_audio(path)


def test_worklet_emits_exact_pcm_frames_and_clamps_samples():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the audio worklet test")
    path = Path(__file__).parents[3] / "src/htn_backend/voice/lab/web/microphone.js"
    script = """
const fs = require('fs'), vm = require('vm');
const frames = []; let Processor;
const context = {AudioWorkletProcessor: class {
  constructor() { this.port = {postMessage: b => frames.push(new Int16Array(b))}; }
}, registerProcessor: (name, cls) => {Processor = cls;}, Int16Array, Math};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const mic = new Processor();
for(let i=0;i<15;i++) mic.process([[new Float32Array(128).fill(i%2 ? 2 : -2)]]);
console.log(JSON.stringify(frames.map(f => ({
  length:f.length,min:Math.min(...f),max:Math.max(...f)
}))));
"""
    result = subprocess.run(
        [node, "-e", script, str(path)], capture_output=True, text=True, check=True
    )
    frames = json.loads(result.stdout)
    assert len(frames) == 4
    assert all(f == {"length": 480, "min": -32767, "max": 32767} for f in frames)
