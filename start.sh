#!/bin/bash
# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "Starting The AfterCall..."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
