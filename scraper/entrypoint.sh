#!/bin/sh
set -e

cd /app
/app/.venv/bin/python main.py >> /var/log/scraper.log 2>&1

cron -f
