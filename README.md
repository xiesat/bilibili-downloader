# B站视频下载器 v2

[![CI](https://github.com/xiesat/bilibili-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/xiesat/bilibili-downloader/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/xiesat/bilibili-downloader/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)](https://github.com/xiesat/bilibili-downloader)

一个面向 Windows 的 B 站视频下载工具：PySide6 图形界面 + asyncio 异步下载引擎。
支持扫码登录、批量下载、分 P / 合集展开、断点续传，并且**直连官方 CDN 原始码流，产物不带任何平台水印**。

---

## 特性

| 能力 | 说明 |
| --- | --- |
| 异步下载引擎 | 视频级并发 + 单视频多连接分块并发（实测 8 连接把 50MB 视频压到 2.7 秒） |
| 断点续传 | 分块进度落盘，中断后精确续传；URL 过期也不影响 |
| 扫码登录 | 官方授权通道，全程不接触账号密码，天然绕过极验风控 |
| Cookie 导入 | 扫码不便时的兜底方案 |
| 凭证加密 | Windows DPAPI 加密，密文绑定当前 Windows 用户 |
| 多视频 | 批量粘贴 / 分 P 展开 / 合集展开 |
| 画质优选 | 按登录态动态探测可用画质，不可用的自动置灰并说明原因 |
| 编码优选 | 同一画质优先 H.264，避免 AV1 / HEVC 导致播放器打不开 |
| CDN 回退 | baseUrl 是 PCDN 节点时自动切换 backupUrl |
| ffmpeg | 三级探测 + 一键下载；没有 ffmpeg 时自动降级为渐进式单文件 |
| 双主题 | 浅色 / 深色一键切换 |
| 命令行 | `python -m bilidown <url>`，便于排错与自动化 |
| 单元测试 | 42 项，覆盖解析、画质选择、配置、文件名、合集展开 |

---

## 快速开始

### 方式一：使用打包版

1. 解压发布包，双击 `B站视频下载器.exe`
2. 首次使用若提示未检测到 ffmpeg，点「一键下载」（约 60MB，只需一次）
3. 粘贴视频地址 → 点「解析」→ 勾选 → 点「开始下载」

### 方式二：从源码运行

```powershell
# 1. 建独立虚拟环境（务必独立，不要用全局 Python）
python -m venv .venv

# 2. 装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. 启动
.\.venv\Scripts\python.exe main.py
```

> 建议不要污染全局 Python 环境，尤其是全局环境里装了 torch 之类的大型库时，
> 打包会把它们一起拖进来，产物又大又容易崩。

---

## 使用说明

### 输入格式

输入框支持一行一个，也支持空格 / 逗号 / 顿号 / 分号混合分隔，自动去重：

```
BV1GJ411x7h7                                        BV 号
av170001                                            av 号
https://www.bilibili.com/video/BV1GJ411x7h7/?p=2    带分 P 的完整链接
https://b23.tv/xxxxxxx                              分享短链（自动跟随跳转）
https://space.bilibili.com/123/channel/collectiondetail?sid=456   合集
```

### 画质与登录

| qn | 清晰度 | 所需条件 |
| --- | --- | --- |
| 127 | 8K | 大会员 |
| 120 | 4K | 大会员 |
| 116 | 1080P60 | 大会员 |
| 112 | 1080P+ | 大会员 |
| 80 | 1080P | 登录 |
| 64 | 720P | 部分视频需登录 |
| 32 | 480P | 游客 |
| 16 | 360P | 游客 |

**未登录时 DASH 实际只能拿到 480P。** 接口返回的 `accept_quality` 虽然列了 1080P+，
但那只是"该视频支持"，不代表当前账号拿得到——所以程序以 `dash.video` 里实际下发的
id 为准来判断可用性，并把拿不到的画质在界面上置灰。

登录方式：

- **扫码登录（推荐）**：点「扫码登录」，用手机 B 站 App 扫一下即可。
  全程不接触账号密码，且走官方授权通道，不会触发极验滑块。
- **粘贴 Cookie**：浏览器 F12 → Network → 任意请求 → 复制 Cookie 请求头，粘贴进去。
- 凭证默认用 Windows DPAPI 加密保存在 `%APPDATA%\BiliDown\credentials.json`，
  密文与当前 Windows 用户绑定，文件被拷走也解不开。

### 关于水印（实测结论）

**B 站 UGC 视频的原始码流本身不带水印。** 实测方式：分别下载渐进式 MP4 与 DASH 流，
各抽取 4 个时间点的画面检查——全部干净，没有任何角标或文字叠加；
接口返回的全部字段中也不存在 `watermark` / `logo` 字段。

你在网页播放器上看到的 "bilibili" 角标、UP 主名浮动标签，是**播放器 DOM 覆盖层**，
是 HTML/CSS 画上去的，根本不在视频文件里。下载原始流天然就没有。

因此本项目对"无水印"的保障是：

1. 始终直连官方 CDN 原始流（`baseUrl` / `backupUrl`），**不经过任何第三方解析站**
2. 候选地址优先原始 upos CDN 节点，PCDN 节点仅作回退
3. 同画质下默认优先 H.264，避免播放器二次处理
4. 合并一律 `-c copy`，只封装不重编码 → **零转码叠加**
5. 可选后处理（默认关闭）：设置里的 `delogo` 实验开关，用于抹掉 **UP 主自己压进画面的水印**。
   这会重编码视频、必然损失画质，所以默认不开。

> 若画面仍有水印，那是 UP 主上传时就带在画面里的，无法无损去除。

### ffmpeg

DASH 高清模式需要 ffmpeg 合并音视频。程序按以下顺序探测：

1. 设置里手动指定的路径
2. `%APPDATA%\BiliDown\bin\ffmpeg.exe`（一键下载的产物）
3. `imageio-ffmpeg` 捆绑的二进制
4. 系统 PATH

都没有时不会静默失败：界面会明确提示并把模式自动降级为**渐进式 MP4**
（B 站已合流的单文件，免合并，画质通常止步 720P）。

「一键下载」在源码运行时优先 `pip install imageio-ffmpeg`（体积小、免管理员），
失败则回退下载官方静态包；打包版直接走下载，因为冻结解释器里 pip 装到哪里都没用。

### 多视频

- **批量粘贴**：一次贴多条，自动去重，无效项会在日志里逐条说明原因
- **分 P 展开**：一个多 P 视频自动列出全部 P，可逐条勾选
- **合集展开**：稿件属于合集（`ugc_season`）时会展开整季

> 注意：按 `sid` 拉取 UP 主合集列表的接口（`seasons_archives_list`）对未登录请求返回
> `-352` 风控，因此**合集链接需要先登录**才能使用；而"稿件本身属于合集"的展开路径
> 是复用 view 响应里的 `ugc_season`，未登录也能用。

### 命令行

```powershell
# 下载单个视频（最高可用画质，自动选 DASH 或渐进式）
.\.venv\Scripts\python.exe -m bilidown BV1GJ411x7h7

# 指定目录、画质、编码、并发
.\.venv\Scripts\python.exe -m bilidown BV1GJ411x7h7 -o D:\Videos -q 80 --codec avc1 -j 3 -c 8

# 带 Cookie 下载 1080P
.\.venv\Scripts\python.exe -m bilidown BV1GJ411x7h7 --cookie "SESSDATA=xxx; bili_jct=yyy"

# 展开合集
.\.venv\Scripts\python.exe -m bilidown BV1GJ411x7h7 --season
```

| 参数 | 说明 |
| --- | --- |
| `inputs` | BV 号 / av 号 / 链接 / 合集链接，可多个 |
| `-o, --output` | 下载目录 |
| `-q, --quality` | 目标画质 qn，0 表示最高可用 |
| `--codec` | `avc1` / `hev1` / `av01` |
| `-m, --mode` | `auto` / `dash` / `progressive` |
| `-j, --jobs` | 同时下载的视频数 |
| `-c, --chunks` | 单个视频的分块连接数 |
| `--season` | 稿件属于合集时展开整季 |
| `--cookie` | 登录 Cookie |
| `--ffmpeg` | 指定 ffmpeg 路径 |

---

## 打包

```powershell
# 默认版：约 60MB，不含 ffmpeg（首次使用时在界面一键下载）
.\build.ps1 -RunTests

# 完整版：内置 ffmpeg，约 140MB，可完全离线
.\build.ps1 -BundleFFmpeg

# 跳过自检
.\build.ps1 -SkipSelftest
```

打包脚本会自动跑单元测试、清理旧产物、调用 PyInstaller，
最后用 `--selftest` 启动产物并校验依赖完整性，同时截一张界面图。

产物在 `dist\B站视频下载器\`，分发时整个目录打成 zip 即可。

### 内置自检

打包版是窗口程序，没有控制台，出问题时看不到任何提示。
所以内置了一个自检入口，把结果写进 JSON：

```powershell
.\dist\B站视频下载器\B站视频下载器.exe --selftest report.json
```

报告会覆盖模块导入、解析、文件名处理、DPAPI、二维码渲染、ffmpeg 探测、
配置读写与界面构建，并生成一张窗口截图。

---

## 项目结构

```
b站视频下载/
├─ main.py                     入口（含 __main__ 保护）
├─ requirements.txt            运行期依赖
├─ requirements-dev.txt        开发/打包依赖
├─ build.spec                  PyInstaller 配置
├─ build.ps1                   一键打包脚本
├─ pytest.ini
├─ assets/app.ico
├─ legacy/                     v1 旧代码归档（仅作回溯）
├─ tests/                      单元测试
└─ bilidown/
   ├─ app.py                   入口分发（GUI / CLI / 自检）
   ├─ cli.py                   命令行模式
   ├─ config.py                AppConfig + JSON 持久化
   ├─ constants.py             接口地址、画质表、编码优先级
   ├─ models.py                领域模型与状态机
   ├─ errors.py                统一异常体系
   ├─ selftest.py              内置自检
   ├─ core/                    ← 零 GUI 依赖
   │   ├─ client.py            httpx 异步客户端（重试/退避/限速/WBI 签名）
   │   ├─ auth.py              扫码登录、Cookie 导入、登录态校验与续期
   │   ├─ credentials.py       DPAPI 加密凭证存储
   │   ├─ parser.py            输入归一化
   │   ├─ metadata.py          稿件详情、分 P、合集展开
   │   └─ playurl.py           画质协商、编码优选、CDN 回退
   ├─ download/                ← 零 GUI 依赖
   │   ├─ engine.py            分块并发 + 断点续传 + 重试
   │   ├─ manager.py           任务队列、并发、暂停/取消、事件分发
   │   └─ mux.py               ffmpeg 合并（-c copy）与可选 delogo
   ├─ util/
   │   ├─ paths.py             运行期目录与资源定位
   │   ├─ filename.py          非法字符过滤、截断、重名去重
   │   ├─ logging.py           滚动文件日志 + 回调 Handler
   │   └─ ffmpeg.py            ffmpeg 三级探测与一键下载
   └─ ui/
       ├─ app.py               主窗口装配
       ├─ theme.py             浅色 / 深色 QSS
       ├─ bridge.py            asyncio 线程 ↔ Qt 信号桥
       └─ views/               输入 / 选项 / 账号 / 结果 / 队列 / 日志 / 卡片
```

**分层铁律**：`core` 与 `download` 完全不 import Qt，因此可以单测、可以被 CLI 复用、
将来换界面框架也不用动内核。

---

## 架构

### 线程模型

```
主线程（Qt）                        后台线程（asyncio）
──────────────────                  ────────────────────────────────
点击「开始下载」
  manager.submit(tasks)
  loop.call_soon_threadsafe(...)
                                      asyncio.run_forever()
                                        ├─ 解析：gather(view + playurl) 并发
                                        ├─ 任务队列：N 个 worker 并发下载
                                        └─ 单任务内：M 个分块 gather 并发
  ▲
  └── SignalBridge(QObject) 发信号 ◄── 进度 / 状态 / 日志
```

Qt 信号跨线程发射时会自动排队到接收者所在线程，因此后台线程只管 `emit`，
界面侧只管 `connect`，从根上避免了跨线程操作控件。
进度事件按 120ms 节流，防止高并发刷爆 GUI 消息队列。

### 并发模型

- **视频级**：worker 协程数量 = 配置里的「并发视频」
- **分块级**：单视频的分块连接数 = 「分块连接」
- 总连接上限约为两者之积，界面上可调

### 关键实测结论（决定了实现方式）

| 现象 | 应对 |
| --- | --- |
| 未登录时 `accept_quality` 会列出 1080P，但实际只下发 480P | 可用性以 `dash.video` 实际 id 为准 |
| 同一画质返回 av01 / hev1 / avc1 三份 | 按编码优先级挑选，默认 H.264 |
| `baseUrl` 常是 PCDN 节点（如 `*.mountaintoys.cn`），会 403 | 保留 `backupUrl` 作为回退 |
| CDN 支持 Range 且 `content-range` 正确 | 多连接分块并发 + 断点续传 |
| `fnval=0` 返回已合流的单个 MP4 | 无 ffmpeg 时的自动降级路径 |
| 合集列表接口对游客返回 `-352` | 明确提示"需登录"，不静默失败 |
| 打包后 `sys.stderr` 为 None | 日志跳过控制台 Handler |
| 打包后 pip 装到别处无效 | ffmpeg 一键下载走直接下载 |

---

## 常见问题

**Q：解析后画质里 1080P 是灰的？**
A：未登录只能拿 480P。点「扫码登录」后用手机 B 站 App 扫一下，1080P 会立刻解锁；
4K / 8K 需要大会员。

**Q：下到一半断网了怎么办？**
A：直接重新开始即可。分块进度已经写在 `.part.meta.json` 里，会命中断点续传。

**Q：下载的文件里音视频分家了？**
A：不会。DASH 模式会自动用 ffmpeg 合并；没有 ffmpeg 时会自动改用渐进式单文件模式，
并在界面上明确告知，不会产出无法播放的分离文件。

**Q：为什么不内置 ffmpeg？**
A：默认版不含它可以把体积从约 140MB 降到约 60MB，而 ffmpeg 只需下载一次。
需要离线绿色版就用 `build.ps1 -BundleFFmpeg`。

**Q：程序目录在 Program Files 下，会不会写不进去？**
A：所有运行期数据（配置、日志、凭证、临时分块、下载的 ffmpeg）都在
`%APPDATA%\BiliDown`，不写程序目录。

**Q：双击 exe 没反应？**
A：用 `--selftest` 生成报告定位：
`B站视频下载器.exe --selftest report.json`。

---

## 已知限制

- 未登录只能下 480P（DASH）/ 720P（渐进式），这是 B 站服务端限制
- 合集链接（按 sid 拉列表）需要登录，游客会被 `-352` 拦截
- 番剧、影视等 PGC 内容有 DRM，不在支持范围
- UP 主自己压进画面的水印无法无损去除
- 仅面向 Windows（凭证用了 DPAPI）

---

## 从 v1 到 v2

v1 只有三个文件、约 200 行，主要问题：

| v1 的问题 | v2 的做法 |
| --- | --- |
| 源码里硬编码完整 Cookie（含 SESSDATA） | 彻底移除，改用扫码登录 + DPAPI 加密存储 |
| XPath `script[4]` 抓播放信息 | 改走官方 API |
| 视频存 mp4、音频存 mp3，不合并 | ffmpeg `-c copy` 合并，无 ffmpeg 时自动降级 |
| 网络请求跑在 UI 线程，界面假死 | asyncio 后台线程 + Qt 信号桥 |
| 未选目录时 `os.mkdir(0)` 崩溃 | 配置层保证路径永远合法 |
| 标题含非法字符时 `open()` 抛异常 | 文件名过滤 + 截断 + 重名去重 |
| 无重试、无进度、无异常处理 | 分块重试、CDN 回退、进度/速度/剩余时间、统一异常体系 |
```

