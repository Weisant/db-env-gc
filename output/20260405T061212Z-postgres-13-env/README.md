# PostgreSQL 13 Docker 环境

本项目用于快速搭建一个配置好的 PostgreSQL 13 数据库环境。

## 环境要求

- Docker
- Docker Compose

## 快速启动

1. **配置环境变量**
   
   复制 `.env.example` 为 `.env`，并根据需要修改配置（默认配置已可直接运行）：
   bash
   cp .env.example .env
   

2. **启动服务**

   在项目根目录下运行：
   bash
   docker-compose up -d
   

3. **验证状态**

   查看容器是否正常运行（healthy）：
   bash
   docker-compose ps
   

## 连接信息

- **Host**: `localhost` 或 `127.0.0.1`
- **Port**: `55432` (映射自容器内部的 5432)
- **User**: `demo`
- **Password**: `demo123` (请在 .env 中修改)
- **Database**: `demo_db`

### 连接命令示例

bash
psql -h localhost -p 55432 -U demo -d demo_db


## 配置说明

本项目通过 Docker Compose 的 `command` 指令强制覆盖了以下 PostgreSQL 参数：
- `max_connections`: 200
- `shared_buffers`: 256MB
- `log_statement`: all

这些配置定义在 `docker-compose.yml` 中，无需手动修改 `postgresql.conf`。

## 目录结构


.
├── docker-compose.yml      # 容器编排文件
├── .env                    # 环境变量配置
├── .env.example            # 环境变量示例
├── config/
│   └── postgresql.conf     # 配置参考文档
├── init/                   # 初始化 SQL 脚本目录
└── README.md               # 本说明文件


## 数据持久化

数据存储在 Docker volume `postgres_data` 中，位于容器内的 `/var/lib/postgresql/data`。

若需完全重置环境，请执行：
bash
docker-compose down -v


## 停止服务

bash
docker-compose down