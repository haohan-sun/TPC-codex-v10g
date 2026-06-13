#!/usr/bin/env bash
# 将 tpc_agent 提交并推送到 GitHub（默认 origin/main）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

REMOTE="${TPC_GITHUB_REMOTE:-origin}"
BRANCH="${TPC_GITHUB_BRANCH:-main}"
MSG="${1:-chore: sync local changes}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "未初始化 git，请先运行: bash scripts/setup_github_repo.sh"
  exit 1
fi

if ! git remote get-url "${REMOTE}" >/dev/null 2>&1; then
  echo "未配置 remote ${REMOTE}，请先运行: bash scripts/setup_github_repo.sh"
  exit 1
fi

git add -A
if git diff --cached --quiet; then
  echo "无变更，跳过提交。"
else
  git commit -m "${MSG}"
fi

echo "推送到 ${REMOTE}/${BRANCH} ..."
git push -u "${REMOTE}" "${BRANCH}"
echo "完成: https://github.com/KevinYin856/TPC"
