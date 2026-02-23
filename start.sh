#!/bin/bash
echo '[START] Launching Management Console on port 8081...'
python management_console.py &

echo '[START] Launching FastAPI on port 8080...'
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
