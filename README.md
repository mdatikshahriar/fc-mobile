# FC Mobile World Cup 2026 Reward Watcher

Automatically claims the free "World's Game" halftime gift in FC Mobile during
every 2026 World Cup match — so you never miss a reward even if you're asleep
or away.

During each match EA gives a free gift that's only claimable for a 45-minute
window around halftime. This bot watches the schedule, launches BlueStacks and
FC Mobile at the right moment, taps through the full reward chain, screenshots
what you won, then closes everything again.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Windows 10 / 11** | macOS/Linux not supported — relies on BlueStacks for Windows and `.bat` scripts |
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) — tick "Add to PATH" during install |
| **BlueStacks 5** | [bluestacks.com](https://www.bluestacks.com/) — install and sign in with your Google account |
| **FC Mobile** | Install from the Play Store inside BlueStacks and log in to your EA account |
| **Android SDK Platform Tools** | Provides `adb.exe` — download the zip from [developer.android.com/tools/releases/platform-tools](https://developer.android.com/tools/releases/platform-tools), extract anywhere |

---

## One-time setup

### 1. Clone the repo

```
git clone https://github.com/mdatikshahriar/fc-mobile.git
cd fc-mobile
```

### 2. Install Python dependencies

```
pip install -r requirements.txt
```

### 3. Set BlueStacks resolution to 1600 × 900

The button templates are captured at exactly this resolution — any other size
will break detection.

In BlueStacks: **Settings → Display → Resolution → 1600 × 900**, then restart
BlueStacks.

### 4. Enable ADB in BlueStacks

In BlueStacks: **Settings → Advanced → Android Debug Bridge → Enable**.

Note the ADB port shown there (default is `5555`).

### 5. Find your BlueStacks instance name

Open BlueStacks Multi-Instance Manager — the instance name is shown in the
title bar of each instance (e.g. `Pie64`, `Nougat64`, etc.).

### 6. Edit `automation/adb_controller.py`

Update the three constants at the top of the file to match your machine:

```python
ADB = r"C:\path\to\your\platform-tools\adb.exe"   # full path to adb.exe
BLUESTACKS_EXE = r"C:\Program Files\BlueStacks_nxt\HD-Player.exe"  # usually unchanged
BLUESTACKS_INSTANCE = "Pie64"                       # your instance name from step 5
```

The `DEVICE` value (`127.0.0.1:5555`) only needs changing if your BlueStacks
ADB port differs from 5555.

### 7. Verify ADB works

With BlueStacks running, open a terminal and run:

```
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 get-state
```

You should see `device`. If you see `offline` or an error, double-check that
ADB is enabled in BlueStacks settings (step 4).

---

## Running the watcher

Double-click **`automation/watcher.bat`**.

A console window opens titled "FC Mobile Reward Watcher" and prints something
like:

```
loaded 88 upcoming/scheduled matches, 0 already claimed
```

**Leave that window open.** It sleeps quietly until the next match's reward
window opens, then springs into action automatically. You can minimize it, but
closing it stops the watcher.

Double-clicking `watcher.bat` again while it's already running will stop it.

### What happens during a claim

1. BlueStacks and FC Mobile are launched automatically.
2. Any in-app pop-ups blocking the screen are dismissed.
3. The **CLAIM REWARD** button is tapped.
4. The gift pack is opened (**TAP TO OPEN**).
5. All items are revealed at once (**REVEAL ALL**) — one screenshot is saved.
6. The reward screen is dismissed (**CONTINUE**).
7. If more rewards are queued (from other in-game events), the loop continues
   until everything is claimed.
8. FC Mobile and BlueStacks are closed.

### If you're using FC Mobile yourself

The watcher checks whether FC Mobile is already running before doing anything.
If it is, it assumes you're playing and leaves everything alone — it retries
automatically a little later in the same window.

### Where to see results

- **`rewards/`** — one screenshot per match, named by date, time, and teams
  (e.g. `20260617_045721_Iraq_vs_Norway.png`).
- **`AUDIT_LOG.md`** — full timestamped log of every action taken.

---

## Keeping the schedule up to date

The fixture list (`worldcup_2026_schedule.json`) is included. Knockout-stage
matchups start as "TBD" on the FIFA site and are confirmed as the tournament
progresses — you'll need to refresh the file when that happens.

The fixtures page is JavaScript-rendered, so it can't be fetched directly.
Instead:

1. Open the FIFA World Cup fixtures page in your browser and apply the
   **BDT** timezone filter.
2. Save the page: **Ctrl + S → Webpage, Complete**.
3. Run:

```
python scripts/parse_fixtures.py "path\to\saved fixtures.html"
```

This overwrites `worldcup_2026_schedule.json` with the updated data.

---

## Timing

| Event | Offset from kickoff |
|---|---|
| Reward actually unlocks | + 45 min |
| Watcher starts acting | + 55 min (10 min safety buffer) |
| Reward window closes | + 90 min |

The watcher has 35 minutes to claim each reward. If it misses the window for
any reason it logs the failure and moves on — it will not retry a closed
window.

---

## Troubleshooting

**ADB can't connect**
- Make sure BlueStacks is fully open (not still loading).
- Confirm ADB is enabled in BlueStacks Settings → Advanced.
- Check the port in BlueStacks settings matches `DEVICE` in `adb_controller.py`.

**Nothing is being detected / claim silently times out**
- Confirm your BlueStacks display is set to exactly 1600 × 900.
- Check `automation/debug/current.png` to see what the screen looks like
  during a poll.

**The watcher stops after a restart**
- It only keeps running as long as the console window is open. Re-launch by
  double-clicking `watcher.bat` after any restart.

**Claimed set seems wrong / need a clean slate**
- Delete or empty `automation/state.json` — it will be recreated on next
  launch.

---

For a deeper technical reference (architecture, detection pipeline, known
gotchas), see [TECHNICAL.md](TECHNICAL.md).
