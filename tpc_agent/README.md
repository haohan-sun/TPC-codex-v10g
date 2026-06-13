# tpc_agent

TPC 旅游行程规划比赛 Agent。

## 设计原则

**总体流程必须普遍，局部模块必须有新意。**

普遍骨架：读懂需求 → 查数据 → 生成计划 → 检查计划 → 修复计划 → 输出结果。

差异化落在各模块内部（主动约束获取、滚动规划、日内优化、类型化修复、多策略择优）。

## 总流程

```
用户自然语言需求
  → 约束卡片抽取
  → 主动约束获取（风险驱动）
  → 语义落地与偏好权重
  → 候选池构建
  → [多策略] 多日任务分配 → 滚动逐日规划 → 日内路线优化
  → 时间表生成 → 预算控制 → 本地检查
  → 官方格式 → 官方 verifier → 类型化修复
  → 多候选择优 → 最终输出
```

## 快速开始

```bash
cd tpc_agent
pip install -r requirements.txt
python main.py query.json
```

## 目录结构

```
tpc_agent/
  main.py                 # solve_one_query() 可执行总流程
  config.yaml
  src/
    data_layer/           # 数据加载与 schema
    constraints/          # 约束卡片抽取
    active/               # 主动约束获取 (Active SLAM)
    semantic/             # 语义落地
    candidates/           # 候选池构建
    planner/              # 多日分配 + 滚动规划 (MPC)
    optimizer/            # 日内路线优化 (ACO/2-opt)
    scheduler/            # 时间表 + 预算
    skills/               # 旅行规划师技能库
    verifier/             # 本地检查 + 官方 verifier
    repair/               # 类型化局部修复
    search/               # 多候选搜索
    submission/           # 官方格式输出
    experiments/          # 实验记录
```

## 模块填充顺序建议

1. `data_layer` + `constraints` — 能读懂 query
2. `candidates` + `planner` — 能生成粗糙 plan
3. `optimizer` + `scheduler` — 能排时间和路线
4. `submission` + `verifier` — 能跑官方检查
5. `repair` + `search` — 能修错和择优
6. `active` + `semantic` + `skills` — 加分项

## ChinaTravel 环境

1. Clone 官方仓库到 `../ChinaTravel`（或配置 `config.yaml` → `paths.chinatravel_root`）
2. 一键下载 environment 数据库（NJU Drive，**无需密码**）：

```bash
bash scripts/setup_chinatravel_env.sh
```

   手动链接：https://box.nju.edu.cn/d/dd83e5a4a9e242ed8eb4/

3. 验证：`python -c "from src.data_layer.world_env_client import get_chinatravel_status; print(get_chinatravel_status())"`

有数据库后 planner 将使用真实 POI/交通，并满足票务、餐饮预算、酒店距离等约束。

## 同步到 GitHub

仓库：[KevinYin856/TPC](https://github.com/KevinYin856/TPC)

```bash
# 首次（已在本机 init 可跳过）
bash scripts/setup_github_repo.sh

# 手动同步
bash scripts/sync_github.sh "你的提交说明"

# 安装「每次 commit 后自动 push」钩子
bash scripts/install_git_hooks.sh
# 临时禁用自动推送: export TPC_DISABLE_AUTO_PUSH=1
```

推送前需已配置 GitHub 认证（HTTPS token 或 SSH）。`data/outputs/` 等大文件已在 `.gitignore` 中排除。
