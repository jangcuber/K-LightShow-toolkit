"""Automatic choreography: music analysis -> timeline of clips.

Each song section gets a template chosen by its energy level and label; beats, downbeats
and onsets drive the hits, and on a parking grid every 4-bar phrase gets a spatial pattern.
"""

import random

from .model import Project

LEFT_FRONT = ["Left Channel 4", "Left Channel 5", "Left Channel 6", "Left Front Fog", "Left Aux Park", "Left Signature"]
RIGHT_FRONT = ["Right Channel 4", "Right Channel 5", "Right Channel 6", "Right Front Fog", "Right Aux Park", "Right Signature"]
LEFT_TURN = ["Left Front Turn", "Left Side Repeater", "Left Rear Turn"]
RIGHT_TURN = ["Right Front Turn", "Right Side Repeater", "Right Rear Turn"]
DROP_FRONT = ["main_beams", "signature", "ch456", "fog", "aux_park", "side_markers"]

STYLES = ("balanced", "energetic", "elegant")
CLOSURE_MODES = ("none", "safe", "full")


class _Builder:
    def __init__(self, project: Project, seed: int):
        self.p = project
        self.a = project.analysis
        self.rng = random.Random(seed)
        self.beat = 60.0 / self.a["bpm"]
        self.bar = 4 * self.beat
        self.grid = project.grid
        self.count = 0

    def add(self, start, end, target, effect, params=None, pattern=None, cars="all", note=None):
        start, end = max(0.0, start), min(self.p.duration, end)
        if end - start < 0.02:
            return
        clip = {"start": round(start, 3), "end": round(end, 3), "target": target, "effect": effect,
                "params": params or {}, "tag": "auto"}
        if pattern and not self.grid.single:
            clip["pattern"] = pattern
        if cars != "all":
            clip["cars"] = cars
        if note:
            clip["note"] = note
        self.p.add_clip(clip)
        self.count += 1

    def phrases(self, start, end, bars=4):
        """Split [start, end) on downbeats into chunks of `bars` bars."""
        db = [d for d in self.a["downbeats"] if start - 1e-3 <= d < end - 1e-3]
        cuts = [start] + [d for i, d in enumerate(db) if i and i % bars == 0] + [end]
        return list(zip(cuts[:-1], cuts[1:]))

    def wave(self, i, span_beats=1.0):
        kinds = ["to_right", "radial_out", "to_left", "diagonal", "to_bottom", "radial_in", "diagonal_rev", "to_top"]
        return {"type": kinds[i % len(kinds)], "span": round(self.beat * span_beats, 3)}


