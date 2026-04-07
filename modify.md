# `0.3` 相对 `0.2` 的版本说明

本文档用于说明当前版本相对于 Git tag `0.2` 的主要修改内容，方便后续继续迭代、打 tag 和回溯设计变化。

## 一、版本定位

`0.2` 的重点是把原有流水线变得更可控、更可观测：

- 支持按阶段配置模型
- 收紧 validator 自动修复触发条件
- 修正阶段耗时与总耗时统计
- 强化 `cve_id`、项目命名和输入结构的一致性

`0.3` 在这个基础上，重点解决的是：

- 让工具层真正独立于 `agent/`
- 在生成前先判断数据库版本是否真实存在
- 在生成前再判断官方镜像是否真实可用
- 让“走官方镜像”还是“走 Dockerfile”不再由 LLM 临场猜测

## 二、相对 `0.2` 的主要变化

### 1. `tools/` 从 `agent/` 目录彻底上移为项目级共享层

`0.2` 虽然在语义上已经把 tools 当成独立执行层使用，但物理目录仍然位于 `agent/tools/`。

`0.3` 做了正式拆分：

- 删除 `agent/tools/`
- 在项目根目录新增 `tools/`
- 统一由主调度器、validator 和状态写盘逻辑直接引用根级 `tools/`

这样做的意义是：

- 目录结构更能反映真实架构分层
- `agent/` 更聚焦“理解、规划、生成、校验”
- `tools/` 更明确承担“确定性辅助步骤 + 文件系统执行”

对应修改文件：

- `agent/agent.py`
- `agent/validator.py`
- `tools/__init__.py`
- `tools/file_tools.py`
- `tools/project_tools.py`
- `tools/state_tools.py`
- `README.md`
- `agent/README.md`

### 2. 新增“版本真实性校验”前置步骤

`0.2` 还默认认为：只要用户给了数据库类型和版本，就可以继续生成环境。

`0.3` 新增了 `VersionResolution` 和 `tools/version_source_tools.py`：

- 在生成前先根据项目内置的官方源码源规则检查版本是否真实存在
- 如果版本没有在可信来源中确认存在，主流程会直接 fail fast
- 不再为“根本不存在的版本”继续生成看似合理但实际错误的环境

当前版本已经内置了部分数据库的官方源码源规则，例如：

- Redis 官方下载源
- PostgreSQL 官方源码归档
- MySQL 官方 GitHub 源码 tag
- MongoDB 官方 GitHub 源码 tag

对应修改文件：

- `agent/models.py`
- `agent/agent.py`
- `tools/version_source_tools.py`
- `tools/state_tools.py`
- `README.md`
- `agent/README.md`

### 3. 新增“官方镜像可用性判断”前置步骤

`0.2` 中，generator 仍然倾向于直接生成使用官方镜像的 compose 文件。

`0.3` 新增了 `ImageResolution` 和 `tools/registry_tools.py`：

- 在 planner / generator 之前先查询 Docker Hub 官方镜像和精确 tag 是否存在
- 如果官方精确 tag 存在，后续阶段必须走 `official_image`
- 如果版本存在但官方镜像 tag 不存在，后续阶段必须走 `custom_dockerfile`

也就是说，镜像策略从“模型生成时的隐式判断”变成了“工具层前置决策”。

对应修改文件：

- `agent/models.py`
- `agent/agent.py`
- `agent/planner.py`
- `agent/generator.py`
- `agent/validator.py`
- `tools/registry_tools.py`
- `tools/state_tools.py`

### 4. 主流水线升级为“双解析 + LLM 规划生成”

相对 `0.2`，主链路已经从：

`parser -> planner -> generator -> tools写盘 -> validator -> tools写状态`

变成：

`parser -> version_source_tools -> registry_tools -> planner -> generator -> tools写盘 -> validator -> tools写状态`

这意味着：

- LLM 不再承担“数据库版本真实性判断”
- LLM 不再承担“官方镜像是否存在”的判断
- planner / generator 接到的是已经收口的结构化前置信息

这样能明显降低：

- 因外部事实不准导致的生成漂移
- 因镜像或源码不存在导致的无效产物

对应修改文件：

- `agent/agent.py`
- `agent/planner.py`
- `agent/generator.py`
- `agent/validator.py`

### 5. 结构化状态模型进一步扩展

`0.3` 增加了新的结构化对象：

- `VersionResolution`
- `ImageResolution`

同时扩展了：

