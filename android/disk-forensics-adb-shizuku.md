# Android Disk Forensics from Termux — ADB, Shizuku, and the Force-Stop Experiment

*How to find out what is eating your phone's storage when the visible files don't add up — using Claude Code on Termux as your forensics cockpit. Battle-tested on a Samsung Galaxy S10 5G (Android 12) where a YouTube client bug silently hoarded ~50 GB of app-private downloads.*

## The problem shape

Your phone is full. You delete gigabytes — apps, media, a 3.7 GB file — and within hours it's full again. Samsung's "Analyze storage" shows media at ~32 GB but **"Other" at 195 GB**. Nothing in `/sdcard` explains it.

**Why deleting never helps:** Android scoped storage means app-private data (`/data/data/<app>`, `/sdcard/Android/data/<app>`) is invisible to Termux and to file managers. It all lands in "Other". If an app is leaking, it eats whatever headroom your deletions create.

## Step 1 — Rule out what you CAN see

From Termux:

```bash
# Your own visible universe
du -sh ~/* ~/.[a-z]* 2>/dev/null | sort -rh | head -20
du -sh /sdcard/* 2>/dev/null | sort -rh | head -20
du -sh /sdcard/Android/media/* 2>/dev/null | sort -rh   # WhatsApp etc. live here
```

Also check via the UI: Samsung Trash (My Files → Trash), Recycle bins in Gallery, and `/sdcard/Android/media/com.whatsapp/` (WhatsApp media is often 5–15 GB and IS visible).

If visible storage doesn't account for the mass → it's app-private data. Continue.

## Step 2 — Measure the leak rate

You can't attribute yet, but you can measure. Free-space delta over time:

```bash
a=$(df /data | tail -1 | awk '{print $4}'); echo "free: $((a/1024)) MB"
sleep 180
b=$(df /data | tail -1 | awk '{print $4}')
echo "free 3min later: $((b/1024)) MB, delta: $(( (a-b)/1024 )) MB"
```

Run this a few times, idle screen vs. active use. A consistent positive delta while the phone is idle = something is downloading or logging. (Our case: ~4 MB/3min baseline with 300 MB bursts ≈ 600 MB/day.)

## Step 3 — The ADB route (per-app attribution)

`dumpsys diskstats` attributes storage per app — the definitive answer. You need shell-level access, via wireless debugging.

### Enable wireless debugging

Settings → Developer options → Wireless debugging → ON. Tap it (the text, not just the toggle) → "Pair device with pairing code". Note: the **pairing port** and the **connection port are different**. Keep the pairing popup open (use split-screen with Termux — the code expires when the popup closes).

### Install adb in Termux

```bash
pkg install android-tools
# If adb crashes with "CANNOT LINK EXECUTABLE ... libprotobuf.so":
pkg install abseil-cpp libprotobuf
```

### KNOWN BUG: `adb pair` is broken in Termux android-tools

As of android-tools 35.0.2-8, `adb pair` fails with:

```
protocol fault (couldn't read status message)
```

on localhost AND LAN IP, regardless of kill-server / retry. Pairing from Termux to the same device does not work. Workarounds, in order of preference:

1. **Pair from a desktop** once (`adb pair <phone-ip>:<pair-port>`), then `adb connect <phone-ip>:<connect-port>` works fine *from Termux* afterwards.
2. **Shizuku** (Play Store) — pairs itself via wireless debugging, then grants shell access to other apps. Pair with **aShell** (F-Droid/Play) for a terminal UI, or `rish` for a Termux shell.
3. No Wi-Fi at all? Wireless debugging needs a Wi-Fi network (not mobile data). Skip to Step 4.

### Once connected

```bash
adb connect <phone-ip>:<connect-port>
adb shell dumpsys diskstats            # per-app data sizes — read the App Data section
adb shell logcat | grep -i download    # watch a suspect act live
```

## Step 4 — The force-stop experiment (no ADB needed)

This is what actually cracked our case, and it needs zero tooling: **an app can't write while it's dead.**

1. Hibernate everything non-essential (Greenify, or Settings → force stop each).
2. Run the Step-2 leak measurement → confirm the leak is still alive.
3. Force-stop your prime suspect (Settings → Apps → [app] → Force stop).
4. Re-run the measurement.

Leak drops to zero → convicted. Then read Settings → Apps → [app] → Storage for the body count.

**Our case:** ~4 MB/3min with 300 MB bursts → **0 MB/3min** after force-stopping YouTube. Its private data: 44 GB, grown to ~50 GB in 2 days — with Smart Downloads OFF and nothing listed in the Downloads screen. A client UI-desync bug (download actions executing without rendering; same regression window as widely-reported Play-Store complaints about Android-only comment loss, dead timestamps, dark-screen bugs).

**Cure for the app-hoard case:** App info → Storage → **Clear data** (not just cache) reclaims the hoard. Recheck the app's storage line a week later; if it regrows, uninstall updates and report.

## Reading Settings screenshots with Claude Code

Termux can't see Settings screens, but Claude Code can read your screenshots:

```bash
ls -t /sdcard/DCIM/Screenshots/ | head -3
```

Caveats learned the hard way:

- **Check dimensions first** (`file <screenshot>.jpg`). Images over ~2000 px on a side can poison the session — every later API call 400s, unrecoverably.
- Tall scroll-captures: split before reading:

```bash
python3 -c "
from PIL import Image
im = Image.open('shot.jpg'); w,h = im.size
for i in range((h+1799)//1800):
    im.crop((0,i*1800,w,min((i+1)*1800,h))).save(f'tile_{i}.jpg')"
```

- Read tiles **one per tool call**, never batched.

## Quick decision tree

```
Phone always full, deletions don't stick
├── du over ~, /sdcard, Android/media, Trash → found it? → done
├── "Other" is the mass → app-private data
│   ├── Leak-rate measurement (df deltas) → is it active?
│   ├── Have Wi-Fi + desktop or Shizuku? → dumpsys diskstats → attribution
│   └── No tooling? → force-stop experiment → conviction by elimination
└── Convicted app → Clear data → verify → recheck in 1 week
```
