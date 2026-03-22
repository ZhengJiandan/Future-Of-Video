#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMAND="${1:-}"

case "$COMMAND" in
  backend)
    cd "$ROOT_DIR/backend"
    exec uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8080}"
    ;;
  worker)
    cd "$ROOT_DIR/backend"
    exec celery -A app.celery_app:celery_app worker --loglevel=info --concurrency=2
    ;;
  frontend)
    cd "$ROOT_DIR/frontend"
    exec npm run dev
    ;;
  build-frontend)
    cd "$ROOT_DIR/frontend"
    exec npm run build
    ;;
  check-backend)
    cd "$ROOT_DIR"
    exec python3 -m py_compile \
      backend/app/main.py \
      backend/app/celery_app.py \
      backend/app/api/api.py \
      backend/app/api/endpoints/script_pipeline.py \
      backend/app/services/pipeline_workflow.py \
      backend/app/workers/render_tasks.py \
      backend/app/services/script_generator.py \
      backend/app/services/script_splitter.py \
      backend/app/services/video_merger.py \
      backend/app/services/doubao_llm.py \
      backend/app/services/doubao_video_official.py \
      backend/app/services/nanobanana_pro.py \
      backend/app/services/pipeline_character_library.py \
      backend/app/services/pipeline_scene_library.py \
      backend/app/models/pipeline_character_profile.py \
      backend/app/models/pipeline_scene_profile.py
    ;;
  *)
    echo "Usage:"
    echo "  bash dev.sh backend"
    echo "  bash dev.sh worker"
    echo "  bash dev.sh frontend"
    echo "  bash dev.sh build-frontend"
    echo "  bash dev.sh check-backend"
    exit 1
    ;;
esac
