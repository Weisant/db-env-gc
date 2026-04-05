# demo_db_postgres_env

PostgreSQL 13 Docker 环境项目，用于本地开发和学习。

## 目录结构


.
├── docker-compose.yml    # 容器编排配置
├── .env.example          # 环境变量示例
├── .env                  # 环境变量（需自行创建）
├── config/
│   └── postgresql.conf   # PostgreSQL 自定义配置
├── init/
│   └── init.sql          # 初始化 SQL 脚本
├── data/                 # 数据持久化目录（自动创建）
└── README.md


## 快速启动

1. 复制环境变量文件：

bash
cp .env.example .env


2. 启动服务：

bash
docker-compose up -d


3. 查看运行状态：

bash
docker-compose ps


4. 查看日志：

bash
docker-compose logs -f postgres


## 连接数据库

使用 psql 命令行连接：

bash
# 通过 docker exec 连接
docker exec -it demo_postgres psql -U demo -d demo_db

# 通过本地 psql 连接
psql -h localhost -p 55432 -U demo -d demo_db


使用超级用户连接：

bash
docker exec -it demo_postgres psql -U postgres -d demo_db


## 关键配置项

| 配置项 | 值 | 说明 |
|--------|-----|------|
| max_connections | 200 | 最大连接数 |
| shared_buffers | 256MB | 共享内存缓冲区 |
| 端口 | 55432 | 主机映射端口 |
| 数据库 | demo_db | 默认数据库 |
| 普通用户 | demo / demo123 | 应用连接用户 |
| 超级用户 | postgres / root | 管理员用户 |

## 常用命令

停止服务：

bash
docker-compose down


停止并删除数据：

bash
docker-compose down -v
rm -rf data/


重启服务：

bash
docker-compose restart


## 自定义初始化

在 `init/init.sql` 文件中添加初始化 SQL 语句，容器首次启动时会自动执行。

示例：

sql
-- 创建额外的表
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入测试数据
INSERT INTO users (username) VALUES ('test_user');


## 注意事项

- 数据存储在 `./data` 目录，请确保有足够的磁盘空间
- 生产环境请修改默认密码
- 默认时区为 UTC，可在 docker-compose.yml 中调整 TZ 和 PGTZ 变量