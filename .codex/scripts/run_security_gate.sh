#!/usr/bin/env bash

set -Eeuo pipefail

readonly repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly audit_venv_candidate="$(mktemp -d "${TMPDIR:-/tmp}/gsp-audit-venv.XXXXXX")"
readonly audit_venv_dir="$(cd "${audit_venv_candidate}" && pwd -P)"

cleanup() {
  rm -rf -- "${audit_venv_dir}"
}
trap cleanup EXIT

python3 -m venv "${audit_venv_dir}"
# shellcheck disable=SC1091
source "${audit_venv_dir}/bin/activate"
python -m pip install --upgrade pip "setuptools>=83.0.0" wheel >/dev/null
pip install -r "${repo_root}/backend/requirements.txt" bandit pip-audit >/dev/null
bandit -r "${repo_root}/backend/app" -ll
PIPAPI_PYTHON_LOCATION="${audit_venv_dir}/bin/python" pip-audit --local
deactivate

npm --prefix "${repo_root}/frontend" audit --audit-level=high
