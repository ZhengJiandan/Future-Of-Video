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

当前主链路现在需要四张表：

- `users`
- `pipeline_projects`
- `pipeline_character_profiles`
- `pipeline_scene_profiles`

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

## 环境变量

后端读取 `backend/.env`。

至少确认这些配置存在且正确：

```env
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/delta_force_video
DOUBAO_API_KEY=...
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=...
DOUBAO_VIDEO_MODEL=...
NANOBANANA_API_KEY=...
UPLOAD_DIR=uploads
```

## 启动方式

推荐只使用一个脚本：

```bash
bash dev.sh backend
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

## 访问地址

- 前端: `http://127.0.0.1:5173`
- 后端 OpenAPI: `http://127.0.0.1:8080/docs`
- 后端健康检查: `http://127.0.0.1:8080/health`

## 备注

- FFmpeg 是系统依赖，不装在 Python 虚拟环境里。
- 角色档案和场景档案都走数据库，不再使用旧 JSON 文件存储。
- 仓库中此前的旧认证、旧角色/地图系统、旧批量脚本和旧占位页面已清理。
