# future of video

`future of video` 是一个面向长链路创作的 AI 视频生成工作台。它把角色档案、场景档案、剧本生成、镜头拆分、关键帧生成、视频渲染和统一音频合成串成了一条可编辑、可审核、可恢复的工作流。

项目当前采用前后端分离架构：

- 前端：React + Vite + Ant Design
- 后端：FastAPI + SQLAlchemy + MySQL
- 媒体处理：FFmpeg
- 模型调用：Doubao、OpenAI 兼容接口、NanoBanana 等外部模型能力
- 任务调度：
  - `full` 模式：Celery + Redis
  - `minimal` 模式：单进程本地后台任务，不依赖 Redis / Celery

## 功能概览

- 账号注册、登录和当前项目草稿保存
- 角色档案库
  - 角色参考图上传
  - 图片分析补全角色字段
  - 角色原型图生成
  - 三视图生成
  - 角色语音绑定与单句试音
- 场景档案库
  - 场景参考图上传
  - 图片分析补全场景字段
  - 场景原型图生成
- 剧本主链路
  - 用户描述生成完整剧本
  - 剧本拆分为视频片段
  - 片段二次校验
  - 关键首帧生成与片段首尾串联
  - 视频渲染
  - 统一音频规划、对白 / 音效 / 环境 / 配乐合成
  - 最终成片输出


## 仓库结构

```text
.
├── backend
│   ├── app
│   │   ├── api            # FastAPI 路由
│   │   ├── core           # 配置与安全
│   │   ├── db             # 数据库引擎与初始化
│   │   ├── models         # SQLAlchemy 模型
│   │   ├── services       # 核心工作流、角色/场景库、音频/视频能力
│   │   └── workers        # Celery worker 入口
│   ├── sql                # 初始化 SQL 与升级脚本
│   ├── tests              # 后端测试
│   └── requirements.txt
├── frontend
│   ├── src
│   │   ├── layouts
│   │   ├── pages
│   │   ├── services       # API client
│   │   └── stores
│   └── package.json
├── docker-compose.yml
└── README.md
```

## 核心流程

1. 用户创建项目并输入创意描述。
2. 选择或创建角色档案、场景档案，并可上传参考图。
3. 后端基于档案与用户描述生成完整剧本。
4. 剧本被拆分为多个视频片段，并做连续性校验。
5. 系统为必要片段生成首帧，其他片段复用上一段尾帧进行串联。
6. 视频片段生成完成后，系统统一补对白、音效、环境音与配乐。
7. FFmpeg 合成最终成片并回写任务状态。

## 运行要求

建议环境：

- Python 3.9+
- Node.js 18+
- MySQL 8.0+
- FFmpeg 可执行文件已安装并在 `PATH` 中可用

可选组件：

- Redis
- Celery worker

如果只是本地体验完整主链路，推荐直接使用 `minimal` 模式，不需要 Redis / Celery。

## 快速开始

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd future-of-video
```

### 2. 准备数据库

创建 MySQL 数据库，或直接执行：

```bash
mysql -u root -p < backend/sql/init_schema.sql
```

默认数据库名示例是 `delta_force_video`。如果你使用自己的数据库名，请同步修改 `backend/.env` 中的 `DATABASE_URL`。

### 3. 配置后端环境变量

```bash
cp backend/.env.example backend/.env
```

至少需要确认这些配置：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `SECRET_KEY`
- `PIPELINE_RUNTIME_MODE`
- `DOUBAO_API_KEY`
- `DOUBAO_TTS_APP_ID`
- `DOUBAO_TTS_ACCESS_TOKEN`
- `NANOBANANA_API_KEY`
- `OPENAI_API_KEY`

如果你只想使用最小运行版：

```env
PIPELINE_RUNTIME_MODE=minimal
```

如果你需要完整队列版：

```env
PIPELINE_RUNTIME_MODE=full
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2
```

### 4. 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

默认后端地址：

- `http://127.0.0.1:8080`
- API 前缀：`/api/v1`

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：

- `http://127.0.0.1:5173`

开发环境下，Vite 会把 `/api/v1` 和 `/uploads` 代理到 `http://127.0.0.1:8080`。

## 运行模式

### `minimal`

适合本地开发、单机部署、演示环境。

特点：

