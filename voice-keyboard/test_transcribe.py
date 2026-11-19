"""Smoke test: load the model (GPU if available) and transcribe an audio file.

Usage: .venv/bin/python test_transcribe.py clip.wav [model]
"""
import subprocess, sys, time
import numpy as np
import voicekey

path = sys.argv[1]
model, dev = voicekey.load_model(sys.argv[2] if len(sys.argv) > 2 else "small.en", "auto")
pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                     capture_output=True, check=True).stdout
audio = np.frombuffer(pcm, dtype=np.float32)
t0 = time.time()
segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
text = " ".join(s.text.strip() for s in segs)
print(f"device={dev} latency={time.time()-t0:.2f}s audio={len(audio)/16000:.1f}s\n{text}")
