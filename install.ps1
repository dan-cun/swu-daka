<#
.SYNOPSIS
  西南大学查寝打卡工具 · 一键环境安装（Windows 10/11）

.DESCRIPTION
  依次检测/安装：Python 3.10+（推荐 3.11）→ pip 依赖（requests/playwright/ddddocr
  + Web 后端 fastapi/uvicorn/pydantic，缺失才装）→ Google Chrome → Node.js 18+（Web 前端）
  → 前端 npm 依赖（缺 node_modules 才装）→ 数据目录 → 运行 --env-check 自检并输出摘要。
  幂等：已存在的组件自动跳过，可重复执行。

.PARAMETER SkipWeb
  只安装 CLI 打卡链路（跳过 Node.js 与前端依赖）。

.PARAMETER PipMirror
  pip 下载源（可选）。例如：https://mirrors.aliyun.com/pypi/simple/

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipWeb
#>
param(
    [switch]$SkipWeb,
    [string]$PipMirror = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "    [X]  $m" -ForegroundColor Red }

function Get-Winget {
    if (Get-Command winget -ErrorAction SilentlyContinue) { return "winget" }
    return $null
}

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") +
                ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Invoke-External {
    param([string[]]$CmdLine, [string]$What)
    $out = & $CmdLine[0] @($CmdLine[1..($CmdLine.Length - 1)]) 2>&1
    if ($LASTEXITCODE -ne 0) {
        $out | ForEach-Object { Write-Host $_ }
        throw "$What 失败 (exit $LASTEXITCODE)，见上方输出。"
    }
    return $out
}

function Invoke-Py {
    param([string[]]$Rest)
    # 子进程输出强制 UTF-8：避免 GBK 控制台无法编码包元数据中的
    # 中文/©（如 ddddocr 的 Summary/License）时 pip 打出 Logging error
    $env:PYTHONIOENCODING = "utf-8"
    # 局部放宽错误策略 + 2>&1：把 Python/pip 的 stderr 当数据而不是致命错误
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PyCmd[0] @($PyCmd[1..($PyCmd.Length - 1)]) @Rest 2>&1
    } finally {
        $ErrorActionPreference = $prev
    }
}

# ================= 1. Python =================
Write-Step "1/6 Python（>= 3.10，推荐 3.11）"
$PyCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("3.11", "3.10")) {
        $ver = (& py "-$v" --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $ver -match '^Python 3\.(1[0-9]|[2-9][0-9])(\..*)?$') {
            $PyCmd = @("py", "-$v")
            Write-Ok "$ver（调用方式: py -$v）"
            break
        }
    }
}
if (-not $PyCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $ver = (& python --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and $ver -match '^Python 3\.(1[0-9]|[2-9][0-9])(\..*)?$') {
        $PyCmd = @("python")
        Write-Ok "$ver（调用方式: python）"
    }
}
if (-not $PyCmd) {
    $winget = Get-Winget
    if ($winget) {
        Write-Warn "未检测到 Python 3.10+，尝试 winget 安装 Python 3.11 ..."
        & winget install -e --id Python.Python.3.11 `
            --accept-source-agreements --accept-package-agreements
        Refresh-Path
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $ver = (& py -3.11 --version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $ver -match '^Python 3\.') {
                $PyCmd = @("py", "-3.11")
                Write-Ok "$ver（winget 安装成功）"
            }
        }
    }
    if (-not $PyCmd) {
        throw "未找到 Python 3.10+。请手动安装 Python 3.11（https://www.python.org/downloads/，勾选 Add python.exe to PATH）后重新运行本脚本。"
    }
}

# ================= 2. pip 依赖 =================
Write-Step "2/6 Python 依赖（pip）"
$mirror = @()
if ($PipMirror) { $mirror = @("-i", $PipMirror) }

$pkgNames = @("requests", "playwright", "ddddocr")
if (-not $SkipWeb) { $pkgNames += @("fastapi", "uvicorn", "pydantic") }

$missing = @()
foreach ($pkg in $pkgNames) {
    $show = Invoke-Py @("-m", "pip", "show", $pkg) 2>&1
    if ($LASTEXITCODE -ne 0) { $missing += $pkg }
}
if ($missing.Count -eq 0) {
    Write-Ok "依赖齐全：$($pkgNames -join ' / ')"
} else {
    Write-Warn "缺少 $($missing -join ', ')，开始安装 ..."
    $installNames = $missing
    if ($installNames -contains "uvicorn") {
        $installNames = $installNames -replace '^uvicorn$', 'uvicorn[standard]'
    }
    $out = Invoke-Py @("-m", "pip", "install") @installNames @mirror 2>&1
    if ($LASTEXITCODE -ne 0) {
        $out | ForEach-Object { Write-Host $_ }
        throw "pip install 失败 (exit $LASTEXITCODE)。网络慢可加 -PipMirror 换源重试。"
    }
    Write-Ok "已安装：$($missing -join ', ')"
}

# 冗余 chardet 会导致 requests 每次导入打印无害的版本告警，清理之
$showChardet = Invoke-Py @("-m", "pip", "show", "chardet") 2>&1
if ($LASTEXITCODE -eq 0) {
    $showCn = Invoke-Py @("-m", "pip", "show", "charset-normalizer") 2>&1
    if ($LASTEXITCODE -eq 0) {
        Invoke-Py @("-m", "pip", "uninstall", "-y", "chardet") 2>&1 | Out-Null
        Write-Ok "已卸载冗余 chardet（消除 requests 版本告警）"
    }
}

# ================= 3. Chrome =================
Write-Step "3/6 Google Chrome（统一认证登录）"
$chromeCandidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) {
    $cv = (Get-Item $chrome).VersionInfo.FileVersion
    Write-Ok "$chrome（$cv）"
} else {
    $winget = Get-Winget
    if ($winget) {
        Write-Warn "未找到 Chrome，尝试 winget 安装 ..."
        & winget install -e --id Google.Chrome `
            --accept-source-agreements --accept-package-agreements
        $chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($chrome) {
            $cv = (Get-Item $chrome).VersionInfo.FileVersion
            Write-Ok "$chrome（$cv，winget 安装成功）"
        }
    }
    if (-not $chrome) {
        throw "未找到 Google Chrome。请安装 64-bit 稳定版 Chrome（https://www.google.com/chrome/），或用 --chrome-exe 指定路径。"
    }
}

