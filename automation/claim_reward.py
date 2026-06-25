"""Core claim loop: launch FC Mobile, then react to whatever popup appears
until the World's Game reward is claimed or the match window runs out.

The halftime gift dialog appears on its own as a popup once the app is open
during the active window - there's no menu navigation involved. Other unrelated
popups (news/promos) can appear first and just need to be dismissed via their
close (X) button.

Claiming is a chain, not a single tap: CLAIM REWARD reveals a "Gift Package"
that needs a second TAP TO OPEN to actually show the prize. After the prize
is revealed a CONTINUE button (bottom-right) dismisses that reveal screen,
and if other unclaimed rewards (from other events, not just this one) were
queued up, the next one appears right after. The loop keeps reacting
(dismiss / claim / open / continue) until nothing new shows up for a few
consecutive polls, rather than stopping after the first successful tap.
"""
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2

import adb_controller as adb
from template_matcher import find, load_gray

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEBUG_DIR = Path(__file__).resolve().parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)
REWARDS_DIR = Path(__file__).resolve().parent.parent / "rewards"
REWARDS_DIR.mkdir(exist_ok=True)

POPUP_CLOSE_THRESHOLD = 0.8
CLAIM_BUTTON_THRESHOLD = 0.85
OPEN_BUTTON_THRESHOLD = 0.85
CONTINUE_BUTTON_THRESHOLD = 0.8
REVEAL_ALL_BUTTON_THRESHOLD = 0.8
REVEAL_ALL_WAIT_SECONDS = 10  # animation after tapping REVEAL ALL before screenshot
POLL_INTERVAL_SECONDS = 5
APP_LAUNCH_WAIT_SECONDS = 20
BLUESTACKS_BOOT_WAIT_SECONDS = 120
REWARD_REVEAL_WAIT_SECONDS = 20
POST_CLAIM_CLOSE_DELAY_SECONDS = 60
TAP_VERIFY_WAIT_SECONDS = 20
BUTTON_SETTLE_WAIT_SECONDS = 20
POST_CLAIM_OPEN_WAIT_SECONDS = 20  # gap before "TAP TO OPEN" appears/works after claiming
POST_CONTINUE_WAIT_SECONDS = 20  # gap after dismissing a reveal, before the next one (if any) shows up
POPUP_CLOSE_WAIT_SECONDS = 20  # gap after dismissing a promo popup
CONSECUTIVE_CLEAR_POLLS = 2  # quiet polls in a row before assuming the reward queue is empty


def _load_template(name):
    path = TEMPLATES_DIR / name
    if not path.exists():
        return None
    return load_gray(path)


def _save_debug(gray_img, label):
    ts = datetime.now().strftime("%H%M%S")
    cv2.imwrite(str(DEBUG_DIR / f"{ts}_{label}.png"), gray_img)


def _save_reward_screenshot(match_label, suffix=None) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9]+", "_", match_label).strip("_") if match_label else ""
    parts = [ts] + ([safe_label] if safe_label else []) + ([str(suffix)] if suffix else [])
    name = "_".join(parts) + ".png"
    path = REWARDS_DIR / name
    adb.screenshot(path)
    return path


def _ensure_bluestacks_running(deadline: datetime, log) -> bool:
    if adb.is_bluestacks_running():
        return True

    log("BlueStacks is closed, starting it...")
    adb.launch_bluestacks()
    boot_deadline = min(deadline, datetime.now() + timedelta(seconds=BLUESTACKS_BOOT_WAIT_SECONDS))
    while datetime.now() < boot_deadline:
        if adb.connect(retries=1, delay=1):
            log("BlueStacks is up and adb is connected")
            return True
        time.sleep(3)
    log(f"BlueStacks did not come up within {BLUESTACKS_BOOT_WAIT_SECONDS}s, killing it so the next retry starts clean")
    adb.close_bluestacks()
    return False


