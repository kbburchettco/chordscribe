# Rock and pop mix test rules

Set before any of these songs were analyzed.

## Songs

- Pink Floyd, *Breathe (In The Air)*
- David Bowie, *Suffragette City*
- Creedence Clearwater Revival, *Who'll Stop The Rain*
- Weezer, *Buddy Holly*
- The Who, *Behind Blue Eyes*
- Echo & The Bunnymen, *The Killing Moon*

Returning songs, requested for comparison. The app has already been scored on these, so they don't count as new evidence:

- Helmet, *In The Meantime*
- Nick Cave & The Bad Seeds, *Where The Wild Roses Grow*

## Rules

1. The chord engine stays frozen. No changes to chord detection are allowed before or during this test.
2. Each song is scored once, using `tests/score_real.py`.
3. Every song is reported, whatever its score. A song is left out only if its official tab has no usable chords or section timing, and the write-up says so.
4. Normal mode is the main result. Power chord mode is shown beside it.
5. Scoring matches the earlier tests: Allowed, Found and the always-one-chord baseline. Sections listing more than four roots, or none, aren't counted.
6. Chord roots are entered as the pitches heard, using only the capo or tuning the tab states. No pitch offset is chosen from the scores.
7. The Helmet, Pantera and other earlier results stay in the case study, labelled as the harder test.

## Added after the first results

Some songs had little of their running time counted, because rule 5 skips sections listing more than four roots. After seeing the results, an all-sections score was added using `--all-sections`. It runs on all eight songs and sits beside the original results without replacing them. Allowed is easier to pass in crowded sections, so Found is the better guide there.
