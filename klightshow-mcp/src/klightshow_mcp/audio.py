"""Music analysis with numpy/scipy only: tempo, beats, downbeats, onsets,
band energies and song sections. Audio is decoded with ffmpeg."""

import shutil
import subprocess

import numpy as np
from scipy import ndimage, signal

SR = 22050
HOP = 256
N_FFT = 2048


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required to read audio. Install it (e.g. brew install ffmpeg / apt install ffmpeg).")
    return exe


def load_audio(path: str, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr`."""
    cmd = [_ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to decode {path}: {out.stderr.decode(errors='replace')[:500]}")
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def convert_for_tesla(src: str, dst: str, duration_s: float | None = None) -> None:
    """Write a 44.1 kHz stereo WAV (Tesla needs 44.1 kHz) or MP3 by extension."""
    cmd = [_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-ar", "44100", "-ac", "2"]
    if duration_s:
        cmd += ["-t", f"{duration_s:.3f}"]
    if str(dst).lower().endswith(".mp3"):
        cmd += ["-codec:a", "libmp3lame", "-b:a", "320k"]
    else:
        cmd += ["-codec:a", "pcm_s16le"]
    cmd.append(str(dst))
    out = subprocess.run(cmd, capture_output=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to convert audio: {out.stderr.decode(errors='replace')[:500]}")


def probe_sample_rate(path: str) -> int | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
         "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def _mel_filterbank(n_bands: int, sr: int, n_fft: int, fmin=30.0, fmax=None) -> np.ndarray:
    fmax = fmax or sr / 2
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = imel(np.linspace(mel(fmin), mel(fmax), n_bands + 2))
    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    fb = np.zeros((n_bands, len(freqs)))
    for i in range(n_bands):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)), 0, None)
    return fb, pts[1:-1]


def _norm01(x: np.ndarray, lo_pct=5, hi_pct=98) -> np.ndarray:
    lo, hi = np.percentile(x, lo_pct), np.percentile(x, hi_pct)
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0, 1)


def _estimate_tempo(onset_env: np.ndarray, fps: float, bpm_min=70, bpm_max=180, prior_bpm=120):
    env = onset_env - onset_env.mean()
    ac = signal.fftconvolve(env, env[::-1], mode="full")[len(env) - 1:]
    ac /= ac[0] + 1e-9
    lags = np.arange(len(ac))
    bpms = 60 * fps / np.maximum(lags, 1)
    valid = (bpms >= bpm_min) & (bpms <= bpm_max)
    # Log-gaussian tempo prior, plus a bit of support from the double-lag peak.
    prior = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / 1.0) ** 2)
    score = np.where(valid, ac * prior, -np.inf)
    double = np.zeros_like(ac)
    double[: len(ac) // 2] = ac[::2][: len(ac) // 2]
    score = np.where(valid, score + 0.5 * double * prior, -np.inf)
    lag = int(np.argmax(score))
    # Parabolic refinement of the lag.
    if 1 <= lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-9:
            lag = lag + 0.5 * (a - c) / denom
    return 60 * fps / lag


def _track_beats(onset_env: np.ndarray, fps: float, bpm: float, tightness=100.0) -> np.ndarray:
    """Ellis (2007) dynamic programming beat tracker. Returns frame indices."""
    period = 60 * fps / bpm
    env = onset_env / (onset_env.std() + 1e-9)
    # Smooth with a gaussian of width ~ period/32 for local scoring.
    win = signal.windows.gaussian(int(period) * 2 + 1, period / 32)
    local = np.convolve(env, win / win.sum(), mode="same")
    n = len(local)
    backlink = -np.ones(n, dtype=int)
    cum = local.copy()
    lo, hi = int(-2 * period), int(-period / 2)
    offsets = np.arange(lo, hi + 1)
    txcost = -tightness * np.log(-offsets / period) ** 2
    for i in range(n):
        idx = i + offsets
        ok = idx >= 0
        if not ok.any():
            continue
        cand = cum[idx[ok]] + txcost[ok]
        j = int(np.argmax(cand))
        if cand[j] > 0:
            cum[i] = local[i] + cand[j]
            backlink[i] = idx[ok][j]
    # Start from the best of the last period's cumulative scores.
    tail = cum[max(0, n - int(period)):]
    i = max(0, n - int(period)) + int(np.argmax(tail))
    beats = []
    while i >= 0:
        beats.append(i)
        i = backlink[i]
    beats = np.array(beats[::-1])
    # Trim weak leading/trailing beats (silence).
    strength = local[beats]
    thr = 0.5 * np.median(strength[strength > 0]) if (strength > 0).any() else 0
    keep = np.where(strength >= thr)[0]
    if len(keep):
        beats = beats[keep[0]: keep[-1] + 1]
    return beats


def _novelty(features: np.ndarray, kernel_beats: int) -> np.ndarray:
    """Foote checkerboard novelty on a beat-synchronous self-similarity matrix."""
    f = features - features.mean(axis=1, keepdims=True)
    f /= np.linalg.norm(f, axis=0, keepdims=True) + 1e-9
    ssm = f.T @ f
    k = kernel_beats
    g = signal.windows.gaussian(2 * k, k / 2)
    kern = np.outer(g, g) * np.block([[np.ones((k, k)), -np.ones((k, k))], [-np.ones((k, k)), np.ones((k, k))]])
    n = ssm.shape[0]
    pad = np.pad(ssm, k, mode="reflect")
    nov = np.array([np.sum(pad[i: i + 2 * k, i: i + 2 * k] * kern) for i in range(n)])
    nov = np.clip(nov, 0, None)
    return nov / (nov.max() + 1e-9)


def analyze(path: str) -> dict:
    y = load_audio(path)
    if len(y) < SR:
        raise ValueError("audio is shorter than 1 second")
    duration = len(y) / SR
    fps = SR / HOP

    f, t, Z = signal.stft(y, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None, padded=False)
    mag = np.abs(Z)
    times = t  # frame centers
    fb, centers = _mel_filterbank(48, SR, N_FFT)
    mel = np.log1p(1000 * (fb @ mag))

    # Onset strength: positive spectral flux on log-mel.
    flux = np.maximum(0, np.diff(mel, axis=1)).mean(axis=0)
    flux = np.concatenate([[0], flux])
    flux = flux - ndimage.uniform_filter1d(flux, size=int(fps))  # remove slow trend
    onset_env = np.clip(flux, 0, None)
    # Beats are carried mostly by kick/bass: weight low-band flux extra for tempo and beat phase.
    low_flux = np.maximum(0, np.diff(mel[:10], axis=1)).mean(axis=0)
    low_flux = np.clip(np.concatenate([[0], low_flux]) - ndimage.uniform_filter1d(np.concatenate([[0], low_flux]), size=int(fps)), 0, None)
    beat_env = onset_env / (onset_env.std() + 1e-9) + 1.5 * low_flux / (low_flux.std() + 1e-9)

    bpm = _estimate_tempo(beat_env, fps)
    beat_frames = _track_beats(beat_env, fps, bpm)
    # Spectral flux peaks slightly before the onset reaches the frame center.
    times = times + N_FFT / 4 / SR
    beat_times = times[beat_frames]
    if len(beat_times) > 4:
        bpm = 60.0 / np.polyfit(np.arange(len(beat_times)), beat_times, 1)[0]

    # Band energies (RMS-like) per frame.
    power = mag ** 2
    def band(lo, hi):
        sel = (f >= lo) & (f < hi)
        return np.sqrt(power[sel].sum(axis=0))
    low, mid, high = band(20, 200), band(200, 2500), band(2500, SR / 2)
    rms = np.sqrt(power.sum(axis=0))
    smooth = lambda x: ndimage.uniform_filter1d(x, size=max(1, int(fps * 0.1)))
    energy = _norm01(smooth(rms))
    low_n, mid_n, high_n = _norm01(smooth(low)), _norm01(smooth(mid)), _norm01(smooth(high))

    # Beat-synchronous log-mel features.
    bounds = np.concatenate([beat_frames, [mel.shape[1]]])
    sync = np.stack([mel[:, bounds[i]: max(bounds[i] + 1, bounds[i + 1])].mean(axis=1)
                     for i in range(len(beat_frames))], axis=1) if len(beat_frames) else np.zeros((mel.shape[0], 0))

    # Downbeats (4/4): chords and arrangements change on bar starts, so pick the bar phase
    # with the largest beat-to-beat spectral change, with low-end onsets as a tie-breaker.
    low_onset = np.clip(np.diff(np.log1p(low), prepend=0), 0, None)
    if len(beat_frames) >= 8:
        change = np.concatenate([[0], np.linalg.norm(np.diff(sync, axis=1), axis=0)])
        change /= change.mean() + 1e-9
        lo_on = low_onset[beat_frames] / (low_onset[beat_frames].mean() + 1e-9)
        scores = [change[p::4].mean() + 0.25 * lo_on[p::4].mean() for p in range(4)]
        phase = int(np.argmax(scores))
    else:
        phase = 0
    downbeat_times = beat_times[phase::4]

    # Onset peaks (strong hits) for accents.
    peaks, props = signal.find_peaks(onset_env, height=np.percentile(onset_env, 90), distance=int(fps * 0.1))
    onset_times = times[peaks]
    onset_strength = _norm01(props["peak_heights"], 0, 100) if len(peaks) else np.array([])

    # Sections from beat-synchronous novelty.
    sections = []
    if len(beat_frames) >= 32:
        nov = _novelty(sync, kernel_beats=8)
        min_gap = 16  # beats (4 bars)
        pk, _ = signal.find_peaks(nov, distance=min_gap, height=0.15)
        # Snap to the nearest downbeat index.
        db_idx = np.arange(phase, len(beat_frames), 4)
        snapped = sorted({int(db_idx[np.argmin(np.abs(db_idx - p))]) for p in pk})
        cut_beats = [0] + [b for b in snapped if min_gap <= b <= len(beat_frames) - 8]
        cut_times = [0.0] + [float(beat_times[b]) for b in cut_beats[1:]] + [duration]
    else:
        cut_times = [0.0, duration]
    # Merge sections shorter than 6 s.
    merged = [cut_times[0]]
    for ct in cut_times[1:-1]:
        if ct - merged[-1] >= 6.0:
            merged.append(ct)
    if duration - merged[-1] < 6.0 and len(merged) > 1:
        merged.pop()
    merged.append(duration)

    sec_energy, sec_slope = [], []
    for a, b in zip(merged[:-1], merged[1:]):
        sel = (times >= a) & (times < b)
        sec_energy.append(float(energy[sel].mean()) if sel.any() else 0.0)
        half = (a + b) / 2
        first, second = sel & (times < half), sel & (times >= half)
        sec_slope.append(float(energy[second].mean() - energy[first].mean()) if first.any() and second.any() else 0.0)
    e = np.array(sec_energy)
    if len(e) > 1 and e.max() - e.min() > 1e-6:
        rel = (e - e.min()) / (e.max() - e.min())
    else:
        rel = np.full(len(e), 0.6)
    for i, (a, b) in enumerate(zip(merged[:-1], merged[1:])):
        level = int(np.clip(round(rel[i] * 3), 0, 3))  # 0 calm .. 3 peak
        nxt = rel[i + 1] if i + 1 < len(rel) else 0
        if i == 0 and level <= 1:
            label = "intro"
        elif level <= 2 and nxt >= 0.75 and sec_slope[i] > 0.03:
            label = "build"
        elif i == len(e) - 1 and level <= 1:
            label = "outro"
        elif level == 3:
            label = "drop"
        elif level == 2:
            label = "chorus"
        elif level == 1:
            label = "verse"
        else:
            label = "break"
        sections.append({"start": round(a, 3), "end": round(b, 3), "energy": round(sec_energy[i], 3),
                         "level": level, "label": label})

    # Downsample curves to 20 ms for the renderer / previews.
    grid_t = np.arange(0, duration, 0.02)
    interp = lambda x: np.interp(grid_t, times, x).round(3).tolist()
    return {
        "source": str(path),
        "duration": round(duration, 3),
        "bpm": round(float(bpm), 2),
        "beats": [round(float(x), 3) for x in beat_times],
        "downbeats": [round(float(x), 3) for x in downbeat_times],
        "onsets": [round(float(x), 3) for x in onset_times],
        "onset_strength": [round(float(x), 3) for x in onset_strength],
        "sections": sections,
        "curves_step": 0.02,
        "curves": {"energy": interp(energy), "low": interp(low_n), "mid": interp(mid_n), "high": interp(high_n)},
    }


def summarize(analysis: dict) -> dict:
    """Compact view for an LLM: no per-frame curves."""
    return {
        "duration": analysis["duration"],
        "bpm": analysis["bpm"],
        "beat_count": len(analysis["beats"]),
        "first_beats": analysis["beats"][:8],
        "downbeat_count": len(analysis["downbeats"]),
        "strong_onset_count": len(analysis["onsets"]),
        "sections": analysis["sections"],
    }
