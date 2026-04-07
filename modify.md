# `0.2` 相对 `0.1` 的版本说明

本文档用于说明当前版本相对于 Git tag `0.1` 的主要修改内容，方便后续继续迭代、打 tag 和回溯设计变化。

## 一、版本定位

`0.1` 的重点是把系统从“多角色混合实现”收敛成一条更清晰的工作流：

- 保留 `parser / planner / generator / validator`
- 把文件写入与状态落盘下沉到 `agent/tools`
- 让 validator 基于真实磁盘快照而不是内存对象做检查

`0.2` 在这个基础上，重点做的是：

- 让模型调用更可控
- 让自动修复更克制
- 让终端运行信息更准确
- 让项目命名规则更稳定
- 让输入结构更适配真实使用场景

## 二、相对 `0.1` 的主要变化

### 1. 新增多模型配置能力

`0.1` 默认所有阶段共用同一个模型配置。

`0.2` 新增了按阶段配置模型的能力，支持：

- `DEFAULT_MODEL`
- `PARSER_MODEL`
- `PLANNER_MODEL`
- `GENERATOR_MODEL`
- `VALIDATOR_MODEL`

如果某个阶段没有单独配置，会自动回退到 `DEFAULT_MODEL`。  
同时保留了对旧字段 `MODEL_NAME` 的兼容，避免旧环境变量立刻失效。

这项改动的目标是：

- parser 和 validator 可以优先使用更快的模型
- generator 可以单独使用更强的模型
- 后续更容易按成本、速度、效果做分层配置

对应修改文件：

- `agent/config.py`
- `agent/llm.py`
- `agent/parser.py`
- `agent/planner.py`
- `agent/generator.py`
- `agent/validator.py`
- `agent/.env.example`

### 2. 自动修复触发策略被收紧

`0.1` 中，validator 只要发现 `findings` 或 `repair_instructions`，通常就会进入修复闭环。

`0.2` 增加了“结构性问题才自动修复”的判定逻辑：

- `warnings` 只报告，不自动修
- README 排版、Markdown 代码块、措辞、轻微格式问题只报告，不自动修
- 缺文件、关键配置不一致、`docker-compose.yml` 结构不完整、端口/镜像/初始化文件问题这类结构性问题才自动修

这样做的好处是：

- 减少额外的大模型调用次数
- 减少为了轻微问题反复重写项目文件
- 让 validator 更像“交付质量把关”，而不是“任何问题都立刻重生成”

对应修改文件：

- `agent/validator.py`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`

### 3. prompt 整体压缩

`0.1` 的 prompt 已经能工作，但整体偏长，很多约束描述存在重复。

`0.2` 对 prompt 做了压缩，原则是：

- 保留必要的边界和输出格式要求
- 删除重复表述
- 让 parser / planner / generator / validator 的职责边界更直接

这项改动的目标不是改功能，而是：

- 减少上下文体积
- 降低单次调用耗时
- 让模型更聚焦当前阶段任务

对应修改文件：

- `agent/prompts/parser.md`
- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`

### 4. 新增阶段计时，并修正总耗时起点

`0.1` 的总耗时是从 `main.py` 启动就开始计算的，这会把“用户还没输入任务”的等待时间也算进去。

`0.2` 做了两件事：

- 每个阶段单独计时，在终端输出 `Step Duration`
- 总耗时改为从“用户提交任务内容之后”开始计算

这样可以更准确地区分：

- 是用户输入慢
- 还是 parser / planner / generator / validator 某个阶段真的慢

对应修改文件：

- `main.py`
- `agent/agent.py`

### 5. 终端提示从“当前 Agent”改成“当前阶段执行方”

`0.1` 的终端输出里使用了：

- `当前 Agent：parser`
- `当前 Agent：validator + tools`

这个说法在单一角色阶段没问题，但在 `validator + tools` 这种组合阶段里不够准确，因为它并不是单独一个 agent。

`0.2` 改成了：

- `当前阶段执行方：parser`
- `当前阶段执行方：validator + tools`

这样更符合当前架构，也减少了概念混淆。

对应修改文件：

- `agent/agent.py`

### 6. 新增 `cve_id` 结构化字段

`0.1` 里虽然已经开始讨论“项目目录名最好带上 CVE 编号”，但这只是 prompt 层的约束，不是正式的数据字段。

`0.2` 把 `cve_id` 正式加入到了结构化链路中：

- `TaskInput`
- `EnvSpec`
- `ProjectArtifacts`

这样带来的收益是：

- parser 不再需要把 CVE 编号塞进自由文本或注释里
- planner / generator 可以稳定使用同一个字段
- validator 也可以正式检查项目命名是否一致

对应修改文件：

