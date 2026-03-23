# future of video

`future of video` 是一个面向长链路创作的 AI 视频生成工作台。它把角色档案、场景档案、剧本生成、镜头拆分、关键帧生成和分段视频渲染串成一条可编辑、可审核、可恢复的工作流。

当前仓库采用前后端分离架构：

- 前端：React + Vite + Ant Design
- 后端：FastAPI + SQLAlchemy + SQLite / MySQL
- 媒体处理：FFmpeg
- 模型调用：Doubao、OpenAI 兼容接口、NanoBanana 等外部模型能力
- 任务调度：
  - `minimal` 模式：单进程本地后台任务，不依赖 Redis / Celery
  - `full` 模式：Celery + Redis

当前运行结论先说清楚：

- `minimal` 最小运行模式下，`MySQL` 已经不是必需组件。
- 最小模式推荐组合是：`SQLite + FastAPI + 前端开发服务器 + FFmpeg + DOUBAO_API_KEY`。
- 只有你显式选择 `MySQL`，或者切到 `full` 队列模式时，才需要再准备 `MySQL / Redis / Celery worker`。

## 在线 Demo

- 展示地址：`http://82.156.153.123/`
- 用户：test，密码：123456
- 仅供展示使用。


## 作者说明

- 这个项目主要解决的是当前视频模型单次生成时长较短、很难直接独立成片的问题。理论上可以通过分段串联生成超过 5 分钟的视频，但考虑到现阶段模型能力，实际更建议控制在 1 分钟以内，以降低角色漂移、风格漂移和连续性失真的风险。
- 这个项目目前完全由个人在业余时间开发维护。我本身也是上班党，所以实现里难免会有疏漏、粗糙之处，欢迎基于实际使用问题一起讨论、交流和改进。
- 当前仓库的主链路默认依赖豆包系大模型。由于 `Seedance 2.0` 的 API 目前还没有开放，再加上豆包视频模型近期受版权审核策略影响，实际可用性和通过率都不算稳定；如果你打算认真投入使用，更建议接入可灵 API 或其他更稳定的视频模型能力。
- 图片模型方面，更推荐使用 `NanoBanana Pro`。项目里目前接的是第三方兼容接入，成本相对便宜；如果不配置 `NANOBANANA_API_KEY`，系统会默认回退到豆包图片模型。

## 功能概览

- 账号注册、登录、当前项目草稿保存
- 角色档案库
  - 角色参考图上传
  - 图片分析补全角色字段
  - 角色原型图生成
  - 三视图 / 近景锚点图生成
  - 音色描述作为角色设定维护
- 场景档案库
  - 场景参考图上传
  - 图片分析补全场景字段
  - 场景原型图生成
- 剧本主链路
  - 未匹配正式角色时自动生成临时角色草稿
  - 用户描述生成完整剧本
  - 剧本结果前端可见、可修改
  - 剧本拆分为视频片段
  - 剧本优化阶段与拆分阶段双重连续性检查
  - 关键首帧生成与片段首尾串联
  - 分段视频生成
  - 临时角色在生成过视频后可按首帧造型保存到正式角色档案库
  - 最终成片输出

## 仓库结构

```text
.
├── backend
│   ├── alembic                  # 数据库迁移
│   ├── app
│   │   ├── api                  # FastAPI 路由
│   │   ├── core                 # 配置与安全
│   │   ├── db                   # 数据库引擎与初始化
│   │   ├── models               # SQLAlchemy 模型
│   │   ├── services             # 核心工作流、角色/场景库、模型能力
│   │   └── workers              # Celery worker 入口
│   ├── sql                      # 初始化 SQL、升级脚本、示例种子数据
│   ├── tests                    # 后端测试
│   └── requirements.txt
├── docs
│   └── examples                 # 对外样例输入与回归用例
├── frontend
│   ├── src
│   │   ├── layouts
│   │   ├── pages
│   │   ├── services
│   │   └── stores
│   └── package.json
├── uploads                     # 根目录运行时产物（如 Docker 挂载目录）
├── docker-compose.yml
└── README.md
```

## 核心流程

1. 用户创建项目并输入创意描述。
2. 选择或创建角色档案、场景档案，并可上传参考图进行分析补全。
3. 如果没有匹配到正式角色档案，系统会先按角色档案格式自动生成临时角色草稿，直接用于本次创作。
4. 后端基于档案与用户描述生成完整剧本。
5. 剧本在前端展示，用户可直接修改。
6. 剧本被拆分为多个视频片段，并做连续性约束检查。
7. 系统为必要片段生成首帧，其他片段尽量复用上一段尾帧进行串联。
8. 分段视频按顺序生成；可逐段确认继续，也可一键全部生成。
9. 如果临时角色已经参与视频生成，前端会提示把该角色按首次出场首帧造型保存到正式角色档案库。
10. 系统输出最终成片并回写任务状态。

