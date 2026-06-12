# scraper/scrape_worldcup.py

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures?country=GB&wtw-filter=ALL"

OUTPUT_FILE = Path("site/data/scores.json")
GAMES_OUTPUT_FILE = Path("site/data/games.json")

GAME_SELECTOR = "div.match-row_matchRowContainer__NoCRI"
TEAM_SELECTOR = "div.team-abbreviations_container__wWtDG.false.d-md-none"
SCORE_SELECTOR = "span.match-row_score__wfcQP"
STAGE_SELECTOR = "span.match-row_bottomLabel__ni63b"

DATE_TITLE_SELECTOR = "div.matches-container_title__ATLsl"
DATE_TITLE_CLASS = "matches-container_title__ATLsl"
TEAM_CONTAINER_SELECTOR = "div.match-row_team__y5Rva"
TEAM_ABBR_SELECTOR = "div.team-abbreviations_container__wWtDG span"
TEAM_NAME_SELECTOR = "span.d-none.d-md-block"
STATUS_LABEL_SELECTOR = "span.match-row_statusLabel__AiSA3"
VENUE_SELECTOR = "div.match-row_stadiumCityLabels__zjXUq span"

WINNER_CLASS_MARKER = "scoreWinner"


PLAYER_TEAMS = {
    "Dan": [
        "Brazil",
        "Belgium",
        "Morocco",
        "Uruguay",
        "Sweden",
        "South Korea",
        "Bosnia and Herzegovina",
        "DR Congo",
        "Uzbekistan",
    ],
    "Mum": [
        "Spain",
        "Germany",
        "Japan",
        "USA",
        "Scotland",
        "Ivory Coast",
        "Czech Republic",
        "Panama",
        "Qatar",
    ],
    "Dad": [
        "France",
        "Portugal",
        "Colombia",
        "Ecuador",
        "Austria",
        "Ghana",
        "Egypt",
        "South Africa",
        "Cape Verde",
    ],
    "Matthew": [
        "Argentina",
        "Netherlands",
        "Switzerland",
        "Turkey",
        "Senegal",
        "Australia",
        "Algeria",
        "Iran",
        "New Zealand",
    ],
    "Naomi": [
        "England",
        "Norway",
        "Mexico",
        "Croatia",
        "Canada",
        "Paraguay",
        "Tunisia",
        "Saudi Arabia",
        "Iraq",
    ],
}


TEAM_ABBREVIATIONS = {
    "Brazil": "BRA",
    "Belgium": "BEL",
    "Morocco": "MAR",
    "Uruguay": "URU",
    "Sweden": "SWE",
    "South Korea": "KOR",
    "Bosnia and Herzegovina": "BIH",
    "DR Congo": "COD",
    "Uzbekistan": "UZB",
    "Spain": "ESP",
    "Germany": "GER",
    "Japan": "JPN",
    "USA": "USA",
    "Scotland": "SCO",
    "Ivory Coast": "CIV",
    "Czech Republic": "CZE",
    "Panama": "PAN",
    "Qatar": "QAT",
    "France": "FRA",
    "Portugal": "POR",
    "Colombia": "COL",
    "Ecuador": "ECU",
    "Austria": "AUT",
    "Ghana": "GHA",
    "Egypt": "EGY",
    "South Africa": "RSA",
    "Cape Verde": "CPV",
    "Argentina": "ARG",
    "Netherlands": "NED",
    "Switzerland": "SUI",
    "Turkey": "TUR",
    "Senegal": "SEN",
    "Australia": "AUS",
    "Algeria": "ALG",
    "Iran": "IRN",
    "New Zealand": "NZL",
    "England": "ENG",
    "Norway": "NOR",
    "Mexico": "MEX",
    "Croatia": "CRO",
    "Canada": "CAN",
    "Paraguay": "PAR",
    "Tunisia": "TUN",
    "Saudi Arabia": "KSA",
    "Iraq": "IRQ",
}


