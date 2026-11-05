"""Score the engine on generated songs whose chords are known exactly.

Each song is plucked-string guitar + bass + simple drums, rendered from a chord
list. Variants add the things that hurt real recordings: distortion, off-pitch
tuning and a vocal-like melody. This proves the pipeline works; it says little
about accuracy on real records, which are much messier.

Run from the project folder:  .venv/bin/python tests/evaluate.py
"""
import os
import sys
import tempfile

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

SR = 44100
OPEN_STRINGS = [40, 45, 50, 55]  # low E A D G as MIDI, used to voice chords low


def hz(midi, cents=0.0):
    return 440.0 * 2 ** ((midi - 69 + cents / 100) / 12)


def pluck(freq, seconds, rng, damping=0.996):
    """Karplus-Strong plucked string."""
    period = max(int(SR / freq), 2)
    n = int(seconds * SR)
    excitation = np.zeros(n)
    excitation[:period] = rng.uniform(-1, 1, period)
    a = np.zeros(period + 2)
    a[0], a[period], a[period + 1] = 1.0, -0.5 * damping, -0.5 * damping
    return lfilter([1.0], a, excitation)


def chord_notes(label):
    root_name = label[:2] if label[1:2] in ("#", "b") else label[:1]
    root = engine.NOTES.index(root_name)
    suffix = label[len(root_name):]
    intervals = next(q[1] for q in engine.QUALITIES + engine.POWER_QUALITIES if q[0] == suffix)
    return root, sorted(intervals)


def render(chords, bpm=100, beats_per_chord=4, cents=0.0, distortion=False, melody=False, seed=1):
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    total = len(chords) * beats_per_chord * beat
    out = np.zeros(int((total + 2) * SR))

    def add(signal, at, gain):
        i = int(at * SR)
        end = min(i + len(signal), len(out))
        out[i:end] += gain * signal[: end - i]

    truth = []
    for index, label in enumerate(chords):
        start = index * beats_per_chord * beat
        truth.append((start, start + beats_per_chord * beat, label))
        root, intervals = chord_notes(label)
        for b in range(beats_per_chord):
            at = start + b * beat
            for k, interval in enumerate(intervals + [12]):
                note = 52 + (root + interval - 4) % 12 + (12 if k >= 2 else 0)
                add(pluck(hz(note, cents), beat * 1.2, rng), at + 0.008 * k, 0.25)
            add(pluck(hz(36 + root, cents), beat * 1.1, rng, 0.998), at, 0.5)
            kick = np.sin(2 * np.pi * 60 * np.arange(int(0.12 * SR)) / SR)
            add(kick * np.exp(-np.arange(len(kick)) / (0.03 * SR)), at, 0.5)
            hat = rng.normal(0, 1, int(0.04 * SR)) * np.exp(-np.arange(int(0.04 * SR)) / (0.01 * SR))
            add(hat, at + beat / 2, 0.12)
            if melody:
                # A sung-like line that often leaves the chord tones.
                scale = [0, 2, 4, 5, 7, 9, 11]
                note = 72 + root + scale[rng.integers(0, 7)]
                t = np.arange(int(beat * SR)) / SR
                vibrato = 0.4 * np.sin(2 * np.pi * 5.5 * t)
                wave = sum(np.sin(2 * np.pi * h * hz(note, cents) * t + h * vibrato) / h for h in (1, 2, 3))
                add(wave * np.hanning(len(t)), at, 0.22)
    if distortion:
        out = np.tanh(out * 6) * 0.5
    return out / (np.abs(out).max() + 1e-9) * 0.9, truth, total


def triad(label):
    """Reduce a label to root + major/minor, the standard easier score."""
    if label == engine.NO_CHORD:
        return label
    return label.replace("m7", "m").replace("7", "")


def root(label):
    return label[:2] if label[1:2] in ("#", "b") else label[:1]


def score(result, truth, total):
    """Share of the song's time labelled correctly, sampled every 50 ms.

    Returns exact chord, root + major/minor, and power chord mode's root.
    """
    exact = simple = power_root = count = 0
    for t in np.arange(0.0, total, 0.05):
        expected = next(c for s, e, c in truth if s <= t < e or e >= total and t >= s)

        def found(key):
            return next((s["chord"] for s in result[key] if s["start"] <= t < s["end"]), engine.NO_CHORD)

        exact += found("segments") == expected
        simple += triad(found("segments")) == triad(expected)
        power_root += root(found("power_segments")) == root(expected)
        count += 1
    return exact / count, simple / count, power_root / count


PROGRESSIONS = {
    "pop I-V-vi-IV": ["C", "G", "Am", "F"] * 4,
    "minor rock": ["Em", "C", "G", "D"] * 4,
    "12-bar blues": ["A7", "A7", "A7", "A7", "D7", "D7", "A7", "A7", "E7", "D7", "A7", "E7"] * 2,
    "ii-V-I sevenths": ["Dm7", "G7", "C", "Am7"] * 4,
    "fast changes": ["C", "Am", "F", "G"] * 6,
    "power chords": ["D5", "F5", "G5", "C5"] * 4,
    "power riff": ["E5", "G5", "A5", "E5", "Bb5", "A5", "G5", "F#5"] * 2,
}
VARIANTS = {
    "clean": {},
    "off-pitch +30c": {"cents": 30.0},
    "distorted": {"distortion": True},
    "with melody": {"melody": True},
}


def main():
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for name, chords in PROGRESSIONS.items():
            per_chord = 2 if name == "fast changes" else 4
            for variant, options in VARIANTS.items():
                audio, truth, total = render(chords, beats_per_chord=per_chord, **options)
                path = os.path.join(folder, "song.wav")
                sf.write(path, audio, SR)
                exact, simple, power = score(engine.analyze(path), truth, total)
                rows.append((name, exact, simple, power))
                print(f"{name:<18} {variant:<16} exact {exact:6.1%}   root+maj/min {simple:6.1%}   "
                      f"power mode root {power:6.1%}", flush=True)
    full = [r for r in rows if not r[0].startswith("power")]
    power = [r for r in rows if r[0].startswith("power")]
    print(f"\nFull-chord songs: exact {np.mean([r[1] for r in full]):.1%}, "
          f"root+maj/min {np.mean([r[2] for r in full]):.1%}, power mode root {np.mean([r[3] for r in full]):.1%}")
    print(f"Power chord songs: power mode root {np.mean([r[3] for r in power]):.1%}")


if __name__ == "__main__":
    main()