## 运行要求

建议环境：

- Python 3.10+
- Node.js 18+
- SQLite 可直接使用系统内置能力
- MySQL 仅在你主动切到 MySQL 数据库，或使用 `full` 队列模式时需要
- FFmpeg 已安装并可通过 `PATH` 调用

可选组件：

- Redis
- Celery worker

如果只是本地体验主链路，推荐直接使用 `minimal` 模式，不需要 Redis / Celery。

这里容易混淆的一点是：

- 仓库代码里的 `Settings.DATABASE_URL` 默认回退值仍然是 MySQL。
- 但仓库提供的推荐启动方式，是先复制 `backend/.env.example`，而这份示例已经改成了 SQLite 最小模式。
- 所以如果你跳过 `cp backend/.env.example backend/.env` 这一步，直接裸跑后端，仍然可能因为默认 MySQL 配置而启动失败。

## 快速开始

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd future-of-video
```

### 推荐路径：GitHub 新用户最短成功路径

如果你只是从 GitHub 拉代码后想先把主链路跑起来，推荐直接使用：

- `minimal` 模式
- SQLite
- 本地前后端开发模式

最少前提：

- 已安装 Python 3.10+
- 已安装 Node.js 18+
- 已安装 FFmpeg
- 已准备 `DOUBAO_API_KEY`
- 已复制 `backend/.env.example` 到 `backend/.env`

注意：

- 当前后端启动时会实例化剧本生成能力，所以 `DOUBAO_API_KEY` 不是“到生成功能时才需要”，而是当前最小链路的启动级依赖。
- `OPENAI_API_KEY` 对当前最小链路不是启动必填项。
- `minimal` + SQLite 组合下不需要 MySQL，也不需要手动建库。
- 本地最小模式的 SQLite 文件默认在 `backend/future_of_video.db`。
- Docker 最小模式的 SQLite 文件默认在 `backend/uploads/future_of_video.db`。

### 2. 配置后端环境变量

```bash
cp backend/.env.example backend/.env
```

说明：

- 本地开发模式下，后端直接读取 `backend/.env`。
- Docker Compose 下，`backend` 和 `worker` 容器也会读取同一个 `backend/.env`。
- 如果你已经有可用的 Doubao Key，直接填到 `DOUBAO_API_KEY` 即可，不需要额外准备第二套 key。
- 如果你想走最小运行路径，`backend/.env` 里应继续保持 SQLite 配置，不要误改回 MySQL。

最少需要确认这些配置：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `SECRET_KEY`
- `PIPELINE_RUNTIME_MODE`
- `DOUBAO_API_KEY`

可选但常用：

- `OPENAI_API_KEY`
  - 当前最小链路不是启动必填项。
- `NANOBANANA_API_KEY`
  - 配置后优先使用 NanoBanana 生成图片。
  - 未配置时，图片生成会回退到 Doubao `doubao-seedream-5-0-260128`。

最小运行模式示例：

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

如果你希望最小测试版本完全不依赖 MySQL，直接使用上面的 SQLite 配置即可。

一个可直接运行的最小示例：

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
DOUBAO_API_KEY=your_doubao_api_key
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

Docker 最小测试示例：

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
DOUBAO_API_KEY=your_doubao_api_key
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

完整队列版示例：

```env
PIPELINE_RUNTIME_MODE=full
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/future_of_video
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2
```

### 3. 安装后端依赖

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 初始化数据库

如果你使用 SQLite 最小模式，这一步可以跳过，应用启动时会自动建表。

补充说明：

- `backend/sql/init_schema.sql` 主要用于新 MySQL 库初始化。
- SQLite 最小模式不要执行这份 MySQL 初始化 SQL。
- SQLite 最小模式通常也不需要手动跑迁移；按 README 启动后端即可自动建表。

新 MySQL 数据库初始化：

```bash
mysql -u root -p < backend/sql/init_schema.sql
```

如果你是在已有数据库上升级，或希望显式同步到最新 schema，执行：

```bash
cd backend
alembic upgrade head
```

默认示例数据库名是 `future_of_video`。如果你使用自己的数据库名，请同步修改 `backend/.env` 中的 `DATABASE_URL`。

### 5. 启动后端

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

默认后端地址：

- `http://127.0.0.1:8080`
- API 前缀：`/api/v1`