def auto_choreograph(project: Project, style="balanced", closures="safe", seed=0, replace=True,
                     title_text=None) -> dict:
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    if closures not in CLOSURE_MODES:
        raise ValueError(f"closures must be one of {CLOSURE_MODES}")
    if replace:
        project.remove_clips(tag="auto")
    b = _Builder(project, seed)
    a = b.a
    sections = a["sections"]
    beat, bar = b.beat, b.bar
    energetic, elegant = style == "energetic", style == "elegant"
    music_start = a["beats"][0] if a["beats"] else 0.0
    blackouts = []
    peak_sections = [s for s in sections if s["level"] >= 3] or sorted(sections, key=lambda s: -s["energy"])[:1]

    for si, sec in enumerate(sections):
        s0, s1 = max(sec["start"], music_start), sec["end"]
        if s1 - s0 < beat:
            continue
        label, level = sec["label"], sec["level"]
        phrases = b.phrases(s0, s1)

        if label == "build":
            mid = s0 + (s1 - s0) / 2
            last_bar = max(mid, s1 - bar)
            end_hits = s1 - beat  # one beat of blackout before the drop
            b.add(s0, mid, ["signature", "fog", "aux_park"], "hits", {"on": "beats", "hold": 0.12},
                  pattern={"type": "radial_in", "span": round(beat, 3)}, note="build: beats")
            b.add(mid, last_bar, ["signature", "fog", "aux_park", "side_markers"], "hits", {"on": "half_beats", "hold": 0.1},
                  pattern={"type": "radial_in", "span": round(beat / 2, 3)}, note="build: half beats")
            b.add(last_bar, end_hits, ["signature", "fog", "aux_park", "side_markers", "ch456"], "strobe",
                  {"period": 0.2 if not energetic else 0.12, "duty": 0.5}, note="build: strobe")
            b.add(max(s0, s1 - 2 * bar), end_hits, "main_beams", "ramp", {"direction": "on", "duration_ms": 2000},
                  note="build: beams swell")
            blackouts.append((end_hits, s1))

        elif label in ("intro", "outro", "break") or level == 0:
            for pi, (p0, p1) in enumerate(phrases):
                b.add(p0, p1, "main_beams", "breathe",
                      {"period": round(bar * (2 if elegant else 1), 3), "duration_ms": 2000 if bar >= 3 else 1000},
                      pattern={"type": "to_right", "span": round(bar, 3)}, note=f"{label}: breathing beams")
                b.add(p0, p1, "signature", "hits", {"on": "downbeats", "hold": round(beat, 3)},
                      pattern=b.wave(pi, 1))
                if not elegant:
                    b.add(p0, p1, None, "chase", {"sequence": ["ch4", "ch5", "ch6"], "step": round(beat, 3), "bounce": True},
                          pattern=b.wave(pi + 1, 2))
            if si == 0 and title_text and not b.grid.single and b.grid.rows >= 5:
                b.add(s0, s1, "all_lights", "bitmap", {"text": title_text, "scroll": "left"}, note="title text")

        elif level >= 3 or label == "drop":
            for pi, (p0, p1) in enumerate(phrases):
                if b.grid.single:
                    b.add(p0, p1, None, "hits", {"on": "beats", "hold": 0.15, "sequence": [LEFT_FRONT + ["main_beams"], RIGHT_FRONT + ["main_beams"]]},
                          note="drop: L/R on beats")
                else:
                    mode = pi % 3
                    if mode == 0:
                        b.add(p0, p1, DROP_FRONT, "hits", {"on": "beats", "hold": 0.15},
                              pattern=b.wave(pi, 1), note="drop: wave on beats")
                    elif mode == 1:
                        b.add(p0, p1, DROP_FRONT, "hits", {"on": "beats", "every": 2, "hold": 0.15}, cars="checker",
                              note="drop: checkerboard A")
                        b.add(p0, p1, DROP_FRONT, "hits", {"on": "beats", "every": 2, "offset": 1, "hold": 0.15},
                              cars="checker_inv", note="drop: checkerboard B")
                    else:
                        b.add(p0, p1, DROP_FRONT, "hits", {"on": "beats", "hold": 0.15},
                              pattern={"type": "radial_out", "span": round(2 * beat, 3)}, note="drop: ripples")
                b.add(p0, p1, "main_beams", "hits", {"on": "downbeats", "hold": round(min(0.4, beat * 0.8), 3)})
                b.add(p0, p1, None, "hits", {"on": "half_beats", "hold": 0.1, "sequence": [LEFT_TURN, RIGHT_TURN]},
                      pattern=b.wave(pi + 2, 0.5))
                b.add(p0, p1, ["brake", "tail"], "hits", {"on": "beats", "hold": 0.15})
                b.add(p0, p1, ["reverse", "license"], "hits", {"on": "half_beats", "every": 2, "offset": 1, "hold": 0.1})
                if not elegant:
                    b.add(p0, p1, ["fog", "rear_fog"], "follow", {"curve": "high", "threshold": 0.75 if energetic else 0.85, "min_hold": 0.1})

        else:  # verse / chorus
            chorus = level >= 2
            for pi, (p0, p1) in enumerate(phrases):
                if chorus:
                    if b.grid.single:
                        b.add(p0, p1, "main_beams", "hits", {"on": "beats", "hold": 0.15})
                    else:
                        b.add(p0, p1, "main_beams", "hits", {"on": "beats", "every": 2, "hold": 0.15}, cars="checker")
                        b.add(p0, p1, "main_beams", "hits", {"on": "beats", "every": 2, "offset": 1, "hold": 0.15}, cars="checker_inv")
                    b.add(p0, p1, None, "chase", {"sequence": ["ch4", "ch5", "ch6"], "step": round(beat / 2, 3), "bounce": True},
                          pattern=b.wave(pi, 1))
                    if not elegant:
                        b.add(p0, p1, None, "hits", {"on": "onsets", "hold": 0.1, "sequence": [LEFT_TURN, RIGHT_TURN]})
                    b.add(p0, p1, "brake", "hits", {"on": "beats", "every": 2, "offset": 1, "hold": 0.15})
                    b.add(p0, p1, "fog", "follow", {"curve": "high", "threshold": 0.7, "min_hold": 0.1})
                else:
                    on = "downbeats" if elegant else "beats"
                    b.add(p0, p1, "outer_main", "hits", {"on": "downbeats", "hold": 0.3}, pattern=b.wave(pi, 1))
                    b.add(p0, p1, None, "hits", {"on": on, "hold": 0.15, "sequence": [LEFT_FRONT, RIGHT_FRONT]},
                          pattern=b.wave(pi + 1, 1))
                    b.add(p0, p1, "brake", "hits", {"on": "beats", "every": 2, "offset": 1, "hold": 0.15})
                    b.add(p0, p1, "side_markers", "follow", {"curve": "high", "threshold": 0.6, "min_hold": 0.12})
                    if energetic:
                        b.add(p0, p1, "turn_signals", "hits", {"on": "onsets", "hold": 0.1})

    # Tail lights stay on through the music, except during blackouts.
    cur = music_start
    for bo0, bo1 in sorted(blackouts) + [(project.duration, project.duration)]:
        b.add(cur, bo0, "tail", "on", note="tail lights base")
        cur = bo1

    # Finale: everything on for the last bar, then the beams fade out.
    last_db = [d for d in a["downbeats"] if d < project.duration - bar]
    if last_db:
        fin = last_db[-1]
        b.add(fin, fin + bar, "all_lights", "on", note="finale")
        b.add(fin + bar, min(project.duration, fin + bar + 2.5), "main_beams", "ramp", {"direction": "off", "duration_ms": 2000})

    closure_plan = []
    if closures != "none" and peak_sections:
        closure_plan = _plan_closures(b, peak_sections, sections, closures)

    project.save()
    return {"clips_added": b.count, "style": style, "closures": closure_plan,
            "sections": [{k: s[k] for k in ("start", "end", "label", "level")} for s in sections]}


