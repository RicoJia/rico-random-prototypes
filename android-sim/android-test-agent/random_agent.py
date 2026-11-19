#!/usr/bin/env python3
"""Random-command test agent for an Android emulator/device via adb.

Fires random taps, swipes, long-presses, key events and text at the device,
optionally keeping one app in the foreground, and logs every action as JSONL
with periodic screenshots.

Examples:
  ./random_agent.py --steps 50                             # go wild anywhere
  ./random_agent.py --package com.ea.gp.fifamobile --duration 300
  ./random_agent.py --dry-run --steps 10 --seed 7          # just print commands
"""
import argparse, json, os, random, re, shutil, subprocess, sys, time
from datetime import datetime

KEYS = {
    # name: (keycode, weight)
    "BACK": (4, 6), "ENTER": (66, 2), "DPAD_UP": (19, 1), "DPAD_DOWN": (20, 1),
    "DPAD_LEFT": (21, 1), "DPAD_RIGHT": (22, 1), "DPAD_CENTER": (23, 1),
    "VOLUME_UP": (24, 1), "VOLUME_DOWN": (25, 1), "MENU": (82, 1),
    "APP_SWITCH": (187, 1), "HOME": (3, 1),
}
WORDS = ["goal", "messi", "hello", "1234", "test", "gg", "ronaldo", "ole", "lol", "zidane", "pass", "shoot"]
STATUS_BAR_PX = 120  # don't tap the status bar
# Screens the agent backs out of immediately: Developer options has "Revoke USB debugging
# authorizations", which kills adb access to the emulator (learned the hard way).
AVOID_ACTIVITIES = ["DevelopmentSettings", "DevelopmentSettingsDashboardActivity"]


class Adb:
    def __init__(self, serial=None, dry=False):
        self.adb = shutil.which("adb") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Android", "Sdk", "platform-tools", "adb")
        self.base = [self.adb] + (["-s", serial] if serial else [])
        self.dry = dry

    def run(self, *args, check=True, binary=False):
        cmd = self.base + list(args)
        read_only = args[:1] == ("get-state",) or args[:2] in (("shell", "wm"), ("shell", "dumpsys"))
        if self.dry and not read_only:
            print("DRY:", " ".join(cmd))
            return b"" if binary else ""
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        if check and r.returncode != 0:
            raise RuntimeError(f"adb failed: {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout if binary else r.stdout.decode(errors="replace")

    def shell(self, *args, **kw):
        return self.run("shell", *args, **kw)

    def screen_size(self):
        out = self.shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out or "")
        return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)

    def foreground_window(self):
        """Return 'package/Activity' of the focused window, or None."""
        out = self.shell("dumpsys", "window", "windows", check=False) or ""
        m = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+/[\w.$]+)", out)
        if m:
            return m.group(1)
        out = self.shell("dumpsys", "activity", "activities", check=False) or ""
        m = re.search(r"topResumedActivity=ActivityRecord\{\S+ \S+ ([\w.]+/[\w.$]+)", out)
        return m.group(1) if m else None

    def launch(self, package):
        self.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", check=False)

    def screenshot(self, path):
        data = self.run("exec-out", "screencap", "-p", binary=True)
        if data:
            with open(path, "wb") as f:
                f.write(data)


