#!/bin/bash
set -e

echo "=== Outreach Command Center Container Starting ==="

# If FORCE_RESET_DB=1 or database file does not exist, check/download initial_db snapshot
if [ "$FORCE_RESET_DB" = "1" ]; then
    echo "FORCE_RESET_DB=1 requested. Downloading initial_db snapshot from GCS..."
    python3 -c "
from google.cloud import storage
import os
client = storage.Client()
bucket = client.bucket('outreach-app-data-946216882779')
blob = bucket.blob('initial_db/app_data.db')
if blob.exists():
    os.makedirs('/app/app_data', exist_ok=True)
    blob.download_to_filename('/app/app_data/app_data.db')
    print('Initial database snapshot (11MB) downloaded successfully.')
else:
    print('WARNING: initial_db/app_data.db not found in bucket!')
" || true
elif [ ! -f /app/app_data/app_data.db ]; then
    echo "Checking for existing Litestream replica in GCS..."
    litestream restore -if-replica-exists -config /app/litestream.yml /app/app_data/app_data.db || true
    
    if [ ! -f /app/app_data/app_data.db ]; then
        echo "No replica found. Downloading initial database snapshot from GCS..."
        python3 -c "
from google.cloud import storage
import os
client = storage.Client()
bucket = client.bucket('outreach-app-data-946216882779')
blob = bucket.blob('initial_db/app_data.db')
if blob.exists():
    os.makedirs('/app/app_data', exist_ok=True)
    blob.download_to_filename('/app/app_data/app_data.db')
    print('Initial database snapshot downloaded successfully.')
" || true
    fi
fi

# Synchronize LinkedIn cookie files from GCS
echo "Syncing cookies from GCS..."
python3 -c "
from google.cloud import storage
import os
os.makedirs('/app/cookies_files', exist_ok=True)
client = storage.Client()
bucket = client.bucket('outreach-app-data-946216882779')
for blob in bucket.list_blobs(prefix='cookies_files/'):
    if not blob.name.endswith('/'):
        dest = os.path.join('/app', blob.name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        blob.download_to_filename(dest)
        print(f'Downloaded {dest}')
print('Cookie sync complete.')
" || true

PORT="${PORT:-8080}"
echo "Starting Litestream replication and Uvicorn on port $PORT..."

# Start Litestream replication and Uvicorn
exec litestream replicate -config /app/litestream.yml --exec "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
