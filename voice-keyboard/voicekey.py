#!/usr/bin/env python3
"""Voice keyboard: hold a hotkey, speak, release, and the text is typed into the focused window.

Runs fully local with faster-whisper (GPU if available, CPU fallback). X11 only (uses XTEST via pynput).

Spoken commands (whole utterance, case-insensitive):
  "new line" / "enter"     -> press Enter
  "scratch that"           -> delete the last typed chunk
  "tab"                    -> press Tab
  "stop listening"         -> quit the daemon
Inline: "... new line ..." inside a sentence becomes a newline.
"""

import argparse
import ctypes
import glob
import os
import queue
import re
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from pynput import keyboard

SAMPLE_RATE = 16000
MIN_SECONDS = 0.3


def preload_cuda_libs():
    """Load pip-installed cuBLAS/cuDNN so CTranslate2 finds them without LD_LIBRARY_PATH."""
    site = os.path.join(os.path.dirname(np.__file__), "..", "nvidia")
    for pattern in ("cublas/lib/libcublasLt.so*", "cublas/lib/libcublas.so*", "cudnn/lib/libcudnn*.so*"):
        for lib in sorted(glob.glob(os.path.join(site, pattern))):
            try:
                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def load_model(name, device):
    from faster_whisper import WhisperModel

    if device in ("auto", "cuda"):
        preload_cuda_libs()
        try:
            model = WhisperModel(name, device="cuda", compute_type="float16")
            # Force a tiny inference so missing CUDA libs fail here, not on first use.
            list(model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))[0])
            return model, "cuda"
        except Exception as e:  # noqa: BLE001
            if device == "cuda":
                raise
            print(f"[voicekey] CUDA unavailable ({e}); falling back to CPU", file=sys.stderr)
    return WhisperModel(name, device="cpu", compute_type="int8"), "cpu"


def notify(msg):
    subprocess.Popen(["notify-send", "-t", "1200", "-a", "voicekey", msg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Recorder:
    def __init__(self):
        self.chunks = []
        self.stream = None

    def start(self):
        self.chunks = []
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                     callback=lambda data, *_: self.chunks.append(data.copy()))
        self.stream.start()

    def stop(self):
        if self.stream is None:
            return np.zeros(0, dtype=np.float32)
        self.stream.stop()
        self.stream.close()
        self.stream = None
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.chunks)[:, 0]


COMMANDS = {
    "new line": "enter", "newline": "enter", "enter": "enter", "press enter": "enter",
    "tab": "tab", "press tab": "tab",
    "scratch that": "undo", "delete that": "undo",
    "stop listening": "quit",
}


def normalize_command(text):
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


class VoiceKeyboard:
    def __init__(self, model, hotkey, mode, language, prompt):
        self.model = model
        self.hotkey = hotkey
        self.mode = mode
        self.language = language
        self.prompt = prompt
        self.recorder = Recorder()
        self.kb = keyboard.Controller()
        self.recording = False
        self.last_typed = ""
        self.jobs = queue.Queue()
        self.quit = threading.Event()

    # --- hotkey handling -------------------------------------------------
    def on_press(self, key):
        if key != self.hotkey:
            return
        if self.mode == "hold" and not self.recording:
            self.begin()
        elif self.mode == "toggle":
            self.end() if self.recording else self.begin()

    def on_release(self, key):
        if key == self.hotkey and self.mode == "hold" and self.recording:
            self.end()

    def begin(self):
        self.recording = True
        self.recorder.start()
        print("[voicekey] listening...", flush=True)

    def end(self):
        self.recording = False
        audio = self.recorder.stop()
        if len(audio) < SAMPLE_RATE * MIN_SECONDS:
            return
        self.jobs.put(audio)

    # --- transcription + output -----------------------------------------
    def worker(self):
        while not self.quit.is_set():
            try:
                audio = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            t0 = time.time()
            segments, _ = self.model.transcribe(
                audio, language=self.language, beam_size=1, vad_filter=True,
                initial_prompt=self.prompt, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments).strip()
            dt = time.time() - t0
            print(f"[voicekey] ({dt:.2f}s, {len(audio)/SAMPLE_RATE:.1f}s audio) {text!r}", flush=True)
            if text:
                self.emit(text)

    def emit(self, text):
        cmd = COMMANDS.get(normalize_command(text))
        if cmd == "enter":
            self.tap(keyboard.Key.enter)
        elif cmd == "tab":
            self.tap(keyboard.Key.tab)
        elif cmd == "undo":
            for _ in range(len(self.last_typed)):
                self.tap(keyboard.Key.backspace)
            self.last_typed = ""
        elif cmd == "quit":
            notify("voicekey stopped")
            self.quit.set()
        else:
            out = re.sub(r"\s*\bnew ?line\b[.,]?\s*", "\n", text, flags=re.IGNORECASE)
            out = out + " " if not out.endswith("\n") else out
            self.kb.type(out)
            self.last_typed = out

    def tap(self, key):
        self.kb.press(key)
        self.kb.release(key)

    def run(self):
        threading.Thread(target=self.worker, daemon=True).start()
        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            while not self.quit.is_set() and listener.running:
                time.sleep(0.1)


HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", ""}


class ContinuousListener(VoiceKeyboard):
    """Always-on mode: cuts speech into utterances at pauses and types each one.

    Enter in the launching terminal, or tapping the hotkey anywhere, toggles listening on/off.
    """

    BLOCK = 480  # 30 ms at 16 kHz

    def __init__(self, *a, silence_s=0.8, max_s=20.0, **kw):
        super().__init__(*a, **kw)
        self.active = threading.Event()
        self.silence_blocks = int(silence_s * SAMPLE_RATE / self.BLOCK)
        self.max_blocks = int(max_s * SAMPLE_RATE / self.BLOCK)
        self.threshold = 0.01

    def calibrate(self):
        print("[voicekey] measuring room noise for 1 s, stay quiet...", flush=True)
        audio = sd.rec(SAMPLE_RATE, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        sd.wait()
        blocks = audio[: len(audio) // self.BLOCK * self.BLOCK, 0].reshape(-1, self.BLOCK)
        noise = float(np.percentile(np.sqrt((blocks ** 2).mean(axis=1)), 90))
        self.threshold = max(0.01, 2.5 * noise)
        print(f"[voicekey] noise={noise:.4f}, speech threshold={self.threshold:.4f}", flush=True)

    def toggle(self):
        if self.active.is_set():
            self.active.clear()
            print("[voicekey] PAUSED. Press Enter here or tap the hotkey to resume.", flush=True)
            notify("voicekey paused")
        else:
            self.active.set()
            print("[voicekey] LISTENING. Click into any window and talk.", flush=True)
            notify("voicekey listening")

    def on_press(self, key):
        if key == self.hotkey:
            self.toggle()

    def on_release(self, key):
        pass

    def segmenter(self):
        """Group 30 ms blocks into utterances: speech starts above threshold, ends after a pause."""
        blocks = queue.Queue()
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=self.BLOCK,
                                callback=lambda data, *_: blocks.put(data[:, 0].copy()))
        stream.start()
        preroll, speech, quiet = [], [], 0
        while not self.quit.is_set():
            try:
                b = blocks.get(timeout=0.2)
            except queue.Empty:
                continue
            if not self.active.is_set():
                preroll, speech, quiet = [], [], 0
                continue
            loud = np.sqrt(np.mean(b ** 2)) > self.threshold
            if not speech:
                preroll = (preroll + [b])[-10:]  # keep 300 ms before speech starts
                if loud:
                    speech, quiet = preroll[:], 0
                continue
            speech.append(b)
            quiet = 0 if loud else quiet + 1
            if quiet >= self.silence_blocks or len(speech) >= self.max_blocks:
                audio = np.concatenate(speech)
                if len(audio) >= SAMPLE_RATE * MIN_SECONDS:
                    self.jobs.put(audio)
                preroll, speech, quiet = [], [], 0
        stream.stop()

    def emit(self, text):
        if normalize_command(text) in HALLUCINATIONS:
            return  # Whisper often invents these from noise
        super().emit(text)

    def run(self):
        self.calibrate()
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.segmenter, daemon=True).start()
        threading.Thread(target=self.stdin_toggle, daemon=True).start()
        print("[voicekey] Press Enter here to start listening.", flush=True)
        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            while not self.quit.is_set() and listener.running:
                time.sleep(0.1)

    def stdin_toggle(self):
        for _ in sys.stdin:
            self.toggle()


def parse_key(name):
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        return keyboard.KeyCode.from_char(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="small.en",
                    help="faster-whisper model: tiny.en, base.en, small.en, medium.en, large-v3, distil-large-v3")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--key", default="ctrl_r", help="pynput Key name (ctrl_r, alt_r, f9, scroll_lock, ...)")
    ap.add_argument("--mode", default="hold", choices=["hold", "toggle", "listen"],
                    help="hold-to-talk, press-to-toggle, or listen (always on, Enter toggles, types at pauses)")
    ap.add_argument("--pause", type=float, default=0.8, help="listen mode: seconds of silence that end a sentence")
    ap.add_argument("--language", default="en")
    ap.add_argument("--prompt", default="ROS, SLAM, LiDAR, IMU, Python, C++, CUDA, git, Docker.",
                    help="vocabulary hint passed to Whisper as initial_prompt")
    args = ap.parse_args()

    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print("[voicekey] warning: Wayland session; typing into other windows may not work", file=sys.stderr)

    print(f"[voicekey] loading {args.model}...", flush=True)
    model, device = load_model(args.model, args.device)
    print(f"[voicekey] ready on {device}. {args.mode} mode, hotkey <{args.key}>. Say 'stop listening' or Ctrl+C to quit.",
          flush=True)
    notify(f"voicekey ready ({device}) - {args.mode} {args.key}")
    try:
        if args.mode == "listen":
            ContinuousListener(model, parse_key(args.key), args.mode, args.language, args.prompt,
                               silence_s=args.pause).run()
        else:
            VoiceKeyboard(model, parse_key(args.key), args.mode, args.language, args.prompt).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
