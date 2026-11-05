"""ChordCruncher engine: turn an audio file into a timed chord chart.

Pipeline
  1. Decode to mono 22 kHz (macOS `afconvert`, so no ffmpeg is needed).
  2. Split harmonic from percussive sound, so drums don't smear the pitch data.
  3. Find the beats, and measure the 12 pitch classes present on each beat.
  4. Compare each beat with a template for every candidate chord.
  5. Viterbi decoding picks the most likely *sequence*. Chords tend to last,
     so one noisy beat can't flip the answer on its own.
"""
import os
import subprocess
import sys
import tempfile

import librosa
import numpy as np
import soundfile as sf

SR = 22050
HOP = 512
NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Chord qualities: label suffix, intervals (weights), and a prior that makes the
# plain triads the default unless the extra note is clearly there.
QUALITIES = [
    ("", {0: 1.0, 4: 1.0, 7: 1.0}, 0.0),
    ("m", {0: 1.0, 3: 1.0, 7: 1.0}, 0.0),
    ("7", {0: 1.0, 4: 1.0, 7: 1.0, 10: 0.7}, -0.03),
    ("m7", {0: 1.0, 3: 1.0, 7: 1.0, 10: 0.7}, -0.03),
]
# Power chord mode: a separate pass that only considers root + fifth. Telling a
# power chord from a full chord doesn't work on distorted records, so the
# listener chooses this mode instead of the app guessing.
POWER_QUALITIES = [("5", {0: 1.0, 7: 1.0}, 0.0)]
NO_CHORD = "N"

# Tuned on generated audio only; see tests/evaluate.py.
SHARPNESS = 30.0  # how strongly a beat's evidence counts
STAY_BONUS = 2.0  # log-odds of a chord continuing on the next beat
BASS_WEIGHT = 0.2  # how much the lowest notes vote for the root
SILENCE_DB = -45.0  # beats quieter than this become "no chord"
COMPRESSION = 100.0  # log compression, so one loud note can't dominate

KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def build_templates(qualities):
    labels, templates, roots, priors = [], [], [], []
    for root in range(12):
        for suffix, intervals, prior in qualities:
            t = np.zeros(12)
            for interval, weight in intervals.items():
                t[(root + interval) % 12] = weight
            labels.append(NOTES[root] + suffix)
            templates.append(t / np.linalg.norm(t))
            roots.append(root)
            priors.append(prior)
    return labels, np.array(templates), np.array(roots), np.array(priors)


def load_audio(path):
    """Decode any format macOS understands into mono float samples at SR."""
    handle, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    try:
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", path, wav_path],
            check=True,
            capture_output=True,
        )
        samples, _ = sf.read(wav_path, dtype="float32")
    except subprocess.CalledProcessError as error:
        raise ValueError("Could not read this audio file. It may be damaged or protected.") from error
    finally:
        # afconvert removes its output file when it fails.
        if os.path.exists(wav_path):
            os.unlink(wav_path)
    if samples.size == 0:
        raise ValueError("This audio file is empty.")
    return samples


def beat_grid(percussive, duration):
    """Beat times covering the whole song, with a fixed grid as the fallback."""
    tempo, frames = librosa.beat.beat_track(y=percussive, sr=SR, hop_length=HOP)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
    if len(beats) < 8:
        # Beatless music (ambient, rubato). Use half-second steps instead.
        return np.arange(0.0, duration, 0.5), 0.0
    # The tracker often locks on late or stops early. Continue the same pulse
    # out to both ends so chord changes there still land on a beat.
    step = float(np.median(np.diff(beats)))
    before = np.arange(beats[0] - step, 0.0, -step)[::-1]
    after = np.arange(beats[-1] + step, duration, step)
    return np.concatenate((before, beats, after)), tempo


def pitch_features(harmonic, tuning):
    """Return (chord chroma, bass chroma), each 12 x frames.

    One constant-Q transform is split at C3. Below it is the bass line, which
    votes for the root. Above it is what defines the chord. Without the split a
    loud bass note and its overtones swamp the third, and Am reads as A.
    Log compression stops any single loud note dominating, and the upper bins
    are faded out because they hold mostly overtones rather than chord notes.
    """
    per_octave = 36
    octaves = 7
    fmin = librosa.note_to_hz("C1")
    spectrum = np.abs(librosa.cqt(
        harmonic, sr=SR, hop_length=HOP, fmin=fmin,
        tuning=tuning * per_octave / 12,  # estimate is in semitones, cqt wants bins
        n_bins=octaves * per_octave, bins_per_octave=per_octave,
    ))
    spectrum = np.log1p(COMPRESSION * spectrum / (spectrum.max() + 1e-9))

    split = 2 * per_octave  # C3
    position = (np.arange(octaves * per_octave - split) / per_octave)[:, None]
    fade = np.clip(1.0 - (position - 2.0) / 3.0, 0.0, 1.0)  # full to C5, gone by C8

    def fold(rows, start_note):
        mapping = librosa.filters.cq_to_chroma(
            rows.shape[0], bins_per_octave=per_octave, n_chroma=12,
            fmin=librosa.note_to_hz(start_note),
        )
        return mapping @ rows

    return fold(spectrum[split:] * fade, "C3"), fold(spectrum[:split], "C1")


