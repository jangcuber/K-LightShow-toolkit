"""Write USB-ready show files: one car, or one .fseq per parking spot."""

import csv
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np

from . import audio
from .fseq import write_fseq
from .model import Project
from .render import Renderer
from .validate import check_frames, validate_file

GRID_README = """K-LIGHT SHOW 차량별 쇼 파일
==============================

쇼 이름: {show}
차량 수: {cars}대 ({rows}행 x {cols}열), 길이 {duration:.1f}초, 스텝 {step}ms, {channels}채널

USB 준비 방법 (차주용)
1. USB를 exFAT 또는 FAT32로 포맷합니다.
2. cars/<내 자리 코드>/LightShow 폴더를 USB 최상위에 그대로 복사합니다.
   예) 자리가 B12면 cars/B12/LightShow → USB:/LightShow
3. audio/{show}.{audio_ext} 파일을 USB:/LightShow 폴더 안에 넣습니다.
   (fseq와 오디오 파일 이름이 같아야 합니다: {show}.fseq + {show}.{audio_ext})
4. 차에 꽂고 Toybox > Light Show에서 "{show}"을(를) 고릅니다.

assignments.csv에 자리 코드, 행/열 위치, 파일 경로가 있습니다.
모든 차의 파일은 같은 길이, 같은 0초 시작점을 가지므로 동시에 시작하면 싱크가 맞습니다.
"""


def export_show(project: Project, out_dir: str | None = None, show_name: str | None = None,
                audio_format: str = "wav", make_zip: bool = True, copy_audio_per_car: bool = False,
                seats: list[str] | None = None, layout: str = "usb") -> dict:
    """layout 'usb': cars/<seat>/LightShow/<show>.fseq + audio/<show>.wav (copy a folder straight to a USB).
    layout 'automator': <show>.mp3 at the root + <seat>/<show>.fseq, the source-folder format of
    K-LightShow USB Automator (it copies the root mp3 and the seat's fseq onto each USB)."""
    if layout not in ("usb", "automator"):
        raise ValueError("layout must be 'usb' or 'automator'")
    if layout == "automator":
        audio_format = "mp3"
    t0 = time.time()
    show = show_name or "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in project.data["name"]) or "lightshow"
    out = Path(out_dir).expanduser() if out_dir else project.dir / "export"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    step = project.data["step_ms"]
    renderer = Renderer(project)
    grid = renderer.grid
    audio_ext = "mp3" if audio_format == "mp3" else "wav"
    duration = renderer.n_frames * step / 1000
    errors, warnings = [], []

    if grid.single:
        ls = out / "LightShow"
        ls.mkdir()
        frames = renderer.render_car(0, 0)
        fseq_path = ls / f"{show}.fseq"
        write_fseq(fseq_path, frames, step)
        audio_path = ls / f"{show}.{audio_ext}"
        audio.convert_for_tesla(project.data["audio_path"], audio_path, duration)
        report = validate_file(str(fseq_path), str(audio_path))
        result = {"mode": "single", "out_dir": str(out), "files": [str(fseq_path), str(audio_path)],
                  "validation": report}
    else:
        automator = layout == "automator"
        if not automator:
            (out / "cars").mkdir()
            (out / "audio").mkdir()
        shared_audio = (out if automator else out / "audio") / f"{show}.{audio_ext}"
        audio.convert_for_tesla(project.data["audio_path"], shared_audio, duration)
        wanted = None
        if seats:
            wanted = {grid.parse_seat(s) for s in seats}
        rows = []
        closure_counts = {}
        for r, c in grid.cars():
            if wanted is not None and (r, c) not in wanted:
                continue
            seat = grid.seat(r, c)
            frames = renderer.render_car(r, c)
            d = out / seat if automator else out / "cars" / seat / "LightShow"
            d.mkdir(parents=True)
            write_fseq(d / f"{show}.fseq", frames, step)
            if copy_audio_per_car:
                shutil.copyfile(shared_audio, d / shared_audio.name)
            e, w, stats = check_frames(frames, step)
            errors += [f"{seat}: {x}" for x in e]
            if not warnings:
                warnings += w  # identical across cars in practice; report once
            for k, v in stats["closure_commands"].items():
                closure_counts[k] = max(closure_counts.get(k, 0), v)
            rows.append({"seat": seat, "row": r + 1, "col": c + 1,
                         "file": f"{seat}/{show}.fseq" if automator else f"cars/{seat}/LightShow/{show}.fseq",
                         "lit_ratio": round(float((frames[:, :30] > 0).mean()), 3)})
        with open(out / "assignments.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
        if not automator:
            (out / "README.txt").write_text(GRID_README.format(
                show=show, cars=len(rows), rows=grid.rows, cols=grid.cols, duration=duration, step=step,
                channels=project.data["channels"], audio_ext=audio_ext), encoding="utf-8")
        first = rows[0]["file"]
        report = validate_file(str(out / first), str(shared_audio), deep=False)
        report["errors"] = report["errors"] + errors[:50]
        report["warnings"] = report["warnings"] + warnings
        report["ok"] = not report["errors"]
        report["max_closure_commands"] = closure_counts
        result = {"mode": "grid", "out_dir": str(out), "cars": len(rows), "grid": f"{grid.rows}x{grid.cols}",
                  "audio": str(shared_audio), "assignments": str(out / "assignments.csv"), "validation": report}

    if make_zip:
        zpath = out.parent / f"{out.name}_{show}.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for fp in sorted(out.rglob("*")):
                if fp.is_file():
                    comp = zipfile.ZIP_STORED if fp.suffix in (".mp3",) else zipfile.ZIP_DEFLATED
                    z.write(fp, fp.relative_to(out), compress_type=comp, compresslevel=6)
        result["zip"] = str(zpath)
        result["zip_mb"] = round(zpath.stat().st_size / 1e6, 1)
    result["seconds"] = round(time.time() - t0, 1)
    return result


def render_preview_frames(project: Project, seat: str | None = None) -> np.ndarray:
    r = Renderer(project)
    rr, cc = r.grid.parse_seat(seat) if seat else next(iter(r.grid.cars()))
    return r.render_car(rr, cc)
