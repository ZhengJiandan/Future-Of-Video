# future of video

[中文](./README.md)

`future of video` is an AI video creation workbench for long-form, multi-step workflows. It connects character profiles, scene profiles, script generation, shot splitting, keyframe generation, and segmented video rendering into an editable, reviewable, and recoverable pipeline.

The repository currently uses a separated frontend/backend architecture:

- Frontend: React + Vite + Ant Design
- Backend: FastAPI + SQLAlchemy + SQLite / MySQL
- Media processing: FFmpeg
- Model integrations: Doubao, OpenAI-compatible APIs, NanoBanana, and other external model providers
- Task scheduling:
  - `minimal` mode: single-process local background tasks, no Redis / Celery required
  - `full` mode: Celery + Redis

## Online Demo

- Demo URL: [http://82.156.153.123/](http://82.156.153.123/)
- User: `test`, password: `123456`
- For demonstration only.

## Author Notes

- This project mainly addresses a practical limitation of current video models: a single generation is usually too short to become a complete standalone film. In theory, segmented generation can be chained into videos longer than 5 minutes, but given current model quality, keeping the final output within 1 minute is still the safer recommendation to reduce character drift, style drift, and continuity artifacts.
- The project is currently developed and maintained by a single person in spare time. Rough edges and omissions are expected. Discussion, feedback, and practical improvements are welcome.
- The repository now supports Kling video generation. When the render provider is set to `auto`, the system prefers Kling multi-image-to-video first and only falls back to Doubao video generation when Kling `AK/SK` credentials are missing. Since the `Seedance 2.0` API is not fully open yet, and recent policy changes have also affected Doubao video generation availability, production stability is not ideal. If you plan to rely on this seriously, configuring Kling first is the recommended path.
- For image generation, `NanoBanana Pro` is generally the better choice. The current unified image router prefers `NanoBanana` first and falls back to Doubao `Seedream 5.0` through the Ark-compatible image API when `NANOBANANA_API_KEY` is missing. For character and scene image-to-image flows, the current Doubao path uses image Base64 input directly instead of relying on a public image URL.

## Feature Overview

- User registration, login, and current-project draft persistence
- Character library
  - Upload character reference images
  - Analyze images to fill character fields
  - Generate character prototype images
  - Generate three-view / close-up anchor images
  - Maintain voice descriptions as part of the character definition
- Scene library
  - Upload scene reference images
  - Analyze images to fill scene fields
  - Generate scene prototype images
- Main script pipeline
  - Automatically generate temporary character drafts when no formal character profile is matched
  - Generate full scripts from user prompts
  - Review and edit script results in the frontend
  - Split scripts into video segments
  - Run continuity checks during both script optimization and splitting
  - Generate key start frames and connect segment endings to following segments
  - Generate segmented videos
  - Save temporary characters into the formal character library after they have been used in video generation
  - Produce a final merged output

## Repository Structure

```text
.
├── backend
│   ├── alembic                  # Database migrations
│   ├── app
│   │   ├── api                  # FastAPI routes
│   │   ├── core                 # Config and security
│   │   ├── db                   # DB engine and initialization
│   │   ├── models               # SQLAlchemy models
│   │   ├── services             # Core workflow, libraries, model integrations
│   │   └── workers              # Celery worker entry
│   ├── sql                      # Init SQL, upgrade scripts, sample seed data
│   ├── tests                    # Backend tests
│   └── requirements.txt
├── docs
│   └── examples                 # Public examples and regression cases
├── frontend
│   ├── src
│   │   ├── layouts
│   │   ├── pages
│   │   ├── services
│   │   └── stores
│   └── package.json
├── docker-compose.yml
├── README.md
└── README.en.md
```

## Core Workflow

1. The user creates a project and enters a creative prompt.
2. The user selects or creates character and scene profiles, and can upload reference images for analysis.
3. If no formal character profile is matched, the system first generates temporary character drafts in the same profile format and uses them directly for the current run.
4. The backend generates a full script based on the profiles and the user prompt.
5. The script is shown in the frontend and can be edited directly.
6. The script is split into multiple video segments with continuity checks.
7. The system generates start frames where needed, while trying to reuse previous end frames whenever possible.
8. Video segments are generated in sequence; the user can confirm segment-by-segment or generate all at once.
9. If a temporary character has already been used in video generation, the frontend can save that character into the formal character library using the first-frame appearance of its first segment.
10. The system outputs the final merged video and writes back task state.

## Requirements

Recommended environment:

- Python 3.10+
- Node.js 18+
- SQLite available locally
- FFmpeg installed and accessible from `PATH`

Optional components:

- MySQL
- Redis
- Celery worker

If you only want to experience the main workflow locally, `minimal` mode is recommended. Redis and Celery are not required.

One common source of confusion:

- The fallback default for `Settings.DATABASE_URL` in code is still MySQL.
- But the recommended startup path in this repository is to copy `backend/.env.example`, and that example file already uses SQLite in minimal mode.
- So if you skip `cp backend/.env.example backend/.env` and start the backend with raw defaults, it may still fail due to the default MySQL configuration.

## Quick Start

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd future-of-video
```

### Recommended Path: Shortest Success Path for New GitHub Users

If you just cloned the project from GitHub and want the primary workflow running as quickly as possible, use:

- `minimal` mode
- SQLite
- local frontend/backend development mode

Minimum assumptions:

- Python 3.10+ is installed
- Node.js 18+ is installed
- FFmpeg is installed
- If you want to use Doubao immediately, you have a `DOUBAO_API_KEY`
- You copied `backend/.env.example` to `backend/.env`

Notes:

- The backend now supports startup without `DOUBAO_API_KEY`; validation only happens when you actually call script generation, image analysis, Doubao video generation, and similar features.
- If the server has no `DOUBAO_API_KEY`, the frontend can accept a temporary one in the current browser session when a request actually needs it.
- `OPENAI_API_KEY` is not a required startup dependency for the current minimal workflow.
- `minimal` + SQLite does not require MySQL and does not require manual database creation.
- In local minimal mode, the SQLite file is created at `backend/future_of_video.db` by default.
- In Docker minimal mode, the SQLite file is created at `backend/uploads/future_of_video.db` by default.

### 2. Configure Backend Environment Variables

```bash
cp backend/.env.example backend/.env
```

Notes:

- In local development, the backend reads `backend/.env` directly.
- In Docker Compose, the `backend` and `worker` containers read the same `backend/.env`.
- If you already have a working Doubao key, put it into `DOUBAO_API_KEY`.
- If you want the minimum setup path, keep the SQLite configuration in `backend/.env` and do not switch it back to MySQL by mistake.

At minimum, review these settings:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `SECRET_KEY`
- `PIPELINE_RUNTIME_MODE`
- `KLING_ACCESS_KEY`
- `KLING_SECRET_KEY`
  - Used for Kling video generation.
  - When `provider=auto`, Kling is preferred if both are configured; otherwise the system falls back to Doubao video generation.
- `DOUBAO_API_KEY`
  - It can be configured server-side in advance, or temporarily provided in the current frontend session when Doubao-backed features are actually called.

Optional but commonly used:

- `OPENAI_API_KEY`
  - Not required for startup in the current minimal workflow.
- `NANOBANANA_API_KEY`
  - If configured, NanoBanana is preferred for image generation.
  - If not configured, image generation falls back to Doubao `doubao-seedream-5-0-260128`.

Minimal runtime example:

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

If you want the smallest test setup with no MySQL dependency at all, use the SQLite configuration above.

A directly runnable minimal example:

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
DOUBAO_API_KEY=your_doubao_api_key
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

Docker minimal example:

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
DOUBAO_API_KEY=your_doubao_api_key
DEBUG=false
MODEL_DEBUG_LOGGING=false
```

Full queue example:

```env
PIPELINE_RUNTIME_MODE=full
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/future_of_video
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2
```

### 3. Install Backend Dependencies

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Initialize the Database

If you use SQLite in minimal mode, you can skip this step. Tables are created automatically on startup.

Additional notes:

- `backend/sql/init_schema.sql` is mainly for initializing a fresh MySQL database.
- Do not run that MySQL initialization SQL in SQLite minimal mode.
- SQLite minimal mode usually does not require manual migrations either; starting the backend as described in this README is enough.

Initialize a new MySQL database:

```bash
mysql -u root -p < backend/sql/init_schema.sql
```

If you are upgrading an existing database, or want to explicitly sync to the latest schema:

```bash
cd backend
alembic upgrade head
```

The default sample database name is `future_of_video`. If you use a different database name, update `DATABASE_URL` in `backend/.env` accordingly.

### 5. Start the Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Default backend address:

- `http://127.0.0.1:8080`
- API prefix: `/api/v1`

### 6. Configure and Start the Frontend

```bash
cp frontend/.env.example frontend/.env
cd frontend
npm install
npm run dev
```

Default frontend address:

- `http://127.0.0.1:5173`

In development, Vite proxies `/api/v1` and `/uploads` to `http://127.0.0.1:8080`.

### 7. What You Should See in Minimal Mode

- The backend starts successfully
- The project list page is accessible
- The SQLite database file is created automatically under `backend/`
- After entering the main workflow, you can continue through characters, scripts, segments, keyframes, and video generation

If the backend fails during startup, check these first:

- Whether `pip install -r requirements.txt` has been executed, especially whether `aiosqlite` is installed
- Whether `ffmpeg` is available in `PATH`
- Whether `backend/.env` has been copied from `.env.example` and still keeps the SQLite configuration

If startup is fine but specific capabilities fail later, check these first:

- Whether `DOUBAO_API_KEY` is available
- Or whether `NANOBANANA_API_KEY` is configured

## Runtime Modes

### `minimal`

Suitable for local development, single-machine deployments, and demos.

- Requires a database
- SQLite is the default recommendation
- Requires external model APIs
- Requires FFmpeg
- Does not require MySQL
- Does not require Redis
- Does not require a Celery worker
- Render jobs run as background coroutines inside the FastAPI process

### `full`

Suitable for environments that need dedicated workers and queue-based scheduling.

- Requires external model APIs
- Requires FFmpeg
- Requires MySQL
- Requires Redis
- Requires a Celery worker

## Database Upgrade Notes

The repository keeps two database preparation paths:

- `backend/sql/init_schema.sql`
  - For quickly initializing a fresh environment.
- `backend/alembic`
  - For ongoing schema migrations and upgrades.

If you are upgrading from an older version, prefer:

```bash
cd backend
alembic upgrade head
```

If you only ran the old initialization SQL without the later migrations, missing-column issues are likely.

## Backend API Overview

The main API prefix is `/api/v1`.

Authentication:

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

Projects:

- `GET /projects`
- `POST /projects`
- `GET /projects/current`
- `PUT /projects/current`

Main pipeline:

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

Both “confirm each segment before continuing” and “generate all at once” are controlled by the `auto_continue_segments` parameter in render requests, not by a separate confirmation API.

Character / scene profiles:

- `GET /pipeline/characters`
- `GET /pipeline/characters/{character_id}`
- `POST /pipeline/characters`
- `PUT /pipeline/characters/{character_id}`
- `DELETE /pipeline/characters/{character_id}`
- `POST /pipeline/characters/upload-reference`
- `POST /pipeline/characters/generate-three-view`
- `POST /pipeline/characters/generate-prototype`
- `POST /pipeline/characters/analyze-reference`
- `GET /pipeline/scenes`
- `GET /pipeline/scenes/{scene_id}`
- `POST /pipeline/scenes`
- `PUT /pipeline/scenes/{scene_id}`
- `DELETE /pipeline/scenes/{scene_id}`
- `POST /pipeline/scenes/upload-reference`
- `POST /pipeline/scenes/generate-prototype`
- `POST /pipeline/scenes/analyze-reference`

## Testing and Build

Backend tests:

```bash
cd backend
python3 -m pytest -o addopts='' tests
```

Backend syntax check:

```bash
python3 -m py_compile backend/app/main.py
```

Frontend build:

```bash
cd frontend
npm run build
```

## Docker Compose

The repository includes an open-source-friendly `docker-compose.yml` example:

- Runs in `minimal` mode by default
- Starts only `backend` and `frontend` by default
- Uses SQLite by default, without requiring MySQL
- The SQLite file is stored at `backend/uploads/future_of_video.db`
- Enable the `full` profile only if you want the MySQL + worker queue version

Minimal mode:

```bash
cp backend/.env.example backend/.env
# At minimum, fill in DOUBAO_API_KEY in backend/.env
# And make sure DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
# Unless you have a special reason, keep PIPELINE_RUNTIME_MODE=minimal
docker compose up --build
```

Default access addresses in minimal mode:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8080`

Things you do not need in minimal mode:

- No local MySQL installation
- No manual SQLite database creation
- No need to run `backend/sql/init_schema.sql`
- No need to start Redis / Celery worker

Full mode:

```bash
cp backend/.env.example backend/.env
# Fill in DOUBAO_API_KEY in backend/.env and explicitly switch to MySQL
DATABASE_URL=mysql+aiomysql://fov:change-me-db@mysql:3306/future_of_video \
PIPELINE_RUNTIME_MODE=full \
docker compose --profile full up --build
```

Notes:

- The database password in compose is a public example value and must be changed in production.
- `backend` / `worker` containers read `backend/.env`.
- The default `docker compose up --build` path uses SQLite minimal mode and does not start `mysql` or `redis`.
- `backend/uploads/` stores uploads, generated assets, and the SQLite database file used by Docker minimal mode.
- The compose file in this repository is a development/demo example, not a production deployment template.

Bottom line:

- The default behavior of `docker compose up --build` already proves that MySQL is not a prerequisite for minimal mode.
- The `mysql` service is only explicitly enabled under `--profile full`.

## Example Inputs and Regression Samples

Public examples are collected in `docs/examples/`:

- `docs/examples/cat-pipeline-inputs.md`
- `docs/examples/ancient-romance-pipeline-inputs.md`
- `docs/examples/cat-character-entry-regression.md`

These files are suitable for local regression testing, demos, and prompt references.

## FAQ

### 1. Why would I avoid Redis / Celery locally?

Just use:

```env
PIPELINE_RUNTIME_MODE=minimal
```

The main workflow still runs; rendering simply does not rely on an external queue.

### 2. Why can the project run without MySQL?

Because `minimal` mode now supports SQLite directly, and tables are created automatically on startup:

```env
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

That means MySQL is no longer a required component in minimal runtime mode. You only need it if you explicitly switch to MySQL or enable `full` mode.

### 3. Why are the SQLite paths different between local and Docker?

Local development typically starts the backend from `backend/`, so it uses:

```env
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

Docker minimal mode uses:

```env
DATABASE_URL=sqlite+aiosqlite:///./uploads/future_of_video.db
```

so the database file can be persisted together with uploads and generated assets in the mounted directory.

### 4. Why can the backend start now even without `DOUBAO_API_KEY`?

Because validation is now lazy. The backend no longer fails immediately at startup when `DOUBAO_API_KEY` is missing. It is checked only when features like these are actually called:

- script generation
- image analysis
- character / scene prototype generation
- character three-view generation
- Doubao video generation

If the server has no key configured in advance, the frontend prompts for one and lets you provide a temporary key for the current browser session.

### 5. Why do I still see MySQL connection errors in minimal mode?

Usually because you did not copy `backend/.env.example`, or changed `DATABASE_URL` back to the MySQL fallback default. The current code-level fallback is still:

```env
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/future_of_video
```

If you want the minimal path, explicitly confirm:

```env
PIPELINE_RUNTIME_MODE=minimal
DATABASE_URL=sqlite+aiosqlite:///./future_of_video.db
```

### 6. Why is image generation not using NanoBanana?

Current logic:

- Prefer `NANOBANANA_API_KEY`
- If missing, fall back to Doubao `Seedream 5.0` associated with `DOUBAO_API_KEY`
- In character and scene image-to-image flows, the current Doubao path sends Base64 input directly

### 7. Why does “auto” prefer Kling for video generation?

Current priority:

- If `KLING_ACCESS_KEY` + `KLING_SECRET_KEY` are configured, `provider=auto` prefers Kling video generation
- If Kling credentials are missing, the system falls back to Doubao video generation
- If neither side has usable credentials, the request fails, or you can explicitly switch to `local` preview mode

### 8. When will temporary characters be offered for saving into the formal character library?

If no formal profile is matched, the system first generates temporary character drafts and uses them directly in the script, keyframe, and video workflow. The frontend only offers saving them into the formal character library after those temporary characters have actually been used in video generation. When saved, the first frame of that character’s first generated segment is used directly as the reference image, without generating extra three-view or close-up images.

### 9. Why is there no extra project-level audio in the final video?

The current repository disables the old project-level audio compositing path by default. Public demo results mainly rely on the video model’s own audio capability, or remain silent. That is the current implementation status, not a configuration issue.

## Disclaimer

This project calls third-party model services and may generate media such as images, audio, and video. Make sure your usage complies with:

- the terms of the model providers you use
- the laws and regulations in your jurisdiction
- your authorization boundaries for materials, characters, audio, and uploaded content

## Contact Me

- QQ Group: `1041169329`

  ![QQ Group QR Code](./backend/img/qq_share.jpg)
- WeChat: `wxid_xw0hc18v0icp12`
- Email: `494829832@qq.com`
- Mention `fov` when you add me.