- `EnvSpec`
- `PipelineResult`

其中：

- `EnvSpec` 现在显式携带 `image_strategy`、`image_ref`、`requires_dockerfile`
- `PipelineResult` 会同时汇总任务输入、版本解析、镜像解析、环境规划、生成产物和校验结果

这让整个流水线在状态回溯时更完整，也更容易调试错误来源。

对应修改文件：

- `agent/models.py`

### 6. `state/` 目录新增前置解析结果落盘

`0.2` 的状态文件主要覆盖：

- `task.json`
- `env_spec.json`
- `artifacts.json`
- `validation.json`

`0.3` 进一步新增：

- `state/version_resolution.json`
- `state/image_resolution.json`

这样后续排查时，可以直接看到：

- 本次版本真实性校验依据了哪些官方来源
- 本次是否命中官方镜像 tag
- 为什么最终走的是 `image:` 还是 `Dockerfile`

对应修改文件：

- `tools/state_tools.py`
- `README.md`

### 7. prompt 和 validator 规则同步升级

`0.3` 对 prompt 做的重点，不是继续加长，而是让它们显式遵守工具层决策：

- planner 必须根据 `ImageResolution` 决定是否要求 `Dockerfile`
- generator 必须根据镜像策略输出 `image:` 或 `build:`
- validator 必须根据镜像策略检查 compose 和 `Dockerfile` 是否自洽
- validator repair 也必须继续遵守镜像策略，不能把两种分支互相改写

这意味着：

- prompt 的职责边界更清晰
- 后续模型输出更不容易与外部事实冲突

对应修改文件：

- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`

### 8. Docker Hub 与版本源查询增加网络回退策略

在真实环境中，直接使用 Python `urllib` 查询外部服务会遇到 TLS 或代理兼容问题。

`0.3` 针对这一点加入了更稳的兜底：

- 优先使用标准 Python 网络请求
- 如果遇到兼容性问题，再回退到 `curl`

这样做的收益是：

- 工具层在受限网络环境里更稳
- 真实线上验证更容易通过
- 失败时仍能以结构化状态返回，而不是让主流程莫名中断

对应修改文件：

- `tools/registry_tools.py`
- `tools/version_source_tools.py`

## 三、关键文件变化

### 本次重点修改文件

- `pyproject.toml`
- `README.md`
- `modify.md`
- `agent/README.md`
- `agent/agent.py`
- `agent/models.py`
- `agent/planner.py`
- `agent/generator.py`
- `agent/validator.py`
- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`
- `tools/__init__.py`
- `tools/file_tools.py`
- `tools/project_tools.py`
- `tools/state_tools.py`
- `tools/registry_tools.py`
- `tools/version_source_tools.py`

### 本次新增的新业务模块

- `tools/registry_tools.py`
- `tools/version_source_tools.py`

### 本次移除的旧目录结构

- `agent/tools/`

## 四、`0.3` 的直接收益

相对 `0.2`，当前版本的直接收益主要有：

- tools 层不再挂在 `agent/` 下，项目分层更清楚
- 不再为不存在的数据库版本继续生成无效环境
- 不再把官方镜像可用性判断留给 LLM 自由发挥
- `Dockerfile` 分支和 `image:` 分支的切换依据更明确
- `state/` 目录可以完整回溯“为什么这样生成”
- 文档、主流程和结构化状态模型的一致性更强

## 五、当前版本仍然存在的已知问题

虽然 `0.3` 相比 `0.2` 又前进了一步，但当前版本仍有一些已知限制：

- 版本源目录目前只覆盖少量高频数据库，还没有覆盖所有数据库或数据库变体
- 特殊漏洞场景仍未形成正式的 `CVE` 上下文覆盖层
- Dockerfile 内容仍然依赖 generator 生成，当前阶段还没有收敛为模板化构建策略
- 工具层虽然能判断“版本是否存在 / 镜像是否存在”，但还不能理解“发行版包漏洞”“模块漏洞”“构建选项漏洞”这类特殊场景

也就是说，`0.3` 主要解决的是：

- 工具层分层
- 外部事实前置校验
- 流水线输入可信度
- 环境生成分支决策

而不是一次性解决所有漏洞上下文建模问题。

## 六、一句话总结

相对 `0.2`，`0.3` 的本质变化是：

**让系统从“基于用户输入直接生成环境”进一步升级为“先用工具确认版本和镜像事实，再由 LLM 在受约束的前提下生成环境”的版本。**