- `agent/models.py`
- `agent/agent.py`
- `agent/prompts/parser.md`
- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`

### 7. 项目命名规则升级为“双模式”

围绕 `cve_id`，`0.2` 还完善了项目命名规则。

现在命名规则分两种情况：

1. 用户提供了 `cve_id`
   项目名使用：
   `CVE编号-数据库名称-版本号`

   例如：
   `CVE-2021-44228-postgres-13`

2. 用户没有提供 `cve_id`
   项目名自动降级为：
   `数据库名称-版本号-env`

   例如：
   `postgres-13-env`

这套规则的意义在于：

- 不会为了命名规则强迫用户必须提供 CVE
- 也不会在没有 CVE 时让模型乱猜一个编号
- 让命名逻辑在“有漏洞编号”和“无漏洞编号”两种场景下都可用

对应修改文件：

- `agent/prompts/parser.md`
- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`
- `agent/agent.py`

### 8. `db_type` 不再被限制为固定四类数据库

`0.1` 早期 prompt 里还保留着：

- `postgres`
- `mysql`
- `redis`
- `mongodb`

这类固定枚举式写法。

`0.2` 把这部分放开了：

- `db_type` 现在表示“数据库名称本身”
- 不再限制为固定四类
- parser prompt 明确要求不要把数据库类型限制死

这样更适合后续扩展到更多数据库或数据库变体场景。

对应修改文件：

- `agent/prompts/parser.md`

### 9. 新增 CLI 可选参数控制是否启用 validator

`0.2` 现在支持通过命令行参数决定是否执行 validator 阶段。

默认情况下：

- 会执行 validator
- 会基于真实磁盘快照做检查
- 在必要时触发内部修复

如果用户希望“只生成项目、先不校验”，现在可以使用：

```bash
python3 main.py --skip-validator
```

启用这个参数后：

- 主流程会跳过 validator 调用
- tools 仍然会正常写入项目文件
- 系统仍会写出结构化 `validation.json`
- 其中会明确记录“本次运行跳过了 validator 阶段”

这样做的意义是：

- 适合快速生成项目草稿
- 能减少一轮或多轮 LLM 调用
- 让用户可以自己决定是否需要自动校验与自动修复

对应修改文件：

- `main.py`
- `agent/agent.py`
- `README.md`

### 10. 默认输出目录改为“当前项目根目录下的 output/”

在早期实现里，默认输出目录写死为固定绝对路径。

`0.2` 现在改成：

- 如果用户在 CLI 里显式传入输出路径，就使用用户提供的路径
- 如果用户没有传入路径，就默认使用“当前项目根目录下的 `output/`”

也就是说，默认行为变成了“随项目目录位置自动变化”，而不是依赖某个写死的绝对路径。

这项改动的好处是：

- 项目被移动到其他目录后，默认输出路径依然正确
- 不再依赖开发机上的固定目录结构
- 更适合作为可迁移的项目使用

对应修改文件：

- `main.py`

## 三、关键文件变化

### 本次重点修改文件

- `main.py`
- `agent/agent.py`
- `agent/config.py`
- `agent/llm.py`
- `agent/models.py`
- `agent/parser.py`
- `agent/planner.py`
- `agent/generator.py`
- `agent/validator.py`
- `agent/.env.example`
- `agent/prompts/parser.md`
- `agent/prompts/planner.md`
- `agent/prompts/generator.md`
- `agent/prompts/validator.md`
- `agent/prompts/validator_repair.md`
- `modify.md`

### 本次没有新增新的业务模块

`0.2` 没有继续拆新的 agent 或 tools 模块，重点是增强现有模块的可控性与一致性，而不是继续扩展架构复杂度。

## 四、`0.2` 的直接收益

相对 `0.1`，当前版本的直接收益主要有：

- 模型配置更灵活，可以按阶段分配不同模型
- 自动修复次数减少，整体运行成本和耗时更可控
- 终端里可以直接看到每个阶段耗时
- 总耗时统计更准确，不再混入等待用户输入的时间
- `cve_id` 成为正式字段，不再只是 prompt 里的隐含规则
- 项目命名规则更稳定，并支持无 CVE 场景自动降级
- `db_type` 不再被固定在早期支持的少数数据库上

## 五、当前版本仍然存在的已知问题

虽然 `0.2` 明显比 `0.1` 更稳，但仍然有一些已知问题需要后续继续优化：

- 生成质量仍然高度依赖 prompt 和模型本身
- validator 的“结构性问题判定”目前仍是启发式关键词判断，还不是严格规则系统
- README 和说明文档的质量仍可能波动
- 尚未加入更细粒度的本地预检查，因此 validator 仍然会消耗一轮 LLM 调用

也就是说，`0.2` 主要优化的是：

- 配置能力
- 命名一致性
- 自动修复策略
- 运行可观测性

而不是把最终生成质量问题一次性彻底解决。

## 六、一句话总结

相对 `0.1`，`0.2` 的本质变化是：

**让系统从“能跑通”进一步变成“更可控、更可观测、命名更稳定、对真实输入场景更友好”的版本。**
