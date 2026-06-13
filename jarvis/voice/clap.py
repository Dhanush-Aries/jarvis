"""Clap detection — an acoustic trigger that needs no speech model.

A clap is a loud, very short broadband transient: a sharp rising edge well above
the recent background level, followed by a quick decay. We scan an audio window
in short frames, count rising edges that clear a dynamic threshold, and report
how many claps occurred. Two claps (default) is robust against random noise.
"""
from __future__ import annotations


def count_claps(audio, sr: int, threshold: float = 0.25,
                min_gap_s: float = 0.08, frame_s: float = 0.01) -> int:
    """Count clap-like transients in a mono float32 array."""
    import numpy as np

    a = np.abs(np.asarray(audio, dtype="float32").reshape(-1))
    if a.size == 0:
        return 0
    frame = max(1, int(frame_s * sr))
    n = a.size // frame
    if n < 2:
        return 0
    peaks = a[: n * frame].reshape(n, frame).max(axis=1)
    # Dynamic floor: claps must clear both an absolute and a relative bar.
    floor = float(np.median(peaks)) + 1e-6
    bar = max(threshold, floor * 6)
    gap_frames = max(1, int(min_gap_s / frame_s))
    claps, last = 0, -gap_frames
    for i in range(1, n):
        if peaks[i] >= bar and peaks[i - 1] < bar and (i - last) >= gap_frames:
            claps += 1
            last = i
    return claps


def is_clap(audio, sr: int, required: int = 2, threshold: float = 0.25) -> bool:
    return count_claps(audio, sr, threshold=threshold) >= required
