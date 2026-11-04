"""Create static/demo.wav, an original generated song that is safe to share."""
import os
import sys

import librosa
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate

audio, _, _ = evaluate.render(["Am", "F", "C", "G"] * 3 + ["Dm7", "G7", "C", "E7"], bpm=96, melody=True)
audio = librosa.resample(audio, orig_sr=evaluate.SR, target_sr=22050)
target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "demo.wav")
sf.write(target, audio, 22050, subtype="PCM_16")
print(f"Wrote {target}: {len(audio) / 22050:.1f}s, {os.path.getsize(target) // 1024} KB")