def per_beat(feature, edges_frames):
    """Median of each feature row between consecutive beat edges."""
    return librosa.util.sync(feature, edges_frames, aggregate=np.median, pad=False)


def viterbi(scores):
    """Best state path through scores (states x beats) with a stay bonus."""
    n_states, n_beats = scores.shape
    best = scores[:, 0].copy()
    back = np.zeros((n_beats, n_states), dtype=np.int32)
    for t in range(1, n_beats):
        top = int(np.argmax(best))
        stay = best + STAY_BONUS
        change_better = best[top] > stay
        back[t] = np.where(change_better, top, np.arange(n_states))
        best = np.where(change_better, best[top], stay) + scores[:, t]
    path = np.zeros(n_beats, dtype=np.int32)
    path[-1] = int(np.argmax(best))
    for t in range(n_beats - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def estimate_key(chroma):
    profile = chroma.mean(axis=1)
    best_score, best_key = -2.0, "Unknown"
    for root in range(12):
        for shape, name in ((KRUMHANSL_MAJOR, "major"), (KRUMHANSL_MINOR, "minor")):
            score = np.corrcoef(profile, np.roll(shape, root))[0, 1]
            if score > best_score:
                best_score, best_key = score, f"{NOTES[root]} {name}"
    return best_key


def analyze(path):
    samples = load_audio(path)
    duration = len(samples) / SR

    harmonic, percussive = librosa.effects.hpss(samples)
    tuning = float(librosa.estimate_tuning(y=harmonic, sr=SR))
    beats, tempo = beat_grid(percussive, duration)

    # Beat edges as unique frames, with times derived from those same frames.
    # Two beats can round to one frame, and the feature columns then no longer
    # line up with a separately kept list of times.
    edges = np.concatenate(([0.0], beats, [duration]))
    edge_frames = np.unique(librosa.time_to_frames(edges, sr=SR, hop_length=HOP))
    edges = librosa.frames_to_time(edge_frames, sr=SR, hop_length=HOP)

    chroma, bass = pitch_features(harmonic, tuning)
    loudness = librosa.amplitude_to_db(
        librosa.feature.rms(y=samples, hop_length=HOP), ref=1.0
    )

    beat_chroma = per_beat(chroma, edge_frames)
    beat_bass = per_beat(bass, edge_frames)
    beat_loud = per_beat(loudness, edge_frames)[0]
    n_beats = beat_chroma.shape[1]
    if len(edges) != n_beats + 1:
        raise RuntimeError("Beat times and pitch features are misaligned.")

    unit = beat_chroma / (np.linalg.norm(beat_chroma, axis=0, keepdims=True) + 1e-9)
    bass_unit = beat_bass / (beat_bass.max(axis=0, keepdims=True) + 1e-9)
    silent = beat_loud < SILENCE_DB

    def decode(qualities):
        """Pick the best chord sequence using only these chord types."""
        labels, templates, roots, priors = build_templates(qualities)
        match = templates @ unit + priors[:, None] + BASS_WEIGHT * bass_unit[roots]

        # "No chord" wins only on near-silent beats.
        no_chord_row = np.where(silent, match.max() + 1.0, match.min() - 1.0)
        path = viterbi(SHARPNESS * np.vstack([match, no_chord_row]))
        all_labels = labels + [NO_CHORD]

        # A chord's confidence is its lead over the best differently-named chord.
        runner_up = np.sort(match, axis=0)[-2]
        segments = []
        start = 0
        for i in range(1, n_beats + 1):
            if i == n_beats or path[i] != path[start]:
                state = path[start]
                if state < len(labels):
                    span = slice(start, i)
                    margin = match[state, span].mean() - runner_up[span].mean()
                    confidence = float(np.clip(0.5 + 4.0 * margin, 0.0, 1.0))
                else:
                    confidence = 1.0
                segments.append({
                    "start": round(float(edges[start]), 3),
                    "end": round(float(edges[i]), 3),
                    "chord": all_labels[state],
                    "confidence": round(confidence, 2),
                })
                start = i
        if segments:
            segments[-1]["end"] = round(duration, 3)
        return segments

    return {
        "duration": round(duration, 3),
        "tempo": round(tempo, 1),
        "key": estimate_key(chroma),
        "tuning_cents": round(tuning * 100, 1),
        "beats": [round(float(b), 3) for b in beats],
        "segments": decode(QUALITIES),
        "power_segments": decode(POWER_QUALITIES),
    }


if __name__ == "__main__":
    result = analyze(sys.argv[1])
    print(f"Key {result['key']}  Tempo {result['tempo']}  Tuning {result['tuning_cents']} cents")
    for seg in result["segments"]:
        print(f"{seg['start']:8.2f}  {seg['chord']:<5} {seg['confidence']:.2f}")