### 6. 配置并启动前端

```bash
cp frontend/.env.example frontend/.env
cd frontend
npm install
npm run dev
```

默认前端地址：

- `http://127.0.0.1:5173`

开发环境下，Vite 会把 `/api/v1` 和 `/uploads` 代理到 `http://127.0.0.1:8080`。

### 7. 最小模式启动后你应该看到什么

- 后端能正常启动，不要求 MySQL
- 项目列表页可以打开
- SQLite 数据库文件会在 `backend/` 目录下自动创建
- 进入主链路后，可以继续做角色、剧本、分段、关键帧和视频生成
- 刷新页面后，`/api/v1/projects` 不应再因为端口或数据库初始化问题报 500

如果后端启动阶段就报错，优先检查：

- `DOUBAO_API_KEY` 是否已配置
- `pip install -r requirements.txt` 是否已经执行，尤其要确认安装了 `aiosqlite`
- `ffmpeg` 是否在 `PATH` 中可用

## 运行模式

### `minimal`

适合本地开发、单机部署、演示环境。

- 需要数据库
- 默认推荐 SQLite
- `MySQL` 不是该模式的必需组件
- 需要外部模型 API
- 需要 FFmpeg
- 不需要 Redis
- 不需要 Celery worker
- 渲染任务在 FastAPI 进程内以后台协程执行

### `full`

适合需要独立 worker 和队列调度的环境。

- 需要数据库
- 需要外部模型 API
- 需要 FFmpeg
- 需要 Redis
- 需要 Celery worker

## 数据库升级说明

仓库同时保留了两套数据库准备方式：

- `backend/sql/init_schema.sql`
  - 用于新环境快速初始化。
- `backend/alembic`
  - 用于后续 schema 迁移和升级。

如果你是从旧版本升级，请优先使用：

```bash
cd backend
alembic upgrade head
```

如果你只执行了旧的初始化 SQL，而没有补迁移，可能会遇到字段缺失问题。

## 后端接口概览

主要接口前缀为 `/api/v1`。

认证：

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

项目：

- `GET /projects`
- `POST /projects`
- `GET /projects/current`
- `PUT /projects/current`

主链路：

- `POST /pipeline/generate-script`
- `POST /pipeline/prepare-characters`
- `POST /pipeline/split-script`
- `POST /pipeline/generate-keyframes`
- `POST /pipeline/render`
- `POST /pipeline/render/{task_id}/resume`
- `POST /pipeline/render/{task_id}/pause`
- `POST /pipeline/render/{task_id}/cancel`
- `POST /pipeline/render/{task_id}/clips/{clip_number}/retry`
- `POST /pipeline/render/{task_id}/retry`
- `GET /pipeline/render/{task_id}`

其中“逐段确认继续生成”和“一键全部生成”都通过渲染请求里的 `auto_continue_segments` 参数控制，而不是单独的确认接口。

角色 / 场景档案：

- `GET /pipeline/characters`
- `POST /pipeline/characters`
- `POST /pipeline/characters/analyze-reference`
- `GET /pipeline/scenes`
- `POST /pipeline/scenes`
- `POST /pipeline/scenes/analyze-reference`

## 测试与构建

后端测试：

```bash
cd backend
python3 -m pytest -o addopts='' tests
```

后端语法检查：

```bash
python3 -m py_compile backend/app/main.py
```

前端构建：

```bash
cd frontend
npm run build
```

## Docker Compose

仓库中包含一个开源友好的 `docker-compose.yml` 示例：

- 默认运行 `minimal` 模式
- 默认只启动 `backend`、`frontend`
- 默认使用 SQLite，不依赖 MySQL
- SQLite 数据库文件会落在 `backend/uploads/future_of_video.db`
- 如果需要 MySQL + worker 队列版，再启用 `full` profile

最小模式：

```bash
cp backend/.env.example backend/.env
# 在 backend/.env 中至少填入 DOUBAO_API_KEY
# 并确认 DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
# 如无特殊需求，保持 PIPELINE_RUNTIME_MODE=minimal
docker compose up --build
```

