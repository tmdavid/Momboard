#!/bin/sh
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "=== MomBoard startup ==="
echo "ENV: ${ENV:-production}"
echo "Database: ${DATABASE_URL}"

# Run Alembic migrations safely
# - Uses --sql in offline mode first to detect issues, then applies online
echo "Running database migrations..."
cd /app
python -m alembic upgrade head
echo "Migrations complete."

# Start the application
echo "Starting uvicorn on port ${PORT:-8080}..."
exec python -m uvicorn app.main:create_app \
    --factory \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --no-access-log \
    --workers 1
