# -*- coding: utf-8 -*-
"""每日定时打卡 + 结果邮件通知（可选附件，与登录修复相互独立）。

> 本文件是 `contrib/idm-waf-login-fix/` 的一部分，属于**可选新增内容**，
> 不修改仓库中任何既有文件。
> 若要实际使用，请把它复制到仓库根目录（脚本按自身位置定位 login_and_checkin.py），
> 或修改下面的 CLI_SCRIPT 路径。
>
> 凭据与邮件配置都放在仓库外的用户目录，**不入库、不硬编码**：
>   %APPDATA%\\swu-daka\\config.json   {"username": "<base64>", "password": "<base64>"}
>   %APPDATA%\\swu-daka\\mail.json     {"smtp_host","smtp_port","use_ssl","sender","auth_code","receiver","notify_on_success"}
> 邮件未配置时只写日志，不影响打卡执行。

流程：
  1. 读取凭据（与打卡助手 GUI 同一份）
  2. 调用 login_and_checkin.py --cqtj-checkin
  3. 解析输出判定结果并写入 auto_task.log
  4. 失败 -> 发邮件告警；成功/已签到 -> 按 notify_on_success 决定是否发信

手动用法：
  python auto_checkin_task.py                # 立即执行一次（等同计划任务触发）
  python auto_checkin_task.py --test-mail    # 只发一封测试邮件，验证邮件配置
"""

import base64
import json
import os
import smtplib
import ssl
import subprocess
import sys
import traceback
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CLI_SCRIPT = APP_DIR / "login_and_checkin.py"


def _config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "swu-daka"
    return Path.home() / "AppData" / "Roaming" / "swu-daka"


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
MAIL_FILE = CONFIG_DIR / "mail.json"
RUN_LOG = CONFIG_DIR / "auto_task.log"

TIMEOUT_SEC = 600
TAIL_LINES = 40

SUCCESS_MARK = "[OK] 签到成功"
ALREADY_MARK = "不重复提交"
REASON_HINTS = (
    ("不在签到范围内", "不在签到点范围内（请检查 legacy/config.py 里的签到点坐标与半径）"),
    ("今日查寝任务为空", "服务端今日未发布查寝任务，或执行时间过早"),
    ("登录失败", "统一认证登录失败（账号密码错误 / 验证码 / 页面变动）"),
    ("缺少登录账号或密码", "本机未保存凭据"),
    ("未同步到今日查寝任务", "未同步到今日查寝任务"),
    ("签到失败", "服务端返回签到失败"),
    ("同步任务日期不是今天", "同步到的任务不是当天"),
)

# 视为「未填写」的占位符，命中则判定邮件未配置
PLACEHOLDERS = ("在这里填", "你的QQ号", "your_", "xxxx", "")


# ============================== 基础工具 ==============================

def log(text: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {text}\n")
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", "replace").decode("utf-8", "replace"))


def mask_account(value: str) -> str:
    """日志里只留首尾各 3 位，避免账号明文落地。"""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"


def load_credentials() -> tuple[str, str]:
    if not CONFIG_FILE.exists():
        return "", ""
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return (
            base64.b64decode(raw.get("username", "")).decode("utf-8"),
            base64.b64decode(raw.get("password", "")).decode("utf-8"),
        )
    except Exception:
        return "", ""


def load_mail_config() -> dict | None:
    if not MAIL_FILE.exists():
        return None
    try:
        cfg = json.loads(MAIL_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"邮件配置解析失败: {exc}")
        return None
    sender = str(cfg.get("sender", "")).strip()
    auth_code = str(cfg.get("auth_code", "")).strip()
    receiver = str(cfg.get("receiver", "")).strip() or sender
    if not sender or not auth_code:
        return None
    if any(p and p in auth_code for p in ("在这里填", "xxxx", "your_")):
        return None
    if any(p and p in sender for p in ("你的QQ号", "your_")):
        return None
    return {
        "host": str(cfg.get("smtp_host", "smtp.qq.com")),
        "port": int(cfg.get("smtp_port", 465)),
        "use_ssl": bool(cfg.get("use_ssl", True)),
        "sender": sender,
        "auth_code": auth_code,
        "receiver": receiver,
        "notify_on_success": bool(cfg.get("notify_on_success", False)),
    }


# ============================== 邮件 ==============================

def send_mail(subject: str, body: str) -> bool:
    cfg = load_mail_config()
    if cfg is None:
        log("邮件未配置（mail.json 缺失或授权码未填），跳过告警发送")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr(("打卡助手", cfg["sender"]))
    msg["To"] = cfg["receiver"]
    msg["Subject"] = Header(subject, "utf-8")
    try:
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(
                cfg["host"], cfg["port"], context=ssl.create_default_context(), timeout=30
            )
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            server.starttls(context=ssl.create_default_context())
        with server:
            server.login(cfg["sender"], cfg["auth_code"])
            server.sendmail(cfg["sender"], [cfg["receiver"]], msg.as_string())
        log(f"告警邮件已发送至 {mask_account(cfg['receiver'])}")
        return True
    except Exception as exc:
        log(f"邮件发送失败: {type(exc).__name__}: {exc}")
        return False


# ============================== 打卡 ==============================

def tail(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-TAIL_LINES:])


