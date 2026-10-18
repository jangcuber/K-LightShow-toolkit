"""Timeline renderer: render(car) -> uint8[frames, channels].

Lights combine highest-takes-precedence; closure channels take the last clip in the list.
Per-car variation comes from car selection, coordinate-based time offsets (patterns)
and bitmap clips where every car is one pixel.
"""

import math

import numpy as np

from . import channels as ch
from .model import Grid, Project

EFFECTS = {
    "on": "Steady value. params: value (0-255) or level ('on','on_500','off_1000',...).",
    "blink": "Square wave. params: period (s, default one beat), duty (0-1, default 0.5), phase (0-1).",
    "strobe": "Fast blink. params: period (s, default 0.2 = 100ms on/off), duty.",
    "hits": "Flash on musical events. params: on ('beats'|'downbeats'|'half_beats'|'onsets'|'bars_2') or times [s], "
            "every (n), offset (n), hold (s, default 0.12), sequence (list of channel groups to rotate per hit).",
    "chase": "Step through groups. params: sequence (list of channel groups), step (s, default one beat / 2), bounce (bool).",
    "ramp": "Tesla ramp command on ramping channels (main beams, ch4-6). params: direction ('on'|'off'), duration_ms (500|1000|2000).",
    "breathe": "Repeated ramp on/off. params: period (s, default one bar), duration_ms (500|1000|2000).",
    "follow": "On while an audio curve is above a threshold. params: curve ('energy'|'low'|'mid'|'high'), threshold (0-1), min_hold (s).",
    "twinkle": "Random sparkle per channel. params: step (s, default 0.1), density (0-1), seed.",
    "bitmap": "Grid only: every car is a pixel. params: text or image (PNG/GIF path), scroll ('left'|'right'|'up'|'down'|'none'), "
              "fit ('contain'|'cover'|'stretch'|'none'), margin (cells), threshold (0-1|'auto'), invert (true|false|'auto'), "
              "trim (bool), speed (cells/s), fps (GIF), loop (bool), pulse ('beats'|'downbeats'|...: light the shape only on beats), "
              "pulse_hold (s). Replaces earlier clips on its channels while active.",
    "closure": "Closure command. params: command ('open'|'dance'|'close'|'stop'). Target a closure group (mirrors, windows, liftgate, charge_port, ...).",
}

PATTERNS = {
    "none": "Every car at the same time.",
    "to_right": "Wave from left column to right.", "to_left": "Wave from right column to left.",
    "to_bottom": "Wave from top row to bottom.", "to_top": "Wave from bottom row to top.",
    "radial_out": "From the center outwards.", "radial_in": "From the edges to the center.",
    "diagonal": "From top-left corner to bottom-right.", "diagonal_rev": "From bottom-right to top-left.",
    "snake": "Car by car in a zig-zag order.", "random": "Random delay per car (seeded).",
}

CAR_SELECTIONS = ("all", "checker", "checker_inv", "odd_rows", "even_rows", "odd_cols", "even_cols",
                  "left_half", "right_half", "top_half", "bottom_half", "border", "center", "rows", "cols", "seats", "random")


def pattern_offsets(grid: Grid, pattern: dict | None) -> np.ndarray:
    """Seconds of delay per (row, col)."""
    rows, cols = grid.rows, grid.cols
    off = np.zeros((rows, cols))
    if not pattern or pattern.get("type", "none") == "none" or grid.single:
        return off
    kind = pattern["type"]
    span = float(pattern.get("span", 1.0))
    r = np.arange(rows)[:, None] * np.ones((1, cols))
    c = np.ones((rows, 1)) * np.arange(cols)[None, :]
    nr, nc = max(rows - 1, 1), max(cols - 1, 1)
    if kind == "to_right":
        x = c / nc
    elif kind == "to_left":
        x = 1 - c / nc
    elif kind == "to_bottom":
        x = r / nr
    elif kind == "to_top":
        x = 1 - r / nr
    elif kind in ("radial_out", "radial_in"):
        d = np.hypot((r - (rows - 1) / 2) / max(rows, 1), (c - (cols - 1) / 2) / max(cols, 1))
        x = d / (d.max() or 1)
        if kind == "radial_in":
            x = 1 - x
    elif kind == "diagonal":
        x = (r / nr + c / nc) / 2
    elif kind == "diagonal_rev":
        x = 1 - (r / nr + c / nc) / 2
    elif kind == "snake":
        order = np.where(r % 2 == 0, r * cols + c, r * cols + (cols - 1 - c))
        x = order / max(rows * cols - 1, 1)
    elif kind == "random":
        x = np.random.default_rng(int(pattern.get("seed", 0))).random((rows, cols))
    else:
        raise ValueError(f"unknown pattern {kind!r}. Patterns: {', '.join(PATTERNS)}")
    off = x * span
    q = pattern.get("quantize")
    if q:
        off = np.round(off / float(q)) * float(q)
    return off


