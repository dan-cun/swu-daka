# 西南大学查寝打卡辅助工具

一个面向本地自用场景的非官方查寝打卡辅助项目。项目包含旧版命令行工具，以及正在开发中的 FastAPI + React 网页界面，可完成统一认证登录、同步当日查寝任务、提交打卡请求和记录本地审计日志。

> [!WARNING]
> 本项目不是西南大学、钉钉或任何校内部门的官方产品。请仅使用本人合法持有并获准使用的账号，并遵守学校、平台及所在地适用规则。程序不能保证打卡成功，每次执行后都应前往官方系统核对最终状态。

## 当前状态

项目仍处于开发阶段，适合本机调试和受控测试，不适合部署到公网或多人共用环境。

已经实现：

- 使用 Chrome 完成统一认证登录，验证码识别失败时可转为人工处理
- 同步当天查寝任务及表单元数据
- 检查任务日期和已有签到状态，默认避免重复提交
- 执行一次性打卡并生成本地审计日志
- 提供 FastAPI 后端和 React 网页入口
- 使用 SQLite 保存用户、凭据元数据和自动任务状态
- 后端运行期间按本地时间每天 `21:00` 执行已启用的自动任务

尚未完成或需要改进：

- 自动任务的校园网密码目前以临时明文形式保存在 SQLite 中
- 后端 API 没有登录认证和访问控制
- 日志列表、清理和部分管理页面仍为占位实现
- 打卡运行记录尚未持久化
- 前端部分中文文案仍需进行编码清理
- 缺少生产级密钥管理、通知、任务队列和日志轮转

## 项目结构

```text
.
|-- login_and_checkin.py        # 旧版 CLI 入口
|-- legacy/                     # 登录、任务同步和打卡实现
|-- checkin-web/
|   |-- backend/                # FastAPI 后端
|   |-- frontend/               # React + TypeScript + Vite 前端
|   |-- data/                   # 本地 SQLite 和日志目录，不提交运行数据
|   `-- docs/                   # 架构、安全说明和用户须知
`-- .gitignore                  # 敏感数据及构建产物忽略规则
```

## 环境要求

- Windows 10/11
- Python 3.11 或兼容版本
- Google Chrome
- Node.js 18 或更高版本
- npm

## 网页端启动

### 1. 安装后端

在项目根目录执行：

```powershell
cd checkin-web\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install requests playwright ddddocr
```

`ddddocr` 是可选依赖。未安装或识别失败时，可以在 Chrome 中手动处理验证码。

### 2. 配置后端

默认配置可以直接用于本地开发。如需调整数据目录、数据库或跨域来源，先在项目根目录创建本地环境文件：

```powershell
Copy-Item ..\.env.example ..\.env
```

可用变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `CHECKIN_WEB_ENV` | `local` | 当前运行环境名称 |
| `CHECKIN_WEB_DATA_DIR` | `./data` | 运行数据目录 |
| `CHECKIN_WEB_DATABASE_URL` | `sqlite:///./data/app.db` | SQLite 数据库地址 |
| `CHECKIN_WEB_LOG_DIR` | `./data/logs` | 后端日志目录 |
| `CHECKIN_WEB_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 允许的前端来源 |

不要在 `.env.example` 中填写真实账号或密码。`.env` 已被 Git 忽略。

### 3. 启动后端

继续在 `checkin-web\backend` 目录执行：

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --env-file ..\.env
```

健康检查和交互式 API 文档：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

### 4. 启动前端

另开一个 PowerShell 窗口，在项目根目录执行：

```powershell
cd checkin-web\frontend
npm ci
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。

如后端不在默认地址，可以在启动前设置：

```powershell
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm run dev
```

## 命令行使用

旧版 CLI 可以独立运行。先安装依赖并检查本机环境：

```powershell
py -3.11 -m pip install requests playwright ddddocr
py -3.11 login_and_checkin.py --env-check
```

使用环境变量提供账号信息，避免密码出现在命令历史和进程参数中：

```powershell
$env:SWU_USERNAME = "你的账号"
$env:SWU_PASSWORD = "你的密码"
py -3.11 login_and_checkin.py --cqtj-checkin
```

只登录、不提交打卡：

```powershell
py -3.11 login_and_checkin.py --login-only
```

只同步当天任务元数据：

```powershell
py -3.11 login_and_checkin.py --sync-cqtj
```

查看全部参数：

```powershell
py -3.11 login_and_checkin.py --help
```

## 本地数据与安全

以下文件可能包含账号、Token、学号、姓名、请求报文或其他敏感信息，禁止提交到 GitHub 或发送给无关人员：

```text
.env
token.txt
checkin_cache.json
audit_logs/
network_logs/
run_logs/
ChromeSwuLoginProfile/
checkin-web/data/*.db
```

这些路径已写入 `.gitignore`，但提交前仍应执行：

```powershell
git status --short
git diff --cached
```

重要安全限制：

- 自动任务当前会把校园网密码以 `plain-temporary` 形式写入 `checkin-web/data/app.db`。在完成加密存储前，不要启用真实账号的长期自动任务。
- 后端接口没有身份验证。必须保持绑定 `127.0.0.1`，不要使用 `0.0.0.0`，不要配置公网端口转发。
- 日志可能包含个人信息。排查完成后应及时清理，并避免上传完整日志或截图。
- 怀疑凭据泄露时，应立即修改密码、删除本地 Token/缓存/数据库，并检查 Git 暂存区和提交历史。

更完整的说明见：

- [`checkin-web/docs/security.md`](checkin-web/docs/security.md)
- [`checkin-web/docs/user_notice.md`](checkin-web/docs/user_notice.md)
- [`checkin-web/docs/architecture.md`](checkin-web/docs/architecture.md)

## 开发检查

后端结构测试：

```powershell
cd checkin-web\backend
python -m pip install pytest
python -m pytest
```

前端类型检查与构建：

```powershell
cd checkin-web\frontend
npm run build
```

## 许可证

本仓库当前尚未包含开源许可证。在添加 `LICENSE` 之前，默认著作权规则仍然适用。公开分发前还应确认学校和相关平台规则是否允许公开其中的接口信息、应用标识和使用方式。