def guess_reason(output: str) -> str:
    for mark, desc in REASON_HINTS:
        if mark in output:
            return desc
    if not output.strip():
        return "打卡进程无任何输出（可能被中断）"
    return "未知原因，请查看日志尾部"


def run_checkin() -> tuple[str, str, str]:
    """返回 (status, reason, output)。status: success / already / failed。"""
    username, password = load_credentials()
    if not username or not password:
        return "failed", "本机未保存凭据（%APPDATA%\\swu-daka\\config.json）", ""

    env = dict(os.environ)
    env["SWU_USERNAME"] = username
    env["SWU_PASSWORD"] = password
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    command = [sys.executable, str(CLI_SCRIPT), "--cqtj-checkin"]
    try:
        proc = subprocess.run(
            command,
            cwd=str(APP_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
        )
        output = "\n".join(p for p in (proc.stdout, proc.stderr) if p)
    except subprocess.TimeoutExpired as exc:
        partial = ""
        for part in (exc.stdout, exc.stderr):
            if part:
                partial += part if isinstance(part, str) else part.decode("utf-8", "replace")
        return "failed", f"打卡超时（超过 {TIMEOUT_SEC} 秒，可能卡在登录或验证码）", partial
    except Exception as exc:
        return "failed", f"执行异常: {type(exc).__name__}: {exc}", traceback.format_exc()

    if SUCCESS_MARK in output:
        return "success", "签到成功", output
    if ALREADY_MARK in output:
        return "already", "今日任务已签到，未重复提交", output
    return "failed", guess_reason(output), output


def _body(account: str, reason: str, output: str, stamp: str) -> str:
    return (
        f"时间：{stamp}\n"
        f"账号：{account}\n"
        f"结果：{reason}\n"
        f"主机：{os.environ.get('COMPUTERNAME', '')}\n\n"
        f"----- 打卡输出尾部 -----\n{tail(output) or '(无输出)'}\n\n"
        f"完整日志：{RUN_LOG}\n"
    )


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username, _ = load_credentials()
    account = mask_account(username) if username else "(未配置)"

    log(f"===== 自动打卡开始（账号 {account}）=====")
    status, reason, output = run_checkin()
    log(f"结果: {status} | {reason} | exit-output-bytes={len(output)}")
    if output.strip():
        log("---- 输出尾部 ----\n" + tail(output))

    cfg = load_mail_config()
    if status == "failed":
        subject = f"[打卡失败] {datetime.now():%m-%d %H:%M} 自动打卡未完成"
        send_mail(subject, _body(account, f"失败 / {reason}", output, stamp))
    elif cfg and cfg["notify_on_success"] and status in ("success", "already"):
        title = "打卡成功" if status == "success" else "今日已签到"
        send_mail(f"[{title}] {datetime.now():%m-%d %H:%M}", _body(account, reason, output, stamp))

    log(f"===== 自动打卡结束（{status}）=====\n")
    return 0 if status in ("success", "already") else 1


if __name__ == "__main__":
    if "--test-mail" in sys.argv:
        ok = send_mail(
            "[打卡助手] 邮件通知测试",
            f"这是一封测试邮件，收到说明邮件通知配置正常。\n时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n",
        )
        print("测试邮件发送成功" if ok else "测试邮件发送失败，请检查 mail.json")
        sys.exit(0 if ok else 1)
    sys.exit(main())
