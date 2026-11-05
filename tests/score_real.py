"""Score the app on real recordings against official tabs, section by section.

  .venv/bin/python tests/score_real.py            tuning songs
  .venv/bin/python tests/score_real.py --check    are all files present and the right length?
  .venv/bin/python tests/score_real.py --holdout  held-out songs (only for a frozen change)
  .venv/bin/python tests/score_real.py --showcase best-case demo songs, chosen to suit the app
  .venv/bin/python tests/score_real.py --mix      rock and pop mix, plus two returning songs

Add --all-sections to count every section that lists chords, however many.
This was added after the first mix results. Allowed is easier to pass there.

Tabs rarely say exactly when each chord lands, so this can't measure
chord-by-chord accuracy. Two scores are reported instead:

  Allowed  share of time showing a root the tab lists for that section.
  Found    in sections with several roots, the share of those roots the app
           showed for at least 10% of the section.

A program that repeats one chord can do well on Allowed but not on Found, so
read them together. Each table also shows the best "always one chord" answer.
Sections listing more than MAX_ROOTS roots are skipped as too easy to pass.
"""
import json
import os
import re
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402

MAX_ROOTS = 12 if "--all-sections" in sys.argv else 4
FOUND_SHARE = 0.10
STEP = 0.05
MODES = (("Normal", "segments"), ("Power", "power_segments"))


def song_path(song):
    return os.path.expanduser(os.path.join("~/Music", song["file"]))


def analyze(song):
    """Analyze a song, using only its opening if the file holds more than the song."""
    clip = song.get("clip_seconds")
    if clip is None:
        return engine.analyze(song_path(song))
    samples = engine.load_audio(song_path(song))[: clip * engine.SR]
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "clip.wav")
        sf.write(path, samples, engine.SR)
        return engine.analyze(path)


def seconds(text):
    minutes, secs = text.split(":")
    return int(minutes) * 60 + int(secs)


def root_index(chord):
    return engine.NOTES.index(re.match(r"[A-G][#b]?", chord).group(0))


def timeline(segments, times):
    """Root index at each sample time, or -1 where no chord is shown."""
    roots = np.full(len(times), -1)
    for segment in segments:
        if segment["chord"] != engine.NO_CHORD:
            roots[(times >= segment["start"]) & (times < segment["end"])] = root_index(segment["chord"])
    return roots


def scored_sections(song, duration):
    """(start, end, allowed root indexes) for each section that counts."""
    total = sum(width for _, width, _ in song["sections"])
    position = 0.0
    sections = []
    for _, width, roots in song["sections"]:
        start = position / total * duration
        position += width
        end = position / total * duration
        if 0 < len(roots) <= MAX_ROOTS:
            sections.append((start, end, {engine.NOTES.index(r) for r in roots}))
    return sections


def score(roots, times, sections, offset=0):
    """Return (allowed, found); found is None if no section has several roots."""
    shifted = np.where(roots >= 0, (roots + offset) % 12, -1)
    hits = shown = 0
    found_sum = found_weight = 0.0
    for start, end, allowed in sections:
        span = shifted[(times >= start) & (times < end)]
        span = span[span >= 0]
        if len(span) == 0:
            continue
        hits += np.isin(span, list(allowed)).sum()
        shown += len(span)
        if len(allowed) > 1:
            present = sum((span == root).mean() >= FOUND_SHARE for root in allowed)
            found_sum += present / len(allowed) * (end - start)
            found_weight += end - start
    return hits / max(shown, 1), (found_sum / found_weight if found_weight else None)


def percent(value):
    return "n/a" if value is None else f"{value:.1%}"


def check(songs):
    for song in songs:
        path = song_path(song)
        if not os.path.exists(path):
            print(f"{song['split']:<8} {song['title']:<30} MISSING")
            continue
        duration = song.get("clip_seconds") or len(engine.load_audio(path)) / engine.SR
        difference = duration - seconds(song["tab_length"])
        flag = "  <- length differs" if abs(difference) > 10 else ""
        print(f"{song['split']:<8} {song['title']:<30} recording {duration:6.1f}s  "
              f"tab {song['tab_length']}  ({difference:+.1f}s){flag}")


def main():
    with open(os.path.join(ROOT, "tests", "real_songs.json")) as source:
        songs = json.load(source)["songs"]
    if "--check" in sys.argv:
        check(songs)
        return

    split = "holdout" if "--holdout" in sys.argv else "showcase" if "--showcase" in sys.argv else "mix" if "--mix" in sys.argv else "tune"
    totals = {name: [] for name, _ in MODES}
    print(f"{split.upper()} SONGS\n")
    print(f"{'Song':<30}{'Counted':>8}  {'Normal':>15}  {'Power':>15}  {'One chord':>15}  Best pitch offset")
    print(f"{'':<30}{'':>8}  {'Allowed/Found':>15}  {'Allowed/Found':>15}  {'Allowed/Found':>15}")
    for song in (s for s in songs if s["split"] == split or (split == "mix" and s.get("also_in_mix"))):
        if not os.path.exists(song_path(song)):
            sys.exit(f"Missing file: {song_path(song)}")
        result = analyze(song)
        times = np.arange(0.0, result["duration"], STEP)
        sections = scored_sections(song, result["duration"])
        counted = sum(end - start for start, end, _ in sections) / result["duration"]

        cells = []
        normal_roots = None
        for name, key in MODES:
            roots = timeline(result[key], times)
            normal_roots = roots if normal_roots is None else normal_roots
            allowed, found = score(roots, times, sections)
            if song["split"] == split:  # returning songs don't count toward the average
                totals[name].append((allowed, found))
            cells.append(f"{percent(allowed)} / {percent(found)}")

        constant = max(
            (score(np.full(len(times), r), times, sections) for r in range(12)),
            key=lambda pair: pair[0],
        )
        offsets = [score(normal_roots, times, sections, k)[0] for k in range(12)]
        best = int(np.argmax(offsets))
        print(f"{song['title']:<30}{counted:>8.0%}  {cells[0]:>15}  {cells[1]:>15}  "
              f"{percent(constant[0]) + ' / ' + percent(constant[1]):>15}  {best} ({offsets[best]:.0%})", flush=True)

    print()
    for name, _ in MODES:
        found = [f for _, f in totals[name] if f is not None]
        print(f"{name} average: Allowed {np.mean([a for a, _ in totals[name]]):.1%}, Found {np.mean(found):.1%}")


if __name__ == "__main__":
    main()
