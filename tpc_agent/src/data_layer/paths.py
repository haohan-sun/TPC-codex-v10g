"""路径与配置读取工具。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # 未安装 pyyaml 时使用简易解析
    yaml = None


def get_project_root() -> Path:
    """返回 tpc_agent 项目根目录（含 main.py 的目录）。"""
    # paths.py -> data_layer -> src -> tpc_agent
    return Path(__file__).resolve().parents[2]


def _parse_yaml_fallback(text: str) -> dict[str, Any]:
    """在无 PyYAML 时的极简 config 解析。"""
    result: dict[str, Any] = {"paths": {}, "planning": {}, "adapter": {}}
    current_section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":") and not line.startswith("  "):
            current_section = stripped[:-1]
            if current_section not in result:
                result[current_section] = {}
            continue
        if line.startswith("  ") and current_section and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().split("#", 1)[0].strip()
            if current_section == "planning" and key == "policies":
                continue  # 列表项在下一行处理
            if value.lower() == "null":
                result[current_section][key] = None
            elif value.isdigit():
                result[current_section][key] = int(value)
            elif value.lower() in ("true", "false"):
                result[current_section][key] = value.lower() == "true"
            else:
                result[current_section][key] = value.strip('"')
        if line.startswith("    - ") and current_section == "planning":
            result.setdefault("planning", {}).setdefault("policies", [])
            result["planning"]["policies"].append(stripped[2:].strip())

    return result


@lru_cache(maxsize=1)
def load_project_config() -> dict[str, Any]:
    """读取 config.yaml，结果缓存避免重复 IO。"""
    config_path = get_project_root() / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _parse_yaml_fallback(text)


def resolve_data_path(key: str, default: str) -> Path:
    """根据 config.yaml 中的 paths 段解析绝对路径。"""
    config = load_project_config()
    relative = config.get("paths", {}).get(key, default)
    path = Path(relative)
    if not path.is_absolute():
        path = get_project_root() / path
    return path
