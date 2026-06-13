#!/usr/bin/env bash
# 安装 post-commit 钩子：每次本地 commit 后自动 push（可用 TPC_DISABLE_AUTO_PUSH=1 跳过）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="${ROOT}/.git/hooks/post-commit"

cat > "${HOOK}" << 'EOF'
#!/usr/bin/env bash
if [ "${TPC_DISABLE_AUTO_PUSH:-0}" = "1" ]; then
  exit 0
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
(
  echo "[tpc_agent] auto-push to origin/${BRANCH} (background) ..."
  git push origin "${BRANCH}" || echo "[tpc_agent] push failed (稍后手动: bash scripts/sync_github.sh)"
) &
EOF

chmod +x "${HOOK}"
echo "已安装 post-commit 自动推送钩子。"
echo "临时禁用: export TPC_DISABLE_AUTO_PUSH=1"
