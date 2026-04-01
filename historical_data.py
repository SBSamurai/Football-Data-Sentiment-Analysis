import pandas as pd
import requests
import time
import json
import re
import unicodedata

# "bs4" is only required for FBref scraping; make the import optional so the
# module can be loaded even if the user has not installed the package yet.
try:
    from bs4 import BeautifulSoup  # type: ignore[reportMissingImports]
except ImportError:
    BeautifulSoup = None

# --------------------------------------------------
# GLOBAL CONSTANTS / SLUG MAPS
# --------------------------------------------------
FOOTBALL_DATA_API_KEY = "YOUR_FOOTBALL_DATA_API_KEY"  # can override via env / Streamlit secrets

COMPETITION_IDS = {
    "Premier League":   "PL",
    "La Liga":          "PD",
    "Bundesliga":       "BL1",
    "Serie A":          "SA",
    "Ligue 1":          "FL1",
    "Champions League": "CL",
}

# Map API codes and variations to canonical competition names
COMPETITION_NORMALIZE = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "Primera Division": "La Liga",  # alternative name
}

UNDERSTAT_LEAGUE_SLUGS = {
    "Premier League": "EPL",
    "La Liga":        "La_liga",
    "Bundesliga":     "Bundesliga",
    "Serie A":        "Serie_A",
    "Ligue 1":        "Ligue_1",
    "Champions League": "CL",
}

FBREF_LEAGUE_URLS = {
    'Premier League': 'https://fbref.com/en/comps/9/Premier-League-Stats',
    'La Liga':        'https://fbref.com/en/comps/12/La-Liga-Stats',
    'Bundesliga':     'https://fbref.com/en/comps/20/Bundesliga-Stats',
    'Serie A':        'https://fbref.com/en/comps/11/Serie-A-Stats',
    'Ligue 1':        'https://fbref.com/en/comps/13/Ligue-1-Stats',
    'Champions League': 'https://fbref.com/en/comps/8/Champions-League-Stats',
}

# --------------------------------------------------
# GENERAL CSV helpers (same as before, plus enrichment)
# --------------------------------------------------

def _remove_accents(text):
    """Convert accented characters to ASCII equivalents (é→e, ö→o, etc)."""
    if not isinstance(text, str):
        return text
    # NFKD decomposition separates base chars from accents
    nfkd = unicodedata.normalize('NFKD', text)
    # keep only ASCII chars (drops accents and non-ASCII)
    return nfkd.encode('ASCII', 'ignore').decode('ASCII')


def normalize_team(name, remove_numbers=False):
    """Normalize team names comprehensively.
    
    Removes:
    - Common club suffixes (FC, CF, AFC, SC, etc.)
    - Accented characters (Köln → Koln)
    - Leading ordinal numbers like '1.' or '2.'
    - (Optional) trailing years and numbers if remove_numbers=True
    """
    if not isinstance(name, str):
        return name
    
    # Convert accents to ASCII
    name = _remove_accents(name)
    
    # Remove leading ordinal numbers + optional club designator like "1. FC " or "2. "
    name = re.sub(r'^\d+\.\s*', '', name)
    # Also remove leading club designators without preceding digit like "FC " or "CF "
    leading_terms = ['FC ', 'CF ', 'AFC ', 'SC ', 'UD ', 'OSC ']
    for term in leading_terms:
        if name.startswith(term):
            name = name[len(term):]
    
    # Remove common club suffixes at the end
    suffixes = [' FC', ' CF', ' AFC', ' SC', ' UD', ' OSC']
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    
    # Optionally remove trailing numbers (years like 1909, 1910, etc.)
    if remove_numbers:
        name = re.sub(r'\s+\d{4}$', '', name)  # remove years at end
        name = re.sub(r'\s+\d+$', '', name)   # remove any trailing numbers
    
    return name.strip()


