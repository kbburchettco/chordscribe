# ChordScribe

Drop in a song and see its chords scroll by in time with the music, with a guitar shape for each one. Everything runs on your Mac, and your audio is never uploaded.

## Start it

Double-click **Open ChordScribe.command**. If macOS blocks it the first time, right-click the file and choose Open. The first run takes a few minutes to install. After that, the app opens in your browser.

To stop it, close the Terminal window.

## How it works

1. Decode the song using a tool built into macOS.
2. Separate the sustained, pitched sound from the drums.
3. Find the beat, and measure which of the 12 notes are sounding on each beat. The bass is measured apart from everything above it, so a loud bass note can't drown out the chord.
4. Compare each beat with 48 chord templates: major, minor, 7 and minor 7 on all 12 roots.
5. Choose the most likely *sequence* of chords (Viterbi decoding), so one noisy beat can't flip the answer.

Power chord mode runs step 5 a second time using only root-and-fifth shapes, so it shows chords like F#5. You switch it on yourself for riff-based rock and metal. It's a manual choice because the app can't reliably tell power chords from full chords on distorted records.

The code is in `engine.py`. `server.py` runs it locally, and `static/index.html` is the player.

## How accurate is it?

**On generated audio with known chords** (28 test songs, run with `.venv/bin/python tests/evaluate.py`):

| Measure | Songs | Score |
|---|---|---|
| Normal mode: correct root and major/minor | 20 full-chord songs | 97.0% |
| Normal mode: exact chord, including sevenths | 20 full-chord songs | 89.2% |
| Power chord mode: correct root | 8 power chord songs | 98.0% |

These results show the pipeline works, but they are not a real-world accuracy figure. Real recordings are harder, and the settings were adjusted using these same songs.

**On real recordings:** 8 songs with Ultimate Guitar official tabs, stored as chord roots and section lengths in `tests/real_songs.json`. Four guided changes to the app. Four were held out until the app was frozen, so a fix couldn't simply be fitted to the test.

Run `.venv/bin/python tests/score_real.py` to score the tuning songs. Current baseline:

| Tuning song | Normal: Allowed / Found | Power: Allowed / Found | Always one chord: Allowed / Found |
|---|---|---|---|
| Helmet, *In The Meantime* | 51.1% / 67.6% | 25.8% / 58.4% | 100.0% / 36.6% |
| Pantera, *Psycho Holiday* | 64.9% / 80.5% | 72.9% / 85.1% | 61.2% / 33.0% |
| Tool, *Hush* | 80.8% / 84.8% | 78.1% / 82.0% | 100.0% / 33.5% |
| Nick Cave, *Into My Arms* | 89.2% / 80.1% | 91.8% / 80.1% | 87.2% / 33.7% |
| **Average** | **71.5% / 78.3%** | **67.2% / 76.4%** | |

- **Allowed** is the share of time showing a root the tab lists for that section.
- **Found** is the share of a section's listed roots that the app showed for at least 10% of the section, in sections with several roots.

Read the two together: repeating one chord can score well on Allowed but not on Found. These are section-level checks, not chord-by-chord accuracy. Sections listing more than four roots or none are skipped. Section times are proportions of the tab's timeline, so they are approximate, especially on *Psycho Holiday*, where the recording runs 18 seconds longer than the tab. The *Bro Hymn* recording is a longer version than its tab, but every section lists the same roots, so timing doesn't affect its score. Eight songs from one listener's library can't support a general accuracy figure.

**Hold-out result:** after engine tuning stopped, the frozen app was scored once on the four held-out songs. This is the fairest figure here, because none of these songs guided any change.

| Hold-out song | Normal: Allowed / Found | Power: Allowed / Found | Always one chord: Allowed / Found | Song counted |
|---|---|---|---|---|
| Helmet, *Unsung* | 75.9% / 71.7% | 68.2% / 71.7% | 100.0% / 34.7% | 100% |
| Pantera, *Cowboys From Hell* | 31.5% / 50.0% | 18.2% / 25.0% | 100.0% / 25.0% | 76% |
| Pantera, *Domination* | 91.9% / 62.0% | 91.7% / 62.0% | 100.0% / 38.0% | 29% |
| Pennywise, *Bro Hymn* | 65.0% / 60.1% | 76.5% / 66.5% | 100.0% / 25.0% | 100% |
| **Average** | **66.1% / 60.9%** | **63.6% / 56.3%** | | |

These four songs have now been used. Any future engine change needs new held-out songs.

**Best-case showcase:** Nick Cave's *Where The Wild Roses Grow*, chosen because it has simple chords and a cleaner sound. This shows what the app can do when the music suits it, and says nothing about typical accuracy.

| Showcase song | Normal: Allowed / Found | Always one chord: Allowed / Found |
|---|---|---|
| Nick Cave, *Where The Wild Roses Grow* | 97.2% / 100.0% | 100.0% / 29.0% |

The app also detected the correct key, G minor. Across the whole song, 91.7% of chord time landed on the song's chords or a seventh version of them. Its choruses list five roots, so they weren't counted in the table, which covers 60% of the song. The recording runs 21 seconds longer than the tab. Run `.venv/bin/python tests/score_real.py --showcase` to repeat this.

## Known limits

- **Power chords aren't detected automatically.** In normal mode, distorted riffs are forced into the nearest major, minor or seventh chord. Turn on power chord mode for those songs. An automatic test for missing thirds worked on generated audio but failed on real recordings, so it was removed.
- **Power chord mode's roots are unreliable on real records.** Across the tuning songs it averages slightly below normal mode, and it does badly on Helmet's *In The Meantime*, often showing F# or A during long D5 sections. Its dashed "unsure" marks are also too rare to be useful.
- **Root and fifth get confused.** A trial fix helped the Helmet song but scored below the current version on the Pantera song, often showing D during G sections, so it was not added. Using the lowest sounding note as the root also failed: all 18 variations scored below the current app on the tuning songs. On the riffs checked, the true low root is weak or missing from the mix. The strongest low sound was often the chord's fifth, or a broad hump of low-end energy that didn't match the notes.
- **Sevenths are the weakest chord type.** Plain chords and sevenths get confused, especially under a melody.
- **Other chord types are missing.** Sus, diminished, augmented and extended jazz chords aren't in the vocabulary. Jazz will be labelled loosely.
- **Busy songs can flicker.** Real recordings can produce quick chord changes that aren't really there.
- **Key is an estimate.** It can confuse a song's major key with its relative minor.
- **The confidence shown is a rough signal.** Dashed chords are less certain, but this hasn't been calibrated against real accuracy.
- **Guitar shapes are suggestions.** They show a common way to play the chord, not necessarily how it was played on the record.
- **Protected files may not open.** Older DRM-protected purchases may fail to load.

## Case study

`case-study/index.html` is the portfolio write-up: results, failed fixes and lessons.
