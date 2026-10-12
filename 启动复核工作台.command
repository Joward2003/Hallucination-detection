#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print '缺少项目虚拟环境，请先按 README 中的安装命令准备环境。'
  read 'reply?按 Enter 退出'
  exit 1
fi
if curl -fsS http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
  open http://127.0.0.1:8000/dashboard
  exit 0
fi
(for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
    open http://127.0.0.1:8000/dashboard
    break
  fi
  sleep 1
done) &
export PYTHONPATH="$PWD/src"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
exec .venv/bin/python -m uvicorn credit_review.api.server:app --host 127.0.0.1 --port 8000
