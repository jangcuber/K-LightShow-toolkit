"""Animated GIF preview of the whole parking lot: each car is a small tile
(white = front lights, amber = turn signals, red = tail/brake)."""

import numpy as np
from PIL import Image

from . import channels as ch
from .model import Project
from .render import Renderer

FRONT = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 19]
AMBER = [12, 13, 20, 21, 22, 23]
RED = [24, 25, 26, 28]
RAMP_MS = {v: int(k.split("_")[1]) for k, v in ch.RAMP_VALUES.items()}


def simulate_brightness(frames: np.ndarray, step_ms: int) -> np.ndarray:
    """Approximate light output 0..1 from commands: 255 on, 0 off, ramp values fade at their rate.
    frames: (..., time, channels); time is axis -2."""
    v = frames.astype(int)
    target = (v >= 128).astype(np.float32)
    rate = np.ones(v.shape, np.float32)
    for val, ms in RAMP_MS.items():
        rate[v == val] = step_ms / ms
    out = np.zeros(v.shape, np.float32)
    level = np.zeros(v.shape[:-2] + v.shape[-1:], np.float32)
    for i in range(v.shape[-2]):
        t, rt = target[..., i, :], rate[..., i, :]
        level = np.where(t > level, np.minimum(t, level + rt), np.maximum(t, level - rt))
        out[..., i, :] = level
    return out


def _tile_image(front, amber, red, exists, cell):
    rows, cols = exists.shape
    img = np.zeros((rows, cols, 3))
    img[...] = 25
    img += front[..., None] * np.array([230, 230, 255])
    img += amber[..., None] * np.array([255, 150, 0]) * (1 - front[..., None] * 0.5)
    img += red[..., None] * np.array([120, 0, 0]) * (1 - front[..., None])
    img[~exists] = 0
    big = np.kron(np.clip(img, 0, 255), np.ones((cell, cell, 1)))
    inner = max(1, cell - 2)
    mask = np.zeros((cell, cell), bool)
    mask[1:1 + inner, 1:1 + inner] = True
    big *= np.tile(mask, (rows, cols))[..., None]
    return Image.fromarray(big.astype(np.uint8))


def bar_label(project: Project, t: float) -> str:
    import bisect
    db = project.analysis["downbeats"]
    i = bisect.bisect_right(db, t + 1e-6)
    if i == 0:
        return f"{t:.2f}s"
    beats = [b for b in project.analysis["beats"] if db[i - 1] - 1e-6 <= b <= t + 1e-6]
    return f"{t:.2f}s  bar {i} beat {max(1, len(beats))}"


def lot_snapshots(project: Project, times: list[float], out_path: str, cell: int | None = None) -> dict:
    """PNG contact sheet: the lot from above at each time, captioned with time and bar.beat."""
    from PIL import ImageDraw

    r = Renderer(project)
    grid = r.grid
    rows, cols = grid.rows, grid.cols
    cell = cell or max(4, min(24, 720 // max(cols, 1)))
    step_ms = project.data["step_ms"]
    look_back = int(2200 / step_ms)  # enough history for the longest 2 s ramp
    cars = list(grid.cars())
    used = FRONT + AMBER + RED
    full = np.stack([r.render_car(rr, cc)[:, used] for rr, cc in cars])
    exists = np.zeros((rows, cols), bool)
    for rr, cc in cars:
        exists[rr, cc] = True
    nf, na = len(FRONT), len(AMBER)
    tiles = []
    for t in times:
        f = min(r.n_frames - 1, max(0, int(round(t * 1000 / step_ms))))
        sim = simulate_brightness(full[:, max(0, f - look_back): f + 1], step_ms)[:, -1]
        front, amber, red = (np.zeros((rows, cols)) for _ in range(3))
        for k, (rr, cc) in enumerate(cars):
            front[rr, cc] = sim[k, :nf].max()
            amber[rr, cc] = sim[k, nf:nf + na].max()
            red[rr, cc] = sim[k, nf + na:].max()
        tiles.append((_tile_image(front, amber, red, exists, cell), bar_label(project, t)))
    w, h = tiles[0][0].size
    cap = 18
    sheet = Image.new("RGB", (w, len(tiles) * (h + cap)), (60, 60, 60))
    d = ImageDraw.Draw(sheet)
    for i, (img, label) in enumerate(tiles):
        y = i * (h + cap)
        d.text((4, y + 3), label, fill=(235, 235, 235))
        sheet.paste(img, (0, y + cap))
    sheet.save(out_path)
    return {"png": str(out_path), "times": [round(t, 3) for t in times], "size": f"{sheet.width}x{sheet.height}"}


def grid_gif(project: Project, out_path: str, start: float = 0.0, end: float | None = None,
             fps: int = 10, cell: int = 8) -> dict:
    r = Renderer(project)
    grid = r.grid
    end = min(end or project.duration, project.duration)
    step = r.step
    f0, f1 = int(start / step), int(end / step)
    stride = max(1, int(round(1 / (fps * step))))
    idx = np.arange(f0, f1, stride)
    if len(idx) > 1500:
        raise ValueError("preview too long: lower fps or shorten the time range (max 1500 frames)")
    rows, cols = grid.rows, grid.cols
    front = np.zeros((len(idx), rows, cols))
    amber = np.zeros_like(front)
    red = np.zeros_like(front)
    exists = np.zeros((rows, cols), bool)
    cars = list(grid.cars())
    used = FRONT + AMBER + RED
    raw = np.stack([r.render_car(rr, cc)[f0:f1, used] for rr, cc in cars])
    sim = simulate_brightness(raw, project.data["step_ms"])[:, idx - f0]
    nf, na = len(FRONT), len(AMBER)
    for k, (rr, cc) in enumerate(cars):
        exists[rr, cc] = True
        front[:, rr, cc] = sim[k, :, :nf].max(axis=1)
        amber[:, rr, cc] = sim[k, :, nf:nf + na].max(axis=1)
        red[:, rr, cc] = sim[k, :, nf + na:].max(axis=1)
    h, w = rows * cell, cols * cell
    frames = []
    inner = max(1, cell - 2)
    for k in range(len(idx)):
        img = np.zeros((rows, cols, 3))
        img[...] = 25
        img += front[k][..., None] * np.array([230, 230, 255])
        img += amber[k][..., None] * np.array([255, 150, 0]) * (1 - front[k][..., None] * 0.5)
        img += red[k][..., None] * np.array([120, 0, 0]) * (1 - front[k][..., None])
        img[~exists] = 0
        big = np.kron(np.clip(img, 0, 255), np.ones((cell, cell, 1)))
        mask = np.zeros((cell, cell), bool)
        mask[1:1 + inner, 1:1 + inner] = True
        big *= np.tile(mask, (rows, cols))[..., None]
        frames.append(Image.fromarray(big.astype(np.uint8)).convert("P", palette=Image.ADAPTIVE, colors=64))
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0)
    return {"gif": str(out_path), "frames": len(frames), "size": f"{w}x{h}", "start": start, "end": end}
