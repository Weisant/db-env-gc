# DB Env GC

`db-env-gc` 是一个数据库环境生成 agent 项目。

它参考了 `plan_and_execute` 的终端输出风格，当前版本采用“结构化解析 + LLM 规划 + LLM 生成 + tools 写盘”的方式：

1. `需求解析智能体` 标准化用户输入
2. `环境规划智能体` 生成环境规划 JSON
3. `环境生成智能体` 产出完整 Docker 项目文件内容
4. `tools` 把文件内容真正写入磁盘
5. `校验智能体` 基于真实磁盘快照检查项目，并在必要时自动修复
6. `tools` 再写入状态文件

当前版本不涉及漏洞利用和验证逻辑，只生成可复现环境所需的 Docker 项目。

## 运行方式

```bash
cd /home/wjh/db-env-gc
python3 main.py
```

也可以指定输出目录：

```bash
python3 main.py /home/wjh/db-env-gc/output
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

每次运行会在 `output/` 下生成一个独立目录，包含：

- `docker-compose.yml`
- `.env`
- `.env.example`
- `README.md`
- `config/`
- `init/`
- `state/task.json`
- `state/env_spec.json`
- `state/artifacts.json`
- `state/validation.json`

另外，项目根目录会记录：

- `terminal_log.txt`
- `agents_log.txt`

## 当前设计取向

- 主架构：`Plan-and-Execute`
- 协作方式：受控串行工作流
- 生成策略：`parser / planner / generator / validator` 由 LLM 驱动
- tools 目录只负责文件系统操作，不参与内容生成
- 代码层只保留调度、日志、状态模型和文件工具，不在业务逻辑中硬编码数据库模板
