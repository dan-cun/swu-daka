# 西南大学查寝打卡辅助工具

本地自用的非官方查寝打卡辅助：统一认证登录默认**人工手动输入**（脚本弹 Chrome 导航到登录页，只捕获 Token 不代填，避免机器瞬填触发认证风控；登录态有效时直接复用缓存 Token 免登录）、自动同步当日查寝任务、定位校验、提交打卡，并生成脱敏审计日志。提供三条使用路径：

- **打卡助手 GUI**（`打卡助手.exe`，双击即用：一次打卡 / 每日自动打卡，推荐普通使用）
- **CLI**（核心链路，`login_and_checkin.py`）
- **本地 Web 界面**（`checkin-web/`，对 CLI 的薄封装 + 每日 21:00 自动任务）

> ⚠️ **声明**：本项目不是西南大学、钉钉或任何校内部门的官方产品。请仅使用本人合法持有并获准使用的账号，遵守学校、平台及所在地规则。工具不保证打卡成功，每次执行后都应在官方系统复核最终状态。详见 [checkin-web/docs/user_notice.md](checkin-web/docs/user_notice.md)。

## 目录

- [一、使用前提](#一使用前提)
- [二、快速开始（打卡助手 GUI，推荐）](#二快速开始打卡助手-gui推荐)
- [三、快速开始（CLI）](#三快速开始cli)
- [四、如何填入数据](#四如何填入数据)
- [五、文件结构和作用](#五文件结构和作用)
- [六、Web 端使用（可选）](#六web-端使用可选)
- [七、已知限制](#七已知限制)
- [八、排错](#八排错)
- [九、安全与合规（摘要）](#九安全与合规摘要)
- [十、许可与声明](#十许可与声明)

---

## 一、使用前提

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 | 登录自动化基于 Windows + Chrome |
| Google Chrome | 64-bit 稳定版 | 登录走 Chrome CDP（端口 9222）驱动独立 profile；其他浏览器未测试 |
| Python | 3.10+（推荐 3.11） | 跑打卡链路与 Web 后端，经 `py` 启动器调用 |
| pip 依赖 | 见 [配置.md](配置.md) | requests / playwright / ddddocr（CLI）+ fastapi / uvicorn / pydantic（Web） |
| Node.js | 18+（仅 Web 端） | React 前端需要；只用 CLI 可不装 |
| 时间 | 当日打卡时段内 | 默认任务 21:00–23:30，以服务端任务为准 |
| 位置 | 签到点半径内 | 默认签到点为融汇南路8号、半径 800 米；越界 verify 拒绝提交 |
| 账号 | 本人合法持有的校园网账号 | 不代他人打卡 |

一键安装/校验环境（幂等，可重复执行）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

完整依赖清单、实测版本、端口、环境变量与 FAQ 见 [配置.md](配置.md)。

## 二、快速开始（打卡助手 GUI，推荐）

双击项目根目录的 **`打卡助手.exe`**（PyInstaller 打包，无需额外安装），图形界面提供：

| 操作 | 说明 |
| --- | --- |
| 校园网账号 / 校园网密码 | 输入后自动回填（来自上次保存）；点"自动打卡"时保存到本机 |
| **一次打卡** | 立即执行：登录态有效直接复用 Token；否则弹 Chrome 到登录页，**账号/密码/验证码由你手动输入**，脚本捕获 Token 后自动继续同步→打卡，窗口内实时显示日志 |
| **自动打卡** | 创建 Windows 计划任务（`SWU_Daka_Auto`），按设定时间（默认 21:00）每天自动执行，**无需保持窗口打开** |
| **关闭自动打卡** | 删除计划任务 |
| 查看自动日志 | 打开自动任务生成的运行日志 |

注意：

- exe 需放在**项目根目录**（与 `login_and_checkin.py` 同目录）；环境须已按"一、使用前提"装好（Python + 依赖 + Chrome）。
- 自动任务要求当天电脑**开机且处于登录状态**；打卡仍需在签到点半径内、时段以服务端任务为准。
- 凭据存于 `%APPDATA%\swu-daka\config.json`（Base64 混淆、非加密），自动日志在 `%APPDATA%\swu-daka\auto_checkin.log`。
- exe 是构建产物（已被 Git 忽略，不在仓库里）；需要时重新构建：
  `py -3.11 -m PyInstaller --onefile --windowed --name 打卡助手 daka_gui.py`

## 三、快速开始（CLI）

```powershell
# 打卡：优先复用缓存 Token；过期则弹 Chrome 由你手动输入账号/密码/验证码登录
py -3.11 login_and_checkin.py --cqtj-checkin

# 环境自检（不发网络请求）
py -3.11 login_and_checkin.py --env-check
```

> 登录默认**人工手动输入**（实测机器瞬填易触发统一认证风控）。若确需机器代填
> （OCR 验证码），在命令后加 `--auto-login`，并先提供账号：
> `$env:SWU_USERNAME="账号"; $env:SWU_PASSWORD="密码"`。

常用参数组合：

| 参数 | 作用 |
| --- | --- |
| `--cqtj-checkin` | 同步今日查寝任务并打卡（已签到 / 越界 / 今日无任务会自动中止，不重复提交） |
| `--sync-cqtj` | 只同步任务元数据，不提交（验证/调试用） |
| `--login-only` | 只登录、刷新 Token（手动模式：弹 Chrome 人工登录后捕获） |
| `--token xxx` | 用已有 Token 跳过登录 |
| `--auto-login` | 机器代填登录（逐字拟人输入 + ddddocr 验证码识别），默认不启用 |
| `--manual-timeout 300` | 手动登录模式等待秒数（默认 300） |
| `--force-login` | 忽略 token.txt 缓存，强制重新登录 |
| `--monitor-chrome` | 网络监听模式：抓取 baida 接口并缓存表单元数据（排障用） |
| `--force-submit` | 即使已签到也强制提交（不建议） |

## 四、如何填入数据

### 3.1 账号 / 密码（登录时由人手动输入）

**默认登录路径**：脚本只负责把 Chrome 导航到学校统一认证登录页，**账号、密码、验证码全部在浏览器里由本人手动输入并点击登录**；脚本仅从登录响应中捕获 Token（存 `token.txt`），有效期内后续打卡不再触发登录。凭据不经命令行、不进环境变量（手动模式下）、不写入任何日志。

其他路径的凭据保存方式：

| 路径 | 填入方式 | 存储位置 |
| --- | --- | --- |
| 打卡助手 GUI | 界面输入框；"一次打卡"仅本次使用，"自动打卡"时保存 | 保存后：`%APPDATA%\swu-daka\config.json`（Base64 混淆、非加密） |
| CLI `--auto-login`（可选） | 环境变量 `SWU_USERNAME` / `SWU_PASSWORD` | 不存储，仅当前进程有效 |
| Web | 页面输入后点"开启每日 21:00 自动打卡" | `checkin-web/data/app.db`（当前临时明文，见已知限制） |

**不要**硬编码进源码、**不要**提交进 Git、**不要**发给任何人。

### 3.2 打卡任务参数（正常情况下无需手填）

- `form_id` / `cqfbid` / `business_key`：`--cqtj-checkin` 会从当日任务自动同步（`cqtj/getTransitionByToday` → `form-instance/select`），并写入当日缓存 `checkin_cache.json`（**仅当天有效**，跨天自动失效）。
- 自动同步拿不到时（如当日未发布任务），可手动指定 `--form-id` / `--cqfbid` / `--business-key`（来源：手机钉钉抓包，或历史审计日志）。
- 签到位置：默认值在 [legacy/config.py](legacy/config.py)（`DEFAULT_LAT/LNG/ADDRESS/QSQDDD/QDBJ`，当前为融汇南路8号、半径 800 米）。签到点变化时修改该文件，或用 `--lat` / `--lng` / `--address` 等参数临时覆盖。
- `verify` 按上述坐标做范围校验，**不在范围内一定不提交**。

### 3.3 自动生成的运行文件（无需手填，可安全删除）

| 文件 | 说明 |
| --- | --- |
| `token.txt` | 最新登录 Token（短命，约一天）；过期后重跑命令自动重新登录 |
| `checkin_cache.json` | 当日表单元数据缓存 |
| `audit_logs/*.jsonl` | 每次运行的完整审计日志（登录/同步/校验/提交/本地判定），敏感字段已脱敏 |
| `network_logs/*.jsonl` | 监听模式下的网络抓包 |

### 3.4 Web 端数据

- `checkin-web/data/app.db`：后端首次启动时自动创建，三张表：
  - `users`（账号、展示名、学号、用户须知确认状态）
  - `credentials`（校园账号凭据，当前临时明文 `plain-temporary`）
  - `auto_checkin_schedules`（每日 21:00 自动任务：开关、下次执行时间、最近结果）
- 可选配置：`Copy-Item checkin-web\.env.example checkin-web\.env`，可调整数据目录、数据库地址、日志目录、CORS 来源（变量表见 [配置.md](配置.md)）。

## 五、文件结构和作用

```text
C:\kaifa\tool\打卡\
├── README.md                   # 本文件：全局介绍
├── 配置.md                      # 运行环境配置（依赖/端口/环境变量/FAQ）
├── install.ps1                 # 一键环境安装脚本（幂等，可 -SkipWeb / -PipMirror）
├── login_and_checkin.py        # CLI 入口（薄封装 → legacy.cli.main）
├── daka_gui.py                 # 打卡助手源码（tkinter GUI + 计划任务管理 + --headless 自动模式）
├── 打卡助手.exe                 # 打包后的打卡助手（双击使用；构建产物，Git 忽略）
├── .gitignore                  # 敏感数据/构建产物忽略规则
│
├── legacy/                     # ★ 打卡链路核心实现（CLI）
│   ├── cli.py                  # 命令行参数、主流程编排（登录→同步→打卡）
│   ├── config.py               # 全部默认值：账号环境变量名、表单 ID、签到位置、登录 URL、钉钉 UA/请求头
│   ├── browser_login.py        # Chrome CDP 登录：CAS→uaaap→IDM，默认人工手动输入（脚本只等 Token）；--auto-login 机器代填+OCR
│   ├── swu_api.py              # API 链路：用户信息 / 当日任务同步 / getDormitory / verify / form-instance/save
│   ├── monitor.py              # 网络监听模式：抓取 baida 接口、缓存表单元数据（排障用）
│   └── common.py               # 环境自检、Chrome profile 管理、缓存、审计日志、敏感脱敏
│
├── audit_logs/                 # 打卡审计日志（自动产生；含个人信息，勿外传）
├── network_logs/               # 监听模式网络抓包（自动产生）
├── run_logs/                   # 手动运行输出日志（自动产生）
│
└── checkin-web/                # Web 端（FastAPI + React；CLI 的薄封装 + 自动任务）
    ├── .env.example            # 可选后端配置模板
    ├── backend/
    │   ├── requirements.txt    # fastapi / uvicorn[standard] / pydantic
    │   ├── app/
    │   │   ├── main.py         # FastAPI 入口：CORS、/health、挂载路由、启动调度器
    │   │   ├── dependencies.py # get_db（SQLite 连接）
    │   │   ├── routers/        # users / checkin / settings
    │   │   └── schemas/        # users / checkin 的 Pydantic 模型
    │   ├── services/
    │   │   ├── checkin_service.py  # ★ 打卡执行（subprocess 调 CLI）+ 21:00 自动任务调度
    │   │   └── auth_service.py     # 用户创建 / 凭据保存 / 须知确认
    │   ├── storage/
    │   │   ├── database.py     # init_database / connect
    │   │   └── models.py       # users / credentials / auto_checkin_schedules 表结构
    │   ├── core/               # config（环境变量）/ security / logging
    │   └── tests/              # 结构测试（pytest）
    ├── frontend/
    │   ├── package.json        # React 19 + TypeScript + Vite 6
    │   └── src/
    │       ├── App.tsx         # 路由：/ → CheckinPage，/terms → TermsPage
    │       ├── pages/CheckinPage.tsx       # ★ 主页面：一键打卡、自动任务、状态展示
    │       ├── pages/TermsPage.tsx         # 用户须知页
    │       ├── components/TermsConsentModal.tsx  # 须知确认弹窗
    │       └── services/api.ts             # fetch 封装（默认 http://127.0.0.1:8000）
    ├── docs/
    │   ├── security.md         # 安全规则（含加密目标方案）
    │   └── user_notice.md      # 用户须知 / 免责声明
    ├── scripts/                # 预留（空）
    └── data/                   # 运行数据（自动产生，Git 忽略）
        ├── app.db              # SQLite（首次启动创建）
        └── logs/
```

## 六、Web 端使用（可选）

Web 端对 CLI 是**薄封装**：后端 `checkin_service` 用 subprocess 调起 `login_and_checkin.py --cqtj-checkin`（240 秒超时），回填结果与日志尾部；调度线程每 15 秒轮询一次数据库，到点（默认 21:00）对已启用用户自动打卡。

```powershell
# 后端（在项目根目录）
cd checkin-web\backend
py -3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000/health 、 http://127.0.0.1:8000/docs

# 前端（另开终端，在项目根目录）
cd checkin-web\frontend
npm run dev
# → http://127.0.0.1:5173
```

主页面（CheckinPage）功能：

- 输入账号/密码 → **一键打卡**（实时显示状态与日志尾部）
- **开启每日 21:00 自动打卡**（保存凭据并写入调度表；后端到点自动执行）
- 使用须知强制确认（弹窗 + `/terms` 页，本地记录确认状态）

主要 API：

| 方法 & 路径 | 用途 |
| --- | --- |
| `POST /api/checkin/runs` | 一键打卡（body：`school_username` / `school_password`） |
| `GET /api/checkin/auto` | 查询自动任务状态（各用户开关、下次执行、最近结果） |
| `POST /api/checkin/auto` | 开启自动任务（存凭据 + 写调度） |
| `POST /api/checkin/auto/users/{username}` | 为已存凭据的用户开启自动任务 |
| `GET/POST /api/users` | 用户列表 / 新建用户 |
| `PUT /api/users/{id}/credential` | 保存凭据（占位：临时明文） |
| `GET /api/settings` | 后端运行配置 |
| `GET /api/checkin/runs` | 占位（运行历史尚未持久化） |

## 七、已知限制

- 自动任务的凭据目前是 SQLite **临时明文**（`plain-temporary`）；长期自动打卡前应先完成加密存储（目标方案见 [security.md](checkin-web/docs/security.md)）。
- 打卡运行历史尚未持久化（`GET /api/checkin/runs` 为占位）；事后排查依赖 `audit_logs/`。
- 后端 API **无认证**：只允许绑定 `127.0.0.1`，禁止公网暴露或端口转发。

## 八、排错

| 现象 | 处理 |
| --- | --- |
| 打卡失败、原因不明 | 打开最新的 `audit_logs/*.jsonl`：看 `response_verify`（定位）与 `response_form_instance_save` + `local_result`（提交结果） |
| "任务已签到，不重复提交" | 服务端已记录今日打卡，去官方系统核对；确需强制再加 `--force-submit` |
| "不在签到范围内" | 你不在签到点附近（默认位置见 `legacy/config.py`），调整位置参数或确认所在位置 |
| "今日查寝任务为空" | 服务端当天未发布任务（如查询过早），稍后重试 |
| 登录风控/验证码死循环 | 默认手动模式即解（人工输入）；`--auto-login` 已做拟人逐字输入（110~260ms 随机键距）仍失败时，改回手动 |
| Token 失效 | 无需处理，重跑打卡命令会自动重新登录 |
| 登录卡在统一认证/IDM 页 | 脚本会等待 60 秒供手动处理；也可先用 `--monitor-chrome` 抓包定位 |
| 环境问题（缺依赖/端口占用/GBK 乱码等） | [配置.md](配置.md) §8 FAQ |

## 九、安全与合规（摘要）

以下文件含敏感信息，**已 Git 忽略，禁止提交、上传或外发**：

```text
token.txt   checkin_cache.json   .env
audit_logs/   network_logs/   run_logs/
checkin-web/data/*.db   %TEMP%\ChromeSwuLoginProfile   captcha.png
```

- 审计日志已对 token/密码/cookie/session 脱敏，但仍含个人信息（学号、姓名、位置），定期清理。
- 怀疑凭据泄露时：改密码 → 删除 token/缓存/数据库 → 检查 Git 暂存区与提交历史。
- 更完整说明：[security.md](checkin-web/docs/security.md) · [user_notice.md](checkin-web/docs/user_notice.md)

## 十、许可与声明

本项目以 [《打卡助手》使用协议 v1.0](LICENSE) 发布：仅供学习与技术研究、**不可牟利**、
修改或再分发（含编译产物）必须显著署名出处且不得删除声明；使用后果自负。
技术讨论 / 问题反馈：QQ 1224145544。
