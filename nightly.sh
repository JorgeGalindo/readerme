#!/bin/bash
# readerme nightly curation + auto-deploy
cd /Users/jorgegalindo/Desktop/projects/readerme

PYTHON=/Users/jorgegalindo/Desktop/projects/readerme/.venv/bin/python

echo "$(date): nightly start" >> data/nightly.log

$PYTHON nightly.py >> data/nightly.log 2>&1
$PYTHON spain.py >> data/nightly.log 2>&1
$PYTHON polls.py >> data/nightly.log 2>&1
$PYTHON markets.py >> data/nightly.log 2>&1

# Auto-commit and push data to trigger Render redeploy
git add data/curated.json data/spain.json data/polls.json data/markets.json data/scores_cache.json data/seen_intl.json data/briefing.mp3 data/briefing.txt 2>/dev/null
git commit -m "nightly: $(date '+%Y-%m-%d %H:%M')" --allow-empty-message 2>/dev/null
git push origin main >> data/nightly.log 2>&1

echo "$(date): nightly done" >> data/nightly.log
