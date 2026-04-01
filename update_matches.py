import requests
import pandas as pd
from datetime import datetime, timedelta
import sys
import os
import toml

# Try to import streamlit 
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

# third‑party helper from our own library
from historical_data import enrich_matches_with_understat

# API details
BASE_URL = 'https://api.football-data.org/v4'

# Get API key from multiple sources (in order of priority)
API_KEY = None

# 1. Try Streamlit secrets (when running in Streamlit context)
if STREAMLIT_AVAILABLE:
    try:
        API_KEY = st.secrets.get('FOOTBALL_DATA_API_KEY', '')
    except:
        API_KEY = ''

# 2. Try environment variable
if not API_KEY:
    API_KEY = os.environ.get('FOOTBALL_DATA_API_KEY', '')

# 3. Try reading from .streamlit/secrets.toml directly (for standalone usage)
if not API_KEY:
    secrets_path = '.streamlit/secrets.toml'
    if os.path.exists(secrets_path):
        try:
            secrets = toml.load(secrets_path)
            API_KEY = secrets.get('FOOTBALL_DATA_API_KEY', '')
        except Exception as e:
            pass

# 4. Try command-line argument (will be set later if provided, this one I will use it to upgrade the project in degree)
if not API_KEY:
    API_KEY = input('📋 Enter your Football-Data.org API key: ')

if not API_KEY or API_KEY == 'YOUR_FOOTBALL_DATA_API_KEY_HERE':
    print("❌ ERROR: FOOTBALL_DATA_API_KEY not configured")
    print("   Please set your API key via:")
    print("   1. .streamlit/secrets.toml (Streamlit app & standalone)")
    print("   2. FOOTBALL_DATA_API_KEY environment variable")
    print("   3. python update_matches.py --api-key YOUR_KEY")
    sys.exit(1)

headers = {'X-Auth-Token': API_KEY}

# Major leagues 
LEAGUES = ['PL', 'PD', 'BL1', 'SA', 'FL1', 'CL']  # Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League

def fetch_matches(league_code, seasons=None):
    """Fetch matches for a league across multiple seasons (most recent first)."""
    if seasons is None:
        # Get current year and previous year for comprehensive recent match data
        current_year = datetime.now().year
        seasons = [current_year, current_year - 1]  # Current season and last season
    
    all_matches = []
    for season in seasons:
        url = f'{BASE_URL}/competitions/{league_code}/matches?season={season}'
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                matches = response.json()['matches']
                all_matches.extend(matches)
                print(f"✓ Fetched {len(matches)} matches for {league_code} season {season}")
            elif response.status_code == 404:
                print(f"⚠ League {league_code} not found for season {season} (404)")
            else:
                print(f"✗ Error fetching {league_code} season {season}: {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"✗ Timeout fetching {league_code} season {season} (connection timeout)")
        except requests.exceptions.ConnectionError as e:
            print(f"✗ Connection error fetching {league_code} season {season}: {str(e)}")
        except Exception as e:
            print(f"✗ Unexpected error fetching {league_code} season {season}: {str(e)}")
    return all_matches

def process_match(match):
    """Extract relevant data from a match dict."""
    home = match['homeTeam']['name']
    away = match['awayTeam']['name']
    date = match['utcDate'][:10]  # YYYY-MM-DD
    home_score = match.get('score', {}).get('fullTime', {}).get('home', None)
    away_score = match.get('score', {}).get('fullTime', {}).get('away', None)
    status = match['status']
    competition = match['competition']['name']
    
    if home_score is not None and away_score is not None:
        if home_score > away_score:
            winner = home
        elif away_score > home_score:
            winner = away
        else:
            winner = 'Draw'
    else:
        winner = None  # Match not played
    
    return {
        'date': date,
        'team_a': home,
        'team_b': away,
        'score_a': home_score,
        'score_b': away_score,
        'competition': competition,
        'winner': winner
    }

def update_matches_csv(export_excel=False):
    """Fetch and update matches.csv with recent season data.
    
    Args:
        export_excel (bool): If True, also export data to matches.xlsx
    """
    print("\n🔄 Fetching recent matches from major leagues...")
    all_matches = []
    for league in LEAGUES:
        matches = fetch_matches(league)
        for match in matches:
            processed = process_match(match)
            if processed['winner'] is not None:  # Only include played matches
                all_matches.append(processed)
    
    if all_matches:
        df_new = pd.DataFrame(all_matches)
        # cast score columns to Int64 to remain consistent when written
        for col in ['score_a','score_b']:
            if col in df_new.columns:
                df_new[col] = pd.to_numeric(df_new[col], errors='coerce').astype('Int64')

        # try to enrich the freshly fetched matches with Understat xG/forecast
        try:
            df_new = enrich_matches_with_understat(df_new)
        except Exception:
            pass
        # Sort by date descending
        df_new = df_new.sort_values('date', ascending=False)
        
        try:
            df_existing = pd.read_csv('data/matches.csv')
            # Avoid duplicates by date, team_a, team_b
            df_combined = pd.concat([df_new, df_existing]).drop_duplicates(subset=['date', 'team_a', 'team_b'], keep='first')
            df_combined = df_combined.sort_values('date', ascending=False)
        except FileNotFoundError:
            df_combined = df_new
        
        try:
            df_combined.to_csv('data/matches.csv', index=False)
            print(f"✓ Updated CSV: data/matches.csv")
            
            # run the duplicate-cleaner to ensure CSV is tidy
            try:
                from historical_data import _clean_duplicates
                df_combined = _clean_duplicates(df_combined)
            except ImportError:
                pass
            
            # Export to Excel if requested
            if export_excel:
                try:
                    df_combined.to_excel('data/matches.xlsx', index=False)
                    print(f"✓ Updated Excel: data/matches.xlsx")
                except ImportError:
                    print("⚠ Warning: openpyxl not installed. Skipping Excel export.")
                except Exception as e:
                    print(f"⚠ Warning: Could not write Excel file: {e}")
            
            print(f"\n✅ Successfully updated matches database")
            print(f"  - Total matches: {len(df_combined)}")
            print(f"  - Leagues covered: {', '.join(sorted(df_combined['competition'].unique()))}")
            print(f"  - Date range: {df_combined['date'].max()} to {df_combined['date'].min()}")
        except PermissionError:
            print("❌ Permission denied: Unable to write to data/matches.csv. Please close any applications that might be using the file (e.g., the Streamlit app) and try again.")
        except Exception as e:
            print(f"❌ Error writing to CSV: {e}")
    else:
        print("❌ No new matches fetched. Check your API key and internet connection.")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Update football match database from Football-Data.org API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python update_matches.py                 # Update CSV only
  python update_matches.py --excel         # Update CSV and Excel
  
Environment Variables:
  FOOTBALL_DATA_API_KEY                    # Alternative to --api-key flag
        """
    )
    
    parser.add_argument(
        '--excel',
        action='store_true',
        help='Also export data to matches.xlsx'
    )
    parser.add_argument(
        '--api-key',
        type=str,
        help='Football-Data.org API key (or use FOOTBALL_DATA_API_KEY env var)'
    )
    
    args = parser.parse_args()
    
    # Override API key if provided via command line
    if args.api_key:
        globals()['API_KEY'] = args.api_key
        headers['X-Auth-Token'] = args.api_key
    
    update_matches_csv(export_excel=args.excel)