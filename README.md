# SonaKit

SonaKit 是一个通用能力服务平台。项目采用 API First 和单点能力服务化设计，每个 capability 拥有独立的 HTTP 契约、参数模型、处理服务和运行时检查。

当前版本提供：

- 多语言动态文本图片水印
- JPEG、PNG、WebP 图片压缩
- JPEG、PNG、WebP 格式转换
- 二维码生成与识别
- 远程视频 JPEG 封面抽帧

## 目录设计

```text
src/
└── sonakit/                 # 可安装、可导入的 Python 包
    ├── api/                 # API 聚合
    ├── capabilities/        # 相互独立的能力模块
    ├── core/                # 配置、错误、日志、能力注册
    ├── media/               # 安全图片解码和编码底座
    └── app.py               # FastAPI 应用入口
tests/                       # 服务和完整应用测试
```

`src/sonakit` 是标准 Python `src layout`。外层 `src` 隔离源码与项目根目录，内层 `sonakit` 提供稳定的包命名空间，避免开发环境因为当前目录在 `sys.path` 中而掩盖安装或镜像问题。

## 启动

生产交付物为 Docker 镜像，容器固定监听 `62793`：

```bash
docker build -t sonakit:local .
docker run --rm -p 62793:62793 sonakit:local
```

也可以使用 Compose：

```bash
docker compose up --build
```

启动后可访问：

- API 文档：`http://localhost:62793/docs`
- OpenAPI：`http://localhost:62793/openapi.json`
- 健康检查：`http://localhost:62793/api/v1/health`
- 能力列表：`http://localhost:62793/api/v1/capabilities`

## 通用图片约束

- 按文件实际内容识别格式，不信任扩展名或 `Content-Type`。
- 输入仅支持 JPEG、PNG 和静态 WebP。
- 上传文件最大 10 MiB，解码后最大 4000 万像素，单边最大 16384px。
- 自动应用 EXIF Orientation，保留视觉方向和尺寸，不裁剪、不缩放。
- ICC profile 转换到 sRGB；输出移除 EXIF、GPS、注释和其他输入元数据。
- PNG 和 WebP 在能力允许时保留透明通道；输出 JPEG 时使用指定背景色铺底。
- 每个 worker 默认最多同时处理 2 张图片，生产镜像默认启动 1 个 worker。

所有失败响应均包含 `code`、`detail` 和 `request_id`。客户端可传入 `X-Request-ID`，服务会在响应中回传；未传时由服务生成。

## 图片水印

`POST /api/v1/image/watermark`，请求类型为 `multipart/form-data`，成功后直接返回源格式图片。

`text` 是每次请求动态传入的任意文本，不是固定文案，也没有文案白名单。客户端应根据当前界面语言传入已经本地化的文案；服务不翻译文本、不接收 `locale`，只根据实际 Unicode 书写系统选择字体。

| 字段 | 必填 | 默认值 | 规则 |
|---|---:|---|---|
| `file` | 是 | - | JPEG、PNG 或静态 WebP |
| `text` | 是 | - | NFC 规范化，去除首尾空白，1-128 字符，单行 |
| `layout` | 否 | `tiled` | `tiled` 铺满图片；`single` 单点水印 |
| `position` | 否 | `bottom_right` | 九宫格位置，仅用于 `single` |
| `font_size` | 否 | `16` | 8-512px；放不下时自动缩小 |
| `font_weight` | 否 | `600` | `400` Regular 或 `600` SemiBold/Bold |
| `letter_spacing` | 否 | `1.1` | Unicode 字素簇之间的额外像素间距，0-20 |
| `color` | 否 | `#FFFFFF` | `#RRGGBB` |
| `opacity` | 否 | `0.5` | 0.05-1.0 |
| `rotation_degrees` | 否 | `-28` | -180 至 180，正数按 CSS 约定顺时针 |
| `tile_width` | 否 | `150` | 平铺单元宽度，32-4096px |
| `tile_height` | 否 | `81` | 平铺单元高度，24-4096px |
| `margin` | 否 | 短边 3%，8-64px | 0-4096px，仅用于 `single` |
| `offset_x` | 否 | `0` | 单点位移或平铺相位，正数向右 |
| `offset_y` | 否 | `0` | 单点位移或平铺相位，正数向下 |
| `stroke_color` | 否 | `#000000` | `#RRGGBB` |
| `stroke_width` | 否 | `0` | 0-32px，0 表示无描边 |

