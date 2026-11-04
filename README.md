# Montube for fnOS

Montube is a native fnOS third-party application package. fnOS manages the service lifecycle, and the app runs directly on the NAS with its Python runtime and yt-dlp.

## Build

Install the fnOS `fnpack` command line tool, then run `./build-fpk.sh`. Import the resulting FPK through the fnOS App Center's manual installation flow.

## 本机调试

本机调试不经过 fnOS 网关。先启动 FastAPI 后端：

```bash
./scripts/dev_run.sh
```

然后另开一个终端启动 Vite 前端：

```bash
cd frontend
npm run dev
```

打开 Vite 显示的地址（通常是 `http://127.0.0.1:5173`）。前端的 `/api` 请求会自动代理到 `127.0.0.1:8080`，调试数据默认保存在 `.devdata/`，下载文件默认保存在 `.devdata/downloads/`。也可以通过 `PYTHON`、`MONTUBE_PORT`、`MONTUBE_DOWNLOAD_DIR` 等环境变量覆盖默认值。

## Runtime

The app declares the fnOS `python312` dependency, creates an isolated virtual environment during installation, and installs FastAPI, Uvicorn, Pydantic and yt-dlp from bundled x86_64 wheels without accessing the network. Audio extraction and separate video/audio merging require `ffmpeg` to be available on the NAS.

The download directory is configurable from the web interface and is persisted in the app database. Choose a directory that fnOS has authorized for the app; the default comes from the app's shared directory environment. Task data and logs are stored in the app's persistent variable directory. The desktop entry uses the fnOS Unix Socket gateway at `/app/montube`. The gateway forwards that prefix as part of the path, so `GatewayPrefixMiddleware` in `app/main.py` strips it before routing while keeping `root_path=/app/montube` visible to endpoints; static mounts and API routes stay registered at the root.

YouTube downloads can use an exported browser `cookies.txt` file. Open **设置**, enter its NAS path in **YouTube cookies 路径**, and save it. The file is only passed to yt-dlp with `--cookies`; Montube does not read or display its contents. The optional **Deno 路径** field enables yt-dlp's YouTube JavaScript runtime support, for example `/usr/local/bin/deno`. The same values can be supplied before startup with `MONTUBE_COOKIES` and `MONTUBE_JS_RUNTIME`.

### 排查空白页

1. 启动日志（`$TRIM_PKGVAR/montube.log`）里 `[montube]` 开头的行会写明版本、构建号和 `static/`、`ui/`、`wheels/` 是否存在，`build=` 为 `montube-YYYYMMDDhhmmss` 才能确认跑的是新包。
2. `GET /api/health` 返回构建号、`root_path`、静态文件清单；`GET /api/diagnostics` 额外返回共享目录下的 `.ui` 链接状态。
3. 通过网关访问时页面里的 JS/CSS 地址都应形如 `/app/montube/assets/...`，直接请求必须返回 200。
4. `./build-fpk.sh` 每次构建都会重新生成 `app/ui/map`（fnOS 桌面入口需要的 UI 包）并写入新的构建号。

The API is in `app/main.py`; the UI is in `app/static/`. FPK metadata, permissions, resource declarations and lifecycle hooks are under `manifest`, `config/`, `cmd/` and `wizard/`.

This package still needs validation with the official fnOS `fnpack` CLI and on an fnOS NAS before publishing.
