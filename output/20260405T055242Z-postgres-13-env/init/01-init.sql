-- 初始化数据库 demo_db
CREATE TABLE IF NOT EXISTS env_ready (
    id SERIAL PRIMARY KEY,
    note TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO env_ready (note) VALUES ('postgres environment ready');
