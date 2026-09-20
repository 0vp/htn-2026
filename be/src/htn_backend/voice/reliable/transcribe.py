"""Complete audio windows, never captions, supply authoritative command text."""

import io
import wave

import numpy as np


class Utterance:
    def __init__(self):
        self.first = None
        self.parts = []
        self.samples = 0
        self.quiet = 0
        self.speech = False

    def add(self, seq, pcm):
        if self.first is None:
            self.first = seq
        self.parts.append(pcm)
        values = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        audible = float(np.sqrt(np.mean(values * values))) > 0.003
        self.samples += len(values)
        self.quiet = 0 if audible else self.quiet + len(values)
        self.speech |= audible
        # Energy identifies boundaries and silence-only windows. All PCM stays
        # in the journal; speech windows include quiet audio and bounded context.
        return (self.quiet >= 24000 and self.samples >= 24000) or self.samples >= 24000 * 30

    def take(self):
        result = self.first, b"".join(self.parts)
        self.__init__()
        return result


def wav_bytes(pcm):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    return out.getvalue()


async def transcribe(client, key, pcm):
    response = await client.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("utterance.wav", wav_bytes(pcm), "audio/wav")},
        data={"model": "gpt-transcribe", "response_format": "json"},
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["text"].strip()
