#!/usr/bin/env bash
# 从 NJU Drive 下载 ChinaTravel environment 数据库并解压
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CT_ROOT="${ROOT}/ChinaTravel"
ENV_DIR="${CT_ROOT}/chinatravel/environment"
TMP="${ROOT}/tpc_agent/data/raw/chinatravel_download"

NJU_SHARE="dd83e5a4a9e242ed8eb4"
NJU_BASE="https://box.nju.edu.cn/d/${NJU_SHARE}/files"

if [ ! -d "${CT_ROOT}/chinatravel" ]; then
  echo "正在 clone ChinaTravel..."
  git clone --depth 1 https://github.com/LAMDA-NeSy/ChinaTravel.git "${CT_ROOT}"
fi

if [ -d "${ENV_DIR}/database/attractions" ] && [ -d "${ENV_DIR}/database_en/attractions" ]; then
  echo "数据库已存在: ${ENV_DIR}"
  exit 0
fi

mkdir -p "${TMP}"
cd "${TMP}"

download() {
  local file="$1"
  echo "下载 ${file} ..."
  curl -fL "${NJU_BASE}/?p=%2F${file}&dl=1" -o "${file}"
}

download "database.zip"
download "database_en.zip"

echo "解压到 ${ENV_DIR} ..."
unzip -o database.zip -d "${ENV_DIR}"
unzip -o database_en.zip -d "${ENV_DIR}"

echo "完成。验证："
cd "${ROOT}/tpc_agent"
python3 -c "from src.data_layer.world_env_client import get_chinatravel_status; print(get_chinatravel_status())"