def car_mask(grid: Grid, sel) -> np.ndarray:
    rows, cols = grid.rows, grid.cols
    if sel in (None, "all"):
        return np.ones((rows, cols), bool)
    if isinstance(sel, str):
        sel = {"select": sel}
    kind = sel.get("select", "all")
    r = np.arange(rows)[:, None] * np.ones((1, cols), int)
    c = np.ones((rows, 1), int) * np.arange(cols)[None, :]
    if kind == "all":
        m = np.ones((rows, cols), bool)
    elif kind == "checker":
        m = (r + c) % 2 == 0
    elif kind == "checker_inv":
        m = (r + c) % 2 == 1
    elif kind == "odd_rows":
        m = r % 2 == 1
    elif kind == "even_rows":
        m = r % 2 == 0
    elif kind == "odd_cols":
        m = c % 2 == 1
    elif kind == "even_cols":
        m = c % 2 == 0
    elif kind == "left_half":
        m = c < cols / 2
    elif kind == "right_half":
        m = c >= cols / 2
    elif kind == "top_half":
        m = r < rows / 2
    elif kind == "bottom_half":
        m = r >= rows / 2
    elif kind == "border":
        m = (r == 0) | (c == 0) | (r == rows - 1) | (c == cols - 1)
    elif kind == "center":
        m = (r >= rows / 4) & (r < rows * 3 / 4) & (c >= cols / 4) & (c < cols * 3 / 4)
    elif kind == "rows":
        idx = [grid.row_ids.index(x) if isinstance(x, str) else int(x) for x in sel["rows"]]
        m = np.isin(r, idx)
    elif kind == "cols":
        idx = [grid.col_ids.index(x) if isinstance(x, str) else int(x) for x in sel["cols"]]
        m = np.isin(c, idx)
    elif kind == "seats":
        m = np.zeros((rows, cols), bool)
        for s in sel["seats"]:
            rr, cc = grid.parse_seat(s)
            m[rr, cc] = True
    elif kind == "random":
        m = np.random.default_rng(int(sel.get("seed", 0))).random((rows, cols)) < float(sel.get("fraction", 0.5))
    else:
        raise ValueError(f"unknown car selection {kind!r}. Options: {', '.join(CAR_SELECTIONS)}")
    if sel.get("invert"):
        m = ~m
    return m


def _otsu(x: np.ndarray) -> float:
    hist, edges = np.histogram(x, bins=64, range=(0, 1))
    w = np.cumsum(hist)
    m = np.cumsum(hist * (edges[:-1] + edges[1:]) / 2)
    total, mt = w[-1], m[-1]
    w1 = total - w
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w / total - m) ** 2 / (w * w1)
    between = np.nan_to_num(between)
    return float(edges[int(np.argmax(between)) + 1]) if between.any() else 0.5


