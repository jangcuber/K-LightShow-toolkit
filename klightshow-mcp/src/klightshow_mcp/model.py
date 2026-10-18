"""Show project: audio + analysis + parking grid + timeline of clips, stored as JSON."""

import json
import os
import string
import time
from pathlib import Path

from . import audio

DEFAULT_HOME = Path(os.environ.get("KLIGHTSHOW_HOME", Path.home() / "klightshow-projects"))


def projects_dir() -> Path:
    DEFAULT_HOME.mkdir(parents=True, exist_ok=True)
    return DEFAULT_HOME


def _row_label(i: int) -> str:
    letters = string.ascii_uppercase
    out = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        out = letters[rem] + out
    return out


class Grid:
    """Parking lot as rows x cols. Row 0 is the top (front) row, col 0 is the left column."""

    def __init__(self, rows=1, cols=1, missing=None, row_ids=None, col_ids=None, **_):
        self.rows, self.cols = int(rows), int(cols)
        if self.rows < 1 or self.cols < 1 or self.rows * self.cols > 10000:
            raise ValueError("grid must have 1..10000 cells")
        self.row_ids = row_ids or [_row_label(r) for r in range(self.rows)]
        width = max(2, len(str(self.cols)))
        self.col_ids = col_ids or [str(c + 1).zfill(width) for c in range(self.cols)]
        if len(self.row_ids) != self.rows or len(self.col_ids) != self.cols:
            raise ValueError("row_ids/col_ids length must match rows/cols")
        self.missing = set()
        for m in missing or []:
            self.missing.add(self.parse_seat(m) if isinstance(m, str) else tuple(m))

    @property
    def single(self) -> bool:
        return self.rows == 1 and self.cols == 1

    def seat(self, r: int, c: int) -> str:
        return f"{self.row_ids[r]}{self.col_ids[c]}"

    def parse_seat(self, code: str) -> tuple[int, int]:
        code = code.strip()
        if "," in code:
            r, c = code.split(",")
            return int(r), int(c)
        for r, rid in enumerate(self.row_ids):
            if code.startswith(rid):
                rest = code[len(rid):]
                for c, cid in enumerate(self.col_ids):
                    if rest == cid or (rest.isdigit() and cid.isdigit() and int(rest) == int(cid)):
                        return r, c
        raise ValueError(f"unknown seat code {code!r}")

    def cars(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) not in self.missing:
                    yield r, c

    def car_count(self) -> int:
        return self.rows * self.cols - len(self.missing)

    def to_dict(self) -> dict:
        return {"rows": self.rows, "cols": self.cols,
                "missing": [self.seat(r, c) for r, c in sorted(self.missing)],
                "row_ids": self.row_ids, "col_ids": self.col_ids}


class Project:
    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path

    # ---- persistence -------------------------------------------------
    @classmethod
    def create(cls, name: str, audio_path: str, channels=48, step_ms=20, rows=1, cols=1, missing=None,
               analyze=True) -> "Project":
        if channels not in (48, 200):
            raise ValueError("channels must be 48 or 200")
        if not 15 <= step_ms <= 100:
            raise ValueError("step_ms must be 15..100 (20 recommended)")
        audio_path = str(Path(audio_path).expanduser().resolve())
        if not Path(audio_path).exists():
            raise FileNotFoundError(audio_path)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "show"
        pdir = projects_dir() / safe
        pdir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1, "name": name, "audio_path": audio_path,
            "channels": channels, "step_ms": step_ms,
            "grid": Grid(rows, cols, missing).to_dict(),
            "clips": [], "next_id": 1, "created": time.time(),
        }
        proj = cls(data, pdir / "project.json")
        if analyze:
            proj.run_analysis()
        proj.save()
        return proj

    @classmethod
    def load(cls, name_or_path: str) -> "Project":
        p = Path(name_or_path).expanduser()
        if p.is_dir():
            p = p / "project.json"
        if not p.exists():
            p = projects_dir() / name_or_path / "project.json"
        if not p.exists():
            raise FileNotFoundError(f"project not found: {name_or_path}")
        return cls(json.loads(p.read_text()), p)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))
        tmp.replace(self.path)

    @property
    def dir(self) -> Path:
        return self.path.parent

    # ---- analysis ----------------------------------------------------
    def run_analysis(self) -> dict:
        a = audio.analyze(self.data["audio_path"])
        (self.dir / "analysis.json").write_text(json.dumps(a))
        self.data["duration"] = a["duration"]
        self._analysis = a
        return a

    @property
    def analysis(self) -> dict:
        if getattr(self, "_analysis", None) is None:
            f = self.dir / "analysis.json"
            self._analysis = json.loads(f.read_text()) if f.exists() else self.run_analysis()
        return self._analysis

    # ---- accessors ---------------------------------------------------
    @property
    def grid(self) -> Grid:
        return Grid(**self.data["grid"])

    def set_grid(self, rows, cols, missing=None, row_ids=None, col_ids=None):
        self.data["grid"] = Grid(rows, cols, missing, row_ids, col_ids).to_dict()

    @property
    def duration(self) -> float:
        return float(self.data.get("duration") or self.analysis["duration"])

    @property
    def clips(self) -> list:
        return self.data["clips"]

    def add_clip(self, clip: dict) -> dict:
        clip = dict(clip)
        clip["id"] = f"c{self.data['next_id']}"
        self.data["next_id"] += 1
        self.clips.append(clip)
        return clip

    def get_clip(self, clip_id: str) -> dict:
        for c in self.clips:
            if c["id"] == clip_id:
                return c
        raise KeyError(f"no clip {clip_id}")

    def remove_clips(self, ids=None, start=None, end=None, tag=None) -> int:
        before = len(self.clips)
        def hit(c):
            if ids is not None and c["id"] not in ids:
                return False
            if start is not None and c["end"] <= start:
                return False
            if end is not None and c["start"] >= end:
                return False
            if tag is not None and c.get("tag") != tag:
                return False
            return True
        self.data["clips"] = [c for c in self.clips if not hit(c)]
        return before - len(self.clips)
