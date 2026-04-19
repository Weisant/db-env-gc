# Agent Layer README

这个目录实现了 `db-env-gc` 的核心多 agent 流水线。

项目整体采用 `Plan-and-Execute` 方式运行，由一个主调度器按顺序调用多个 LLM agent，并通过项目根目录下的 `tools/` 完成外部证据收集、制品事实查询和真实文件系统操作。

## 整体处理流程

入口在 [main.py](/db-env-gc/main.py)，主调度逻辑在 [agent.py](/db-env-gc/agent/agent.py)。

当前主链路为：

`用户输入 -> parser -> tools(证据收集) -> reproduction_profile -> artifact_plan(直接调用镜像/源码工具) -> planner -> generator -> tools写盘 -> validator(含按需修复) -> tools写状态`

它的设计重点不是先把漏洞分成固定类别，而是先把外部证据转成“复现约束画像”，让后续阶段围绕约束求解环境。

## 主调度器

主调度器位于 [agent.py](/db-env-gc/agent/agent.py)。

它负责：

- 定义执行计划 `create_plan()`
- 维护上下文对象：
  - `TaskInput`
  - `EvidenceItem`
  - `ReproductionProfile`
  - `ArtifactFact`
  - `ArtifactPlan`
  - `EnvSpec`
  - `ProjectArtifacts`
  - `ValidationReport`
- 控制各阶段调用顺序
- 在终端打印 `Thought / Action / Observation / Step Result`
- 将各阶段结构化输出写入 `agents_log.txt`

主调度器本身不直接生成文件内容，也不直接做低层文件读写，它只负责：

- 编排 agent
- 调用 `tools/`
- 汇总状态

## 各阶段说明

### 1. Parser Agent

位置：[parser.py](/db-env-gc/agent/parser.py)  
提示词：[prompts/parser.md](/db-env-gc/agent/prompts/parser.md)

作用：

- 将用户自然语言请求标准化为 `TaskInput`
- 提取 `db_type`、`version`、`port`、`database`、`username`、`password`、`config` 等字段

它只回答“用户想要什么”，不负责解释漏洞世界。

### 2. Evidence Tools

位置：[evidence_tools.py](/db-env-gc/tools/evidence_tools.py)

作用：

- 当任务带有 `cve_id` 时，收集外部证据
- 当前优先尝试 NVD、Debian、Ubuntu、Red Hat 等高可信来源
- 输出结构化 `EvidenceItem[]`

它只负责收集事实，不直接给出复现方案。

### 3. Reproduction Profile Agent

位置：[reproduction_profile.py](/db-env-gc/agent/reproduction_profile.py)  
提示词：[prompts/reproduction_profile.md](/db-env-gc/agent/prompts/reproduction_profile.md)

作用：

- 根据 `TaskInput + EvidenceItem[]` 生成 `ReproductionProfile`
- 把“漏洞语义”转成“环境必须满足的约束”

画像会显式描述：

- `required_artifacts`
- `required_components`
- `required_relationships`
- `required_runtime_conditions`
- `required_configuration`
- `required_setup_steps`
- `forbidden_choices`
- `verification_targets`

### 4. Artifact Plan Agent

位置：[artifact_plan.py](/db-env-gc/agent/artifact_plan.py)  
提示词：[prompts/artifact_plan.md](/db-env-gc/agent/prompts/artifact_plan.md)

作用：

- 直接调用 Docker Hub 与源码地址工具收集制品事实
- 基于 `TaskInput + ReproductionProfile + ArtifactFact[]` 生成 `ArtifactPlan`
- 决定最终更适合走镜像还是源码构建

这一步的目标是把“画像约束 + 外部事实”收敛成统一制品计划，而不是让纯工具层自己拍板。

### 5. Planner Agent

位置：[planner.py](/db-env-gc/agent/planner.py)  
提示词：[prompts/planner.md](/db-env-gc/agent/prompts/planner.md)

作用：

- 根据 `TaskInput + ReproductionProfile + ArtifactPlan` 生成 `EnvSpec`
- 先定义项目结构、交付方式和关键约束，而不是直接写文件

`EnvSpec` 当前会显式携带：

- `deployment_approach`
- `base_image`
- `install_method`
- `requires_dockerfile`
- `suggested_files`
- `constraints`
- `assumptions`

### 6. Generator Agent

位置：[generator.py](/db-env-gc/agent/generator.py)  
提示词：[prompts/generator.md](/db-env-gc/agent/prompts/generator.md)

作用：

- 根据 `TaskInput + ReproductionProfile + ArtifactPlan + EnvSpec` 生成完整 Docker 项目文件集合
- 输出 `ProjectArtifacts`

它只生成内容，不写盘。

### 7. Validator Agent

位置：[validator.py](/db-env-gc/agent/validator.py)  
提示词：

- [prompts/validator.md](/db-env-gc/agent/prompts/validator.md)
- [prompts/validator_repair.md](/db-env-gc/agent/prompts/validator_repair.md)

作用：

- 基于真实磁盘快照校验项目是否完整、自洽、可交付
- 在必要时执行自动修复

它现在主要关注 Docker 项目的运行性，而不是严格做漏洞语义审计。

## LLM 调用层

位置：

- [llm.py](/db-env-gc/agent/llm.py)
- [config.py](/db-env-gc/agent/config.py)

作用：

- 从 [agent/.env](/db-env-gc/agent/.env) 读取模型配置
- 统一向兼容 OpenAI 的接口发请求
- 强制要求返回 JSON
- 去掉模型偶尔返回的代码块包裹

当前真正调用 LLM 的是：

- parser
- reproduction_profile
- planner
- generator
- validator

## 数据流

结构化模型定义在 [models/](/home/wjh/db-env-gc/agent/models/) 包下。

当前核心数据流为：

`raw_request -> TaskInput -> EvidenceItem[] -> ReproductionProfile -> ArtifactFact[] -> ArtifactPlan -> EnvSpec -> ProjectArtifacts -> ValidationReport -> PipelineResult`

其中：

- `TaskInput`：标准化后的用户任务
- `EvidenceItem`：外部证据条目
- `ReproductionProfile`：证据驱动的复现约束画像
- `ArtifactFact`：底层工具查到的镜像 tag / 源码下载等事实
- `ArtifactPlan`：LLM 基于画像和事实生成的结构化制品计划
- `EnvSpec`：环境规划结果
- `ProjectArtifacts`：待写盘的完整文件集合
- `ValidationReport`：校验结果
- `PipelineResult`：一次完整运行的汇总结果
