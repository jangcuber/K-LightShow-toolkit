"""Checks a show against Tesla's rules: teslamotors/light-show validator.py plus the README limits
(closure command limits, dance-after-open, charge port timeout, 44.1 kHz audio, matching names)."""

from pathlib import Path

import numpy as np

from . import audio
from . import channels as ch
from .fseq import read_fseq

MAX_DURATION_S = 4 * 60 * 60
NEEDS_OPEN_BEFORE_DANCE = {"liftgate", "charge_port", "falcon_door_left", "falcon_door_right"}


def check_frames(frames: np.ndarray, step_ms: int) -> tuple[list, list, dict]:
    errors, warnings = [], []
    stats = {"closure_commands": {}}
    n = len(frames)
    for name, (chans, limit, dance_ok) in ch.CLOSURES.items():
        col = frames[:, chans[0]]
        if not col.any():
            continue
        states = np.array(["idle", "open", "dance", "close", "stop"])[np.digitize(col, [32, 96, 160, 224])]
        changes = np.flatnonzero(states[1:] != states[:-1]) + 1
        starts = ([0] if states[0] != "idle" else []) + list(changes)
        cmds = [(i, states[i]) for i in starts if states[i] in ("open", "dance", "close")]
        stats["closure_commands"][name] = len(cmds)
        if len(cmds) > limit:
            errors.append(f"{name}: {len(cmds)} open/dance/close commands, limit is {limit} per show")
        position = "closed"
        open_time = None
        dance_frames = 0
        for i, st in cmds:
            t = i * step_ms / 1000
            if st == "dance":
                if not dance_ok:
                    warnings.append(f"{name}: dance at {t:.2f}s is not supported for this closure")
                elif name in NEEDS_OPEN_BEFORE_DANCE and position != "open":
                    warnings.append(f"{name}: dance at {t:.2f}s without an earlier open; the car ignores it")
                elif name in NEEDS_OPEN_BEFORE_DANCE and open_time is not None:
                    need = 14.0 if name == "liftgate" else 20.0 if name.startswith("falcon") else 2.0
                    if t - open_time < need:
                        warnings.append(f"{name}: dance at {t:.2f}s only {t - open_time:.1f}s after open (needs ~{need:.0f}s to open fully)")
            if st == "open":
                position, open_time = "open", t
            elif st == "close":
                position, open_time = "closed", None
        dance_frames = int((states == "dance").sum())
        if dance_frames * step_ms / 1000 > 30 and name != "charge_port":
            warnings.append(f"{name}: dances for {dance_frames * step_ms / 1000:.0f}s; ~30s or less avoids thermal limits")
        if name == "charge_port":
            opens = [i for i, s in cmds if s == "open"]
            closes = [i for i, s in cmds if s == "close"]
            for o in opens:
                nxt = [c for c in closes if c > o]
                end = nxt[0] if nxt else n
                if (end - o) * step_ms / 1000 > 120:
                    warnings.append("charge_port: open for more than 2 minutes; the car closes it automatically")

    # Boolean lights: very short pulses.
    short = 0
    for c in ch.LIGHT_CHANNELS:
        on = frames[:, c] > 0
        if not on.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))
        lengths = (edges[1::2] - edges[0::2]) * step_ms
        short += int((lengths < 100).sum())
        bad_ramp = (c not in ch.RAMPING_CHANNELS) & (frames[:, c] > 0) & (frames[:, c] < 255)
        if bad_ramp.any():
            warnings.append(f"channel {c} ({ch.CHANNEL_NAMES[c]}): ramp values on a channel that is on/off only on most cars (treated as on/off)")
    if short:
        stats["pulses_under_100ms"] = short
    if frames.shape[1] >= 48 and frames[:, 46:48].any():
        warnings.append("channels 46-47 are unused by Tesla but contain data")
    on_ratio = (frames[:, :30] > 0).mean(axis=0)
    stats["busiest_channels"] = [f"{ch.CHANNEL_NAMES[i]} {on_ratio[i]:.0%}" for i in np.argsort(-on_ratio)[:5]]
    return errors, warnings, stats


def validate_file(fseq_path: str, audio_path: str | None = None, deep: bool = True) -> dict:
    errors, warnings = [], []
    p = Path(fseq_path)
    raw = p.read_bytes()[:24]
    if raw[:4] != b"PSEQ":
        return {"ok": False, "errors": ["Unknown file format, expected FSEQ v2.0"], "warnings": []}
    frames, h = read_fseq(p)
    if h["data_offset"] < 24 or h["frame_count"] < 1 or h["step_ms"] < 15:
        errors.append("Unknown file format, expected FSEQ v2.0")
    if h["channel_count"] not in (48, 200):
        errors.append(f"Expected 48 or 200 channels, got {h['channel_count']}")
    if h["compression"] != 0:
        errors.append("Expected file format to be V2 Uncompressed")
    if h["major"] != 2 or h["minor"] not in (0, 2):
        warnings.append(f"FSEQ version {h['major']}.{h['minor']}; only 2.0 and 2.2 are validated by Tesla")
    if h["step_ms"] > 100:
        warnings.append("step time above 100 ms is outside the supported 15-100 ms range")
    duration = h["frame_count"] * h["step_ms"] / 1000
    if duration > MAX_DURATION_S:
        errors.append("Expected total duration to be less than 4 hours")
    expected = 24 if h["data_offset"] == 24 else h["data_offset"]
    if p.stat().st_size < expected + h["frame_count"] * h["channel_count"]:
        errors.append("file is truncated")
    stats = {}
    if deep and not errors:
        e2, w2, stats = check_frames(frames, h["step_ms"])
        errors += e2
        warnings += w2
    if audio_path:
        ap = Path(audio_path)
        if ap.stem != p.stem:
            warnings.append(f"audio file name {ap.name} must match {p.stem}.wav/.mp3 on the USB drive")
        if ap.suffix.lower() not in (".wav", ".mp3"):
            errors.append("audio must be .wav or .mp3")
        sr = audio.probe_sample_rate(str(ap))
        if sr and sr != 44100:
            errors.append(f"audio sample rate is {sr} Hz; Tesla needs 44.1 kHz")
    return {
        "ok": not errors, "errors": errors, "warnings": warnings,
        "frames": h["frame_count"], "step_ms": h["step_ms"], "channels": h["channel_count"],
        "duration_s": round(duration, 3), **stats,
    }
