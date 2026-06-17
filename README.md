# FC Mobile World Cup Reward Watcher

## What is this?

During the 2026 World Cup, EA Sports FC Mobile gives out a free "World's Game"
halftime gift during every match — but only if you open the app and tap
**CLAIM REWARD** while the gift is available. The gift is only claimable for a
short window during each match, and if you miss it, it's gone.

This tool watches the World Cup match schedule for you. When a gift becomes
available, it automatically:

1. Opens BlueStacks (the Android emulator) and FC Mobile, if they aren't
   already open.
2. Closes any pop-ups in the way.
3. Taps **CLAIM REWARD**, then opens the gift pack that appears, then taps
   **CONTINUE** to reveal the prize — taking a screenshot of each prize along
   the way.
4. If more than one reward is waiting (not just this match's gift, but
   anything else queued up), it keeps going until everything is claimed.
5. Closes FC Mobile and BlueStacks again.

If you're already using FC Mobile yourself when a gift becomes available, the
watcher notices and leaves you alone — it won't interrupt anything you're
doing.

## How to start it

On your Desktop there's an icon called **"FC Mobile Reward Watcher"**.

1. Double-click it.
2. A black window will pop up and start printing messages like
   `loaded 88 upcoming/scheduled matches`. That means it's working.
3. **Leave that window open.** It needs to keep running in the background to
   catch each match's reward window. You can minimize it, but don't close it.

That's it — you don't need to do anything else. It will sit quietly until the
next match's reward becomes available, then spring into action on its own.

## How to stop it

Double-click the same **"FC Mobile Reward Watcher"** icon again. It will
detect that it's already running and shut itself down.

(You can also just close the black window directly — either way works.)

## How do I know if it's working / what did it claim?

- **`rewards` folder** (in this project folder) — every time a reward is
  successfully claimed, a screenshot of the prize is saved here, named with
  the date/time and the two teams that played, e.g.
  `20260617_015532_France_vs_Senegal.png`.
- **`AUDIT_LOG.md`** (in this project folder) — a plain text diary of
  everything the watcher has done, with timestamps, such as when a match
  window opened, when it claimed a reward, or if something went wrong.

## A few things to know

- **Your PC needs to be on** for this to work — if you shut down or restart,
  just double-click the desktop icon again afterward to start the watcher.
- **It won't interfere if you're playing FC Mobile yourself.** If the app is
  already open when a reward window starts, the watcher just waits and checks
  back again a little later in case you close it.
- It only acts on **matches that are still upcoming**. Matches that have
  already been played are skipped automatically.
- If FIFA changes/confirms a fixture (for example, knockout-stage matchups
  that were "TBD"), the schedule may need to be refreshed — ask whoever set
  this up to re-run the schedule update.