def _plan_closures(b: _Builder, peaks, sections, mode) -> list[str]:
    plan = []
    dur = b.p.duration
    first = peaks[0]
    # Mirrors fold at every peak start and unfold at its end (2 commands per peak, limit 20).
    for pk in peaks[:4]:
        b.add(pk["start"], pk["start"] + 1.0, "mirrors", "closure", {"command": "close"}, note="mirrors fold")
        b.add(pk["end"] - 2.5, pk["end"] - 1.5, "mirrors", "closure", {"command": "open"}, note="mirrors unfold")
        plan.append(f"mirrors fold {pk['start']:.1f}s / unfold {pk['end'] - 2.5:.1f}s")
    # Charge port: open 4 s before the first peak, rainbow dance (max 20 s), close. 3 commands = the limit.
    o = max(0.0, first["start"] - 4.0)
    d_end = min(first["end"], first["start"] + 20.0)
    b.add(o, o + 1.0, "charge_port", "closure", {"command": "open"}, note="charge port open")
    b.add(first["start"], d_end, "charge_port", "closure", {"command": "dance"}, note="charge port dance")
    b.add(d_end, d_end + 1.0, "charge_port", "closure", {"command": "close"}, note="charge port close")
    plan.append(f"charge port open {o:.1f}s, dance {first['start']:.1f}-{d_end:.1f}s, close {d_end:.1f}s")
    if mode == "full":
        big = max(peaks, key=lambda s: s["energy"])
        w_end = min(big["end"], big["start"] + 16.0)
        b.add(big["start"], w_end, "windows", "closure", {"command": "dance"}, note="windows dance")
        plan.append(f"windows dance {big['start']:.1f}-{w_end:.1f}s")
        last = peaks[-1]
        lo = last["start"] - 15.0
        if lo >= 0:
            l_end = min(last["end"], last["start"] + 20.0)
            b.add(lo, lo + 1.0, "liftgate", "closure", {"command": "open"}, note="liftgate open (takes ~14 s)")
            b.add(last["start"], l_end, "liftgate", "closure", {"command": "dance"}, note="liftgate dance")
            close_t = min(dur - 5.0, l_end + 1.0)
            b.add(close_t, close_t + 1.0, "liftgate", "closure", {"command": "close"}, note="liftgate close")
            plan.append(f"liftgate open {lo:.1f}s, dance {last['start']:.1f}-{l_end:.1f}s, close {close_t:.1f}s")
    return plan