TEAM_TO_PLAYER = {
    TEAM_ABBREVIATIONS[team]: player
    for player, teams in PLAYER_TEAMS.items()
    for team in teams
}


ABBREVIATION_TO_TEAM = {abbr: team for team, abbr in TEAM_ABBREVIATIONS.items()}


GROUP_STAGES = {
    "First Stage",
    "Group A",
    "Group B",
    "Group C",
    "Group D",
    "Group E",
    "Group F",
    "Group G",
    "Group H",
    "Group I",
    "Group J",
    "Group K",
    "Group L",
}


KNOCKOUT_WIN_POINTS = {
    "Round of 32": 3,
    "Round of 16": 4,
    "Quarter-final": 5,
    "Semi-final": 6,
    "Play-off for third place": 4,
}


FINAL_WIN_POINTS = 12
RUNNER_UP_POINTS = 6


def parse_score(value: str) -> Optional[int]:
    value = value.strip()

    if not value or value in {"-", "–"}:
        return None

    return int(value)


def get_winner_and_loser(
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    won_a: bool,
    won_b: bool,
) -> tuple[str, str]:
    if won_a:
        return team_a, team_b

    if won_b:
        return team_b, team_a

    if score_a == score_b:
        raise ValueError(
            f"Match is level with no penalty winner indicated: "
            f"{team_a} {score_a}-{score_b} {team_b}"
        )

    if score_a > score_b:
        return team_a, team_b

    return team_b, team_a


def get_match_points(
    stage: str,
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    won_a: bool,
    won_b: bool,
) -> dict[str, int]:
    if stage in GROUP_STAGES:
        if score_a == score_b:
            return {
                team_a: 1,
                team_b: 1,
            }

        winner, _ = get_winner_and_loser(team_a, team_b, score_a, score_b, won_a, won_b)

        return {
            winner: 2,
        }

    if stage == "Final":
        winner, loser = get_winner_and_loser(team_a, team_b, score_a, score_b, won_a, won_b)

        return {
            winner: FINAL_WIN_POINTS,
            loser: RUNNER_UP_POINTS,
        }

    if stage in KNOCKOUT_WIN_POINTS:
        winner, _ = get_winner_and_loser(team_a, team_b, score_a, score_b, won_a, won_b)

        return {
            winner: KNOCKOUT_WIN_POINTS[stage],
        }

    raise ValueError(f"No points mapping for stage: {stage}")


def scrape_html() -> str:
    with sync_playwright() as p:
        print("Launching browser...", flush=True)
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200,
            }
        )

        print(f"Navigating to {URL}...", flush=True)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        print(f"Waiting for selector '{GAME_SELECTOR}'...", flush=True)
        page.wait_for_selector(GAME_SELECTOR, timeout=30_000)

        print("Selector found, reading page content...", flush=True)
        html = page.content()

        browser.close()
        print("Browser closed.", flush=True)

    return html


def calculate_scores(html: str) -> dict[str, int]:
    soup = BeautifulSoup(html, "html.parser")

    player_scores = defaultdict(int)

    for game in soup.select(GAME_SELECTOR):
        teams = [
            el.get_text(strip=True)
            for el in game.select(TEAM_SELECTOR)
        ]

        score_elements = game.select(SCORE_SELECTOR)

        scores = [
            parse_score(el.get_text(strip=True))
            for el in score_elements
        ]

        won = [
            any(WINNER_CLASS_MARKER in cls for cls in el.get("class", []))
            for el in score_elements
        ]

        stage_el = game.select_one(STAGE_SELECTOR)
        stage = stage_el.get_text(strip=True) if stage_el else None

        if len(teams) != 2 or len(scores) != 2 or stage is None:
            continue

        team_a, team_b = teams
        score_a, score_b = scores
        won_a, won_b = won

        # Game has not been played yet.
        if score_a is None or score_b is None:
            continue

        team_points = get_match_points(
            stage=stage,
            team_a=team_a,
            team_b=team_b,
            score_a=score_a,
            score_b=score_b,
            won_a=won_a,
            won_b=won_b,
        )

        for team, points in team_points.items():
            player = TEAM_TO_PLAYER.get(team)

            # Teams not picked by any player (e.g. Haiti, Curaçao, Jordan)
            # score no points for anyone.
            if player is None:
                continue

            player_scores[player] += points

    return {
        player: player_scores[player]
        for player in PLAYER_TEAMS
    }


