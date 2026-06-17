"""Loads worldcup_2026_schedule.json and computes claim windows in local (BDT) time."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "worldcup_2026_schedule.json"

CLAIM_OPENS_AFTER = timedelta(minutes=55)  # reward unlocks at +45min; +10min safety buffer before acting
CLAIM_CLOSES_AFTER = timedelta(minutes=90)


@dataclass
class MatchWindow:
    home: str
    away: str
    kickoff: datetime
    claim_start: datetime
    claim_end: datetime

    @property
    def key(self):
        return f"{self.kickoff.isoformat()}_{self.home}_{self.away}"


def _parse_kickoff(date_str: str, time_str: str) -> datetime:
    d = datetime.strptime(date_str, "%A %d %B %Y")
    h, m = (int(x) for x in time_str.split(":"))
    return d.replace(hour=h, minute=m)


def load_match_windows(path: Path = SCHEDULE_PATH) -> list[MatchWindow]:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)

    windows = []
    for row in rows:
        if not row.get("time_bdt"):
            continue  # match already played, FIFA page shows score instead of kickoff time
        kickoff = _parse_kickoff(row["date"], row["time_bdt"])
        windows.append(MatchWindow(
            home=row["home"],
            away=row["away"],
            kickoff=kickoff,
            claim_start=kickoff + CLAIM_OPENS_AFTER,
            claim_end=kickoff + CLAIM_CLOSES_AFTER,
        ))
    return windows


def active_window(windows: list[MatchWindow], now: datetime) -> MatchWindow | None:
    for w in windows:
        if w.claim_start <= now <= w.claim_end:
            return w
    return None


def next_claim_start(windows: list[MatchWindow], now: datetime) -> datetime | None:
    upcoming = [w.claim_start for w in windows if w.claim_start > now]
    return min(upcoming) if upcoming else None
