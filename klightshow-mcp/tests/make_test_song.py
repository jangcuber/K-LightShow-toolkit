"""Synthesize a 128 BPM test track with clear sections (intro/verse/build/drop/break/drop/outro)."""
import sys
import wave

import numpy as np

SR = 44100
BPM = 128.0
BEAT = 60 / BPM
rng = np.random.default_rng(0)


def env(n, decay):
    return np.exp(-np.arange(n) / (decay * SR))


def kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    f = 50 + 100 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.12)


def snare():
    n = int(0.2 * SR)
    return (rng.standard_normal(n) * 0.6 + np.sin(2 * np.pi * 190 * np.arange(n) / SR) * 0.4) * env(n, 0.05)


def hat():
    n = int(0.05 * SR)
    x = rng.standard_normal(n); x = np.diff(x, prepend=0)
    return x * env(n, 0.01) * 0.4


def tone(freq, dur, amp):
    n = int(dur * SR); t = np.arange(n) / SR
    return amp * (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * np.minimum(1, t * 20) * np.minimum(1, (dur - t) * 20)


sections = [("intro", 8), ("verse", 8), ("build", 4), ("drop", 8), ("break", 8), ("build", 4), ("drop", 8), ("outro", 4)]
lead_in = 0.5
total_bars = sum(b for _, b in sections)
out = np.zeros(int((lead_in + total_bars * 4 * BEAT + 2) * SR))


def add(sig, t, gain=1.0):
    i = int(t * SR)
    out[i:i + len(sig)] += gain * sig[: len(out) - i]


t0 = lead_in
chords = [220.0, 174.6, 261.6, 196.0]
for name, bars in sections:
    for bar in range(bars):
        bt = t0 + bar * 4 * BEAT
        chord = chords[bar % 4]
        if name in ("intro", "break", "outro"):
            add(tone(chord, 4 * BEAT, 0.15), bt); add(tone(chord * 1.5, 4 * BEAT, 0.08), bt)
            for e in range(8):
                add(hat(), bt + e * BEAT / 2, 0.5)
        if name == "verse":
            add(tone(chord, 4 * BEAT, 0.1), bt)
            for b in range(4):
                add(kick(), bt + b * BEAT, 0.8)
                add(hat(), bt + b * BEAT + BEAT / 2)
        if name == "build":
            div = 2 if bar < bars // 2 else 4
            for k in range(4 * div):
                add(snare(), bt + k * BEAT / div, 0.3 + 0.5 * (bar * 4 * div + k) / (bars * 4 * div))
            add(tone(chord * 2, 4 * BEAT, 0.1), bt)
        if name == "drop":
            for b in range(4):
                add(kick(), bt + b * BEAT, 1.0)
                add(tone(chord / 4, BEAT * 0.45, 0.35), bt + b * BEAT + BEAT / 2)
                add(hat(), bt + b * BEAT + BEAT / 2, 1.2)
                if b % 2 == 1:
                    add(snare(), bt + b * BEAT, 0.9)
            add(tone(chord, 4 * BEAT, 0.15), bt); add(tone(chord * 2, 4 * BEAT, 0.1), bt)
    t0 += bars * 4 * BEAT

out /= np.abs(out).max() * 1.1
pcm = (out * 32767).astype(np.int16)
path = sys.argv[1] if len(sys.argv) > 1 else "test_song.wav"
with wave.open(path, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print(path, len(out) / SR, "s; sections start at", lead_in, "with bars", sections)
