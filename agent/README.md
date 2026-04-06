# Agent Layer README

这个目录实现了 `db-env-gc` 的核心多 agent 流水线。

项目整体采用 `Plan-and-Execute` 方式运行，由一个主调度器按顺序调用多个 LLM agent，并通过 `tools` 目录完成真实文件系统操作。

## 整体处理流程

入口在 [main.py](/home/wjh/db-env-gc/main.py)，主调度逻辑在 [agent.py](/home/wjh/db-env-gc/agent/agent.py)。

完整流程如下：

1. 用户在终端输入数据库环境生成需求
2. `main.py` 初始化运行环境、日志文件和主调度器
3. 主调度器按固定计划依次调用各个 agent
4. 每个 agent 输出结构化 JSON，作为下一个 agent 的输入
5. `tools` 负责把 generator 产出的文件内容写到真实项目目录
6. validator 基于真实磁盘快照做校验，并在必要时直接触发修复
7. 最终再由 `tools` 写入 `state/` 目录

当前主链路为：

`用户输入 -> parser -> planner -> generator -> tools写盘 -> validator(含按需修复) -> tools写状态`

## 主调度器

主调度器位于 [agent.py](/home/wjh/db-env-gc/agent/agent.py)。

它负责：

- 定义执行计划 `create_plan()`
- 维护上下文对象：
  - `TaskInput`
  - `EnvSpec`
  - `ProjectArtifacts`
  - `ValidationReport`
- 控制 agent 的调用顺序
- 在终端打印 `Thought / Action / Observation / Step Result`
- 将各阶段结构化输出写入 `agents_log.txt`

主调度器本身不直接生成文件内容，也不直接做低层文件读写，它只负责：
- 编排 agent
- 调用 tools
- 汇总状态

## 各 Agent 说明

### 1. Parser Agent

位置：[parser.py](/home/wjh/db-env-gc/agent/parser.py)  
提示词：[prompts/parser.md](/home/wjh/db-env-gc/agent/prompts/parser.md)

作用：

- 将用户自然语言请求标准化为 `TaskInput`
- 统一提取并规范字段，例如：
  - `db_type`
  - `version`
  - `port`
  - `database`
  - `username`
  - `password`
  - `config`
  - `project_name`

处理逻辑：

1. 接收原始输入 `raw_request`
2. 调用 LLM
3. 要求模型只输出 JSON
4. 使用 [models.py](/home/wjh/db-env-gc/agent/models.py) 中的 `TaskInput.from_dict()` 做结构化校验

它的目标是让后续所有 agent 共用同一份干净、稳定的任务输入。

### 2. Planner Agent

位置：[planner.py](/home/wjh/db-env-gc/agent/planner.py)  
提示词：[prompts/planner.md](/home/wjh/db-env-gc/agent/prompts/planner.md)

作用：

- 根据 `TaskInput` 生成环境规划 `EnvSpec`
- 先定义项目结构和约束，而不是直接写文件

处理逻辑：

1. 接收 `TaskInput`
2. 调用 LLM 生成规划结果
3. 输出：
  - `project_name`
  - `objective`
  - `suggested_files`
  - `constraints`
  - `assumptions`
4. 使用 `EnvSpec.from_dict()` 转成结构化对象

它的目标是把“这次项目应该长什么样”先规划清楚，再交给 writer 执行。

### 3. Generator Agent

位置：[generator.py](/home/wjh/db-env-gc/agent/generator.py)  
提示词：[prompts/writer.md](/home/wjh/db-env-gc/agent/prompts/writer.md)

作用：

- 根据 `TaskInput + EnvSpec` 直接生成完整 Docker 项目文件集合

处理逻辑：

1. 接收任务信息和环境规划
2. 调用 LLM
3. 输出 `ProjectArtifacts`
4. 每个文件对象包含：
  - `path`
  - `purpose`
  - `content`

通常会生成：

- `docker-compose.yml`
- `.env.example`
- `README.md`
- `config/...`
- `init/...`

它是项目中真正生成文件内容的核心 agent。

注意：

