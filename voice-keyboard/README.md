# voice-keyboard

Hold a key, talk, release: the words are typed into whatever window has focus.
Runs locally with faster-whisper on the GPU (CPU fallback). X11 only.

## Always-on mode (no keys while talking)

```bash
./listen.sh
```

1. Wait for "Press Enter here to start listening" (about 30 s).
2. Press Enter in that terminal. It says LISTENING.
3. Click into any window and talk. Each sentence is typed when you pause (0.8 s; change with `--pause 1.2`).
4. Press Enter in the terminal again, or tap Right Ctrl from anywhere, to pause and resume.

It measures room noise for 1 s at startup, so stay quiet then.

## Push-to-talk mode

```bash
./run.sh                      # hold Right Ctrl to talk
./run.sh --mode toggle --key f9   # tap F9 to start, tap again to stop
./run.sh --model distil-large-v3  # more accurate, more VRAM
```

Startup takes about 30 s (model load and CUDA init). After that, an 11 s clip
transcribes in about 0.2 s with `small.en` on the RTX A4000.

## Spoken commands

Say these as the whole utterance:

| Say | Does |
|---|---|
| "new line" / "enter" | Enter |
| "tab" | Tab |
| "scratch that" | Delete the last typed chunk |
| "stop listening" | Quit |

"new line" inside a sentence becomes a line break.

## Vocabulary

Pass jargon with `--prompt "ROS, SLAM, LiDAR, Livox, FAST-LIO"` so Whisper
spells it right.

## Test

```bash
.venv/bin/python test_transcribe.py some_clip.wav
```

## Autostart

Copy the line below into `~/.config/autostart/voicekey.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=voicekey
Exec=/home/rjia/file_exchange_port/my-prototypes/voice-keyboard/run.sh
```

## Limits and next steps

- Typing uses XTEST; it does not work on Wayland.
- Right Ctrl is still seen by apps while held. Pick an unused key
  (`scroll_lock`, `f9`, `pause`) if that causes trouble.
- Next: an optional LLM pass to clean punctuation, format code, or run
  commands like "open a terminal"; streaming partial text while speaking.
