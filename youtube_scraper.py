import streamlit as st
from googleapiclient.discovery import build

API_KEY = st.secrets.get('YOUTUBE_API_KEY', 'YOUR_YOUTUBE_API_KEY_HERE')

# Official league channels for post-match analysis
LEAGUE_CHANNELS = {
    'Premier League': '@premierleague',  # English Premier League, Premier League (Official), 9.33M subs
    'La Liga': '@LaLiga',                # La Liga, LALIGA (Official), 14.1M subs
    'Serie A': '@seriea',                # Serie A, Serie A (Official), 10.2M subs
    'Bundesliga': '@bundesliga',         # Bundesliga, Bundesliga (Official), 5.56M subs
    'Ligue 1': 'UCQsH5XtIc9hONE1BQjucM0g',  # Ligue 1 McDonald's (Official), 3.29M subs
    'MLS': '@mls',                       # Major League Soccer (Official), 2.14M subs
    'UEFA Champions League': '@UEFA'     # UEFA (Official), 6.47M subs
}

def get_channel_id(handle):
    """Get channel ID from handle."""
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    response = youtube.channels().list(
        part='id',
        forHandle=handle
    ).execute()
    if response['items']:
        return response['items'][0]['id']
    return None

def search_match_video(team_a, team_b, date):
    """Find the YouTube video ID for a match highlight, filtered by date."""
    from datetime import datetime, timedelta
    
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    query = f'{team_a} vs {team_b} highlights'
    
    # Parse date and create a search window (match day + 7 days after)
    match_date = datetime.strptime(str(date), '%Y-%m-%d')
    published_after = match_date.isoformat() + 'Z'
    published_before = (match_date + timedelta(days=7)).isoformat() + 'Z'
    
    response = youtube.search().list(
        q=query, 
        part='snippet', 
        maxResults=5, 
        type='video',
        publishedAfter=published_after,
        publishedBefore=published_before,
        order='relevance'
    ).execute()
    if not response['items']:
        return None  # No video found — handle gracefully in UI
    return response['items'][0]['id']['videoId']

def search_post_match_video(team_a, team_b, competition, match_date=None):
    """Find post-match analysis video from official channel."""
    channel_handle = LEAGUE_CHANNELS.get(competition)
    if not channel_handle:
        return None
    
    if channel_handle.startswith('@'):
        channel_id = get_channel_id(channel_handle)
    else:
        channel_id = channel_handle
    
    if not channel_id:
        return None
    
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    query = f'{team_a} vs {team_b} post match analysis'
    
    # Build search parameters
    search_params = {
        'q': query,
        'part': 'snippet',
        'maxResults': 1,
        'type': 'video',
        'channelId': channel_id
    }
    
    # Add date filtering if match_date is provided
    if match_date:
        from datetime import datetime, timedelta
        try:
            match_date_obj = datetime.strptime(str(match_date), '%Y-%m-%d')
            published_after = match_date_obj.isoformat() + 'Z'
            published_before = (match_date_obj + timedelta(days=7)).isoformat() + 'Z'
            search_params['publishedAfter'] = published_after
            search_params['publishedBefore'] = published_before
        except (ValueError, TypeError):
            # If date parsing fails, continue without date filtering
            pass
    
    response = youtube.search().list(**search_params).execute()
    if not response['items']:
        return None
    return response['items'][0]['id']['videoId']

def get_comments(video_id, max_comments=300):
    """Fetch top-level comments from a YouTube video."""
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    comments = []
    request = youtube.commentThreads().list(
        part='snippet', videoId=video_id,
        maxResults=100, order='relevance'
    )
    while request and len(comments) < max_comments:
        try:
            response = request.execute()
        except Exception:
            break  # Comments may be disabled on this video
        for item in response['items']:
            text = item['snippet']['topLevelComment']['snippet']['textDisplay']
            comments.append(text)
        request = youtube.commentThreads().list_next(
            request, response
        )
    return comments