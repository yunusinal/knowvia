#!/usr/bin/env bash
# Konteyner açılışı: demo verisini hazırla, sonra API ve arayüzü başlat.
# Seed adımları API'den ÖNCE çalışır: Qdrant local klasörünü aynı anda tek süreç açabilir.
set -euo pipefail

python -m scripts.seed_users
# İlk açılışta embedding modeli (~2.3 GB) indirilir; sonraki açılışlarda var olan belgeler atlanır.
python -m scripts.seed_demo_documents

# Tek worker: Qdrant local kilidi ve bellekteki istek sınırları tek süreç varsayar.
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 &
api=$!
streamlit run frontend/streamlit_app.py \
    --server.address 0.0.0.0 --server.port 8501 --server.headless true \n    --server.fileWatcherType none --server.runOnSave false &  # sunucuda kod değişmez; izleme CPU harcar
ui=$!

trap 'kill -TERM "$api" "$ui" 2>/dev/null' TERM INT
# Biri durursa konteyner de durur; restart politikası ikisini birlikte yeniden başlatır.
wait -n "$api" "$ui"
kill -TERM "$api" "$ui" 2>/dev/null || true
exit 1
