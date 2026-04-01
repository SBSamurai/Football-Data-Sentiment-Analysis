from transformers import pipeline
import warnings
import logging
import os
import streamlit as st

# Set HF token from Streamlit secrets or environment variable
hf_token = os.environ.get('HF_TOKEN') or st.secrets.get('HF_TOKEN')
if hf_token:
    os.environ['HF_TOKEN'] = hf_token
    os.environ['HUGGINGFACE_HUB_TOKEN'] = hf_token

# Suppress HF Hub warnings and telemetry
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
logging.getLogger("transformers").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*You are sending unauthenticated requests.*")
warnings.filterwarnings("ignore", category=UserWarning, module="transformers")

# Load the model once when the module is imported
sentiment_pipeline = pipeline(
    'sentiment-analysis',
    model='cardiffnlp/twitter-roberta-base-sentiment-latest',
    truncation=True,
    max_length=128,
    token=hf_token  # Use token if available
)

def analyze(comments):
    """Return a list of dicts with comment, sentiment, confidence."""
    results = sentiment_pipeline(comments, batch_size=16)
    labeled = []
    for comment, result in zip(comments, results):
        label = result['label'].capitalize()  # 'positive', 'neutral', 'negative'
        labeled.append({
            'comment':    comment,
            'sentiment':  label,
            'confidence': round(result['score'], 3)
        })
    return labeled

def summarize(labeled_results):
    """Return percentage breakdown of each sentiment class."""
    total = len(labeled_results)
    counts = {'Positive': 0, 'Neutral': 0, 'Negative': 0}
    for r in labeled_results:
        counts[r['sentiment']] = counts.get(r['sentiment'], 0) + 1
    return {k: round(v / total * 100, 1) for k, v in counts.items()}


def confidence_stats(labeled_results):
    """Return mean/median/min/max confidence (0.0-1.0)."""
    if not labeled_results:
        return {'mean': 0.0, 'median': 0.0, 'min': 0.0, 'max': 0.0}
    scores = [float(r['confidence']) for r in labeled_results]
    import statistics
    return {
        'mean': round(statistics.mean(scores), 3),
        'median': round(statistics.median(scores), 3),
        'min': round(min(scores), 3),
        'max': round(max(scores), 3),
    }


def low_confidence_items(labeled_results, threshold=0.6):
    """Return items with confidence at or below threshold."""
    return [r for r in labeled_results if float(r['confidence']) <= threshold]


def _tokenize(comment):
    """Simple clean tokenizer for word-frequency analysis."""
    if not isinstance(comment, str):
        return []
    import re
    tokens = re.findall(r"\b[a-z]{4,}\b", comment.lower())
    return tokens


def top_words_by_sentiment(labeled_results, sentiment='Positive', top_n=10):
    """Return most frequent words for a specific sentiment class."""
    from collections import Counter
    words = []
    for r in labeled_results:
        if r['sentiment'] == sentiment:
            words.extend(_tokenize(r['comment']))
    counts = Counter(words)
    return counts.most_common(top_n)


def analyze_form_trend(recent_matches_df, team_name):
    """
    Analyze recent form as wins/losses/draws trend.
    
    Returns dict with:
    - 'wins': count of wins
    - 'losses': count of losses
    - 'draws': count of draws
    - 'win_rate': percentage wins
    - 'goals_for': total goals scored
    - 'goals_against': total goals conceded
    - 'goal_diff': net goal difference
    """
    if recent_matches_df.empty:
        return {
            'wins': 0, 'losses': 0, 'draws': 0,
            'win_rate': 0, 'goals_for': 0, 'goals_against': 0, 'goal_diff': 0
        }
    
    wins = losses = draws = 0
    goals_for = goals_against = 0
    
    for _, match in recent_matches_df.iterrows():
        is_home = match['team_a'] == team_name
        
        if is_home:
            gf = int(match.get('score_a', 0) or 0)
            ga = int(match.get('score_b', 0) or 0)
        else:
            gf = int(match.get('score_b', 0) or 0)
            ga = int(match.get('score_a', 0) or 0)
        
        goals_for += gf
        goals_against += ga
        
        if match['winner'] == team_name:
            wins += 1
        elif match['winner'] == 'Draw':
            draws += 1
        else:
            losses += 1
    
    total = wins + losses + draws
    win_rate = (wins / total * 100) if total > 0 else 0
    goal_diff = goals_for - goals_against
    
    return {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'win_rate': round(win_rate, 1),
        'goals_for': goals_for,
        'goals_against': goals_against,
        'goal_diff': goal_diff,
        'total_matches': total
    }


def calculate_form_outcome_correlation(recent_form_a, recent_form_b, actual_result):
    """
    Calculate correlation between recent form and match outcome.
    
    Returns dict with correlation metrics and interpretation.
    """
    # Determine actual winner from the result string robustly (e.g., "Barcelona 0-1 Newcastle United")
    result_winner = 'Result unavailable'
    import re
    score_match = re.search(r"(\d+)\s*-\s*(\d+)", actual_result)
    team_a_name = recent_form_a.get('team_name', 'Team A')
    team_b_name = recent_form_b.get('team_name', 'Team B')

    if score_match:
        home_score = int(score_match.group(1))
        away_score = int(score_match.group(2))
        if home_score > away_score:
            result_winner = team_a_name
        elif away_score > home_score:
            result_winner = team_b_name
        else:
            result_winner = 'Draw'
    elif actual_result.strip().lower().startswith('draw'):
        result_winner = 'Draw'
    else:
        # fallback to first token if no score found
        fallback = actual_result.split()[0] if actual_result else 'Result unavailable'
        result_winner = fallback
    
    # Score prediction based on recent form
    a_expected = recent_form_a.get('win_rate', 0)
    b_expected = recent_form_b.get('win_rate', 0)
    
    # Determine form-based prediction
    if a_expected > b_expected:
        predicted_winner = team_a_name
        expected_margin = a_expected - b_expected
    elif b_expected > a_expected:
        predicted_winner = team_b_name
        expected_margin = b_expected - a_expected
    else:
        predicted_winner = 'Draw'
        expected_margin = 0
    
    # Check if prediction matches outcome
    form_predicts_outcome = (predicted_winner == result_winner)
    
    # Calculate goal differential correlation
    a_goal_diff = recent_form_a.get('goal_diff', 0)
    b_goal_diff = recent_form_b.get('goal_diff', 0)
    
    return {
        'prediction': predicted_winner,
        'actual': result_winner,
        'matches': form_predicts_outcome,
        'predicted_margin': round(expected_margin, 1),
        'goal_diff_a': a_goal_diff,
        'goal_diff_b': b_goal_diff,
        'stronger_offense': team_a_name if recent_form_a['goals_for'] > recent_form_b['goals_for'] else team_b_name,
        'stronger_defense': team_a_name if recent_form_a['goals_against'] < recent_form_b['goals_against'] else team_b_name,
    }
