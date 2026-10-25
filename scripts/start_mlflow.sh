#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec .venv-mlflow/bin/mlflow server --backend-store-uri sqlite:///.mlflow/mlflow.db --host 127.0.0.1 --port 5001