默认 `tiled` 会按 `tile_width` 和 `tile_height` 生成交错平铺网格，覆盖整张图片并返回实际水印实例数。单次最多生成 10000 个实例，避免异常平铺参数造成不可控资源消耗。文字无法容纳时逐像素缩小到 8px；仍无法容纳会返回 `400`，不会修改或截断客户端传入的文案。

内置 Noto 字体覆盖拉丁、西里尔、简体中文、日文、天城文、泰卢固文和泰米尔文，可渲染以下 14 种目标语言对应的书写系统：English、中文、Čeština、Deutsch、Español、Français、Italiano、日本語、Polski、Português、Русский、हिन्दी、తెలుగు、தமிழ்。出现假名时使用日文字体，纯汉字使用简体中文字体；无法由单个内置字体完整覆盖的混合文本会明确拒绝。

```bash
curl -X POST http://localhost:62793/api/v1/image/watermark \
  -F 'file=@source.png' \
  -F 'text=免费试用' \
  -F 'font_weight=600' \
  -F 'rotation_degrees=-28' \
  --output watermarked.png
```

响应头包含 `X-Image-Width`、`X-Image-Height`、`X-Watermark-Font-Size`、`X-Watermark-Layout` 和 `X-Watermark-Count`。`layout=single` 时还包含 `X-Watermark-Position`。

## 图片压缩

`POST /api/v1/image/compress`，请求类型为 `multipart/form-data`，保持源格式和尺寸。

| 字段 | 必填 | 默认值 | 规则 |
|---|---:|---|---|
| `file` | 是 | - | JPEG、PNG 或静态 WebP |
| `quality` | 否 | `80` | 1-100，作用于 JPEG/WebP |
| `optimize` | 否 | `true` | 启用编码器优化 |
| `progressive` | 否 | `true` | 仅作用于 JPEG |
| `png_colors` | 否 | - | 2-256；传入时对 PNG 做有损颜色量化 |

```bash
curl -X POST http://localhost:62793/api/v1/image/compress \
  -F 'file=@source.webp' \
  -F 'quality=75' \
  --output compressed.webp
```

响应头包含源/输出格式、尺寸、`X-Source-Bytes`、`X-Output-Bytes` 和 `X-Compression-Ratio`。压缩结果不保证一定小于源文件，客户端应以响应头中的实际字节数判断。

## 图片格式转换

`POST /api/v1/image/convert`，请求类型为 `multipart/form-data`。

| 字段 | 必填 | 默认值 | 规则 |
|---|---:|---|---|
| `file` | 是 | - | JPEG、PNG 或静态 WebP |
| `target_format` | 是 | - | `jpeg`、`png`、`webp` |
| `quality` | 否 | `90` | 1-100，作用于 JPEG/WebP |
| `background_color` | 否 | `#FFFFFF` | 转 JPEG 时用于透明区域铺底 |

```bash
curl -X POST http://localhost:62793/api/v1/image/convert \
  -F 'file=@source.png' \
  -F 'target_format=webp' \
  -F 'quality=88' \
  --output converted.webp
```

## 二维码生成

`POST /api/v1/qrcode/generate`，请求类型为 `application/json`，返回 PNG。

```json
{
  "text": "https://example.com/order/4W9X2",
  "error_correction": "M",
  "box_size": 10,
  "border": 4,
  "dark_color": "#000000",
  "light_color": "#FFFFFF"
}
```

`text` 长度为 1-2048 字符；纠错级别支持 `L`、`M`、`Q`、`H`；`box_size` 为 1-20；`border` 为 0-20。

## 二维码识别

`POST /api/v1/qrcode/recognize`，使用 `multipart/form-data` 上传 `file`。服务优先执行多二维码识别，并在需要时回退到单二维码识别。

```json
{
  "count": 1,
  "codes": [
    {
      "text": "https://example.com/order/4W9X2",
      "points": [[40.0, 40.0], [280.0, 40.0], [280.0, 280.0], [40.0, 280.0]]
    }
  ]
}
```

图片中没有可读取二维码时返回 `400` 和 `qr_code_not_found`。

## 视频封面抽帧

`POST /api/v1/video/thumbnail`，请求类型为 `application/json`。服务端通过 `ffprobe`
探测远程 HTTP(S) 视频时长，再通过 `ffmpeg` 流式输出单个 JPEG 帧；不会将完整视频下载到
Python 内存。