def _shot_gray(path):
    adb.screenshot(path)
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def claim_reward(deadline: datetime, log=print, match_label=None):
    """Attempts to claim whatever reward(s) are pending. Retries until `deadline`.

    Returns True if at least one reward was claimed (and the chain ran out
    without anything left pending), False if the deadline passed without
    claiming anything, or None if the app was already open (assumed to mean
    the user is using it themselves, so we leave it alone).
    """
    close_x = _load_template("popup_close_x.png")
    claim_button = _load_template("claim_reward_button.png")
    open_button = _load_template("tap_to_open_button.png")
    continue_button = _load_template("continue_button.png")
    reveal_all_button = _load_template("reveal_all_button.png")

    if not _ensure_bluestacks_running(deadline, log):
        log("BlueStacks did not come up in time")
        return False

    if not adb.connect():
        log("adb: could not connect to device")
        return False

    if adb.is_fc_mobile_running():
        log("FC Mobile is already open - assuming you're using it, leaving it alone")
        return None

    log("launching FC Mobile...")
    adb.launch_fc_mobile()
    time.sleep(APP_LAUNCH_WAIT_SECONDS)

    attempt = 0
    claimed_anything = False
    reward_index = 0
    consecutive_unrecognized = 0
    while datetime.now() < deadline:
        attempt += 1
        gray = _shot_gray(DEBUG_DIR / "current.png")

        if claim_button is not None:
            m = find(gray, claim_button, "claim_reward_button", threshold=CLAIM_BUTTON_THRESHOLD)
            if m:
                consecutive_unrecognized = 0
                log(f"attempt {attempt}: found CLAIM REWARD button (conf={m.confidence:.2f}), waiting {BUTTON_SETTLE_WAIT_SECONDS}s for it to settle before tapping")
                time.sleep(BUTTON_SETTLE_WAIT_SECONDS)
                settle_gray = _shot_gray(DEBUG_DIR / "settle.png")
                m = find(settle_gray, claim_button, "claim_reward_button", threshold=CLAIM_BUTTON_THRESHOLD)
                if not m:
                    log(f"attempt {attempt}: button no longer visible after settling, re-checking")
                    continue
                log(f"attempt {attempt}: tapping {m.center}")
                adb.tap(*m.center)
                time.sleep(TAP_VERIFY_WAIT_SECONDS)
                verify_gray = _shot_gray(DEBUG_DIR / "verify.png")
                still_present = find(verify_gray, claim_button, "claim_reward_button", threshold=CLAIM_BUTTON_THRESHOLD)
                if still_present:
                    log(f"attempt {attempt}: button still visible after tap - tap likely didn't register, retrying")
                    continue
                claimed_anything = True
                log(f"attempt {attempt}: button gone after tap, claimed")
                log(f"waiting {POST_CLAIM_OPEN_WAIT_SECONDS}s in case a TAP TO OPEN step follows")
                time.sleep(POST_CLAIM_OPEN_WAIT_SECONDS)
                continue

        if open_button is not None:
            m = find(gray, open_button, "tap_to_open_button", threshold=OPEN_BUTTON_THRESHOLD)
            if m:
                consecutive_unrecognized = 0
                log(f"attempt {attempt}: found TAP TO OPEN button (conf={m.confidence:.2f}), tapping {m.center}")
                adb.tap(*m.center)
                time.sleep(REWARD_REVEAL_WAIT_SECONDS)
                claimed_anything = True
                continue

        if continue_button is not None:
            m = find(gray, continue_button, "continue_button", threshold=CONTINUE_BUTTON_THRESHOLD)
            if m:
                consecutive_unrecognized = 0
                log(f"attempt {attempt}: found CONTINUE button (conf={m.confidence:.2f}), tapping {m.center} to dismiss reveal / check for more rewards")
                adb.tap(*m.center)
                time.sleep(POST_CONTINUE_WAIT_SECONDS)
                continue

        if reveal_all_button is not None:
            m = find(gray, reveal_all_button, "reveal_all_button", threshold=REVEAL_ALL_BUTTON_THRESHOLD)
            if m:
                consecutive_unrecognized = 0
                log(f"attempt {attempt}: found REVEAL ALL button (conf={m.confidence:.2f}), tapping {m.center}")
                adb.tap(*m.center)
                time.sleep(REVEAL_ALL_WAIT_SECONDS)
                reward_index += 1
                reward_path = _save_reward_screenshot(match_label, reward_index)
                log(f"saved reward screenshot to {reward_path}")
                time.sleep(1)
                continue

        if close_x is not None:
            m = find(gray, close_x, "popup_close_x", threshold=POPUP_CLOSE_THRESHOLD)
            if m:
                consecutive_unrecognized = 0
                log(f"attempt {attempt}: dismissing popup (conf={m.confidence:.2f}) at {m.center}")
                adb.tap(*m.center)
                time.sleep(POPUP_CLOSE_WAIT_SECONDS)
                continue

        consecutive_unrecognized += 1
        if claimed_anything and consecutive_unrecognized >= CONSECUTIVE_CLEAR_POLLS:
            log("no more pending rewards detected, wrapping up")
            break

        log(f"attempt {attempt}: nothing recognized, waiting")
        _save_debug(gray, f"unrecognized_{attempt}")
        time.sleep(POLL_INTERVAL_SECONDS)

    if claimed_anything:
        log(f"waiting {POST_CLAIM_CLOSE_DELAY_SECONDS}s before closing...")
        time.sleep(POST_CLAIM_CLOSE_DELAY_SECONDS)
        log("closing FC Mobile and BlueStacks...")
        adb.stop_fc_mobile()
        adb.close_bluestacks()
        return True

    log("deadline reached without claiming anything")
    return False
