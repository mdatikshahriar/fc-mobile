# Technical Notes (for future dev/agent sessions)

This is the engineering-facing companion to [README.md](README.md). It exists
so a future session (human or AI) doesn't have to re-derive context that was
expensive to gather the first time.

## Architecture

```
schedule.py        -> loads worldcup_2026_schedule.json, computes per-match
                       claim windows (MatchWindow: kickoff/claim_start/claim_end)
run.py              -> long-running loop: sleeps until the next claim_start,
                       calls claim_reward() when a window is active, persists
                       outcomes to state.json and logs to AUDIT_LOG.md
claim_reward.py     -> single-attempt claim logic for one match window:
                       ensure BlueStacks is running -> ensure FC Mobile is
                       running -> poll screenshots, reacting to whatever's on
                       screen (dismiss popup / tap CLAIM REWARD / tap TAP TO
                       OPEN / tap CONTINUE) in a loop until the reward queue
                       runs dry -> close both apps. See "The reward chain"
                       section below for the full sequence.
adb_controller.py   -> the only module that shells out to adb.exe or controls
                       BlueStacks/Windows processes directly
template_matcher.py -> OpenCV template-matching helpers (exact + multi-scale)
watcher.bat          -> double-click toggle (start if not running, stop if
                       running) wrapping `python run.py`, for non-technical use
```

## File map

- `automation/adb_controller.py` — thin ADB wrapper + BlueStacks process control.
- `automation/template_matcher.py` — `find()` (exact scale), `find_multiscale()`
  (tries the template resized 0.6x-1.4x), `find_best()`.
- `automation/schedule.py` — schedule loading + claim window math.
- `automation/claim_reward.py` — the actual claim attempt for one match.
- `automation/run.py` — orchestration loop, `state.json`, `AUDIT_LOG.md`.
- `automation/watcher.bat` — start/stop toggle for the desktop shortcut.
- `automation/templates/*.png` — cropped reference images used for matching,
  all captured at the live device's exact resolution (1600x900): `popup_close_x.png`,
  `claim_reward_button.png`, `tap_to_open_button.png`, `continue_button.png`.
- `scripts/parse_fixtures.py` — regenerates `worldcup_2026_schedule.json` from
  a browser-saved copy of the FIFA fixtures page (it's a JS SPA — can't be
  fetched directly, must be saved via Ctrl+S "Webpage, Complete" with the BDT
  country filter applied first).
- `worldcup_2026_schedule.json` — source of truth for the schedule. Rows with
  `time_bdt: null` are matches already played (FIFA shows a score instead of
  a kickoff time for those) and are skipped by `load_match_windows()`.
- `rewards/` — timestamped screenshots of successfully claimed gifts, one per
  reward in the chain. Scratch output, intentionally wiped during cleanup
  whenever its contents don't represent a confirmed real claim.
- `automation/debug/` — diagnostic screenshots from poll iterations that
  didn't recognize anything on screen, plus a few fixed-name snapshots
  (`current.png`, `settle.png`, `verify.png`) overwritten every attempt. Pure
  scratch space — safe to wipe any time, regenerated automatically.
