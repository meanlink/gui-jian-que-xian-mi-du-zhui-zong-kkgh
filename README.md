# 轨检缺陷密度追踪

密度聚类的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览、审计轨迹和批次冷存。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery、ColdArchive。

### 批次冷存（06 / COLD TIER）
历史批次可转入独立冷存卷 `cold-store`（环境变量 `COLD_STORE_DIR`，默认 `/coldstore`），与数据库、产物卷分离：
- **保留全部业务记录**：批次目录、来源、点数、内容指纹，历史分析任务结果与分发简报都留在在线库，取回前后均可直接查阅；只有在线原始点会在核齐后释放。
- **核齐才释放**：搬移先写 `.staging` 半成品并记录偏移，封存后从磁盘回读文件指纹、点数与内容指纹，三项一致才在一个事务内释放 `datasets.records`；半成品始终不开放。
- **取回校验**：新试验遇到冷存批次立即登记为 `waiting` 并写明原因，同时只发起一次共用的取回；清单/文件指纹/点数/内容指纹全部通过才恢复在线并把任务放回 `queued`。缺件或篡改保持等待并记录阻断原因，可在页面重试。
- **并发安全**：释放与恢复都在数据集行锁内完成；worker 计算前再核对批次仍在线且指纹一致，清退与新试验并发时不会读到空批次。
- **中断恢复**：搬移或取回中断后保留 staging 并记录 `bytes_done`；重试从原偏移续传（前缀不符则从头），复用同一条 `ColdArchive`，不新增批次、不重复搬移。
- **页面**：`#/cold` 展示每个批次的存储状态、冷存位置与清单路径、进度、等待试验数和阻断原因；负责人可发起冷存、重试取回/搬移。接口：`GET /datasets/{id}/cold`、`GET /cold-archives`、`POST /datasets/{id}/cold/{archive|restore|retry}`。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18210；后端文档 http://localhost:19210/docs；数据库宿主端口 17710。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载、批次冷存与取回|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准、安排分发或发起冷存|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR、COLD_STORE_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/waiting/completed/failed；StorageState：online/archiving/cold/restoring；ColdState：queued/archiving/sealed/restore_queued/restoring/restored/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=rail-density；FRONTEND_PORT=18210；BACKEND_PORT=19210；DB_PORT=17710；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷；冷存使用独立命名卷 `cold-store` 挂载到 `COLD_STORE_DIR`，便于单独扩容与清理。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1011/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