- 需要数据库
- 需要外部模型 API
- 需要 FFmpeg
- 不需要 Redis
- 不需要 Celery worker
- 渲染任务在 FastAPI 进程内以后台协程执行

### `full`

适合需要独立 worker 和队列调度的环境。

特点：

- 需要数据库
- 需要外部模型 API
- 需要 FFmpeg
- 需要 Redis
- 需要 Celery worker

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
- `GET /pipeline/render/{task_id}`

角色 / 场景档案：

- `GET /pipeline/characters`
- `POST /pipeline/characters`
- `POST /pipeline/characters/analyze-reference`
- `GET /pipeline/scenes`
- `POST /pipeline/scenes`
- `POST /pipeline/scenes/analyze-reference`

## 测试与构建

后端语法检查：

```bash
python3 -m py_compile backend/app/main.py
```

后端测试：

```bash
cd backend
python3 -m pytest
```

前端构建：

```bash
cd frontend
npm run build
```

## Docker Compose

仓库中包含一个开源友好的 `docker-compose.yml` 示例：

- 默认直接运行 `minimal` 模式
- 默认只启动 `mysql`、`backend`、`frontend`
- 如果你需要队列版，再启用 `full` profile

最小模式：

```bash
docker compose up --build
```

完整模式：

```bash
PIPELINE_RUNTIME_MODE=full docker compose --profile full up --build
```

注意：

- compose 中的数据库口令是公开示例值，生产环境必须改掉
- 模型 API key 不在 compose 中硬编码，建议通过 `.env` 或 shell 环境传入
- 如果你只做本地体验，优先使用 `minimal`

## 开源发布前建议

在真正公开到 GitHub 之前，建议优先完成这些动作：

### 必做

- 补 `LICENSE`
  - 这是开源发布的前提，否则别人默认没有合法使用权。
- 全量检查凭证与示例配置
  - 包括 `.env`、`.env.example`、`docker-compose.yml`、脚本、截图、日志、测试数据。
- 清理本地产物
  - 尤其是 `backend/uploads/` 下的渲染结果、音频文件、模型输出和下载素材。
- 补完整 `README`
  - 当前这份 README 已覆盖基础说明，但如果你要对外宣传，最好再补截图、Demo 视频和架构图。

### 强烈建议

- 增加 CI
  - 仓库现在已经补了一个基础 GitHub Actions CI，但你仍然需要根据自己的发布策略继续完善。
- 增加 `CONTRIBUTING.md`
  - 说明分支策略、代码规范、提交流程。
- 增加 Issue / PR 模板
  - 降低沟通成本。
- 增加部署说明
  - 至少覆盖单机最小模式部署。

### 可能要决定的事情

- 是否公开模型 provider 绑定实现细节
- 是否要把默认数据库从 MySQL 扩展到 SQLite 演示模式
- 是否要提供在线 Demo
- 是否要拆分“产品仓库”和“纯开源核心仓库”

## 当前已做的开源准备

本次已经顺手补了两件事：

- `.gitignore` 增加了运行产物和上传目录忽略
- `backend/.env.example` 清掉了看起来像真实凭证的示例值
- 新增了 `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`、GitHub Issue / PR 模板和基础 CI

## 常见问题

### 1. 为什么我本地不想装 Redis / Celery？

直接用：

```env
PIPELINE_RUNTIME_MODE=minimal
```

这样主链路仍然可以跑，只是渲染任务不会走外部队列。

### 2. 为什么生成视频失败？

优先检查：

- 外部模型 API 是否已配置
- FFmpeg 是否安装成功
- MySQL 是否可连接
- 上传目录是否可写
- 后端日志中的 provider 返回错误

### 3. 为什么图片分析 / 试音 / 原型图不可用？

这些能力依赖相应 provider 配置：

- 图片分析：`OPENAI_API_KEY`
- 剧本与视频相关能力：`DOUBAO_API_KEY`
- 语音试音：`DOUBAO_TTS_APP_ID` 与 `DOUBAO_TTS_ACCESS_TOKEN`
- 角色 / 场景图生成：`NANOBANANA_API_KEY`

## 免责声明

本项目会调用第三方模型服务，并可能生成图片、音频、视频等媒体内容。请确保你的使用方式符合：

- 相关模型服务商的使用条款
- 你所在地区的法律法规
- 你对素材、角色、音频和上传内容的授权边界
