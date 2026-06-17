"""Regenerates worldcup_2026_schedule.json from a FIFA fixtures page saved as HTML.

The official FIFA fixtures page is a JS-rendered SPA, so it must be saved from a
browser (Ctrl+S, "Webpage, Complete") after it has fully loaded with the BDT
country filter applied, rather than fetched directly. Re-run this after saving a
fresh copy once knockout-stage matchups (currently TBD) are confirmed.

Usage:
    python scripts/parse_fixtures.py "path/to/saved fifa page.html"
"""
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "worldcup_2026_schedule.json"


def parse(html_path: Path) -> list[dict]:
    with open(html_path, "rb") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    titles = soup.select('[class*="matches-container_title"]')
    results = []

    for title in titles:
        date_text = title.get_text(strip=True)
        container = title
        rows = []
        for _ in range(6):
            container = container.parent
            if container is None:
                break
            rows = container.select('[class*="match-row_matchRowContainer"]')
            if rows:
                break

        for row in rows:
            teams = row.select('[class*="match-row_team__"]')
            home = teams[0].select_one("span.d-none.d-md-block")
            away = teams[1].select_one("span.d-none.d-md-block")
            time_el = row.select_one('[class*="match-row_matchTime__"]')
            group_el = row.select_one(
                '[class*="match-row_statiumCityWrapper"] [class*="match-row_bottomLabel"]'
            )
            venue_el = row.select_one('[class*="match-row_stadiumCityLabels"]')
            results.append({
                "date": date_text,
                "time_bdt": time_el.get_text(strip=True) if time_el else None,
                "home": home.get_text(strip=True) if home else None,
                "away": away.get_text(strip=True) if away else None,
                "group": group_el.get_text(strip=True) if group_el else None,
                "venue": venue_el.get_text(" ", strip=True) if venue_el else None,
            })

    return results


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    html_path = Path(sys.argv[1])
    results = parse(html_path)

    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    scheduled = sum(1 for r in results if r["time_bdt"])
    print(f"wrote {len(results)} matches ({scheduled} with a kickoff time) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
