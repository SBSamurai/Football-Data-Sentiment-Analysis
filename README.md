# Game Outcome Reasoning System

Evidence-Based Analysis Using YouTube Sentiment

## Overview

This Streamlit application analyzes football match outcomes by combining YouTube comment sentiment analysis with historical match data. It provides evidence-based explanations for why teams win or lose based on fan sentiment and head-to-head statistics.

## Features

- **YouTube Video Discovery**: Automatically finds match highlight videos
- **Comment Collection**: Fetches and preprocesses YouTube comments
- **Sentiment Analysis**: Uses RoBERTa model trained on social media text
- **Official Post-Match Analysis**: Fetches sentiment from league official channels
- **Recent Team Performance**: Shows last 5 matches for each team (most recent fixtures, not historical two‑year old games)
- **Quantitative Statistics**: Analyzes wins/losses/draws and goals for last 20 matches
- **Expected‑goals / xG**: Understat data is pulled during updates and stored in the database; explanations take xG into account when available
- **Optional Advanced Stats**: FBref scrapers are included for future work (pressing, progressive passes, etc.)
- **Qualitative & Quantitative Explanations**: Combines sentiment and stats for comprehensive analysis
- **Interactive Dashboard**: Clean Streamlit UI with metrics, charts, and expandable sections

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## YouTube API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create credentials (API Key)
5. Copy the API key to `.streamlit/secrets.toml`:
   ```
   YOUTUBE_API_KEY = "your-actual-api-key-here"
   ```

## Football Data API Setup

1. Go to [Football-Data.org](https://www.football-data.org/client/register)
2. Register for a free account
3. Get your API token
4. Add to `.streamlit/secrets.toml`:
   ```
   FOOTBALL_DATA_API_KEY = "your-football-data-api-key-here"
   ```

## Updating Match Data

To automatically update `data/matches.csv` with recent matches from major leagues:

```
python update_matches.py
```

This fetches completed matches from Premier League, La Liga, Bundesliga, Serie A, and Ligue 1 for the current season and appends new matches to the CSV.  During the same run the script will also pull Understat expected‑goal (xG) and pre‑match forecast information and merge those columns into the CSV so that the dashboard can reference them.

> **Maintenance**: the update routine automatically removes any duplicate fixtures before
> writing the files, but if you ever need to clean the database manually you can run:
> ```python
> from historical_data import remove_duplicate_matches_files
> remove_duplicate_matches_files()
> ```

## Usage

Run the application:
```
streamlit run app.py
```

Open the provided URL in your browser. Fill in:
- Team A and Team B names
- Match date
- Competition (Premier League, La Liga, etc.)

Click "Analyze Outcome" to run the full analysis pipeline. The dashboard will automatically:

- fetch the latest recorded head‑to‑head result between the teams and display it
- use that result’s date when searching for the highlight video (so qualitative & quantitative data align)

Click "Analyze Outcome" to run the full analysis pipeline.

## Project Structure

```
project/
├── app.py                   # Main Streamlit application
├── youtube_scraper.py       # YouTube API integration
├── preprocessor.py          # Text cleaning and preprocessing
├── sentiment.py             # Sentiment analysis with RoBERTa
├── historical_data.py       # Match data loading and queries
├── explainer.py             # Explanation generation
├── data/
│   └── matches.csv          # Historical match results
├── .streamlit/
│   └── secrets.toml         # API keys (not committed)
└── requirements.txt         # Python dependencies
```

## Deployment

### Streamlit Community Cloud (Free)

1. Push to GitHub repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub account
4. Select repository and set main file to `app.py`
5. Add `YOUTUBE_API_KEY` in Secrets section
6. Deploy

## Data Sources

- **Sentiment Data**: YouTube comments from match highlight videos
- **Historical Data**: Sample Premier League matches (expand with real data from Football-Data.org)

## Model Details

- **Sentiment Model**: cardiffnlp/twitter-roberta-base-sentiment-latest
- **Processing**: Batch processing with truncation for efficiency
- **Output**: Positive/Neutral/Negative classification with confidence scores

## Limitations

- Requires YouTube API key (free quota: 10,000 units/day)
- Sentiment analysis may take 30-60 seconds for 200 comments
- Historical data is sample; use real datasets for production

## Academic Contribution

This project demonstrates the correlation between pre-match fan sentiment and actual match outcomes, providing a novel approach to sports analytics using social media data.