最小模式下的默认访问地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8080`

最小模式下不需要做这些事：

- 不需要本地安装 MySQL
- 不需要手动建 SQLite 库
- 不需要执行 `backend/sql/init_schema.sql`
- 不需要启动 Redis / Celery worker

完整模式：

```bash
cp backend/.env.example backend/.env
# 在 backend/.env 中填入 DOUBAO_API_KEY，并显式切换到 MySQL
DATABASE_URL=mysql+aiomysql://fov:change-me-db@mysql:3306/future_of_video \
PIPELINE_RUNTIME_MODE=full \
docker compose --profile full up --build
```

注意：

- compose 中的数据库口令是公开示例值，生产环境必须改掉。
- backend / worker 容器会读取 `backend/.env`。
- 默认 `docker compose up --build` 走的是 SQLite 最小模式，不会拉起 `mysql` 和 `redis`。
- 当前最小链路仍然要求 `DOUBAO_API_KEY`，否则后端启动阶段会失败。
- `backend/uploads/` 同时保存上传文件、生成产物和 Docker 最小模式下的 SQLite 数据库文件。
- 开源仓库里的 compose 仅作为开发 / 演示示例，不是生产部署模板。

补一句结论：

- `docker compose up --build` 的默认行为已经证明最小模式不把 `mysql` 当成前置依赖。
- `mysql` 服务只会在 `--profile full` 下被显式启用。

## 示例输入与回归样例

对外样例已经整理到 `docs/examples/`：

- `docs/examples/cat-pipeline-inputs.md`
- `docs/examples/ancient-romance-pipeline-inputs.md`
- `docs/examples/cat-character-entry-regression.md`

这些文件适合本地回归测试、演示和 prompt 样例参考。

## 开源发布前建议

如果你准备公开部署或接受外部贡献，建议至少确认这些事项：

- 检查 `.env`、日志、截图、测试数据里没有真实密钥或敏感信息。
- 清理 `backend/uploads/`、`uploads/` 等本地产物。
- 为生产环境单独配置 `DEBUG=false`、密钥管理、HTTPS、对象存储和上传安全策略。
- 确认第三方模型服务的条款允许你的使用方式。

## 常见问题

### 1. 为什么我本地不想装 Redis / Celery？

直接使用：

```env
PIPELINE_RUNTIME_MODE=minimal
```

这样主链路仍然可以跑，只是渲染任务不会走外部队列。

### 2. 为什么我不配 MySQL 也能跑？

因为 `minimal` 模式现在支持直接使用 SQLite，而且应用启动时会自动建表：

```env
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

这意味着 `MySQL` 已经不是最小运行模式的必需组件；只有你主动切换到 MySQL，或启用 `full` 模式时才需要它。

### 3. 为什么本地和 Docker 的 SQLite 路径不一样？

本地开发默认从 `backend/` 目录启动后端，所以使用：

```env
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

Docker 最小模式为了把数据库文件和上传产物一起持久化到挂载目录，默认使用：

```env
DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
```

### 4. 为什么后端启动时就提示 `DOUBAO_API_KEY` 未配置？

因为当前后端启动时会初始化剧本生成服务，所以 `DOUBAO_API_KEY` 现在是启动级依赖，不只是调用生成接口时才需要。

### 4.1 为什么我明明用的是 minimal，还会看到 MySQL 连接错误？

通常是因为你没有复制 `backend/.env.example`，或者把 `DATABASE_URL` 改回了 MySQL 默认值。当前代码层的回退默认值仍然是：

```env
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/future_of_video
```

如果你要走最小运行路径，请显式确认：

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

### 5. 为什么图片生成没有走 NanoBanana？

当前逻辑是：

- 优先使用 `NANOBANANA_API_KEY`
- 如果未配置，则回退到 `DOUBAO_API_KEY` 对应的 Doubao 图片模型

### 6. 临时角色什么时候会提示保存到角色档案库？

如果角色没有匹配到正式档案，系统会先生成临时角色草稿，并直接进入本次剧本、关键帧和视频链路。只有当该临时角色已经实际参与过视频生成后，前端才会提示保存到正式角色档案库；保存时会直接使用该角色首次出场片段的首帧造型作为参考图，不再额外生成三视图或面部特写。

### 7. 为什么最终视频没有项目级额外音频？

当前仓库默认关闭旧的项目级音频合成链路，公开视频效果主要依赖视频模型自身音频能力，或输出静音结果。这是当前实现状态，不是配置错误。

## 免责声明

本项目会调用第三方模型服务，并可能生成图片、音频、视频等媒体内容。请确保你的使用方式符合：

- 相关模型服务商的使用条款
- 你所在地区的法律法规
- 你对素材、角色、音频和上传内容的授权边界
