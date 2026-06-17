"""Long-running loop: sleeps until each match's claim window opens, then
attempts to claim the World's Game reward. Leave this running in a terminal
for the duration of the tournament.

Usage:
    python run.py
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from claim_reward import claim_reward
from schedule import active_window, load_match_windows, next_claim_start

STATE_PATH = Path(__file__).resolve().parent / "state.json"
AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "AUDIT_LOG.md"
IDLE_POLL_SECONDS = 60


def _load_state():
    if STATE_PATH.exists():
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    return set()


def _save_state(claimed_keys):
    STATE_PATH.write_text(json.dumps(sorted(claimed_keys), indent=2), encoding="utf-8")


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    if not AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.write_text("# FC Mobile Reward Automation - Audit Log\n\n", encoding="utf-8")
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"- {line}\n")


def main():
    windows = load_match_windows()
    claimed = _load_state()
    log(f"loaded {len(windows)} upcoming/scheduled matches, {len(claimed)} already claimed")

    while True:
        now = datetime.now()
        w = active_window(windows, now)

        if w and w.key not in claimed:
            log(f"claim window OPEN: {w.home} vs {w.away} (kickoff {w.kickoff}, ends {w.claim_end})")
            try:
                success = claim_reward(deadline=w.claim_end, log=log, match_label=f"{w.home}_vs_{w.away}")
            except Exception as e:
                log(f"ERROR during claim attempt for {w.home} vs {w.away}: {e!r} - will retry shortly")
                time.sleep(min(IDLE_POLL_SECONDS, max((w.claim_end - datetime.now()).total_seconds(), 1)))
                continue
            if success is True:
                claimed.add(w.key)
                _save_state(claimed)
                log(f"marked claimed: {w.home} vs {w.away}")
            elif success is None:
                log(f"app already open for {w.home} vs {w.away}, will check again shortly")
                time.sleep(min(IDLE_POLL_SECONDS, max((w.claim_end - datetime.now()).total_seconds(), 1)))
            else:
                log(f"did not claim {w.home} vs {w.away} before window closed, will not retry")
                claimed.add(w.key)  # window is over either way, no point retrying
                _save_state(claimed)
            continue

        nxt = next_claim_start(windows, now)
        if nxt is None:
            log("no more upcoming matches in schedule, exiting")
            break

        sleep_for = min((nxt - now).total_seconds(), IDLE_POLL_SECONDS)
        sleep_for = max(sleep_for, 1)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