- generator 只生成内容
- 真正写入磁盘由 `agent/tools` 完成

### 4. Validator Agent

位置：[validator.py](/home/wjh/db-env-gc/agent/validator.py)  
提示词：[prompts/validator.md](/home/wjh/db-env-gc/agent/prompts/validator.md)

作用：

- 从交付质量角度检查真实磁盘项目是否完整、自洽、可交付
- 在必要时直接触发修复并通过 tools 覆盖文件

处理逻辑：

1. 接收：
  - `TaskInput`
  - `EnvSpec`
  - 真实磁盘快照
2. 调用 LLM
3. 输出 `ValidationReport`

校验报告包含：

- `passed`
- `findings`
- `warnings`
- `repair_instructions`

重点检查内容：

- 文件是否齐全
- `docker-compose.yml` 是否具备基础可运行结构
- 数据库类型、版本、端口、账号、配置是否和任务一致
- `config/`、`init/`、README 是否互相一致
- README 是否清晰说明启动方式、目录结构和关键配置

它的目标是把“生成完成”提升为“可交付完成”，并在可修复时直接完成闭环。

### 5. Tools Layer

位置：

- [tools/file_tools.py](/home/wjh/db-env-gc/agent/tools/file_tools.py)
- [tools/project_tools.py](/home/wjh/db-env-gc/agent/tools/project_tools.py)
- [tools/state_tools.py](/home/wjh/db-env-gc/agent/tools/state_tools.py)

作用：

- 负责真实的文件系统动作，例如：
  - 创建运行目录
  - 写入项目文件
  - 读取项目快照
  - 覆盖修复后的文件
  - 写入 `state` 状态文件

这些 tools 不参与内容生成，也不负责理解数据库语义。

## LLM 调用层

位置：

- [llm.py](/home/wjh/db-env-gc/agent/llm.py)
- [config.py](/home/wjh/db-env-gc/agent/config.py)

作用：

- 从 [agent/.env](/home/wjh/db-env-gc/agent/.env) 读取模型配置
- 统一向兼容 OpenAI 的接口发请求
- 强制要求返回 JSON
- 去掉模型偶尔返回的代码块包裹

也就是说，当前真正调用 LLM 的是：

- parser
- planner
- generator
- validator

它们都通过这层能力去调用 LLM。

## 数据流

结构化模型定义在 [models.py](/home/wjh/db-env-gc/agent/models.py)。

关键对象包括：

- `TaskInput`
- `EnvSpec`
- `ProjectArtifacts`
- `ValidationReport`
- `PipelineResult`

数据流转关系为：

`raw_request -> TaskInput -> EnvSpec -> ProjectArtifacts -> ValidationReport -> PipelineResult`

这些对象的作用分别是：

- `TaskInput`：标准化用户需求
- `EnvSpec`：环境规划结果
- `ProjectArtifacts`：完整项目文件集合
- `ValidationReport`：校验与修复建议
- `PipelineResult`：最终运行汇总结果

## 终端日志机制

终端里会看到类似下面的结构：

- `Thought`
- `Action`
- `Observation`
- `Step Result`

这些内容不是 agent 自己直接打印的，而是主调度器在 [agent.py](/home/wjh/db-env-gc/agent/agent.py) 中统一输出的执行日志风格。

目的有两个：

- 让用户看到当前执行到了哪一步
- 让一次运行的上下文更容易排查和复现

其中：

- `Thought`：当前步骤为什么要做
- `Action`：调用了哪个 agent 或模块
- `Observation`：该步骤的结构化输出
- `Step Result`：本阶段的简短结论

## 总结

这个目录实现的是一个由 orchestrator 驱动的全 agent 流水线系统：

- `parser / planner / generator / validator` 是当前的核心 LLM agent
- `tools` 是纯文件系统执行层
- validator 已经内聚了“发现问题后按需修复”的能力
- 最终产出完整的 Docker 项目和状态文件

如果后续还要扩展，可以继续在这个目录下增加：

- 更强的 repair 闭环
- 多轮 replan
- 外部检索 agent
- 镜像兼容性验证 agent
