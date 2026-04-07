#!/bin/bash
# readerme nightly curation + auto-deploy
cd /Users/jorgegalindo/Desktop/projects/readerme

echo "$(date): nightly start" >> data/nightly.log

.venv/bin/python nightly.py >> data/nightly.log 2>&1
.venv/bin/python spain.py >> data/nightly.log 2>&1
.venv/bin/python polls.py >> data/nightly.log 2>&1
.venv/bin/python markets.py >> data/nightly.log 2>&1

# Auto-commit and push data to trigger Render redeploy
git add data/curated.json data/spain.json data/polls.json data/markets.json data/feedback.json data/scores_cache.json data/seen_intl.json data/feedback_processed.json data/briefing.mp3 data/briefing.txt 2>/dev/null
git commit -m "nightly: $(date '+%Y-%m-%d %H:%M')" --allow-empty-message 2>/dev/null
git push origin main >> data/nightly.log 2>&1

echo "$(date): nightly done" >> data/nightly.log
