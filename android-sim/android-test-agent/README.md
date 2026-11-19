# android-test-agent

A for-fun random-command agent that pokes an Android emulator/device over adb:
random taps, double taps, long presses, swipes, flick bursts, key events and text.
Every action is logged to `runs/<timestamp>/actions.jsonl`, with a screenshot every N steps.

## Prereqs
- Emulator running: `../fifa-emulator.sh` (boots the `fifa_pixel` AVD on the NVIDIA GPU; SDK and AVD live in `../Android`)
- `adb` on PATH (open a new shell, or `source ~/.bashrc`)

## Usage
```bash
cd ~/file_exchange_port/tmp/android-test-agent
./random_agent.py --dry-run --steps 5                 # see what it would do
./random_agent.py --package com.android.settings --steps 30
./random_agent.py --package com.ea.gp.fifamobile --duration 600 --interval 0.4 --seed 42
```
`--package` keeps that app in the foreground (relaunches it if a random BACK leaves it) and
disables HOME / APP_SWITCH keys. `--seed` makes a run reproducible. Ctrl-C stops cleanly.

## Safety guard
The agent immediately presses BACK if it lands in Android's **Developer options** screen
(`AVOID_ACTIVITIES` in the script). A run in Settings once tapped "Revoke USB debugging
authorizations" there, which locked adb out of the emulator until the AVD was wiped
(`../fifa-emulator.sh fifa_pixel -wipe-data`). Add more activity names to that list as needed.
