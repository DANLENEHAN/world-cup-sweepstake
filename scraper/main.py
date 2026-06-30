# scraper/scrape_worldcup.py

import json
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures?country=GB&wtw-filter=ALL"
STANDINGS_URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/standings"

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
MATCH_TIME_SELECTOR = "span.match-row_matchTime__9QJXJ"
VENUE_SELECTOR = "div.match-row_stadiumCityLabels__zjXUq span"

# Penalty shoot-out tallies (e.g. "(4)") render in document order as
# home then away, sitting either side of the full-time score.
PENALTY_SELECTOR = "span[class*='match-row_penalties']"

# Standings page: rows for teams knocked out at the group stage carry an
# "eliminated" modifier class. Class hashes are matched by prefix so a FIFA
# build bump doesn't silently break selection.
STANDINGS_ROW_SELECTOR = "tr[class*='standings-table-row_tableRow']"
STANDINGS_ELIMINATED_SELECTOR = "tr[class*='standings-table-row_eliminated']"
STANDINGS_ABBR_SELECTOR = "div.team-abbreviations_container__wWtDG span"
STANDINGS_NAME_SELECTOR = "span.d-none.d-md-1024-block"

# The FIFA page renders kickoff times in UTC regardless of locale.
SOURCE_TIME_ZONE = timezone.utc
DISPLAY_TIME_ZONE = ZoneInfo("Europe/London")

WINNER_CLASS_MARKER = "scoreWinner"
FULL_TIME_CLASS_MARKER = "fullTime"


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


# FIFA's pages don't always use the same display name for a team as our squad
# lists do. The three-letter code is the stable key, but as a safety net for
# when a code is missing or unexpected we also map known display-name aliases
# back to our canonical names. Includes straight and curly apostrophe variants.
NAME_ALIASES = {
    "Côte d'Ivoire": "Ivory Coast",
    "Côte d’Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Korea Republic": "South Korea",
    "Republic of Korea": "South Korea",
    "IR Iran": "Iran",
    "United States": "USA",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Czechia": "Czech Republic",
}


def canonical_team_name(abbr: Optional[str], raw_name: Optional[str]) -> Optional[str]:
    """Resolve a team to our canonical name, keyed first by 3-letter code."""
    if abbr and abbr in ABBREVIATION_TO_TEAM:
        return ABBREVIATION_TO_TEAM[abbr]

    if raw_name in NAME_ALIASES:
        return NAME_ALIASES[raw_name]

    return raw_name


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


# Stages where a single match eliminates the loser. A team that loses any of
# these is out of the tournament.
KNOCKOUT_STAGES = set(KNOCKOUT_WIN_POINTS) | {"Final"}


def parse_score(value: str) -> Optional[int]:
    value = value.strip()

    if not value or value in {"-", "–"}:
        return None

    return int(value)


def parse_penalty(value: str) -> Optional[int]:
    """Parse a penalty tally such as "(4)" into an integer."""
    value = value.strip().strip("()")

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


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


