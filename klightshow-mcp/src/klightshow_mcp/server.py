"""MCP server: lets an AI turn a music file into a complete Tesla light show (one car or a whole parking lot)."""

import json
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import Image as _Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image as _Image

from . import audio
from . import channels as ch
from .choreo import CLOSURE_MODES, STYLES, auto_choreograph as _auto
from .export import export_show as _export, render_preview_frames
from .model import Project, projects_dir
from .preview import grid_gif, lot_snapshots
from .render import CAR_SELECTIONS, EFFECTS, PATTERNS, Renderer, ascii_preview
from .validate import validate_file

INSTRUCTIONS = """Tesla light show generator for K-LIGHT SHOW style events.

Fastest path (music only): call generate_show_from_music(audio_path, rows, cols). It analyzes the song,
choreographs every section, renders one 48-channel .fseq per car, converts the audio to 44.1 kHz,
validates against Tesla's rules and returns the export folder, zip and a parking-lot preview GIF.

Editing path: create_project -> get_project (sections, bpm) -> auto_choreograph and/or add_clip /
update_clip / remove_clips -> preview_car / preview_frames / preview_grid -> export_show.
Images: place_image(project, image_path, start="bar:33") puts a shape (logo, heart, text image, GIF) on the
lot, every car one pixel, and returns a rendered picture of how it will look; dry_run=True only previews.
preview_frames returns pictures of the lot at any times so you can check before exporting.
Times accept seconds (12.5) or musical positions: "bar:17" (start of bar 17, 1-based), "beat:64",
"section:3" (start of section 3, 1-based), "section_end:3". Call reference() for channels, groups,
effects, patterns and closure limits. Closures (mirrors, windows, liftgate, charge port) have hard command
limits per show; validation reports them."""

mcp = _Server("klightshow", instructions=INSTRUCTIONS)