def get_available_teams(df, competition=None):
    """Return a sorted list of unique team names, optionally filtered by competition."""
    teams = set(df['team_a'].unique()) | set(df['team_b'].unique())
    if competition:
        # filter to teams that appear in the specified competition
        comp_df = df[df['competition'] == competition]
        comp_teams = set(comp_df['team_a'].unique()) | set(comp_df['team_b'].unique())
        teams = teams & comp_teams
    return sorted(list(teams))


def get_available_competitions(df):
    """Return a sorted list of unique competitions."""
    return sorted(df['competition'].unique().tolist())


def _clean_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate rows from a matches dataframe and rewrite files if needed.

    Duplicates are checked on the primary keys that identify a fixture
    (date, home/away team and competition).  If any rows are removed the
    CSV (and Excel, when available) is rewritten to keep the on‑disk data
    consistent with what is returned.
    
    The cleaned dataframe is returned.
    """
    before = len(df)
    df = df.drop_duplicates(subset=['date', 'team_a', 'team_b', 'competition'],
                             keep='last')
    if len(df) != before:
        # persist changes back to storage
        df.to_csv('data/matches.csv', index=False)
        try:
            df.to_excel('data/matches.xlsx', index=False)
        except ImportError:
            # Excel support is optional
            pass
    return df


def remove_duplicate_matches_files() -> pd.DataFrame:
    """Public helper that removes duplicates from the on‑disk CSV/Excel.

    This simply reads the CSV and delegates to :func:`_clean_duplicates`.
    Useful for one-off maintenance operations or when the Streamlit UI wants
    to offer a "clean database" button.
    """
    try:
        df = pd.read_csv('data/matches.csv')
    except FileNotFoundError:
        return pd.DataFrame()
    return _clean_duplicates(df)


def load_matches(enrich=True):
    """Load the match database, normalise names and optionally enrich with xG/forecast.

    The enrichment step will only run if the expected columns are missing and the
    table has at least one row.  It will also write back to disk so the expensive
    network calls are not repeated on every page refresh.
    """
    # read and immediately clean duplicates so every consumer works with a
    # consistent dataset
    df = pd.read_csv('data/matches.csv')
    df = _clean_duplicates(df)

    # normalise team names and ensure score columns are integer types
    df['team_a'] = df['team_a'].apply(normalize_team)
    df['team_b'] = df['team_b'].apply(normalize_team)
    df['winner'] = df['winner'].apply(lambda x: normalize_team(x) if x != 'Draw' else x)

    # cast scores to integers (they may be floats in the CSV due to pandas behaviour)
    for col in ['score_a', 'score_b']:
        if col in df.columns:
            # use nullable Int64 so that NaNs are preserved
            try:
                df[col] = df[col].astype('Int64')
            except Exception:
                # fallback: coerce and fill with zero
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    if enrich and 'xg_a' not in df.columns and not df.empty:
        try:
            df = enrich_matches_with_understat(df)
            # persist enriched data so we do not redo it every time
            df.to_csv('data/matches.csv', index=False)
            # also write to Excel for confirmation (if openpyxl is available)
            try:
                df.to_excel('data/matches.xlsx', index=False)
            except ImportError:
                print("[Warning] openpyxl not installed; skipping Excel export.")
        except Exception:
            # if enrichment fails for any reason, just return raw data
            pass
    return df


def get_head_to_head(df, team_a, team_b, last_n=5):
    """Return last N meetings between two teams."""
    mask = (
        ((df.team_a == team_a) & (df.team_b == team_b)) |
        ((df.team_a == team_b) & (df.team_b == team_a))
    )
    meetings = df[mask].copy()
    if not meetings.empty:
        meetings['date'] = pd.to_datetime(meetings['date'])
        meetings = meetings.sort_values('date', ascending=False)
    return meetings.head(last_n)


def head_to_head_summary(df, team_a, team_b, last_n=10):
    """Return summary statistics for head-to-head meetings."""
    meetings = get_head_to_head(df, team_a, team_b, last_n=last_n)
    if meetings.empty:
        return {
            'team_a': team_a,
            'team_b': team_b,
            'matches': 0,
            'wins_a': 0,
            'wins_b': 0,
            'draws': 0,
            'goals_a': 0,
            'goals_b': 0,
            'dominant': None,
        }

    wins_a = wins_b = draws = goals_a = goals_b = 0
    for _, row in meetings.iterrows():
        if row['winner'] == team_a:
            wins_a += 1
        elif row['winner'] == team_b:
            wins_b += 1
        else:
            draws += 1

        if row['team_a'] == team_a:
            goals_a += int(row.get('score_a', 0) or 0)
            goals_b += int(row.get('score_b', 0) or 0)
        else:
            goals_a += int(row.get('score_b', 0) or 0)
            goals_b += int(row.get('score_a', 0) or 0)

    dominant = team_a if wins_a > wins_b else team_b if wins_b > wins_a else 'Draw'
    return {
        'team_a': team_a,
        'team_b': team_b,
        'matches': len(meetings),
        'wins_a': wins_a,
        'wins_b': wins_b,
        'draws': draws,
        'goals_a': goals_a,
        'goals_b': goals_b,
        'dominant': dominant,
    }


def summarize_matches(df):
    """Return summary metrics for the adopted historical dataset."""
    if df.empty:
        return {
            'matches': 0,
            'avg_goals_per_match': 0.0,
            'home_win_pct': 0.0,
            'avg_score_a': 0.0,
            'avg_score_b': 0.0,
            'max_goals_in_match': 0,
        }
    total = len(df)
    goals_total = (df['score_a'].fillna(0) + df['score_b'].fillna(0)).astype(int)
    home_wins = (df['winner'] == df['team_a']).sum()

    score_a = pd.to_numeric(df['score_a'], errors='coerce').fillna(0).astype(int)
    score_b = pd.to_numeric(df['score_b'], errors='coerce').fillna(0).astype(int)
    return {
        'matches': total,
        'avg_goals_per_match': round(goals_total.mean(), 2),
        'home_win_pct': round(home_wins / total * 100, 1),
        'avg_score_a': round(score_a.mean(), 2),
        'avg_score_b': round(score_b.mean(), 2),
        'max_goals_in_match': int(goals_total.max()),
    }


def get_recent_form(df, team, last_n=5):
    """Return last N matches involving a team, based on most recent dates."""
    mask = (df.team_a == team) | (df.team_b == team)
    subset = df[mask].copy()
    if subset.empty:
        return subset
    # ensure date column is datetime
    subset['date'] = pd.to_datetime(subset['date'])
    subset = subset.sort_values('date', ascending=False)
    return subset.head(last_n)


def get_team_stats(df, team, last_n=20):
    """Calculate statistics for a team's recent matches.

    If the dataframe contains Understat columns (xg_a/xg_b) those are included in
    the returned dictionary so they can be used by the explainer.
    """
    recent = get_recent_form(df, team, last_n)
    if recent.empty:
        return {
            'wins': 0, 'losses': 0, 'draws': 0,
            'goals_for': 0, 'goals_against': 0,
            'matches': 0
        }

    wins = losses = draws = 0
    goals_for = goals_against = 0
    xg_for = xg_against = 0.0

    for _, match in recent.iterrows():
        if match['team_a'] == team:
            gf = match.get('score_a', 0) or 0
            ga = match.get('score_b', 0) or 0
            if match['winner'] == team:
                wins += 1
            elif match['winner'] == 'Draw':
                draws += 1
            else:
                losses += 1
            if 'xg_a' in match:
                xg_for += match.get('xg_a', 0) or 0
                xg_against += match.get('xg_b', 0) or 0
        else:
            gf = match.get('score_b', 0) or 0
            ga = match.get('score_a', 0) or 0
            if match['winner'] == team:
                wins += 1
            elif match['winner'] == 'Draw':
                draws += 1
            else:
                losses += 1
            if 'xg_a' in match:
                xg_for += match.get('xg_b', 0) or 0
                xg_against += match.get('xg_a', 0) or 0
        goals_for += gf
        goals_against += ga
    res = {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'goals_for': goals_for,
        'goals_against': goals_against,
        'matches': len(recent)
    }
    if len(recent) > 0 and xg_for > 0:
        res['xg_for'] = xg_for
        res['xg_against'] = xg_against
        res['avg_xg_for'] = xg_for / len(recent)
        res['avg_xg_against'] = xg_against / len(recent)
    return res


def get_last_result(df, team_a, team_b):
    """Return the result string of the most recent meeting between two teams."""
    mask = (
        ((df.team_a == team_a) & (df.team_b == team_b)) |
        ((df.team_a == team_b) & (df.team_b == team_a))
    )
    meetings = df[mask].copy()
    if meetings.empty:
        return None
    meetings['date'] = pd.to_datetime(meetings['date'])
    meetings = meetings.sort_values('date', ascending=False)
    last = meetings.iloc[0]
    # format scores as ints to avoid showing 0.0
    def fmt(score):
        try:
            return int(score)
        except Exception:
            return score

    if last['team_a'] == team_a:
        return f"{team_a} {fmt(last['score_a'])} - {fmt(last['score_b'])} {team_b}"
    else:
        return f"{team_a} {fmt(last['score_b'])} - {fmt(last['score_a'])} {team_b}"

# --------------------------------------------------
# UNDERSTAT SCRAPERS / HELPERS
# --------------------------------------------------

def _understat_get(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
               " AppleWebKit/537.36 (KHTML, like Gecko)"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)  # Increased timeout to 30 seconds
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.Timeout:
        print(f"[Understat] Request timed out after 30 seconds: {url}")
        raise
    except requests.exceptions.RequestException as e:
        print(f"[Understat] Request failed: {e}")
        raise


def _extract_json_var(html: str, var_name: str):
    pattern = rf"var\s+{var_name}\s*=\s*JSON\.parse\('(.+?)'\)"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return None
    raw = match.group(1).encode().decode("unicode_escape")
    return json.loads(raw)


def get_league_xg(competition: str, season: str) -> pd.DataFrame:
    """Return a full season of expected-goals data from Understat.

    The dataframe contains one row per match with the following columns:
    date, home, away, xg_home, xg_away, goals_home, goals_away,
    forecast_w, forecast_d, forecast_l.
    """
    slug = UNDERSTAT_LEAGUE_SLUGS.get(competition, 'EPL')
    url = f"https://understat.com/league/{slug}/{season}"
    try:
        html = _understat_get(url)
        time.sleep(1)  # be polite
    except Exception as e:
        print(f"[Understat] fetch error: {e}")
        print("Continuing without xG data...")
        return pd.DataFrame()

    data = _extract_json_var(html, "datesData")
    if not data:
        print("[Understat] No data found in response")
        return pd.DataFrame()

    rows = []
    for m in data:
        rows.append({
            "date":       m.get("datetime", "")[:10],
            "home":       m.get("h", {}).get("title", ""),
            "away":       m.get("a", {}).get("title", ""),
            "xg_home":    float(m.get("xg", {}).get("h", 0) or 0),
            "xg_away":    float(m.get("xg", {}).get("a", 0) or 0),
            "goals_home": int(m.get("goals", {}).get("h", 0) or 0),
            "goals_away": int(m.get("goals", {}).get("a", 0) or 0),
            "forecast_w": float(m.get("forecast", {}).get("w", 0) or 0),
            "forecast_d": float(m.get("forecast", {}).get("d", 0) or 0),
            "forecast_l": float(m.get("forecast", {}).get("l", 0) or 0),
        })
    return pd.DataFrame(rows)


def get_team_xg_rolling(team_name: str,
                       competition: str = "Premier League",
                       season: str = "2024",
                       last_n: int = 5) -> pd.DataFrame:
    """Return rolling xG for/against for a team's last N matches.

    This uses the full league dataset returned by ``get_league_xg`` and
    computes which side (home/away) corresponds to the requested team.
    """
    df = get_league_xg(competition, season)
    if df.empty:
        return df
    mask = (
        df.home.str.contains(team_name, case=False) |
        df.away.str.contains(team_name, case=False)
    )
    team_df = df[mask].tail(last_n).copy()
    # determine xg_for/against based on whether the team was home
    def _xg_for(row):
        return row['xg_home'] if team_name.lower() in row['home'].lower() else row['xg_away']
    def _xg_ag(row):
        return row['xg_away'] if team_name.lower() in row['home'].lower() else row['xg_home']

    team_df['xg_for'] = team_df.apply(_xg_for, axis=1)
    team_df['xg_against'] = team_df.apply(_xg_ag, axis=1)
    return team_df


def enrich_matches_with_understat(df: pd.DataFrame) -> pd.DataFrame:
    """Add xG/forecast columns to a dataframe of matches.

    This function looks up each match in the appropriate Understat season
    dataset and appends the xG for / against along with the pre‑match
    forecast probabilities.  If no corresponding Understat row can be found the
    match is left untouched.

    Before fetching, check if we already have the data to avoid redundant network calls.
    """
    if df.empty:
        return df

    out = df.copy()
    out['season'] = pd.to_datetime(out['date']).dt.year

    # Check if we already have enriched data
    if 'xg_a' in out.columns:
        print("[Understat] Data already enriched, skipping network fetch.")
        return out

    # iterate by competition + season to avoid refetching pages
    for comp in out['competition'].unique():
        for season in out.loc[out['competition'] == comp, 'season'].unique():
            xg_df = get_league_xg(comp, str(season))
            if xg_df.empty:
                continue

            mask = (out['competition'] == comp) & (out['season'] == season)
            for idx in out[mask].index:
                row = out.loc[idx]
                candidates = xg_df[
                    (xg_df.date == row['date']) &
                    (
                        (xg_df.home.str.contains(row['team_a'], case=False) &
                         xg_df.away.str.contains(row['team_b'], case=False)) |
                        (xg_df.home.str.contains(row['team_b'], case=False) &
                         xg_df.away.str.contains(row['team_a'], case=False))
                    )
                ]
                if not candidates.empty:
                    m = candidates.iloc[0]
                    # determine which side is team_a in our row
                    if row['team_a'].lower() in m['home'].lower():
                        out.at[idx, 'xg_a'] = m['xg_home']
                        out.at[idx, 'xg_b'] = m['xg_away']
                        out.at[idx, 'forecast_a'] = m['forecast_w']
                        out.at[idx, 'forecast_b'] = m['forecast_l']
                    else:
                        out.at[idx, 'xg_a'] = m['xg_away']
                        out.at[idx, 'xg_b'] = m['xg_home']
                        out.at[idx, 'forecast_a'] = m['forecast_l']
                        out.at[idx, 'forecast_b'] = m['forecast_w']
    return out

# --------------------------------------------------
# OPTIONAL: FBREF SCRAPERS (not wired into update_matches yet)
# --------------------------------------------------

from typing import Any


def _fbref_get(url: str) -> Any:  # return type left generic to avoid issues when bs4 is missing
    """Fetch an FBref page with polite delay.

    Requires the optional ``bs4`` package; if it isn't installed we raise a
    clear ImportError so callers can decide what to do.
    """
    if BeautifulSoup is None:
        raise ImportError("BeautifulSoup4 is required to scrape FBref pages")
    time.sleep(4)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_squad_advanced_stats(competition: str = "Premier League") -> pd.DataFrame:
    base_url = FBREF_LEAGUE_URLS.get(competition, FBREF_LEAGUE_URLS["Premier League"])
    try:
        soup = _fbref_get(base_url)
    except Exception as e:
        print(f"[FBref] Fetch error: {e}")
        return pd.DataFrame()

    target_ids = ["stats_squads_possession", "stats_squads_misc", "stats_squads_passing"]
    dfs = []
    for tid in target_ids:
        tag = soup.find("table", {"id": tid})
        if tag:
            try:
                df = pd.read_html(str(tag))[0]
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [" ".join(c).strip() for c in df.columns]
                dfs.append(df)
            except Exception:
                continue

    if not dfs:
        print("[FBref] Could not find advanced stats tables.")
        return pd.DataFrame()

    result = dfs[0]
    for extra in dfs[1:]:
        squad_col = [c for c in extra.columns if "squad" in c.lower()]
        if squad_col:
            try:
                result = result.merge(extra, on=squad_col[0], how="left", suffixes=("", "_dup"))
                result = result[[c for c in result.columns if not c.endswith("_dup")]]
            except Exception:
                pass
    return result


def get_player_stats(team: str, competition: str = "Premier League") -> pd.DataFrame:
    base_url = FBREF_LEAGUE_URLS.get(competition, FBREF_LEAGUE_URLS["Premier League"])
    try:
        soup = _fbref_get(base_url)
    except Exception as e:
        print(f"[FBref] Competition page error: {e}")
        return pd.DataFrame()

    team_link = None
    for a_tag in soup.find_all("a", href=True):
        if "/squads/" in a_tag["href"] and team.lower().replace(" ", "-") in a_tag["href"].lower():
            team_link = "https://fbref.com" + a_tag["href"]
            break

    if not team_link:
        print(f"[FBref] Could not find squad link for: {team}")
        return pd.DataFrame()

    try:
        squad_soup = _fbref_get(team_link)
    except Exception as e:
        print(f"[FBref] Squad page error: {e}")
        return pd.DataFrame()

    stats_table = squad_soup.find("table", id=lambda x: x and "stats_standard" in str(x))
    if not stats_table:
        print(f"[FBref] No player stats table found for {team}")
        return pd.DataFrame()

    try:
        df = pd.read_html(str(stats_table))[0]
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(c).strip() for c in df.columns]
        df = df[df.iloc[:, 0] != df.columns[0]]
        return df
    except Exception as e:
        print(f"[FBref] Parse error: {e}")
        return pd.DataFrame()

# --------------------------------------------------
# AGGREGATOR / HIGH‑LEVEL METHODS
# --------------------------------------------------

def get_full_match_context(team_a: str, team_b: str,
                            competition: str = "Premier League",
                            season: str = "2024") -> dict:
    """Pulls all unique stats from each source for a head‑to‑head pairing.

    Returns a dict with keys:
      h2h, standings, form_a, form_b  -> Football‑Data.org
      xg_h2h, xg_season_a, xg_season_b -> Understat
      advanced_squad, players_a, players_b -> FBref
    """
    print(f"\n Fetching full context: {team_a} vs {team_b} | {competition} {season}\n")

    # Football‑Data.org portion
    try:
        h2h       = get_head_to_head_from_api(team_a, team_b, competition, season)
        standings = get_standings_from_api(competition, season)
        upcoming  = get_upcoming_fixtures_from_api(competition, season)
    except Exception:
        h2h = standings = upcoming = pd.DataFrame()

    # Understat portion
    xg_all = get_league_xg(competition, season)
    xg_a   = get_team_xg_rolling(team_a, competition, season)
    xg_b   = get_team_xg_rolling(team_b, competition, season)

    # FBref portion
    team_stats = get_squad_advanced_stats(competition)
    def_stats  = None  # could add defensive stats later
    players_a  = get_player_stats(team_a, competition)
    players_b  = get_player_stats(team_b, competition)

    return {
        'h2h': h2h,
        'standings': standings,
        'upcoming': upcoming,
        'xg_team_a': xg_a,
        'xg_team_b': xg_b,
        'xg_all_matches': xg_all,
        'team_stats': team_stats,
        'defensive_stats': def_stats,
        'players_a': players_a,
        'players_b': players_b,
    }

# helper wrappers around Football‑Data.org API for the aggregator

def _fd_headers():
    return {'X-Auth-Token': FOOTBALL_DATA_API_KEY}


def get_match_results_from_api(team_a: str, team_b: str, competition: str = "Premier League", season: int = 2024) -> pd.DataFrame:
    comp_id = COMPETITION_IDS.get(competition, "PL")
    url = f"https://api.football-data.org/v4/competitions/{comp_id}/matches"
    params = {'season': season, 'status': 'FINISHED'}
    try:
        resp = requests.get(url, headers=_fd_headers(), params=params, timeout=10)
        resp.raise_for_status()
        matches = resp.json().get('matches', [])
    except Exception as e:
        print(f"[Football-Data] Error: {e}")
        return pd.DataFrame()
    rows = []
    for m in matches:
        home = m['homeTeam']['name']
        away = m['awayTeam']['name']
        if not (team_a.lower() in home.lower() or team_a.lower() in away.lower()):
            continue
        if not (team_b.lower() in home.lower() or team_b.lower() in away.lower()):
            continue
        score = m['score']['fullTime']
        hg, ag = score['home'], score['away']
        if hg is None:
            continue
        winner = home if hg > ag else (away if ag > hg else "Draw")
        rows.append({
            "date":        m["utcDate"][:10],
            "home":        home,
            "away":        away,
            "home_goals":  hg,
            "away_goals":  ag,
            "winner":      winner,
            "competition": competition,
        })
    return pd.DataFrame(rows)


def get_head_to_head_from_api(team_a: str, team_b: str, competition: str = "Premier League", season: int = 2024) -> pd.DataFrame:
    df = get_match_results_from_api(team_a, team_b, competition, season)
    return df


def get_standings_from_api(competition: str = "Premier League", season: int = 2024) -> pd.DataFrame:
    comp_id = COMPETITION_IDS.get(competition, "PL")
    url = f"https://api.football-data.org/v4/competitions/{comp_id}/standings"
    params = {'season': season}
    try:
        r = requests.get(url, headers=_fd_headers(), params=params, timeout=10)
        r.raise_for_status()
        table = r.json()['standings'][0]['table']
        rows = []
        for entry in table:
            rows.append({
                'position':      entry['position'],
                'team':          entry['team']['name'],
                'played':        entry['playedGames'],
                'won':           entry['won'],
                'draw':          entry['draw'],
                'lost':          entry['lost'],
                'goals_for':     entry['goalsFor'],
                'goals_against': entry['goalsAgainst'],
                'goal_diff':     entry['goalDifference'],
                'points':        entry['points'],
                'form':          entry.get('form', 'N/A'),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"[Football-Data] standings error: {e}")
        return pd.DataFrame()


def get_upcoming_fixtures_from_api(competition: str = "Premier League", season: int = 2024) -> pd.DataFrame:
    comp_id = COMPETITION_IDS.get(competition, "PL")
    url = f"https://api.football-data.org/v4/competitions/{comp_id}/matches"
    params = {'season': season, 'status': 'SCHEDULED'}
    try:
        r = requests.get(url, headers=_fd_headers(), params=params, timeout=10)
        r.raise_for_status()
        matches = r.json().get('matches', [])
        rows = [{'date': m['utcDate'][:10],
                 'home': m['homeTeam']['name'],
                 'away': m['awayTeam']['name'],
                 'matchday': m['matchday']} for m in matches]
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"[Football-Data] fixtures error: {e}")
        return pd.DataFrame()
