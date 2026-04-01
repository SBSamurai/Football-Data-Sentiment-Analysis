import streamlit as st
import pandas as pd
import altair as alt
from youtube_scraper   import search_match_video, get_comments, search_post_match_video
from preprocessor      import preprocess
from sentiment         import analyze, summarize, analyze_form_trend, calculate_form_outcome_correlation
from historical_data   import load_matches, get_recent_form, get_team_stats, get_last_result, get_head_to_head, get_available_teams, get_available_competitions, normalize_team
from update_matches      import update_matches_csv
from explainer         import generate_explanation

#set the title and icon for the Streamlit app
st.set_page_config(page_title='Game Outcome Reasoning', page_icon='⚽')
st.title('⚽  Game Outcome Reasoning System')
st.caption('Evidence-Based Analysis Using YouTube Sentiment')

# ── Query Form ───────────────────────────────────────────
# Pre-load data for team suggestions (load once and reuse)
df_for_suggestions = load_matches(enrich=False) # load without xG to speed up suggestions
all_competitions = get_available_competitions(df_for_suggestions)
all_competitions = [comp for comp in all_competitions if comp != 'PL']

# League selector at the top
selected_league = st.selectbox(
    'Select League (optional - filters team suggestions)',
    ['All Leagues'] + all_competitions,
    index=0
)

# Get teams for the selected league
if selected_league == 'All Leagues':
    available_teams = get_available_teams(df_for_suggestions)
else:
    available_teams = get_available_teams(df_for_suggestions, competition=selected_league)

# Add empty option and sort
team_options = [''] + available_teams