- `AUDIT_LOG.md` — human-readable, timestamped action log (same content the
  console prints, also written to disk via `run.py`'s `log()`). Has been
  wiped back to just the header more than once during development whenever
  it recorded a claim that turned out to be a false positive — don't treat
  it as historical truth predating its last reset.
- `automation/state.json` — set of match-window keys already resolved
  (claimed, or given up on after the window closed). Prevents retry-forever
  across restarts. **Not reset automatically** — delete it manually for a
  clean slate.

## Environment specifics (re-verify if anything stops working)

- ADB binary: `C:\Users\mdati\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- Device address: `127.0.0.1:5555` — BlueStacks instance name `Pie64`,
  `adb_port="5555"` set in `C:\ProgramData\BlueStacks_nxt\bluestacks.conf`.
- FC Mobile package: `com.ea.gp.fifamobile`.
- Device screen resolution: **1600x900** (`adb shell wm size`). Any new
  template must either be cropped at exactly this resolution, or matched via
  `find_multiscale()` if its source image was a different resolution.
- BlueStacks launch command: `"C:\Program Files\BlueStacks_nxt\HD-Player.exe" --instance Pie64`
  (confirmed from the real "BlueStacks 5" Start Menu shortcut).
- BlueStacks ADB access is **off by default** and must be enabled once by a
  human via BlueStacks Settings → Advanced → "Android Debug Bridge (ADB)".
  Don't try to flip `bst.enable_adb_access` directly in the conf file while
  BlueStacks is running — edit through the UI instead.

## Claim window timing — why two different numbers

- The in-game reward actually unlocks at **kickoff + 45 min** and stays
  claimable until **kickoff + 90 min** (confirmed via in-game screenshots).
- The watcher deliberately waits until **kickoff + 55 min** before acting
  (`CLAIM_OPENS_AFTER` in `schedule.py`) — a 10-minute safety buffer added at
  the user's explicit request. This is a buffer on when *we* act, not a
  change to when the reward is actually available. `claim_end` (kickoff + 90)
  is untouched, so the effective action window is 35 minutes, not 45.

## The reward chain

Claiming is not a single tap. Confirmed live (screenshots in commit history /
dev session, not kept in `rewards/`):

1. **CLAIM REWARD** button (bright yellow-green pill) — tapping it reveals a
   "Gift Package" screen (FC Mobile branded pack art, "TAP TO OPEN" below it).
2. **TAP TO OPEN** button (same yellow-green pill style) — tapping it and
   waiting ~20s reveals the actual prize (e.g. "ITEM PACK / Training Transfer
   Point x1,000").
3. **CONTINUE** button (blue pill, bottom-right corner of the reveal screen)
   — dismisses the reveal. If another reward was already queued (e.g. from an
   unrelated in-game event, not just the World Cup gift), the next one's
   Gift Package / TAP TO OPEN screen appears right after.
4. The loop in `claim_reward.py` re-screenshots and re-reacts (close popup /
   CLAIM REWARD / TAP TO OPEN / CONTINUE) each iteration until nothing new
   shows up for `CONSECUTIVE_CLEAR_POLLS` (2) polls in a row, then closes
   both apps. This is what lets it drain an arbitrary number of queued
   rewards, not just the one it came looking for.

`templates/continue_button.png` was cropped directly from a live 1600x900
screenshot the user captured manually after tapping through the chain by
hand — confirmed at 0.98 confidence via offline `find()` against that
screenshot, but **the CONTINUE branch in the actual poll loop has not yet
fired during a real live run** (see Outstanding section).

## Wait-timing policy

Every wait that follows an actual action (a tap) is a flat **20 seconds** —
this was an explicit user directive after a false-positive claim turned out
to be caused by tapping/checking too fast, before the UI had settled:
`BUTTON_SETTLE_WAIT_SECONDS`, `TAP_VERIFY_WAIT_SECONDS`,
`REWARD_REVEAL_WAIT_SECONDS`, `POST_CLAIM_OPEN_WAIT_SECONDS`,
`POST_CONTINUE_WAIT_SECONDS`, `POPUP_CLOSE_WAIT_SECONDS` are all `20` in
`claim_reward.py`. Two waits are intentionally *not* 20s:

- `POST_CLAIM_CLOSE_DELAY_SECONDS` (60) — the final pause before force-closing
  both apps once the reward queue is empty. Bigger than 20 on purpose, left
  alone per "unless I mentioned a bigger wait time previously."
- `POLL_INTERVAL_SECONDS` (5) and the BlueStacks-boot retry sleep (3, inside
  `_ensure_bluestacks_running`) — these are idle "check again" cadences while
  *waiting for something to appear*, not a pause after performing an action,
  so the 20s policy doesn't apply to them.

If a future change adds another post-tap wait, default it to 20s unless
told otherwise.

## Behavioral constraints — do not regress these

1. **Never interrupt the user.** If FC Mobile is already running when a claim
   window opens, `claim_reward()` does nothing at all (no force-stop, no tap)
   and returns `None`. `run.py` must treat `None` as "skip, don't mark
   claimed" so it retries later in the same window — never treat it as a
   failure to give up on.
2. **No menu navigation.** The reward dialog appears as a self-contained
   popup once the app is open during the active window — there is no "GO
   NOW" banner involved. (An earlier `go_now_button.png` template was built
   and then deleted after this was clarified — don't reintroduce it.)
3. Only launch/relaunch the app when it was confirmed **not** already
   running.

## Detection pipeline details

All four templates are now cropped at the live device's exact resolution
(1600x900) from real on-device screenshots, matched with exact-scale `find()`
(no `find_multiscale()` needed anymore — that helper still exists in
`template_matcher.py` for the case of a resolution-mismatched template, but
nothing currently uses it):

- `popup_close_x.png` — threshold 0.8. Verified at ~0.9998 confidence live.
- `claim_reward_button.png` — threshold 0.85. **Confirmed live**, multiple
  times, at 0.98-1.00 confidence. The original version of this template (cropped
  from an off-resolution reference JPG, matched via `find_multiscale()`) caused
  a false-positive claim early on — the button was misidentified and the tap
  landed in the wrong place, but the code still concluded "button gone, must
  be claimed" because of a UI animation that briefly hid the real button. It
  was replaced with a crop taken directly from a live screenshot, and the
  settle/verify steps below were added as a second layer of defense.
- `tap_to_open_button.png` — threshold 0.85. Confirmed present on the real
  "Gift Package" screen (captured live, see "The reward chain" above), but
  the poll loop's `open_button` branch tapping it has not yet been observed
  firing in an actual live run.
- `continue_button.png` — threshold 0.8. Confirmed via offline `find()`
  against a live screenshot at 0.98 confidence; not yet exercised inside an
  actual live run (see Outstanding section).

Two defenses against false positives, both born from the incident above:

- **Settle-before-tap**: when `claim_reward_button` is first detected, wait
  `BUTTON_SETTLE_WAIT_SECONDS` (20s) and re-screenshot/re-match before
  actually tapping, in case the UI is still mid-animation.
- **Tap-verify**: after tapping, wait `TAP_VERIFY_WAIT_SECONDS` (20s),
  re-screenshot, and check the button is actually gone before declaring the
  claim successful. If it's still there, the tap is treated as not having
  registered and the loop retries instead of marking it claimed.

## Known gotchas hit while building this

- `pidof <pkg>` exits non-zero when no process is found — that's a normal
  "not running" result, not an adb error. `is_fc_mobile_running()` calls
  `subprocess.run` directly rather than the shared `_run()` helper (which
  raises on any non-zero exit) for this reason.
- Git Bash (MSYS) silently mangles arguments that look like Unix paths (e.g.
  `/c`) when shelling out to native Windows commands — `cmd /c "..."` ends up
  opening an interactive session that immediately exits instead of running
  the command. Use `MSYS_NO_PATHCONV=1` or double-slash (`tasklist //FI ...`)
  when testing Windows-native commands from this shell.
- Reference screenshots supplied during development came in at least three
  different resolutions (1600x900, 901x507, 1438x753). Never assume a crop
  from an arbitrary screenshot is pixel-compatible with the live device —
  check resolution first, use `find_multiscale()` if in doubt.
- Parsing the saved FIFA HTML must read the file as raw bytes (`open(path,
  "rb")`) and let BeautifulSoup/lxml detect encoding, not pre-decode as text
  — avoids mangling non-ASCII team names (e.g. "Türkiye"). That said, one
  apparent case of this was actually just a Bash/Windows console codepage
  display artifact, not real file corruption — verify with raw byte
  inspection before assuming a real bug.
- Python caches imported modules per-process — editing any `automation/*.py`
  file requires actually restarting the watcher process. There is no
  hot-reload.
- `adb get-state == device` only proves the ADB transport is up, **not** that
  Android has finished booting. Right after a cold BlueStacks launch, the
  package/activity manager can still be initializing, which makes app-launch
  commands fail even though `get-state` already says `device`. Fixed by
  `_boot_completed()` in `adb_controller.py`, which additionally checks
  `adb shell getprop sys.boot_completed == "1"` before `connect()` returns
  success.
- Stopping a background task (e.g. a Claude Code `run_in_background` shell)
  kills its entire process tree, including any GUI app spawned from within it
  via `subprocess.Popen()`. Stopping a watcher task that itself launched
  BlueStacks via `adb.launch_bluestacks()` will also kill BlueStacks/
  `HD-Player.exe` — don't be surprised by that, it's expected, not a bug.
- `adb_controller.screenshot(path)` calls `path.write_bytes(...)`, so it
  requires a `pathlib.Path`, not a plain string — passing a string raises
  `AttributeError: 'str' object has no attribute 'write_bytes'`.

## Restarting after a code change

- Running via a Claude Code background task: stop the old task, then start a
  new background `python run.py` from `automation/`.
- Running via the desktop icon: double-click to stop, double-click again to
  start.
- `state.json` persists across restarts on purpose — delete it manually if
  you need a clean slate (e.g. after testing).

## Regenerating the schedule

The fixtures page is a JS-rendered SPA, so it can't be fetched directly.
Save it from a browser (Ctrl+S, "Webpage, Complete") with the BDT country
filter applied, then run:

```
python scripts/parse_fixtures.py "path/to/saved fixtures.html"
```

Re-run this once knockout-stage matchups (TBD as of this writing) are
confirmed by FIFA.

## Outstanding / not yet fully verified

- The CLAIM REWARD tap itself is confirmed live (multiple times, including
  the settle/verify defenses). What's **not** yet confirmed in a real live
  run: the `open_button` (TAP TO OPEN) branch and the `continue_button`
  branch actually firing inside `claim_reward.py`'s poll loop — both
  templates are confirmed accurate offline against real screenshots, but the
  code paths that react to them have only run against synthetic/offline
  checks so far, not a live in-game sequence end to end.
- The multi-reward loop (CONTINUE → another Gift Package appears →
  drain until `CONSECUTIVE_CLEAR_POLLS` quiet polls) has never been exercised
  live at all — there's no live evidence yet of more than one reward being
  queued at once.
- Next live test should specifically watch whether the loop gets all the way
  through CLAIM REWARD → TAP TO OPEN → CONTINUE → (close apps) unattended,
  during the next match's claim window.
