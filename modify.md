# `0.4` 相对 `0.3` 的版本说明

本文档记录本次 `0.4` 版本相对于 `0.3` 的主要变化。

## 对比基线

- `0.3` 基线提交：`8562078`
- `0.4` 发布提交：见本次 tag `0.4`

## 一、核心升级

### 1. 运行时架构拆分（从单体到模块化）

核心变化：

- 主调度与流水线步骤从单文件拆分为 `agent/runtime/` 目录。
- 模型从 `agent/models.py` 拆分为按职责分层的 `agent/models/` 包。

代表性文件变化：

- 删除：`agent/agent.py`
- 删除：`agent/models.py`
- 新增：`agent/runtime/agent.py`
- 新增：`agent/runtime/pipeline_steps.py`
- 新增：`agent/runtime/payload_builders.py`
- 新增：`agent/models/task_models.py`
- 新增：`agent/models/project_models.py`
- 新增：`agent/models/profile_models.py`
- 新增：`agent/models/utils.py`
- 修改：`main.py`（入口切换到 `agent.runtime.agent`）

### 2. 主链路升级为“证据 -> 画像 -> 制品计划”

核心变化：

- 新增 CVE 外部证据收集阶段。
- 新增复现约束画像阶段（`reproduction_profile`）。
- 新增制品计划阶段（`artifact_plan`），在受控 ReAct 下执行候选版本探测与策略收束。

新链路：

`parser -> evidence_tools -> reproduction_profile -> artifact_plan -> planner -> generator -> tools写盘 -> validator -> tools写状态`

代表性文件变化：

- 新增：`tools/evidence_tools.py`
- 新增：`agent/reproduction_profile.py`
- 新增：`agent/artifact_plan.py`
- 新增：`agent/prompts/reproduction_profile.md`
- 新增：`agent/prompts/artifact_plan.md`
- 修改：`tools/state_tools.py`（状态文件新增 evidence/profile/artifact_plan 等）

### 3. 候选版本顺序探测机制

核心变化：

- `artifact_plan` 支持从 `version_candidates_json` 读取候选版本队列。
- 在固定探测路线下按候选顺序探测：当前候选失败则切换下一个候选。

代表性文件变化：

- 新增：`agent/artifact_plan.py`
- 修改：`agent/prompts/artifact_plan.md`
- 修改：`agent/prompts/reproduction_profile.md`

### 4. 交付语义扩展：`package_install`

核心变化：

- `delivery_strategy` 在 prompt 语义层新增 `package_install`，用于显式区分：
  - `container_image`（直接镜像）
  - `source_build`（源码构建）
  - `package_install`（包管理器安装）

说明：

- 本次仍坚持“LLM 主导”，未额外引入硬编码策略映射规则。

代表性文件变化：

- 修改：`agent/prompts/artifact_plan.md`
- 修改：`agent/prompts/planner.md`
- 修改：`agent/prompts/generator.md`

### 5. parser / planner / generator / validator 同步对齐

核心变化：

- 结构化输入输出字段与新的阶段边界对齐。
- 提示词与实现同步调整，减少阶段间语义漂移。

代表性文件变化：

- 修改：`agent/parser.py`
- 修改：`agent/planner.py`
- 修改：`agent/generator.py`
- 修改：`agent/validator.py`
- 修改：`agent/llm.py`
- 修改：`agent/prompts/parser.md`
- 修改：`agent/prompts/planner.md`
- 修改：`agent/prompts/generator.md`
- 修改：`agent/prompts/validator.md`
- 修改：`agent/prompts/validator_repair.md`

## 二、文档与工程信息更新

- 修改：`README.md`
- 修改：`agent/README.md`
- 修改：`modify.md`
- 修改：`pyproject.toml`

## 三、版本收益

相对 `0.3`，`0.4` 的主要收益：

- 架构更清晰：运行时与模型拆分，维护成本下降。
- 决策更可靠：由证据和画像驱动制品计划，不再仅依赖前置版本/镜像分支。
- 版本收敛更稳：支持候选版本顺序探测。
- 语义更明确：`package_install` 与 `source_build` 区分清晰。

## 四、一句话总结

`0.4` 把系统从“前置版本/镜像解析驱动”进一步升级为“证据与复现约束驱动”，并在最小硬编码前提下强化了版本收敛与交付语义表达能力。