def _resolve_time(p: Project, t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    s = str(t).strip()
    if ":" not in s:
        return float(s)
    kind, num = s.split(":", 1)
    a = p.analysis
    if kind == "bar":
        x = float(num) - 1
        db = a["downbeats"]
        i = int(x)
        if i >= len(db):
            raise ValueError(f"song has {len(db)} bars")
        base = db[i]
        nxt = db[i + 1] if i + 1 < len(db) else base + 240 / a["bpm"]
        return base + (x - i) * (nxt - base)
    if kind == "beat":
        x = float(num) - 1
        b = a["beats"]
        i = int(x)
        if i >= len(b):
            raise ValueError(f"song has {len(b)} beats")
        nxt = b[i + 1] if i + 1 < len(b) else b[i] + 60 / a["bpm"]
        return b[i] + (x - i) * (nxt - b[i])
    if kind in ("section", "section_end"):
        sec = a["sections"][int(num) - 1]
        return sec["start"] if kind == "section" else sec["end"]
    raise ValueError(f"cannot parse time {t!r}")


def _info(p: Project) -> dict:
    a = p.analysis
    g = p.grid
    return {
        "project": p.data["name"], "dir": str(p.dir), "audio": p.data["audio_path"],
        "duration": p.duration, "bpm": a["bpm"], "bars": len(a["downbeats"]),
        "channels": p.data["channels"], "step_ms": p.data["step_ms"],
        "grid": {"rows": g.rows, "cols": g.cols, "cars": g.car_count(), "missing": g.to_dict()["missing"][:50],
                 "seat_example": g.seat(0, 0)},
        "sections": [dict(s, number=i + 1) for i, s in enumerate(a["sections"])],
        "clip_count": len(p.clips),
    }


@mcp.tool()
def generate_show_from_music(audio_path: str, name: str | None = None, rows: int = 1, cols: int = 1,
                             missing_seats: list[str] | None = None, style: str = "balanced",
                             closures: str = "safe", title_text: str | None = None, channels: int = 48,
                             audio_format: str = "wav", preview: bool = True, seed: int = 0,
                             layout: str = "usb") -> dict:
    """One shot: music file -> complete, validated Tesla light show.

    rows x cols > 1 builds a parking-lot show with one .fseq per car (seat codes A01, A02, ...; row letter + column),
    e.g. rows=16, cols=63 for ~1,000 cars. style: balanced | energetic | elegant.
    closures: none | safe (mirrors + charge port) | full (also windows dance and liftgate).
    title_text scrolls across the lot during the intro (grid only). layout: usb (copy-ready folders) or
    automator (source folder for K-LightShow USB Automator: root mp3 + <seat>/ folders). Returns export paths, validation and a preview GIF.
    """
    name = name or Path(audio_path).stem
    p = Project.create(name, audio_path, channels=channels, rows=rows, cols=cols, missing=missing_seats)
    plan = _auto(p, style=style, closures=closures, seed=seed, title_text=title_text)
    result = {"project": p.data["name"], "analysis": audio.summarize(p.analysis), "choreography": plan,
              "export": _export(p, audio_format=audio_format, layout=layout)}
    if preview and not p.grid.single:
        busiest = max(p.analysis["sections"], key=lambda s: s["energy"])
        result["preview_gif"] = grid_gif(p, str(p.dir / "preview.gif"), busiest["start"],
                                         min(busiest["end"], busiest["start"] + 12), fps=10)
    return result


@mcp.tool()
def analyze_music(audio_path: str) -> dict:
    """Analyze a song without creating a project: duration, BPM, beats, and sections (label, energy level 0-3)."""
    return audio.summarize(audio.analyze(audio_path))


@mcp.tool()
def create_project(name: str, audio_path: str, rows: int = 1, cols: int = 1, missing_seats: list[str] | None = None,
                   channels: int = 48, step_ms: int = 20) -> dict:
    """Create a show project from a music file (analyzes it). rows x cols is the parking grid (1x1 = single car)."""
    return _info(Project.create(name, audio_path, channels=channels, step_ms=step_ms, rows=rows, cols=cols,
                                missing=missing_seats))


@mcp.tool()
def list_projects() -> list:
    """List saved projects."""
    out = []
    for d in sorted(projects_dir().iterdir()):
        f = d / "project.json"
        if f.exists():
            data = json.loads(f.read_text())
            g = data["grid"]
            out.append({"project": d.name, "name": data["name"], "duration": data.get("duration"),
                        "grid": f"{g['rows']}x{g['cols']}", "clips": len(data["clips"])})
    return out


@mcp.tool()
def get_project(project: str) -> dict:
    """Project overview: grid, BPM, numbered song sections, clip count."""
    return _info(Project.load(project))


@mcp.tool()
def get_music_events(project: str, start: str | float = 0, end: str | float | None = None,
                     kinds: list[str] | None = None) -> dict:
    """Beat, downbeat (bar start) and strong onset times inside a window, plus mean energy/low/mid/high."""
    p = Project.load(project)
    a = p.analysis
    s, e = _resolve_time(p, start), _resolve_time(p, end) if end is not None else p.duration
    kinds = kinds or ["beats", "downbeats", "onsets"]
    out = {"start": s, "end": e, "bpm": a["bpm"]}
    for k in kinds:
        out[k] = [t for t in a[k] if s <= t < e][:400]
    step = a["curves_step"]
    i0, i1 = int(s / step), max(int(s / step) + 1, int(e / step))
    for k, v in a["curves"].items():
        seg = v[i0:i1]
        out[f"mean_{k}"] = round(sum(seg) / max(1, len(seg)), 3)
    return out


@mcp.tool()
def set_grid(project: str, rows: int, cols: int, missing_seats: list[str] | None = None,
             row_ids: list[str] | None = None, col_ids: list[str] | None = None) -> dict:
    """Set the parking layout. missing_seats are empty spots (seat codes like 'A01' or 'row,col' 0-based)."""
    p = Project.load(project)
    p.set_grid(rows, cols, missing_seats, row_ids, col_ids)
    p.save()
    return _info(p)


@mcp.tool()
def auto_choreograph(project: str, style: str = "balanced", closures: str = "safe", seed: int = 0,
                     title_text: str | None = None, replace: bool = True) -> dict:
    """Generate clips for the whole song from its analysis. replace=True removes previous auto clips
    (clips you added by hand are kept). style: balanced|energetic|elegant; closures: none|safe|full."""
    return _auto(Project.load(project), style=style, closures=closures, seed=seed, replace=replace,
                 title_text=title_text)


@mcp.tool()
def list_clips(project: str, start: str | float | None = None, end: str | float | None = None,
               limit: int = 200) -> dict:
    """List clips overlapping a time window."""
    p = Project.load(project)
    s = _resolve_time(p, start) if start is not None else None
    e = _resolve_time(p, end) if end is not None else None
    clips = [c for c in p.clips if (s is None or c["end"] > s) and (e is None or c["start"] < e)]
    return {"total": len(clips), "clips": clips[:limit]}


@mcp.tool()
def add_clip(project: str, start: str | float, end: str | float, effect: str, target: str | list | None = None,
             params: dict | None = None, pattern: dict | None = None, cars: str | dict | None = None,
             blend: str | None = None, note: str | None = None) -> dict:
    """Add a clip. effect: see reference(). target: group name (main_beams, tail, turn_signals, mirrors, ...),
    channel index or list. pattern (grid wave): {"type": "to_right", "span": seconds, "quantize": seconds}.
    cars: "all" | "checker" | {"select": "rows", "rows": ["A","B"]} | {"select": "seats", "seats": ["A01"]} ...
    blend: "max" (default) or "override" (replace earlier clips on these channels while active)."""
    p = Project.load(project)
    clip = {"start": round(_resolve_time(p, start), 3), "end": round(_resolve_time(p, end), 3),
            "effect": effect, "target": target, "params": params or {}, "tag": "manual"}
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect}. Effects: {', '.join(EFFECTS)}")
    if pattern:
        clip["pattern"] = pattern
    if cars:
        clip["cars"] = cars
    if blend:
        clip["blend"] = blend
    if note:
        clip["note"] = note
    if clip["end"] <= clip["start"]:
        raise ValueError("end must be after start")
    clip = p.add_clip(clip)
    Renderer(p)  # fail fast on bad params
    p.save()
    return clip


