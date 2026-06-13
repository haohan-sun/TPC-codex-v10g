#!/usr/bin/env bash
# 初始化 git 并关联 https://github.com/KevinYin856/TPC
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

REPO_URL="${TPC_GITHUB_URL:-https://github.com/KevinYin856/TPC.git}"
BRANCH="${TPC_GITHUB_BRANCH:-main}"
INSTALL_HOOK="${TPC_INSTALL_AUTO_PUSH_HOOK:-0}"

if [ ! -d .git ]; then
  git init -b "${BRANCH}"
fi

if git remote get-url origin >/dev/null 2>&1; then
  echo "origin 已存在: $(git remote get-url origin)"
else
  git remote add origin "${REPO_URL}"
  echo "已添加 origin: ${REPO_URL}"
fi

git fetch origin "${BRANCH}" 2>/dev/null || true

if git rev-parse --verify "origin/${BRANCH}" >/dev/null 2>&1; then
  if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    git checkout -b "${BRANCH}" "origin/${BRANCH}" 2>/dev/null || git checkout -b "${BRANCH}"
  fi
  echo "合并远程 ${BRANCH}（允许无关历史）..."
  git pull origin "${BRANCH}" --allow-unrelated-histories --no-rebase -X ours -m "merge: sync with remote ${BRANCH}" || true
else
  git checkout -B "${BRANCH}" 2>/dev/null || true
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -m "feat: sync tpc_agent pipeline (ChinaTravel bridge, planner, eval)"
fi

echo "首次推送..."
git push -u origin "${BRANCH}"

if [ "${INSTALL_HOOK}" = "1" ]; then
  bash "$(dirname "$0")/install_git_hooks.sh"
fi

echo "仓库已关联: ${REPO_URL}"