with st.form('query_form'):
    col1, col2 = st.columns(2)
    
    team_a = col1.selectbox(
        'Team A',
        team_options,
        index=0,
        help='Select or start typing to filter teams'
    )
    
    team_b = col2.selectbox(
        'Team B',
        team_options,
        index=0,
        help='Select or start typing to filter teams'
    )
    
    match_date = st.date_input('Match Date', value=None)

    if selected_league != 'All Leagues':
        competition = selected_league
        st.info(f'Using league: {competition}')
    else:
        comp_options = sorted(all_competitions) if all_competitions else \
            ['Premier League', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1', 'Champions League']
        competition = st.selectbox('Competition (optional)', comp_options, index=0 if comp_options else None)
    
    submitted = st.form_submit_button('🔍  Analyze Outcome')

if submitted:
    team_a_normalized = normalize_team(team_a, remove_numbers=True)
    team_b_normalized = normalize_team(team_b, remove_numbers=True)
    
    if not team_a or not team_b:
        st.error('Please select both Team A and Team B')
        st.stop()

    df = load_matches()

    missing = []
    for t in (team_a, team_b):
        if not ((df_for_suggestions.team_a == t) | (df_for_suggestions.team_b == t)).any():
            missing.append(t)
    if missing:
        with st.spinner('Fetching statistics for the teams...'):
            update_matches_csv()
        df = load_matches()

        # Check if teams are still missing after update
        still_missing = []
        for t in (team_a, team_b):
            if not ((df.team_a == t) | (df.team_b == t)).any():
                still_missing.append(t)
        if still_missing:
            st.error('Sorry, no records found for the entered teams.')
            st.stop()#

    if not match_date:
        latest_match = get_last_result(df, team_a, team_b)
        if latest_match:
            h2h = get_head_to_head(df, team_a, team_b, last_n=1)
            if not h2h.empty:
                match_date = h2h.iloc[0]['date']
                st.info(f"Using latest match: {latest_match} on {match_date}")
            else:
                st.error("No historical match found between these teams.")
                st.stop()
        else:
            with st.spinner('Fetching statistics for the teams...'):
                update_matches_csv()
            df = load_matches()
            latest_match = get_last_result(df, team_a, team_b)
            if latest_match:
                h2h = get_head_to_head(df, team_a, team_b, last_n=1)
                match_date = h2h.iloc[0]['date']
                st.info(f"Using latest match: {latest_match} on {match_date}")
            else:
                st.error("No historical match found between these teams.")
                st.stop()

    # ── Step 0: Compute last result ──────────────────────────────
    last_res = get_last_result(df, team_a, team_b)
    actual_result = last_res or 'Result unavailable'
    if last_res:
        st.info(f"Latest match between {team_a} and {team_b}: {actual_result}")
    else:
        st.warning('No previous meeting found; actual result not available.')

    # ── Validate date and team combination ───────────────────────
    # Check if there was actually a match between these teams on the selected date
    match_exists = (
        ((df.team_a == team_a) & (df.team_b == team_b)) |
        ((df.team_a == team_b) & (df.team_b == team_a))
    ) & (df.date == match_date)
    
    if not match_exists.any():
        st.error('Wrong date and team combination. No match found between these teams on the selected date.')
        st.stop()

    # ── Step 1: Find YouTube match video ─────────────────────────
    match_date_str = match_date.strftime('%Y-%m-%d')

    with st.spinner('Searching YouTube for match video...'):
        video_id = search_match_video(team_a, team_b, match_date_str)
    if not video_id:
        st.error('No YouTube video found. Try a different date.')
        st.stop()
    st.success(f'Video found: youtube.com/watch?v={video_id} (using date {match_date_str})')

    # ── Step 2: Collect Comments ──────────────────────────────────
    with st.spinner('Fetching comments...'):
        raw     = get_comments(video_id, max_comments=200)
        cleaned = preprocess(raw)
    st.info(f'Collected {len(cleaned)} usable comments')

    if len(cleaned) < 10:
        st.warning('Too few comments to analyse reliably.')
        st.stop()

    # ── Step 3: Sentiment Analysis ────────────────────────────────
    with st.spinner('Running sentiment analysis...'):
        results = analyze(cleaned)
        summary = summarize(results)

    st.subheader('📊  Sentiment Analysis Summary')
    c1, c2, c3 = st.columns(3)
    c1.metric('✅  Positive', f"{summary['Positive']}%")
    c2.metric('➖  Neutral',  f"{summary['Neutral']}%")
    c3.metric('❌  Negative', f"{summary['Negative']}%")
    sentiment_data = pd.DataFrame({
        'Sentiment': ['Positive', 'Neutral', 'Negative'],
        'Percentage': [summary['Positive'], summary['Neutral'], summary['Negative']]
    })
    sentiment_chart = alt.Chart(sentiment_data).mark_bar().encode(
        x=alt.X('Sentiment:N', sort=['Positive', 'Neutral', 'Negative'], title='Sentiment'),
        y=alt.Y('Percentage:Q', title='Percentage'),
        color=alt.Color('Sentiment:N', scale=alt.Scale(
            domain=['Positive', 'Neutral', 'Negative'],
            range=['#2ca02c', '#ff7f0e', '#d62728']
        ))
    ).properties(height=280, width=480)
    st.altair_chart(sentiment_chart, use_container_width=True)

    # ── Step 4: Post-Match Analysis Sentiment ─────────────────────
    post_match_sentiment = None
    post_match_samples = [r['comment'][:120] for r in results if r['sentiment'] == 'Positive'][:2]

    with st.spinner('Searching for official post-match analysis...'):
        post_video_id = search_post_match_video(team_a, team_b, competition)
        if post_video_id:
            post_comments = get_comments(post_video_id, max_comments=100)
            if post_comments:
                post_cleaned = preprocess(post_comments)
                if len(post_cleaned) >= 10:
                    post_results = analyze(post_cleaned)
                    post_match_sentiment = summarize(post_results)
                    if not post_match_samples:
                        post_match_samples = [r['comment'][:120] for r in post_results if r['sentiment'] == 'Positive'][:2]
                    st.subheader('📺  Official Post-Match Sentiment')
                    pc1, pc2, pc3 = st.columns(3)
                    pc1.metric('✅  Positive', f"{post_match_sentiment['Positive']}%")
                    pc2.metric('➖  Neutral',  f"{post_match_sentiment['Neutral']}%")
                    pc3.metric('❌  Negative', f"{post_match_sentiment['Negative']}%")

    if post_match_samples:
        st.subheader('📝 Sample Post-Match Comments')
        for idx, comment_text in enumerate(post_match_samples, 1):
            st.write(f"{idx}. {comment_text}")
        st.caption('Showing first two positive comments from the main sample comments.')

    # ── Step 5: Historical Data ───────────────────────────────────
    h2h = get_head_to_head(df, team_a, team_b, last_n=5)
    if 'xg_a' in h2h.columns and not h2h.empty:
        st.subheader('📈  xG in Head‑to‑Head')
        display = h2h[['date','team_a','xg_a','team_b','xg_b']].copy()
        display.columns = ['date','home','xg_home','away','xg_away']
        st.dataframe(display, use_container_width=True)

    st.subheader(f'📁  Recent Form: {team_a} (Last 20 Matches)')
    recent_a = get_recent_form(df, team_a, 20)
    st.dataframe(recent_a, use_container_width=True)

    form_a = analyze_form_trend(recent_a, team_a)
    form_a['team_name'] = team_a
    col1, col2, col3 = st.columns(3)
    col1.metric("Wins", form_a['wins'])
    col2.metric("Draws", form_a['draws'])
    col3.metric("Losses", form_a['losses'])

    form_data_a = pd.DataFrame({
        'Result': ['Wins', 'Draws', 'Losses'],
        'Count': [form_a['wins'], form_a['draws'], form_a['losses']]
    })
    form_chart_a = alt.Chart(form_data_a).mark_bar().encode(
        x=alt.X('Result:N', sort=['Wins', 'Draws', 'Losses'], title='Result'),
        y=alt.Y('Count:Q', title='Matches'),
        color=alt.Color('Result:N', scale=alt.Scale(
            domain=['Wins', 'Draws', 'Losses'],
            range=['#1f77b4', '#ff7f0e', '#2ca02c']
        )),
    ).properties(height=280, width=480)
    st.altair_chart(form_chart_a, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Goals Scored", form_a['goals_for'])
    col2.metric("Goals Conceded", form_a['goals_against'])
    col3.metric("Goal Difference", form_a['goal_diff'])

    st.subheader(f'📁  Recent Form: {team_b} (Last 20 Matches)')
    recent_b = get_recent_form(df, team_b, 20)
    st.dataframe(recent_b, use_container_width=True)

    form_b = analyze_form_trend(recent_b, team_b)
    form_b['team_name'] = team_b
    col1, col2, col3 = st.columns(3)
    col1.metric("Wins", form_b['wins'])
    col2.metric("Draws", form_b['draws'])
    col3.metric("Losses", form_b['losses'])

    form_data_b = pd.DataFrame({
        'Result': ['Wins', 'Draws', 'Losses'],
        'Count': [form_b['wins'], form_b['draws'], form_b['losses']]
    })
    form_chart_b = alt.Chart(form_data_b).mark_bar().encode(
        x=alt.X('Result:N', sort=['Wins', 'Draws', 'Losses'], title='Result'),
        y=alt.Y('Count:Q', title='Matches'),
        color=alt.Color('Result:N', scale=alt.Scale(
            domain=['Wins', 'Draws', 'Losses'],
            range=['#1f77b4', '#ff7f0e', '#2ca02c']
        )),
    ).properties(height=280, width=480)
    st.altair_chart(form_chart_b, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Goals Scored", form_b['goals_for'])
    col2.metric("Goals Conceded", form_b['goals_against'])
    col3.metric("Goal Difference", form_b['goal_diff'])

    # ── Head-to-Head History ──────────────────────────────────────
    st.subheader('🤝  Last 5 Head-to-Head Matches')
    h2h = get_head_to_head(df, team_a, team_b, last_n=5)
    if h2h.empty:
        st.info('No past encounters between these teams in the dataset.')
    else:
        if len(h2h) < 5:
            st.info(f'Only {len(h2h)} historical meetings found; consider updating the dataset.')
        h2h['date'] = pd.to_datetime(h2h['date'])
        h2h = h2h.sort_values('date', ascending=False)
        st.dataframe(h2h[['date','team_a','score_a','team_b','score_b','competition','winner']], use_container_width=True)

    if not h2h.empty:
        h2h_wins_a = int((h2h['winner'] == team_a).sum())
        h2h_wins_b = int((h2h['winner'] == team_b).sum())
        h2h_draws  = int((h2h['winner'] == 'Draw').sum())

        # ── Metric tiles: Team A Wins | Draws | Team B Wins ───────
        col1, col2, col3 = st.columns(3)
        col1.metric(f"{team_a} Wins", h2h_wins_a)
        col2.metric("Draws", h2h_draws)
        col3.metric(f"{team_b} Wins", h2h_wins_b)

        # Same pattern as the form charts — plain string column, sort list matches
        # the metric tile order above: Team A Wins | Draws | Team B Wins
        h2h_chart_data = pd.DataFrame({
            'Result': [f'{team_a} Wins', 'Draws', f'{team_b} Wins'],
            'Count':  [h2h_wins_a, h2h_draws, h2h_wins_b]
        })
        h2h_chart = alt.Chart(h2h_chart_data).mark_bar().encode(
            x=alt.X('Result:N', sort=[f'{team_a} Wins', 'Draws', f'{team_b} Wins'], title='Result'),
            y=alt.Y('Count:Q', title='Matches'),
            color=alt.Color('Result:N', scale=alt.Scale(
                domain=[f'{team_a} Wins', 'Draws', f'{team_b} Wins'],
                range=['#1f77b4', '#ff7f0e', '#2ca02c']
            )),
        ).properties(height=280, width=480)
        st.altair_chart(h2h_chart, use_container_width=True)

    # ── Team Stats Comparison ─────────────────────────────────────
    st.subheader('⚖️  Team Form Comparison')

    comparison_data = pd.DataFrame({
        'Metric': ['Wins', 'Draws', 'Losses', 'Goals For', 'Goals Against', 'Goal Diff'],
        team_a: [form_a['wins'], form_a['draws'], form_a['losses'], form_a['goals_for'], form_a['goals_against'], form_a['goal_diff']],
        team_b: [form_b['wins'], form_b['draws'], form_b['losses'], form_b['goals_for'], form_b['goals_against'], form_b['goal_diff']]
    })
    comparison_long = comparison_data.melt(id_vars='Metric', var_name='Team', value_name='Value')
    metric_order = ['Wins', 'Draws', 'Losses', 'Goals For', 'Goals Against', 'Goal Diff']
    comparison_chart = alt.Chart(comparison_long).mark_bar().encode(
        x=alt.X('Metric:N', sort=metric_order, title='Metric'),
        y=alt.Y('Value:Q', title='Value'),
        color=alt.Color('Team:N', title='Team'),
        xOffset='Team:N'
    ).properties(height=360, width=700)
    st.altair_chart(comparison_chart, use_container_width=True)

    # ── Correlation Analysis: Form vs Outcome ─────────────────────
    st.subheader('📈  Form-to-Outcome Correlation Analysis')

    correlation = calculate_form_outcome_correlation(form_a, form_b, actual_result)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Recent Form Prediction:**")
        if correlation['prediction'] == 'Draw':
            st.info(f"🎯 Based on recent form, a draw is expected (margin: {correlation['predicted_margin']}%).")
        else:
            st.info(f"🎯 Based on recent form, **{correlation['prediction']}** are favored (margin: {correlation['predicted_margin']}%).")
    with col2:
        st.markdown("**Actual Match Outcome:**")
        st.success(f"✅ {actual_result}")

    if correlation['matches']:
        st.markdown(
            f"✅ **CORRELATION CONFIRMED**: Recent form correctly predicted the outcome! "
            f"{correlation['prediction']} had better recent form and won the match."
        )
    else:
        st.markdown(
            f"⚠️ **UPSET**: Form prediction didn't match. {correlation['prediction']} were favored by form, "
            f"but {correlation['actual']} won the match."
        )

    st.markdown("### Detailed Interpretation:")
    interpretation = f"""
- **Offensive Strength**: {correlation['stronger_offense']} has been scoring more goals recently
- **Defensive Strength**: {correlation['stronger_defense']} has conceded fewer goals recently
- **{team_a} Goal Differential**: {correlation['goal_diff_a']:+d} (goals for - goals against)
- **{team_b} Goal Differential**: {correlation['goal_diff_b']:+d} (goals for - goals against)

"""
    if form_a['win_rate'] > form_b['win_rate']:
        interpretation += f"- {team_a} had a **better win rate** ({form_a['win_rate']}%) compared to {team_b} ({form_b['win_rate']}%) over recent form, suggesting superior consistency.\n"
    elif form_b['win_rate'] > form_a['win_rate']:
        interpretation += f"- {team_b} had a **better win rate** ({form_b['win_rate']}%) compared to {team_a} ({form_a['win_rate']}%), indicating stronger recent performance.\n"
    else:
        interpretation += f"- Both teams had **similar win rates** ({form_a['win_rate']}%), suggesting a closely matched fixture.\n"

    if actual_result != 'Result unavailable':
        result_winner = actual_result.split()[0]
        if result_winner == correlation['prediction']:
            interpretation += f"- Fan sentiment favored the form-predicted winner, strengthening the correlation signal."
        else:
            interpretation += f"- The upset suggests other factors (injuries, motivation, tactical changes) may have overridden recent form."

    st.markdown(interpretation)

    # ── Evidence-Based Explanation ────────────────────────────────
    st.subheader('💡  Evidence-Based Explanation')
    stats_a = get_team_stats(df, team_a, 20)
    stats_b = get_team_stats(df, team_b, 20)
    if 'avg_xg_for' in stats_a and 'avg_xg_for' in stats_b:
        xg1 = f"{stats_a['avg_xg_for']:.2f}" if stats_a.get('avg_xg_for') is not None else "n/a"
        xg2 = f"{stats_b['avg_xg_for']:.2f}" if stats_b.get('avg_xg_for') is not None else "n/a"
        c1, c2 = st.columns(2)
        c1.metric(f"{team_a} avg xG", xg1)
        c2.metric(f"{team_b} avg xG", xg2)
    explanation = generate_explanation(
        team_a, team_b, actual_result, summary, stats_a, stats_b, post_match_sentiment, post_match_samples
    )
    st.markdown(explanation)

    # ── Sample Comments ───────────────────────────────────────────
    with st.expander('View sample comments'):
        for r in results[:20]:
            st.write(
                f"**{r['sentiment']}** ({r['confidence']}) — "
                f"{r['comment'][:120]}"
            )