| 字段 | 必填 | 默认值 | 规则 |
|---|---:|---|---|
| `video_url` | 是 | - | 服务端可访问的 HTTP(S) 视频 URL |
| `prefer_first_frame` | 否 | `true` | 优先尝试 0.1、0.3、0.5 秒处的帧 |
| `fallback_random_window_seconds` | 否 | `3.0` | 0.1-3.0 秒的早期随机兜底窗口 |
| `max_output_width` | 否 | `1080` | 320-1080px，保持原始比例 |
| `frame_selection_strategy` | 否 | `near_start` | `near_start` 或 `random_cover` |
| `random_min_ratio` | 否 | `0.15` | `random_cover` 的最小时间比例，0-0.95 |
| `random_max_ratio` | 否 | `0.85` | `random_cover` 的最大时间比例，0-0.98，且不得小于最小值 |
| `random_candidate_count` | 否 | `3` | `random_cover` 的分段候选数，1-5 |

```bash
curl -X POST http://localhost:62793/api/v1/video/thumbnail \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://cdn.example.com/video.mp4","frame_selection_strategy":"random_cover"}' \
  --output preview.jpg
```

成功时响应为 `image/jpeg`，并带有 `X-Frame-Time-Seconds`、`X-Frame-Strategy` 和
`X-Source-Duration-Seconds`。缺少 `ffprobe` 或 `ffmpeg` 时服务会在启动阶段失败；远端视频
不可用或无法处理时返回 `502`，排队、探测和抽帧共享 60 秒处理截止时间，超时返回 `504`。

## 错误状态

| 状态码 | 含义 |
|---:|---|
| `400` | 图片损坏、动画图片、文本/布局失败、无可识别二维码等业务校验失败 |
| `413` | 上传大小、解码像素或图片边长超限 |
| `415` | 图片实际格式不支持 |
| `422` | 表单或 JSON 参数类型、范围、枚举不合法 |
| `502` | 远端视频无法探测、读取或解码 |
| `503` | 必需的运行时能力不可用 |
| `504` | 远端视频处理超时 |

## 配置

环境变量统一使用 `SONAKIT_` 前缀：

| 环境变量 | 默认值 |
|---|---:|
| `SONAKIT_PORT` | `62793` |
| `SONAKIT_LOG_LEVEL` | `INFO` |
| `SONAKIT_MAX_UPLOAD_BYTES` | `10485760` |
| `SONAKIT_MAX_IMAGE_PIXELS` | `40000000` |
| `SONAKIT_MAX_IMAGE_DIMENSION` | `16384` |
| `SONAKIT_IMAGE_CONCURRENCY` | `2` |
| `SONAKIT_VIDEO_THUMBNAIL_CONCURRENCY` | `2` |
| `SONAKIT_VIDEO_THUMBNAIL_MAX_DURATION_SECONDS` | `1800` |
| `SONAKIT_VIDEO_THUMBNAIL_MAX_OUTPUT_WIDTH` | `1080` |
| `SONAKIT_VIDEO_THUMBNAIL_TOTAL_TIMEOUT_SECONDS` | `60` |
| `SONAKIT_CORS_ORIGINS` | `[]`，JSON 数组 |

## 本地开发

项目要求 Python 3.11。macOS 上本地运行多语言水印测试时，Pillow 必须从源码链接 Homebrew RAQM：

```bash
brew install libraqm pkg-config
uv sync --python 3.11 --all-groups
LDFLAGS='-L/opt/homebrew/opt/libraqm/lib' \
CPPFLAGS='-I/opt/homebrew/opt/libraqm/include' \
PKG_CONFIG_PATH='/opt/homebrew/opt/libraqm/lib/pkgconfig:/opt/homebrew/lib/pkgconfig' \
uv pip install --reinstall --no-binary pillow pillow==12.3.0
uv run ruff check .
uv run pytest
```

生产镜像在构建阶段强制从源码编译 Pillow 并链接 RAQM，启动时还会验证 RAQM、全部 Regular/SemiBold/Bold 内置字体和字体 Unicode cmap；依赖缺失时直接启动失败。

字体来源及固定版本、哈希和 OFL 许可证见 `src/sonakit/capabilities/image_watermark/assets/fonts/README.md`。
