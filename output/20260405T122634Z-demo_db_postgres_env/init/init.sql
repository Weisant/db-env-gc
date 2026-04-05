-- PostgreSQL 初始化脚本
-- 容器首次启动时自动执行此脚本
-- 数据库 demo_db 和用户 demo 已通过环境变量自动创建

-- 设置默认搜索路径
SET search_path TO public;

-- 示例：创建测试表（可选）
-- CREATE TABLE IF NOT EXISTS example (
--     id SERIAL PRIMARY KEY,
--     name VARCHAR(100),
--     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );

-- 示例：授予权限（可选）
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO demo;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO demo;

-- 初始化完成提示
DO $$ 
BEGIN
    RAISE NOTICE 'Initialization script completed successfully.';
END $$;