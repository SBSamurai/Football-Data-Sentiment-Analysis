def generate_explanation(team_a, team_b, actual_result, sentiment_summary, stats_a, stats_b, post_match_sentiment=None, post_match_samples=None):
    dominant = max(sentiment_summary, key=sentiment_summary.get)
    pos = sentiment_summary.get('Positive', 0)
    neg = sentiment_summary.get('Negative', 0)

    result_winner = actual_result.split()[0]  # first word = winner
    sentiment_aligned = (dominant == 'Positive' and result_winner == team_a) or (dominant == 'Negative' and result_winner == team_b)

    # Quantitative analysis
    quant_explanation = f"""
**Quantitative Analysis:**
- **{team_a} Recent Performance** (last {stats_a['matches']} matches): {stats_a['wins']} wins, {stats_a['losses']} losses, {stats_a['draws']} draws. Goals: {stats_a['goals_for']} scored, {stats_a['goals_against']} conceded.
- **{team_b} Recent Performance** (last {stats_b['matches']} matches): {stats_b['wins']} wins, {stats_b['losses']} losses, {stats_b['draws']} draws. Goals: {stats_b['goals_for']} scored, {stats_b['goals_against']} conceded.
"""
    # add expected‑goals information if present
    if 'avg_xg_for' in stats_a and 'avg_xg_for' in stats_b:
        quant_explanation += f"\n- **xG Form (last {stats_a['matches']}):** {team_a} averaged {stats_a['avg_xg_for']:.2f} xG vs {stats_b['avg_xg_for']:.2f} for {team_b}." + "\n"
    # compute a human-readable summary of relative form
    if abs(stats_a['wins'] - stats_b['wins']) <= 1:
        form_summary = 'both teams were evenly matched'
    else:
        stronger = team_a if stats_a['wins'] > stats_b['wins'] else team_b
        form_summary = f"{stronger} had a stronger recent form"
    quant_explanation += f"\nThe statistics show that {form_summary}.\n"

    # Qualitative analysis
    qual_explanation = f"""
**Qualitative Analysis:**
- **Fan Sentiment:** YouTube comments for this match were {pos}% Positive and {neg}% Negative. The overall fan sentiment was **{dominant}**.
"""
    if post_match_sentiment:
        post_pos = post_match_sentiment.get('Positive', 0)
        post_neg = post_match_sentiment.get('Negative', 0)
        post_dominant = max(post_match_sentiment, key=post_match_sentiment.get)
        qual_explanation += f"- **Official Post-Match Sentiment:** Analysis from the league's official channel showed {post_pos}% Positive and {post_neg}% Negative sentiment, with **{post_dominant}** overall tone."

    # Conclusion
    conclusion = f"""
**Conclusion:**
The match result {'aligns with' if sentiment_aligned else 'contrasts with'} the pre-match fan sentiment. 
Quantitatively, {'the stronger performing team won' if (stats_a['wins'] > stats_b['wins'] and result_winner == team_a) or (stats_b['wins'] > stats_a['wins'] and result_winner == team_b) else 'form did not directly predict the outcome'}.
"""
    # add xG evaluation
    if 'avg_xg_for' in stats_a and 'avg_xg_for' in stats_b:
        xg_adv = stats_a['avg_xg_for'] - stats_b['avg_xg_for']
        winner_xg = team_a if xg_adv > 0 else team_b if xg_adv < 0 else 'neither'
        xg_sentence = f" The expected‑goals averages ({stats_a['avg_xg_for']:.2f} vs {stats_b['avg_xg_for']:.2f}) "
        if winner_xg == result_winner:
            xg_sentence += f"also favoured {result_winner}, which matches the actual outcome."
        elif winner_xg == 'neither':
            xg_sentence += "were identical, making the match difficult to call."
        else:
            xg_sentence += f"favoured {winner_xg}, which contrasts with the result."
        conclusion += xg_sentence
    if post_match_sentiment:
        post_dominant = max(post_match_sentiment, key=post_match_sentiment.get)
        post_pos = post_match_sentiment.get('Positive', 0)
        post_aligned = (post_dominant == 'Positive' and result_winner == team_a) or (post_dominant == 'Negative' and result_winner == team_b)
        conclusion += f"Qualitatively, the official post-match analysis showed {post_pos}% positive sentiment, indicating that {'the winning team was praised' if post_aligned and result_winner != 'Draw' else 'the outcome was controversial' if not post_aligned else 'the draw was well-received'}."
        if post_match_samples:
            conclusion += "\n\n**Sample Post-Match Comments:**\n"
            for i, sample in enumerate(post_match_samples[:2], 1):  # Show up to 2 positive comments
                conclusion += f"{i}. \"{sample}...\"\n"
    else:
        conclusion += "Qualitatively, the sentiment analysis provides insights into fan expectations and reactions."

    conclusion += "\n\nThis combined analysis helps explain the match outcome from both statistical and perceptual perspectives."

    explanation = f"""
**Match:** {team_a} vs {team_b}

**Result:** {actual_result}

{qual_explanation.strip()}

{quant_explanation.strip()}

{conclusion.strip()}
"""
    return explanation