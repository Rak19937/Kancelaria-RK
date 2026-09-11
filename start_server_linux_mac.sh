#!/usr/bin/env sh
cd "$(dirname "$0")"
export SPRAWNIK_HOST=0.0.0.0
export SPRAWNIK_OPEN_BROWSER=0
export SPRAWNIK_AUTO_SHUTDOWN=0
python3 -c "import reportlab" 2>/dev/null || python3 -m pip install -r requirements.txt
python3 app.py