# ================= 4. Node.js =================
$nodeVer = $null
if ($SkipWeb) {
    Write-Step "4/6 Node.js —— 跳过（-SkipWeb）"
} else {
    Write-Step "4/6 Node.js（>= 18，Web 前端）"
    if (Get-Command node -ErrorAction SilentlyContinue) {
        $nv = (& node --version 2>&1 | Out-String).Trim()
        $major = [int]($nv.TrimStart('v').Split('.')[0])
        if ($major -ge 18) {
            $npmv = (& npm --version 2>&1 | Out-String).Trim()
            $nodeVer = $nv
            Write-Ok "Node.js $nv / npm $npmv"
        } else {
            Write-Warn "Node.js $nv 版本过低（< 18），尝试安装 LTS ..."
        }
    } else {
        Write-Warn "未检测到 Node.js，尝试安装 LTS ..."
    }
    if (-not $nodeVer) {
        $winget = Get-Winget
        if ($winget) {
            & winget install -e --id OpenJS.NodeJS.LTS `
                --accept-source-agreements --accept-package-agreements
            Refresh-Path
            if (Get-Command node -ErrorAction SilentlyContinue) {
                $nv = (& node --version 2>&1 | Out-String).Trim()
                $major = [int]($nv.TrimStart('v').Split('.')[0])
                if ($major -ge 18) { $nodeVer = $nv; Write-Ok "Node.js $nv（winget 安装成功）" }
            }
        }
        if (-not $nodeVer) {
            throw "未找到 Node.js 18+。请安装 Node.js LTS（https://nodejs.org/）后重新运行本脚本。"
        }
    }
}

# ================= 5. 前端依赖 =================
if ($SkipWeb) {
    Write-Step "5/6 前端依赖 —— 跳过（-SkipWeb）"
} else {
    Write-Step "5/6 前端依赖（checkin-web/frontend）"
    $fe = Join-Path $Root "checkin-web\frontend"
    $nm = Join-Path $fe "node_modules"
    if (Test-Path $nm) {
        Write-Ok "node_modules 已存在，跳过 npm 安装"
    } else {
        Push-Location $fe
        try {
            $lock = Test-Path (Join-Path $fe "package-lock.json")
            if ($lock) { Invoke-External @("npm", "ci") "npm ci" }
            else        { Invoke-External @("npm", "install") "npm install" }
            Write-Ok "前端依赖安装完成"
        } finally {
            Pop-Location
        }
    }
}

# ================= 6. 数据目录 + 自检 =================
Write-Step "6/6 数据目录与环境自检"
$dirs = @("audit_logs", "network_logs", "run_logs", (Join-Path "checkin-web" "data\logs"))
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}
Write-Ok "数据目录就绪：$($dirs -join ', ')"

Push-Location $Root
try {
    & $PyCmd[0] @($PyCmd[1..($PyCmd.Length - 1)], "login_and_checkin.py", "--env-check")
} finally {
    Pop-Location
}

Write-Host "`n" + ("=" * 52)
Write-Host " 安装/检查完成。开始使用："
Write-Host '   $env:SWU_USERNAME = "你的账号"'
Write-Host '   $env:SWU_PASSWORD = "你的密码"'
Write-Host "   $($PyCmd -join ' ') login_and_checkin.py --cqtj-checkin"
Write-Host ("=" * 52)



