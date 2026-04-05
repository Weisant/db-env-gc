# postgres-13-env

这是一个用于复现数据库运行环境的 Docker 项目。

## 环境信息

- 数据库类型: postgres
- 版本: 13
- 宿主机端口: 55432
- 项目名称: postgres-13-env

## 目录说明

- `docker-compose.yml`: 容器编排
- `.env`: 运行时环境变量
- `config/`: 数据库配置文件
- `init/`: 初始化文件

## 使用方式

```bash
docker compose up -d
docker compose ps
docker compose logs -f postgres
```

## 边界说明

本项目只负责生成数据库环境，不包含漏洞利用代码，也不包含漏洞验证 payload。