@mcp.tool()
def update_clip(project: str, clip_id: str, changes: dict) -> dict:
    """Change fields of a clip (start, end, effect, target, params, pattern, cars, blend, note)."""
    p = Project.load(project)
    clip = p.get_clip(clip_id)
    for k, v in changes.items():
        if k in ("start", "end"):
            v = round(_resolve_time(p, v), 3)
        if k == "id":
            continue
        clip[k] = v
    Renderer(p)
    p.save()
    return clip


@mcp.tool()
def remove_clips(project: str, clip_ids: list[str] | None = None, start: str | float | None = None,
                 end: str | float | None = None, tag: str | None = None) -> dict:
    """Remove clips by id, and/or all clips overlapping [start, end), and/or by tag ('auto' or 'manual')."""
    p = Project.load(project)
    n = p.remove_clips(ids=clip_ids, start=_resolve_time(p, start) if start is not None else None,
                       end=_resolve_time(p, end) if end is not None else None, tag=tag)
    p.save()
    return {"removed": n, "remaining": len(p.clips)}


@mcp.tool()
def reference() -> dict:
    """Channels, groups, effects, grid patterns, car selections, ramp values and closure limits."""
    return {
        "channels": {i: n for i, n in enumerate(ch.CHANNEL_NAMES)},
        "groups": ch.GROUPS,
        "effects": EFFECTS,
        "patterns": PATTERNS,
        "car_selections": list(CAR_SELECTIONS),
        "light_levels": {"on": 255, "off": 0, **ch.RAMP_VALUES},
        "ramping_channels": ch.RAMPING_CHANNELS,
        "closures": {k: {"channels": v[0], "command_limit": v[1], "dance": v[2]} for k, v in ch.CLOSURES.items()},
        "styles": STYLES, "closure_modes": CLOSURE_MODES,
        "rules": [
            "FSEQ v2.0 uncompressed, 48 or 200 channels, 15-100 ms step (20 ms recommended), < 4 hours",
            "Audio .wav/.mp3 at 44.1 kHz with the same file name as the .fseq, inside USB:/LightShow",
            "Liftgate/charge port/falcon doors must be open before dance; liftgate takes ~14 s to open",
            "Charge port closes automatically 2 minutes after opening",
            "Keep closure dances to ~30 s per show (thermal limits); on/off pulses >= 100 ms look best",
        ],
    }


@mcp.tool()
def preview_car(project: str, seat: str | None = None, start: str | float = 0, end: str | float | None = None,
                resolution: float = 0.1, channels: list[int] | None = None) -> str:
    """Text timeline for one car (default the first seat): '#' on, '+'/'-' ramp on/off, O/D/C/S closures."""
    p = Project.load(project)
    s = _resolve_time(p, start)
    e = _resolve_time(p, end) if end is not None else min(p.duration, s + 10)
    frames = render_preview_frames(p, seat)
    return ascii_preview(frames, p.data["step_ms"], s, e, resolution, channels)