def parse_date_label(label: str) -> Optional[str]:
    try:
        return datetime.strptime(label, "%A %d %B %Y").date().isoformat()
    except ValueError:
        return None


def parse_team_side(team_el) -> Optional[dict]:
    abbr_el = team_el.select_one(TEAM_ABBR_SELECTOR)

    if abbr_el is None:
        return None

    abbr = abbr_el.get_text(strip=True)

    name_el = team_el.select_one(TEAM_NAME_SELECTOR)
    name = (
        name_el.get_text(strip=True)
        if name_el
        else ABBREVIATION_TO_TEAM.get(abbr, abbr)
    )

    return {
        "abbr": abbr,
        "name": name,
        "player": TEAM_TO_PLAYER.get(abbr),
    }


def collect_games(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    games = []
    date_label = None
    date = None

    # Date headers and match rows are interleaved in document order, so each
    # match belongs to the most recently seen date header.
    for el in soup.select(f"{DATE_TITLE_SELECTOR}, {GAME_SELECTOR}"):
        if DATE_TITLE_CLASS in el.get("class", []):
            date_label = el.get_text(strip=True)
            date = parse_date_label(date_label)
            continue

        team_els = el.select(TEAM_CONTAINER_SELECTOR)

        if len(team_els) != 2:
            continue

        home = parse_team_side(team_els[0])
        away = parse_team_side(team_els[1])

        if home is None or away is None:
            continue

        score_elements = el.select(SCORE_SELECTOR)

        if len(score_elements) == 2:
            scores = [parse_score(s.get_text(strip=True)) for s in score_elements]
            won = [
                any(WINNER_CLASS_MARKER in cls for cls in s.get("class", []))
                for s in score_elements
            ]
        else:
            scores = [None, None]
            won = [False, False]

        home["score"], away["score"] = scores
        home["winner"], away["winner"] = won

        played = home["score"] is not None and away["score"] is not None

        # If the page didn't flag a winner (no penalties), decide on score.
        if played and not home["winner"] and not away["winner"]:
            home["winner"] = home["score"] > away["score"]
            away["winner"] = away["score"] > home["score"]

        bottom_labels = [
            b.get_text(strip=True)
            for b in el.select(STAGE_SELECTOR)
        ]
        venue_parts = [v.get_text(strip=True) for v in el.select(VENUE_SELECTOR)]

        status_el = el.select_one(STATUS_LABEL_SELECTOR)

        games.append({
            "date": date,
            "date_label": date_label,
            "stage": bottom_labels[0] if bottom_labels else None,
            "group": bottom_labels[1] if len(bottom_labels) > 1 else None,
            "venue": " ".join(venue_parts) if venue_parts else None,
            "status": status_el.get_text(strip=True) if status_el else None,
            "played": played,
            "home": home,
            "away": away,
        })

    return games


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = path.with_suffix(".json.tmp")

    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    tmp_file.replace(path)


def main() -> None:
    html = scrape_html()
    updated_at = datetime.now(timezone.utc).isoformat()

    scores = calculate_scores(html)
    write_json(OUTPUT_FILE, {"updated_at": updated_at, "scores": scores})

    games = collect_games(html)
    write_json(GAMES_OUTPUT_FILE, {"updated_at": updated_at, "games": games})

    print(json.dumps(scores, indent=2))
    print(f"Wrote {len(games)} games to {GAMES_OUTPUT_FILE}")


if __name__ == "__main__":
    main()