def load_image_frames(path: str, rows: int, cols: int, params: dict) -> list:
    """Image/GIF -> list of 0/1 float arrays sized for the lot.
    Shapes are found by luminance x alpha; a dark shape on a light background is inverted automatically
    (invert: true/false overrides), blank borders are trimmed, then the shape is fitted to the grid
    (fit: contain | cover | stretch | none) and thresholded (threshold: 0-1 or 'auto')."""
    from PIL import Image, ImageSequence

    im = Image.open(path)
    lums = []
    for fr in ImageSequence.Iterator(im):
        arr = np.asarray(fr.convert("RGBA"), float) / 255
        lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        alpha = arr[..., 3]
        inv = params.get("invert", "auto")
        if inv == "auto":
            border = np.concatenate([lum[0], lum[-1], lum[:, 0], lum[:, -1]])
            border_a = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
            inv = bool(border_a.mean() > 0.9 and border.mean() > 0.5)
        lums.append(((1 - lum) if inv else lum) * alpha)
    thr = params.get("threshold", "auto")
    thr = _otsu(np.concatenate([l.ravel() for l in lums])) if thr == "auto" else float(thr)
    if params.get("trim", True):
        on = np.any([l >= thr for l in lums], axis=0)
        if on.any():
            ys, xs = np.flatnonzero(on.any(axis=1)), np.flatnonzero(on.any(axis=0))
            lums = [l[ys[0]: ys[-1] + 1, xs[0]: xs[-1] + 1] for l in lums]
    scroll = params.get("scroll", "none")
    fit = params.get("fit", "contain")
    margin = int(params.get("margin", 0))
    R, C = max(1, rows - 2 * margin), max(1, cols - 2 * margin)
    out = []
    for lum in lums:
        h, w = lum.shape
        if scroll in ("left", "right"):
            size = (max(1, round(w * R / h)), R)
        elif scroll in ("up", "down"):
            size = (C, max(1, round(h * C / w)))
        elif fit == "stretch":
            size = (C, R)
        elif fit == "cover":
            k = max(R / h, C / w)
            size = (max(1, round(w * k)), max(1, round(h * k)))
        elif fit == "none":
            size = (w, h)
        else:  # contain
            k = min(R / h, C / w)
            size = (max(1, round(w * k)), max(1, round(h * k)))
        img = Image.fromarray((np.clip(lum, 0, 1) * 255).astype(np.uint8))
        if size != (w, h):
            img = img.resize(size, Image.BOX if size[0] < w else Image.NEAREST)
        a = np.asarray(img, float) / 255
        if fit == "cover" and scroll == "none":
            hh, ww = a.shape
            y0, x0 = max(0, (hh - R) // 2), max(0, (ww - C) // 2)
            a = a[y0: y0 + R, x0: x0 + C]
        out.append((a >= thr).astype(float))
    return out


def _beat_period(analysis) -> float:
    return 60.0 / float(analysis.get("bpm") or 120)


def _event_times(analysis, spec, start, end, every=1, offset=0) -> list[float]:
    if isinstance(spec, (list, tuple)):
        times = [float(t) for t in spec]
    else:
        beats = analysis["beats"]
        if spec == "beats":
            times = beats
        elif spec == "downbeats":
            times = analysis["downbeats"]
        elif spec == "bars_2":
            times = analysis["downbeats"][::2]
        elif spec == "half_beats":
            times = sorted(beats + [(a + b) / 2 for a, b in zip(beats[:-1], beats[1:])])
        elif spec == "quarter_beats":
            times = []
            for a, b in zip(beats[:-1], beats[1:]):
                times += [a + (b - a) * k / 4 for k in range(4)]
        elif spec == "onsets":
            times = analysis["onsets"]
        else:
            raise ValueError(f"unknown event source {spec!r}")
    times = [t for t in times if start - 1e-6 <= t < end]
    return times[offset::max(1, int(every))]


def _level_value(params, default=ch.ON) -> int:
    if "value" in params:
        return int(np.clip(params["value"], 0, 255))
    lvl = params.get("level")
    if lvl in (None, "on"):
        return default
    if lvl == "off":
        return 0
    return ch.RAMP_VALUES[lvl]


class Renderer:
    def __init__(self, project: Project):
        self.p = project
        self.analysis = project.analysis
        self.step = project.data["step_ms"] / 1000.0
        self.n_frames = int(math.ceil(project.duration / self.step))
        self.n_channels = project.data["channels"]
        self.grid = project.grid
        self.prepared = [self._prepare(c) for c in project.clips]

    def f(self, t: float) -> int:
        return int(round(t / self.step))

    # ---- per-clip base signal ------------------------------------------
    def _prepare(self, clip: dict) -> dict:
        params = clip.get("params", {})
        effect = clip["effect"]
        start_f, end_f = self.f(clip["start"]), self.f(clip["end"])
        n = max(0, end_f - start_f)
        target = clip.get("target", "all_lights")
        if effect in ("chase",) or (effect == "hits" and params.get("sequence")):
            seq = [ch.resolve_channels(g) for g in params["sequence"]]
            chans = ch.resolve_channels([c for g in seq for c in g])
        else:
            seq = None
            chans = ch.resolve_channels(target)
        base = np.zeros((n, len(chans)), np.uint8)
        col = {c: i for i, c in enumerate(chans)}
        t_local = np.arange(n) * self.step
        ms_local = np.arange(n) * self.p.data["step_ms"]  # integer ms avoids float phase drift

        def phase_of(period, phase0=0.0):
            period_ms = max(1, int(round(period * 1000)))
            return ((ms_local + int(round(phase0 * period_ms))) % period_ms) / period_ms
        beat = _beat_period(self.analysis)
        bitmap = None

        if effect == "on":
            base[:] = _level_value(params)
        elif effect in ("blink", "strobe"):
            period = float(params.get("period", beat if effect == "blink" else 0.2))
            duty = float(params.get("duty", 0.5))
            phase = phase_of(period, float(params.get("phase", 0)))
            base[phase < duty - 1e-9] = _level_value(params)
        elif effect == "hits":
            times = _event_times(self.analysis, params.get("on", "beats"), clip["start"], clip["end"],
                                 params.get("every", 1), params.get("offset", 0))
            hold = max(1, self.f(float(params.get("hold", 0.12))))
            val = _level_value(params)
            # Let the last hit finish its hold past the clip end instead of cutting it short.
            base = np.zeros((n + hold, len(chans)), np.uint8)
            for k, t in enumerate(times):
                i0 = self.f(t) - start_f
                cols = [col[c] for c in seq[k % len(seq)]] if seq else slice(None)
                base[max(0, i0): max(0, i0 + hold), cols] = val
        elif effect == "chase":
            step = float(params.get("step", beat / 2))
            idx = ms_local // max(1, int(round(step * 1000)))
            L = len(seq)
            if params.get("bounce") and L > 1:
                cyc = 2 * L - 2
                idx = idx % cyc
                idx = np.where(idx < L, idx, cyc - idx)
            else:
                idx = idx % L
            val = _level_value(params)
            for k, g in enumerate(seq):
                rows_on = idx == k
                for c in g:
                    base[rows_on, col[c]] = val
        elif effect == "ramp":
            key = f"{params.get('direction', 'on')}_{int(params.get('duration_ms', 1000))}"
            base[:] = ch.RAMP_VALUES[key]
        elif effect == "breathe":
            period = float(params.get("period", beat * 4))
            dur = int(params.get("duration_ms", 1000))
            phase = phase_of(period)
            base[phase < 0.5] = ch.RAMP_VALUES[f"on_{dur}"]
            base[phase >= 0.5] = ch.RAMP_VALUES[f"off_{dur}"]
        elif effect == "follow":
            curve = np.asarray(self.analysis["curves"][params.get("curve", "energy")])
            cstep = self.analysis.get("curves_step", 0.02)
            ti = np.clip(((clip["start"] + t_local) / cstep).astype(int), 0, len(curve) - 1)
            on = curve[ti] >= float(params.get("threshold", 0.6))
            hold = max(1, self.f(float(params.get("min_hold", 0.1))))
            if hold > 1 and on.any():
                on = np.convolve(on.astype(int), np.ones(hold, int), mode="full")[: len(on)] > 0
            base[on] = _level_value(params)
        elif effect == "twinkle":
            step = max(self.step, float(params.get("step", 0.1)))
            per = max(1, int(round(step / self.step)))
            rng = np.random.default_rng(int(params.get("seed", 0)))
            blocks = rng.random((n // per + 1, len(chans))) < float(params.get("density", 0.3))
            base[:] = np.repeat(blocks, per, axis=0)[:n] * _level_value(params)
        elif effect == "closure":
            base[:] = ch.CLOSURE_VALUES[params.get("command", "open")]
        elif effect == "bitmap":
            bitmap = self._bitmap_frames(clip, n)
            base[:] = _level_value(params)
        else:
            raise ValueError(f"unknown effect {effect!r}. Effects: {', '.join(EFFECTS)}")

        offsets = np.round(pattern_offsets(self.grid, clip.get("pattern")) / self.step).astype(int)
        return {
            "clip": clip, "start_f": start_f, "n": len(base), "chans": np.array(chans, int),
            "closure": ch.is_closure(chans), "base": base,
            "mask": car_mask(self.grid, clip.get("cars", "all")), "offsets": offsets, "bitmap": bitmap,
            "override": clip.get("blend", "override" if effect == "bitmap" else "max") == "override",
        }

    def _bitmap_frames(self, clip, n) -> np.ndarray:
        """Bool array (n, rows, cols): which cars are lit on each frame."""
        from PIL import Image, ImageDraw, ImageFont, ImageSequence

        params = clip.get("params", {})
        rows, cols = self.grid.rows, self.grid.cols
        frames = []
        if params.get("text"):
            text = str(params["text"])
            size = max(8, rows)
            try:
                font = ImageFont.load_default(size=size)
            except TypeError:
                font = ImageFont.load_default()
            bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
            img = Image.new("L", (bbox[2] - bbox[0] + 2, bbox[3] - bbox[1] + 2), 0)
            ImageDraw.Draw(img).text((-bbox[0] + 1, -bbox[1] + 1), text, fill=255, font=font)
            if img.height > rows:
                img = img.resize((max(1, round(img.width * rows / img.height)), rows), Image.LANCZOS)
            frames = [np.asarray(img, float) / 255]
        else:
            frames = load_image_frames(params["image"], rows, cols, params)
        thr = params.get("threshold", 0.5)
        thr = 0.5 if thr == "auto" else float(thr)
        scroll = params.get("scroll", "left" if params.get("text") else "none")
        fps = float(params.get("fps", 10))
        dur = max(n * self.step, self.step)
        out = np.zeros((n, rows, cols), bool)
        for i in range(n):
            t = i * self.step
            src = frames[int(t * fps) % len(frames)] if len(frames) > 1 else frames[0]
            h, w = src.shape
            canvas = np.zeros((rows, cols))
            if scroll in ("left", "right"):
                total = w + cols
                speed = float(params.get("speed", total / dur))
                pos = int(t * speed) % total if params.get("loop") else min(int(t * speed), total)
                x0 = cols - pos if scroll == "left" else pos - w
                y0 = (rows - h) // 2
            elif scroll in ("up", "down"):
                total = h + rows
                speed = float(params.get("speed", total / dur))
                pos = min(int(t * speed), total)
                y0 = rows - pos if scroll == "up" else pos - h
                x0 = (cols - w) // 2
            else:
                x0, y0 = (cols - w) // 2, (rows - h) // 2
            # Paste src at (y0, x0) with clipping.
            ys, xs = max(0, y0), max(0, x0)
            ye, xe = min(rows, y0 + h), min(cols, x0 + w)
            if ye > ys and xe > xs:
                canvas[ys:ye, xs:xe] = src[ys - y0: ye - y0, xs - x0: xe - x0]
            lit = canvas >= thr
            out[i] = ~lit if params.get("invert") is True and params.get("text") else lit
        pulse = params.get("pulse")
        if pulse:
            times = _event_times(self.analysis, pulse, clip["start"], clip["end"])
            hold = max(1, self.f(float(params.get("pulse_hold", 0.15))))
            gate = np.zeros(n, bool)
            for t in times:
                i0 = self.f(t) - self.f(clip["start"])
                gate[max(0, i0): max(0, i0 + hold)] = True
            out &= gate[:, None, None]
        return out

    # ---- per-car output ----------------------------------------------------
    def render_car(self, r: int = 0, c: int = 0) -> np.ndarray:
        N = self.n_frames
        out = np.zeros((N, self.n_channels), np.uint8)
        for pc in self.prepared:
            if pc["n"] == 0 or not pc["mask"][r, c]:
                continue
            s = pc["start_f"] + int(pc["offsets"][r, c])
            e = min(N, s + pc["n"])
            if e <= 0 or s >= N:
                continue
            a = max(0, s)
            seg = pc["base"][a - s: e - s]
            if pc["bitmap"] is not None:
                lit = pc["bitmap"][a - s: e - s, r, c]
                seg = seg * lit[:, None]
            chans = pc["chans"]
            if pc["closure"]:
                region = out[a:e][:, chans]
                cmd = seg > 0
                region[cmd] = seg[cmd]
                out[a:e, chans] = region
            elif pc["override"]:
                out[a:e, chans] = seg
            else:
                out[a:e, chans] = np.maximum(out[a:e, chans], seg)
        return out


def ascii_preview(frames: np.ndarray, step_ms: int, start: float, end: float, resolution: float = 0.1,
                  channels=None) -> str:
    """One row per used channel, one char per `resolution` seconds: '#' on, '+' ramp up, '-' ramp down, letters for closures."""
    s, e = int(start * 1000 / step_ms), int(end * 1000 / step_ms)
    per = max(1, int(round(resolution * 1000 / step_ms)))
    seg = frames[s:e, :48]
    used = channels if channels is not None else [i for i in range(48) if seg[:, i].any()]
    lines = [f"time {start:.1f}s..{end:.1f}s, 1 char = {per * step_ms} ms"]
    for i in used:
        row = ""
        for k in range(0, len(seg), per):
            v = int(seg[k: k + per, i].max())
            if i in ch.CLOSURE_CHANNELS:
                row += {"idle": ".", "open": "O", "dance": "D", "close": "C", "stop": "S"}[ch.closure_state(v)]
            elif v == 0:
                row += "."
            elif v == 255:
                row += "#"
            elif v >= 128:
                row += "+"
            else:
                row += "-"
        lines.append(f"{i:2d} {ch.CHANNEL_NAMES[i][:22]:22s} {row}")
    return "\n".join(lines)
