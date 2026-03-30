#!/bin/bash
set -e

echo "Starting Armageddon API..."

# Start infrastructure
docker compose up -d

# Wait for postgres
echo "Waiting for Postgres..."
until docker exec $(docker ps -qf "name=postgres") pg_isready -U armageddon > /dev/null 2>&1; do
    sleep 1
done
echo "Postgres ready."

# Run migrations
alembic upgrade head

# Create storage dirs
mkdir -p storage/{uploads,gameplay,outputs}

echo ""
echo "Start the API:     uvicorn app.main:app --reload --port 8000"
echo "Start the worker:  celery -A app.worker worker --loglevel=info"
echo "Start Stripe CLI:  stripe listen --forward-to localhost:8000/billing/webhook"