@mcp.tool()
def preview_grid(project: str, start: str | float = 0, end: str | float | None = None, fps: int = 10,
                 out_path: str | None = None) -> dict:
    """Animated GIF of the parking lot from above (white front lights, amber turn signals, red tail/brake)."""
    p = Project.load(project)
    s = _resolve_time(p, start)
    e = _resolve_time(p, end) if end is not None else min(p.duration, s + 15)
    return grid_gif(p, out_path or str(p.dir / f"preview_{s:.0f}-{e:.0f}.gif"), s, e, fps=fps)


def _with_picture(info: dict, png: str):
    return [json.dumps(info, ensure_ascii=False), _Image(path=png)]


@mcp.tool()
def place_image(project: str, image_path: str, start: str | float, end: str | float | None = None,
                target: str | list = "all_lights", fit: str = "contain", margin: int = 0,
                invert: bool | str = "auto", threshold: float | str = "auto", scroll: str = "none",
                pulse: str | None = None, cars: str | dict | None = None, dry_run: bool = False):
    """Show an image's shape on the parking lot (every car = one pixel) at a point in the song, and return
    a rendered picture of the result. start/end accept "bar:33" etc.; end defaults to 2 bars after start.
    fit: contain (whole shape visible) | cover (fill the lot, crop) | stretch | none (1 px = 1 car).
    A dark shape on a white background is detected and inverted automatically. scroll: none|left|right|up|down.
    pulse: 'beats' / 'downbeats' / 'half_beats' lights the shape only on those beats.
    dry_run=True renders the preview without changing the project."""
    p = Project.load(project)
    if p.grid.single:
        raise ValueError("images need a parking grid (set_grid with rows x cols > 1); a single car is one pixel")
    if not Path(image_path).expanduser().exists():
        raise FileNotFoundError(image_path)
    s = _resolve_time(p, start)
    e = _resolve_time(p, end) if end is not None else s + 8 * 60 / p.analysis["bpm"]
    params = {"image": str(Path(image_path).expanduser().resolve()), "fit": fit, "margin": margin,
              "invert": invert, "threshold": threshold, "scroll": scroll}
    if pulse:
        params["pulse"] = pulse
    clip = {"start": round(s, 3), "end": round(min(e, p.duration), 3), "effect": "bitmap", "target": target,
            "params": params, "tag": "manual", "note": f"image {Path(image_path).name}"}
    if cars:
        clip["cars"] = cars
    clip = p.add_clip(clip)
    Renderer(p)
    if not dry_run:
        p.save()
    first = s + 0.06
    if pulse:
        from .render import _event_times
        ev = _event_times(p.analysis, pulse, s, e)
        first = (ev[0] + 0.06) if ev else first
    times = [first, (s + e) / 2] if scroll != "none" else [first]
    png = str(p.dir / f"image_{clip['id']}{'_dry' if dry_run else ''}.png")
    snap = lot_snapshots(p, times, png)
    return _with_picture({"clip": clip, "saved": not dry_run, "preview": snap}, png)


@mcp.tool()
def preview_frames(project: str, times: list[str | float], cell: int | None = None):
    """Rendered pictures of the whole lot from above at the given times (e.g. ["bar:33", "bar:33.5", 61.2]),
    stacked with time and bar.beat captions. White = front lights, amber = turn signals, red = tail/brake."""
    p = Project.load(project)
    ts = [_resolve_time(p, t) for t in times][:12]
    png = str(p.dir / "preview_frames.png")
    return _with_picture(lot_snapshots(p, ts, png, cell), png)


@mcp.tool()
def export_show(project: str, out_dir: str | None = None, show_name: str | None = None, audio_format: str = "wav",
                zip: bool = True, copy_audio_per_car: bool = False, seats: list[str] | None = None,
                layout: str = "usb") -> dict:
    """Render and write USB-ready files. Single car: LightShow/<show>.fseq + .wav. Grid: cars/<seat>/LightShow/<show>.fseq,
    one shared 44.1 kHz audio, assignments.csv and README.txt; validated against Tesla's rules.
    layout="automator" writes the K-LightShow USB Automator source folder instead: <show>.mp3 + <seat>/<show>.fseq."""
    return _export(Project.load(project), out_dir, show_name, audio_format, zip, copy_audio_per_car, seats, layout)


@mcp.tool()
def validate_fseq(fseq_path: str, audio_path: str | None = None) -> dict:
    """Validate any .fseq (Tesla validator.py rules + closure command limits, dance-after-open, 44.1 kHz audio)."""
    return validate_file(fseq_path, audio_path)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
