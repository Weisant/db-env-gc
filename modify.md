# 本次重构说明

本文档用于说明“相对于昨晚版本”的主要修改内容，重点记录这次架构调整、职责变化和关键文件改动，方便后续继续迭代时快速回溯。

## 一、改动目标

这次重构的核心目标不是增加功能，而是调整系统职责边界，让项目更符合当前阶段的设计要求：

- 保留 `parser / planner / generator / validator` 作为核心 LLM agent
- 不再保留独立的 `repair agent`
- 不再使用独立的 `persist` 模块承担全部落盘逻辑
- 把“真实文件写入、项目快照读取、状态文件写入”下沉到 `agent/tools` 目录
- 保持 `generator.py` 只负责生成文件内容，不负责写入磁盘

## 二、相对上一个版本的主要变化

### 1. 主流程从“多阶段落盘”改为“generator 生成内容 + tools 写盘”

昨晚版本的主流程更接近：

`parser -> planner -> generator -> validator -> persist`

这次改为：

`parser -> planner -> generator -> tools写盘 -> validator(含按需修复) -> tools写状态`

变化点：

- generator 仍然负责生成完整文件集合
- tools 负责真正把文件写到磁盘
- validator 不再只校验内存中的结果，而是改为校验真实磁盘快照

### 2. repair 不再是独立 agent

上一个版本中，repair 是一个独立角色，负责在 validator 之后修复项目。

这次重构后：

- 删除了独立的 `agent/repair.py`
- validator 内部保留了“修复子步骤”
- 当 validator 发现 `findings` 或 `repair_instructions` 时，会在内部调用修复 prompt
- 修复后的文件再通过 tools 覆盖回项目目录

也就是说：

- 系统层面不再把 repair 当成一个独立阶段
- 但修复能力并没有消失，而是内聚进 validator 阶段

### 3. persist 模块被 tools 层替代

上一个版本使用 `persist.py` 同时负责：

- 创建运行目录
- 写入项目文件
- 写入 `state/*.json`

这次重构后，将这些动作拆分到了 tools 层：

- `project_tools.py`
  - 创建运行目录
  - 写入项目文件
  - 覆盖修复后的文件
  - 读取真实项目快照
- `state_tools.py`
  - 写入 `state/task.json`
  - 写入 `state/env_spec.json`
  - 写入 `state/artifacts.json`
  - 写入 `state/validation.json`

这样做的好处是：

- 文件系统职责更集中
- 主调度器更清楚地分成“agent 决策”和“tools 执行”
- 后续如果要扩展更多文件工具，不需要再改业务 agent

### 4. validator 的校验对象从“内存文件集合”改成“真实磁盘快照”

上一个版本的 validator 主要检查的是内存中的 `ProjectArtifacts`。

这次改成：

- generator 先输出 `ProjectArtifacts`
- tools 先把这些文件写入真实目录
- validator 再读取项目目录中的真实文件快照
- 基于真实文件做校验和按需修复

这意味着 validator 看到的是最终交付物，而不是“还没写盘的抽象结果”。

这是这次重构里非常关键的一点，因为它让“校验对象”和“最终交付对象”一致了。

### 5. 新增 agent/tools 目录

这次新增了：

- `agent/tools/__init__.py`
- `agent/tools/file_tools.py`
- `agent/tools/project_tools.py`
- `agent/tools/state_tools.py`

它们的定位非常明确：

- 只做文件系统操作
- 不做内容生成
- 不做模板渲染
- 不做数据库语义判断

这和当前阶段的设计要求一致：tools 只作为执行层存在。

### 6. 终端输出进一步增强

本次还额外增强了终端日志的可读性：

- 在“任务开始”时，除了显示任务编号和任务描述
- 现在还会显示“当前 Agent”

例如：

- `parser`
- `planner`
- `generator`
- `validator + tools`
- `tools`

这样用户在终端里可以更直观看到当前是哪个角色在工作。

### 7. LLM 调用层增加了轻量重试

在实际测试中，模型接口偶发出现 SSL/TLS 抖动，导致请求在握手阶段失败。

为了解决这个问题，这次还修改了：

- `agent/llm.py`

新增内容：

- 对网络层 `URLError` 做有限次重试
- 不重试明确的 HTTP 4xx/5xx 服务端错误

这项改动的目标不是改变业务逻辑，而是提升流水线在真实运行时的稳定性。

## 三、关键文件变化

### 新增文件

- `agent/tools/__init__.py`
- `agent/tools/file_tools.py`
- `agent/tools/project_tools.py`
- `agent/tools/state_tools.py`
- `modify.md`

### 删除文件

- `agent/repair.py`
- `agent/persist.py`

### 重点修改文件

- `agent/agent.py`
- `agent/validator.py`
- `agent/generator.py`
- `agent/parser.py`
- `agent/planner.py`
- `agent/models.py`
- `agent/llm.py`
- `agent/prompts/writer.md`
- `agent/prompts/validator.md`
- `agent/prompts/repair.md`
- `agent/README.md`
- `README.md`

## 四、当前版本的职责分工

### LLM agent

- `parser`
  - 负责结构化解析用户输入
- `planner`
  - 负责生成环境规划
- `generator`
  - 负责生成完整文件内容
- `validator`
  - 负责基于真实磁盘快照做校验，并在必要时触发内部修复

### tools

- 创建运行目录
- 写入项目文件
- 覆盖修复后的项目文件
- 读取真实项目快照
- 写入状态文件

## 五、本次重构后的收益

相对于上一个版本，这次重构带来的直接收益包括：

- generator 的职责更纯粹，只生成内容，不碰文件系统
- validator 的职责更贴近最终交付物，改为校验真实磁盘文件
- repair 从“独立阶段”收敛为“validator 内部能力”，主流程更紧凑
- tools 目录把文件系统操作集中起来，主流程更清晰
- 终端日志更容易理解，运行时能直观看到当前 agent
- 网络抖动导致的偶发失败有所缓解

## 六、当前仍然存在的已知问题

虽然这次重构已经跑通，但当前版本仍有一些质量问题值得后续继续优化：

- `README.md` 的 Markdown 格式偶尔仍然不够理想
- generator 输出的项目质量仍然受 prompt 质量影响较大
- validator 虽然能自动修复，但修复效果仍依赖模型表现

也就是说，这次重构主要解决的是“架构职责边界”和“执行路径”，而不是最终把生成质量问题一次性彻底消灭。

## 七、一句话总结

相对于上一个版本，这次修改的本质是：

**把“文件系统执行”从业务 agent 中剥离到 tools 层，把 repair 从独立阶段收敛到 validator 内部，并让 validator 基于真实磁盘快照而不是内存对象进行校验。**