def fetch_html(url: str, wait_selector: str) -> str:
    with sync_playwright() as p:
        print("Launching browser...", flush=True)
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200,
            }
        )

        print(f"Navigating to {url}...", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        print(f"Waiting for selector '{wait_selector}'...", flush=True)
        page.wait_for_selector(wait_selector, timeout=30_000)

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


def parse_kickoff(date: Optional[str], raw_time: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Combine a match date with its raw (UTC) kickoff time.

    Returns a tuple of (kickoff ISO timestamp in UTC, kickoff time formatted
    for display in Europe/London).
    """
    if not date or not raw_time:
        return None, None

    try:
        match_date = datetime.strptime(date, "%Y-%m-%d").date()
        hour, minute = (int(part) for part in raw_time.split(":"))
        kickoff_utc = datetime.combine(match_date, time(hour, minute), tzinfo=SOURCE_TIME_ZONE)
    except ValueError:
        return None, None

    kickoff_london = kickoff_utc.astimezone(DISPLAY_TIME_ZONE)

    return kickoff_utc.isoformat(), kickoff_london.strftime("%H:%M")


def parse_team_side(team_el) -> Optional[dict]:
    abbr_el = team_el.select_one(TEAM_ABBR_SELECTOR)

    if abbr_el is None:
        return None

    abbr = abbr_el.get_text(strip=True)

    name_el = team_el.select_one(TEAM_NAME_SELECTOR)
    raw_name = name_el.get_text(strip=True) if name_el else None

    return {
        "abbr": abbr,
        "name": canonical_team_name(abbr, raw_name) or abbr,
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

        penalty_elements = el.select(PENALTY_SELECTOR)

        if len(penalty_elements) == 2:
            penalties = [parse_penalty(p.get_text(strip=True)) for p in penalty_elements]
        else:
            penalties = [None, None]

        home["penalties"], away["penalties"] = penalties

        status_el = el.select_one(STATUS_LABEL_SELECTOR)

        # A match is only "played" once it has gone to full time. While a
        # game is live, FIFA already shows the in-progress score here too,
        # so checking for scores alone would mark live games as finished.
        played = status_el is not None and any(
            FULL_TIME_CLASS_MARKER in cls for cls in status_el.get("class", [])
        )

        # If the page didn't flag a winner (no penalties), decide on score.
        if played and not home["winner"] and not away["winner"]:
            home["winner"] = home["score"] > away["score"]
            away["winner"] = away["score"] > home["score"]

        bottom_labels = [
            b.get_text(strip=True)
            for b in el.select(STAGE_SELECTOR)
        ]
        venue_parts = [v.get_text(strip=True) for v in el.select(VENUE_SELECTOR)]

        time_el = el.select_one(MATCH_TIME_SELECTOR)
        raw_time = time_el.get_text(strip=True) if time_el else None
        kickoff, display_time = parse_kickoff(date, raw_time)

        games.append({
            "date": date,
            "date_label": date_label,
            "stage": bottom_labels[0] if bottom_labels else None,
            "group": bottom_labels[1] if len(bottom_labels) > 1 else None,
            "venue": " ".join(venue_parts) if venue_parts else None,
            "status": status_el.get_text(strip=True) if status_el else None,
            "kickoff": kickoff,
            "time": display_time,
            "played": played,
            "home": home,
            "away": away,
        })

    return games


def collect_eliminated(games: list[dict]) -> list[str]:
    """Names of teams knocked out by losing a played knockout match.

    Group-stage elimination (failing to advance on points) is not handled
    here — only direct knockout losses.
    """
    eliminated = []

    for game in games:
        if not game["played"] or game["stage"] not in KNOCKOUT_STAGES:
            continue

        home = game["home"]
        away = game["away"]

        if home["winner"] and not away["winner"]:
            eliminated.append(away["name"])
        elif away["winner"] and not home["winner"]:
            eliminated.append(home["name"])

    return eliminated


def collect_group_eliminated(html: str) -> list[str]:
    """Names of teams knocked out at the group stage.

    The standings page flags these rows with an "eliminated" modifier class.
    Teams are keyed by their three-letter code so naming differences between
    pages (e.g. "Korea Republic" vs "South Korea") map back to our canonical
    names.
    """
    soup = BeautifulSoup(html, "html.parser")

    eliminated = []

    for row in soup.select(STANDINGS_ELIMINATED_SELECTOR):
        abbr_el = row.select_one(STANDINGS_ABBR_SELECTOR)
        abbr = abbr_el.get_text(strip=True) if abbr_el else None

        name_el = row.select_one(STANDINGS_NAME_SELECTOR)
        raw_name = name_el.get_text(strip=True) if name_el else None

        name = canonical_team_name(abbr, raw_name) or abbr

        if name:
            eliminated.append(name)

    return eliminated


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = path.with_suffix(".json.tmp")

    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    tmp_file.replace(path)


def main() -> None:
    html = fetch_html(URL, GAME_SELECTOR)
    updated_at = datetime.now(timezone.utc).isoformat()

    games = collect_games(html)
    eliminated = collect_eliminated(games)

    # Group-stage exits live on a separate standings page. A failure there
    # shouldn't lose the scores and fixtures we already scraped.
    try:
        standings_html = fetch_html(STANDINGS_URL, STANDINGS_ROW_SELECTOR)
        group_eliminated = collect_group_eliminated(standings_html)
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        print(f"Warning: failed to scrape standings: {exc}", flush=True)
        group_eliminated = []

    # Merge knockout losers with group-stage exits, preserving order and
    # dropping duplicates.
    all_eliminated = list(dict.fromkeys(eliminated + group_eliminated))

    scores = calculate_scores(html)
    write_json(
        OUTPUT_FILE,
        {"updated_at": updated_at, "scores": scores, "eliminated": all_eliminated},
    )

    write_json(GAMES_OUTPUT_FILE, {"updated_at": updated_at, "games": games})

    print(json.dumps(scores, indent=2))
    print(f"Wrote {len(games)} games to {GAMES_OUTPUT_FILE}")


if __name__ == "__main__":
    main()