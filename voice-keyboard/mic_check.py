"""Record from the default mic, show the input level, and transcribe it.

Usage: .venv/bin/python mic_check.py [seconds] [model]
"""
import sys, time
import numpy as np
import sounddevice as sd
import voicekey

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6
model, dev = voicekey.load_model(sys.argv[2] if len(sys.argv) > 2 else "small.en", "auto")
print(f"input device: {sd.query_devices(kind='input')['name']}  (whisper on {dev})")
for i in (3, 2, 1):
    print(f"talk in {i}...", flush=True); time.sleep(1)
print(f">>> TALK NOW for {secs:.0f} s", flush=True)
chunks = []
def cb(data, *_):
    chunks.append(data.copy())
    rms = float(np.sqrt(np.mean(data ** 2)))
    print(f"\rlevel {'#' * min(50, int(rms * 500)):<50}", end="", flush=True)
with sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=cb):
    time.sleep(secs)
audio = np.concatenate(chunks)[:, 0]
peak, rms = float(np.abs(audio).max()), float(np.sqrt(np.mean(audio ** 2)))
print(f"\npeak={peak:.3f} rms={rms:.4f}  ({'OK' if peak > 0.05 else 'TOO QUIET - check mute/volume'})")
segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
print("heard:", " ".join(s.text.strip() for s in segs) or "(nothing)")
