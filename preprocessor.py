import re

def clean_comment(text):
    text = text.lower()
    text = re.sub(r'http\S+', '', text)          # remove URLs
    text = re.sub(r'<[^>]+>', '', text)           # remove HTML tags
    text = re.sub(r'\s+', ' ', text).strip()     # collapse whitespace
    return text

def preprocess(comments):
    cleaned = [clean_comment(c) for c in comments]
    # Drop comments that are too short to carry meaning
    return [c for c in cleaned if len(c.strip()) > 4]