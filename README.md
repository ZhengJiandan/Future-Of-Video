# long-video-master

当前仓库只保留一条主链路：

1. 用户输入创意、选择角色档案、选择场景档案、上传参考图
2. 后端生成完整剧本
3. 用户审核剧本后拆分片段
4. 生成首段首帧，后续片段串联上一段尾帧
5. 调用真实视频 provider 生成片段并合成成片

## 当前有效目录

- `backend/app/api/endpoints/script_pipeline.py`
- `backend/app/services/pipeline_workflow.py`
- `backend/app/services/script_generator.py`
- `backend/app/services/script_splitter.py`
- `backend/app/services/doubao_video_official.py`
- `backend/app/services/nanobanana_pro.py`
- `backend/app/services/video_merger.py`
- `frontend/src/pages/ScriptPipelinePage.tsx`
- `frontend/src/pages/CharacterLibraryPage.tsx`
- `frontend/src/pages/SceneLibraryPage.tsx`

## 环境要求

- Python 3.9+
- Node.js 18+
- MySQL 8
- FFmpeg

## 数据库

执行：

```sql
SOURCE backend/sql/init_schema.sql;
```

当前主链路现在需要五张表：

- `users`
- `pipeline_projects`
- `pipeline_character_profiles`
- `pipeline_scene_profiles`
- `pipeline_render_tasks`

如果你之前已经执行过旧版 `init_schema.sql`，还需要额外执行一次：

```sql
SOURCE backend/sql/upgrade_project_history.sql;
```

这个脚本会把 `pipeline_projects` 从“每个用户只能有一个项目”升级成“每个用户可保存多个历史项目”。

如果你本地还保留了历史版本的 `users` 表，注册时报类似 `Unknown column 'users.name'`，再执行一次：

```sql
SOURCE backend/sql/upgrade_user_auth_schema.sql;
```

如果你之前已经建过角色档案/场景档案表，想升级到“分类标签”版本，再执行一次：

```sql
SOURCE backend/sql/upgrade_profile_category_schema.sql;
```

如果你之前已经建过角色档案表，但还没有“面部特写锚点”字段，再执行一次：

```sql
SOURCE backend/sql/upgrade_character_anchor_pack_schema.sql;
```

如果你之前已经建过主链路表，但还没有渲染任务持久化表，再执行一次：

```sql
SOURCE backend/sql/upgrade_render_task_schema.sql;
```

## 环境变量

后端读取 `backend/.env`。
仓库提供了可提交的模板文件：`backend/.env.example`。

至少确认这些配置存在且正确：

```env
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/delta_force_video
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2
DOUBAO_API_KEY=...
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=...
DOUBAO_VIDEO_MODEL=...
DOUBAO_READ_TIMEOUT=240
DOUBAO_SCRIPT_READ_TIMEOUT=360
DOUBAO_MAX_RETRIES=2
NANOBANANA_API_KEY=...
UPLOAD_DIR=uploads
```

注意：

- 不要把真实密钥提交到仓库。
- 旧版本里如果已经提交过真实凭据，需要立即轮换。
- `DEBUG` 现在接受 `true/false/debug/release` 这类值，`ENVIRONMENT` 也可作为 `ENV` 的别名。

## 启动方式

推荐只使用一个脚本：

```bash
bash dev.sh backend
bash dev.sh worker
bash dev.sh frontend
```

或手动分别启动：

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

```bash
cd frontend
npm run dev
```

```bash
cd backend
celery -A app.celery_app:celery_app worker --loglevel=info --concurrency=2
```

现在渲染任务已经切到独立 Celery worker 执行：

- API 进程只负责创建任务、入库和投递到队列
- Celery worker 负责实际渲染和合成
- 服务重启后，数据库中处于 `processing` 的任务会重置为 `queued`，并在启动时重新投递

## 本地联调

推荐按这个顺序做一次最小闭环联调：

1. 启动基础依赖：MySQL、Redis，以及你配置的 Celery broker
2. 执行数据库初始化或升级脚本，确认 `pipeline_render_tasks` 已存在
3. 启动后端 API：`bash dev.sh backend`
4. 启动 Celery worker：`bash dev.sh worker`
5. 启动前端：`bash dev.sh frontend`
6. 访问 `/api/v1/pipeline/health` 和 `/health`，确认 API 正常
7. 在页面里走一遍“生成剧本 -> 拆片 -> 关键帧 -> 渲染”
8. 观察后端日志和 worker 日志，确认任务经历 `queued -> processing -> completed`

如果要验证异常链路，再补做这三项：

1. 渲染过程中重启后端 API，确认任务会从数据库恢复并重新投递
2. 在 `queued` 或 `processing` 状态点“取消任务”，确认任务变成 `cancelled`
3. 对 `failed` 或 `cancelled` 的任务点“重试任务”，确认会生成新的 `task_id`

## 访问地址

- 前端: `http://127.0.0.1:5173`
- 后端 OpenAPI: `http://127.0.0.1:8080/docs`
- 后端健康检查: `http://127.0.0.1:8080/health`

## 备注

- FFmpeg 是系统依赖，不装在 Python 虚拟环境里。
- 角色档案和场景档案都走数据库，不再使用旧 JSON 文件存储。
- 仓库中此前的旧认证、旧角色/地图系统、旧批量脚本和旧占位页面已清理。
