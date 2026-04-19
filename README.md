# DB Env GC

`db-env-gc` 是一个数据库环境生成 agent 项目。

它采用 `Plan-and-Execute` 风格的串行流水线，把“用户任务解析”“外部证据收集”“复现约束建模”“制品计划”“环境规划”“文件生成”“磁盘校验”拆成多个明确阶段。

当前版本的主链路为：

1. `parser` 标准化用户输入
2. `tools/evidence_tools.py` 围绕 CVE 收集外部证据
3. `reproduction_profile` agent 根据任务与证据生成复现约束画像
4. `artifact_plan` agent 基于画像执行受控 ReAct：读取候选版本队列、确定探测路线（镜像或源码）并按候选顺序探测，生成结构化制品计划
5. `planner` 输出环境规划 JSON
6. `generator` 产出完整 Docker 项目文件内容
7. `tools/` 把文件真正写入磁盘
8. `validator` 基于真实磁盘快照检查项目，并在必要时执行内部修复
9. `tools/` 把状态对象写入 `state/`

当前版本不涉及漏洞利用和验证逻辑，只生成可复现环境所需的 Docker 项目。

## 交付策略语义

`artifact_plan -> planner -> generator` 之间通过 `delivery_strategy` 传递主交付语义：

- `container_image`：直接使用可用镜像
- `source_build`：通过源码或源码包构建
- `package_install`：在基础镜像中通过系统包管理器安装目标版本

当前项目采用“LLM 主导 + 工具探测”的方式：

- 工具层负责镜像 / 源码可用性探测
- 具体采用哪种 `delivery_strategy` 由上游结构化约束和 LLM 决策决定

## 运行方式

```bash
cd /home/wjh/db-env-gc
python3 main.py
```

也可以指定输出目录：

```bash
python3 main.py /home/wjh/db-env-gc/output
```

如果你只想快速生成项目、不想执行 validator 阶段，也可以这样运行：

```bash
python3 main.py --skip-validator
```

启动后可直接输入自然语言，或输入 JSON / 键值对形式的任务描述。

## 输入示例

### 自然语言

```text
帮我生成一个 postgres 13 的 Docker 环境。
端口用 55432。
数据库名 demo_db，用户名 demo，密码 demo123。
额外配置：
max_connections=200
shared_buffers=256MB
```

```text
debian软件包漏洞
生成用于复现 CVE-2022-0543 的 redis 环境
```

```text
dockerhub存在镜像
生成用于复现 CVE-2025-46817 的环境
```

```text
预发布版本
生成用于复现 CVE-2018-12453 的环境
```

```text
组件 RedisBloom 漏洞
生成用于复现 CVE-2024-25115 的环境
```

```text
给错误的数据库版本
生成用于复现 CVE-2025-46817 的版本为 2.0.0 的 redis 环境。
```

### 键值对

```text
db_type: mysql
version: 8.0
port: 3307
database: demo
username: demo
password: demo123
config:
  max_connections=150
  sql_mode=STRICT_TRANS_TABLES
```

### JSON

```json
{
  "db_type": "redis",
  "version": "7",
  "port": 6380,
  "password": "redis123",
  "config": {
    "maxmemory": "256mb",
    "appendfsync": "everysec"
  }
}
```

## 输出结果

每次运行会在 `output/` 下生成一个独立目录，通常包含：

- `docker-compose.yml`
- `Dockerfile`（按环境规划决定是否需要）
- `.env`
- `.env.example`
- `README.md`
- `config/`
- `init/`
- `state/task.json`
- `state/evidence.json`
- `state/reproduction_profile.json`
- `state/artifact_facts.json`
- `state/artifact_plan.json`
- `state/env_spec.json`
- `state/artifacts.json`
- `state/validation.json`

另外，项目根目录会记录：

- `terminal_log.txt`
- `agents_log.txt`

## 当前设计取向

- 主架构：`Plan-and-Execute`
- 协作方式：受控串行工作流
- 生成策略：`parser / reproduction_profile / artifact_plan / planner / generator / validator` 由 LLM 驱动，`tools/` 负责证据收集、制品事实查询和文件执行
- `tools/` 目录负责联网证据收集、镜像/源码存在性查询和文件系统操作，不参与内容生成
- `artifact_plan` 会优先读取画像中的 `version_candidates_json`（若存在），并在固定探测路线下按候选版本顺序探测
- 系统不再只围绕“数据库版本 + 官方镜像”做二选一，而是先构建“复现约束画像”，再由后续阶段求解环境形态
- 代码层只保留调度、日志、状态模型和文件工具，不在业务逻辑中硬编码数据库模板
