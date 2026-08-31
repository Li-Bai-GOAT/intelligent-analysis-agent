# 数据库迁移与备份恢复计划

> 状态：已验证
>
> 优先级：P0
>
> 最后核验：2026-08-31
>
> 适用范围：单一 PostgreSQL 数据库、Tortoise ORM、Aerich、Windows + Docker Desktop

## 1. 落地原则

项目继续使用一个长期 PostgreSQL 数据库，不拆分开发和生产数据库。结构发布遵循固定顺序：

1. 修改模型前创建带日期的 PostgreSQL custom-format 备份。
2. 使用 Aerich 生成迁移，人工检查 SQL 是否涉及删列、类型变化或大范围数据重写。
3. 通过统一维护工具再次自动备份并执行 `aerich upgrade`。
4. 执行后端回归、`/ready` 和关键浏览器页面验证。
5. 使用最新备份恢复到一次性数据库，确认备份实际可恢复。

`downgrade` 只适用于经过审查的可逆迁移。删除列、字段类型变化、清空或重写数据必须以已验证备份为主要恢复方案。

## 2. 已实现内容

- `migrations/models/0_20260830_schema_baseline.py`：幂等完整 schema 基线，可接管已有表，也可构建空恢复库；基线禁止 downgrade。
- `migrations/models/1_20260829_sandbox_lifecycle.py`：保留生命周期字段升级；对已有字段使用幂等 SQL。
- `app/database.py`：关闭自动建表时校验数据库已应用仓库全部迁移；无 Aerich 基线或存在待执行迁移时拒绝启动。
- `app/config.py` 与 `.env.example`：`DB_AUTO_CREATE_SCHEMA` 默认改为 `false`；生产环境继续强制禁止自动建表。
- `scripts/db_maintenance.py`：统一备份、迁移、迁移头检查、临时库恢复验证和受保护的正式恢复。
- `tests/test_database_migrations.py`：8 项测试覆盖配置门禁、迁移顺序、旧 Aerich 元数据兼容、启动迁移头校验、基线幂等和恢复确认保护。

## 3. 标准操作

所有命令从仓库根目录执行。

### 3.1 模型修改前备份

```powershell
.\.venv\Scripts\python.exe .\scripts\db_maintenance.py backup
```

输出位于 `backups/database/`：

- `*.dump`：PostgreSQL custom-format 备份；
- `*.json`：创建时间、数据库名、文件大小、SHA-256 和已应用迁移。

### 3.2 生成并检查迁移

```powershell
.\.venv\Scripts\aerich.exe migrate --name describe_the_change
git diff -- migrations
```

不得跳过 SQL 审查。发现 `DROP COLUMN`、类型转换、`DELETE`、`TRUNCATE` 或不可逆数据变换时，必须在变更说明中写出使用哪个备份恢复、预期停机方式和数据校验查询。

### 3.3 自动备份并升级

```powershell
.\.venv\Scripts\python.exe .\scripts\db_maintenance.py migrate
.\.venv\Scripts\python.exe .\scripts\db_maintenance.py heads
```

`migrate` 不提供跳过备份选项。只有备份成功后才运行 Aerich；升级后若仍有 migration head，命令返回失败。

若旧数据库已经记录迁移 `1`、但尚未记录后来补充的完整基线 `0`，工具会复制最新模型状态并以更早的 Aerich 元数据 ID 登记基线，然后再执行 upgrade。这样不会重建现有表，也不会颠倒后续 downgrade 顺序。

### 3.4 验证备份可恢复

```powershell
.\.venv\Scripts\python.exe .\scripts\db_maintenance.py verify-restore `
  --backup-file .\backups\database\<backup>.dump
```

工具在同一个 PostgreSQL 容器创建随机命名的一次性数据库，执行 `pg_restore --exit-on-error`，检查 public 表和 Aerich 记录后在 `finally` 中删除验证库。它不是第二套长期环境。

### 3.5 正式恢复

先停止 DataAgent 主服务，然后显式确认目标数据库名：

```powershell
.\scripts\start.ps1 -Action down
.\.venv\Scripts\python.exe .\scripts\db_maintenance.py restore `
  --backup-file .\backups\database\<backup>.dump `
  --confirm-restore data_analysis
```

`--confirm-restore` 的值必须替换为当前 `.env` 中的 `DB_NAME`；本地验收基线为 `data_analysis`。

正式恢复有三层保护：

- 确认文本必须与当前 `DB_NAME` 完全一致；
- 8090 仍监听时拒绝恢复；
- 覆盖前自动创建 `pre_restore` 备份。

## 4. 每次迁移后的验收

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_database_migrations -v
.\.venv\Scripts\python.exe -m unittest tests.test_task_regressions -v
Invoke-RestMethod http://127.0.0.1:8090/ready | ConvertTo-Json -Depth 4

cd frontend
npm.cmd run lint
npm.cmd run build
npm.cmd run test:e2e
```

至少再从真实浏览器验证登录、会话列表和管理后台系统提示词读取，证明认证、会话和外键相关表可正常访问。

## 5. 真实验收结果

2026-08-31 已在当前 `data_analysis` PostgreSQL 数据库完成：

1. 迁移前手工备份与 `migrate` 自动备份均成功生成非空 custom-format dump 和 SHA-256 manifest；
2. 旧库原有 `1_20260829_sandbox_lifecycle.py`，工具将完整基线安全登记为更早的 `id=0`，没有重建业务表；
3. `aerich heads` 返回 `No available heads`，数据库记录基线 `0` 和生命周期迁移 `1`；
4. 迁移前备份成功恢复到一次性数据库：13 张 public 表、1 条迁移记录；
5. 迁移后备份成功恢复到一次性数据库：13 张 public 表、2 条迁移记录；两次验证库均在 `finally` 中删除，残留数为 0；
6. 主服务以 `DB_AUTO_CREATE_SCHEMA=false` 重启成功，`/ready` 的 PostgreSQL、Redis、Sandbox、Milvus、Embedding 全部为 `ok`；
7. 后端 72 项中 69 项通过，3 项 Linux/POSIX 进程组测试在 Windows 跳过；
8. 前端 lint、生产构建、9 项确定性 Chromium E2E 和 3 项真实服务浏览器验收全部通过；
9. 浏览器临时普通用户、管理员及测试会话已清理，残留账号为 0。

迁移后可恢复快照：`data_analysis_20260831_022212_606104_manual.dump`，大小 661621 字节，SHA-256 为 `0d2c8aca8450164fd37554419fc1bd273604a758815ca4d787299d081154648b`。备份目录已被 Git 忽略，不进入源码提交。