class RandomAgent:
    def __init__(self, adb, rng, width, height, package=None):
        self.adb, self.rng, self.w, self.h, self.package = adb, rng, width, height, package
        self.actions = [  # (name, weight)
            ("tap", 40), ("double_tap", 5), ("long_press", 8), ("swipe", 25),
            ("key", 12), ("text", 5), ("flick_sequence", 5),
        ]

    def rand_point(self):
        return self.rng.randint(0, self.w - 1), self.rng.randint(STATUS_BAR_PX, self.h - 1)

    def pick_action(self):
        names, weights = zip(*self.actions)
        return self.rng.choices(names, weights)[0]

    def do(self, name):
        s = self.adb.shell
        if name == "tap":
            x, y = self.rand_point(); s("input", "tap", str(x), str(y)); return {"x": x, "y": y}
        if name == "double_tap":
            x, y = self.rand_point()
            s("input", "tap", str(x), str(y)); time.sleep(0.08); s("input", "tap", str(x), str(y))
            return {"x": x, "y": y}
        if name == "long_press":
            x, y = self.rand_point(); ms = self.rng.randint(600, 1500)
            s("input", "swipe", str(x), str(y), str(x), str(y), str(ms)); return {"x": x, "y": y, "ms": ms}
        if name == "swipe":
            x1, y1 = self.rand_point(); x2, y2 = self.rand_point(); ms = self.rng.randint(80, 600)
            s("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))
            return {"from": [x1, y1], "to": [x2, y2], "ms": ms}
        if name == "flick_sequence":
            n = self.rng.randint(2, 5); pts = []
            for _ in range(n):
                x1, y1 = self.rand_point(); x2, y2 = self.rand_point()
                s("input", "swipe", str(x1), str(y1), str(x2), str(y2), "60"); pts.append([x1, y1, x2, y2])
                time.sleep(0.05)
            return {"flicks": pts}
        if name == "key":
            keys = {k: v for k, v in KEYS.items() if not (self.package and k in ("HOME", "APP_SWITCH"))}
            k = self.rng.choices(list(keys), [v[1] for v in keys.values()])[0]
            s("input", "keyevent", str(keys[k][0])); return {"key": k}
        if name == "text":
            t = " ".join(self.rng.choices(WORDS, k=self.rng.randint(1, 3)))
            s("input", "text", t.replace(" ", "%s")); return {"text": t}
        raise ValueError(name)

    def keep_in_app(self):
        """Relaunch the target app if we wandered off, and back out of screens that
        can break the test rig itself (Developer options can revoke adb authorization)."""
        fg_window = self.adb.foreground_window()
        if fg_window and any(bad in fg_window for bad in AVOID_ACTIVITIES):
            self.adb.shell("input", "keyevent", "4"); time.sleep(0.5)
            return {"backed_out_of": fg_window}
        if not self.package:
            return None
        fg = fg_window.split("/")[0] if fg_window else None
        if fg and fg != self.package:
            self.adb.launch(self.package); time.sleep(1.5)
            return {"relaunched_from": fg}
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--serial", help="adb device serial (default: the only connected device)")
    p.add_argument("--package", help="keep this app in the foreground, e.g. com.ea.gp.fifamobile")
    p.add_argument("--steps", type=int, default=100, help="number of random actions (default 100)")
    p.add_argument("--duration", type=float, help="stop after this many seconds instead of --steps")
    p.add_argument("--interval", type=float, default=0.7, help="mean seconds between actions (default 0.7)")
    p.add_argument("--seed", type=int, help="RNG seed for a reproducible run")
    p.add_argument("--screenshot-every", type=int, default=10, help="screenshot every N steps (0=off)")
    p.add_argument("--out", default="runs", help="output root directory (default ./runs)")
    p.add_argument("--dry-run", action="store_true", help="print adb commands instead of running them")
    a = p.parse_args()

    seed = a.seed if a.seed is not None else random.randrange(1 << 31)
    rng = random.Random(seed)
    adb = Adb(a.serial, dry=a.dry_run)
    run_dir = os.path.join(a.out, datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    if not a.dry_run and "device" not in adb.run("get-state", check=False):
        sys.exit("no device: start the emulator first (e.g. ~/bin/fifa-emulator.sh)")
    w, h = adb.screen_size() if not a.dry_run else (1080, 2400)
    agent = RandomAgent(adb, rng, w, h, a.package)
    if a.package and not a.dry_run:
        adb.launch(a.package); time.sleep(3)
    print(f"seed={seed} screen={w}x{h} package={a.package or '*'} log={run_dir}/actions.jsonl")

    start, step = time.time(), 0
    with open(os.path.join(run_dir, "actions.jsonl"), "a") as log:
        try:
            while True:
                if a.duration is not None and time.time() - start >= a.duration:
                    break
                if a.duration is None and step >= a.steps:
                    break
                step += 1
                rec = {"step": step, "t": round(time.time() - start, 2)}
                try:
                    guard = agent.keep_in_app()
                    if guard:
                        rec.update(guard)
                    name = agent.pick_action()
                    rec["action"] = name
                    rec.update(agent.do(name) or {})
                    if a.screenshot_every and step % a.screenshot_every == 0 and not a.dry_run:
                        shot = os.path.join(run_dir, f"step{step:04d}.png")
                        adb.screenshot(shot); rec["screenshot"] = shot
                except Exception as e:  # keep going on flaky adb
                    rec["error"] = str(e)
                print(json.dumps(rec)); log.write(json.dumps(rec) + "\n"); log.flush()
                time.sleep(max(0.05, rng.expovariate(1 / a.interval)))
        except KeyboardInterrupt:
            print("\nstopped by user")
    print(f"done: {step} steps in {time.time() - start:.1f}s -> {run_dir}")


if __name__ == "__main__":
    main()
