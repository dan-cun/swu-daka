import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

from .config import *

requests = None

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

# ============================== 环境/缓存工具 ==============================

def require_requests():
    global requests
    if requests is None:
        try:
            import requests as requests_module
        except ImportError as e:
            raise RuntimeError(
                "缺少 requests, 请执行: py -3.11 -m pip install requests"
            ) from e
        requests = requests_module
    return requests


def require_playwright():
    if async_playwright is None:
        raise RuntimeError(
            "缺少 playwright, 请执行: py -3.11 -m pip install playwright"
        )


def resolve_chrome_exe(chrome_exe: str | None = None) -> str:
    candidates = [
        chrome_exe,
        CHROME_EXE,
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for item in candidates:
        if item and os.path.exists(item):
            return item
    raise FileNotFoundError(
        "未找到 Google Chrome, 请用 --chrome-exe 指定 chrome.exe 完整路径"
    )


def is_safe_profile_dir(path: str) -> bool:
    profile = os.path.abspath(path)
    temp_dir = os.path.abspath(os.environ.get("TEMP", "C:\\Temp"))
    try:
        common = os.path.commonpath([profile, temp_dir])
    except ValueError:
        return False
    return common == temp_dir and os.path.basename(profile) == "ChromeSwuLoginProfile"


def stop_chrome_profile_processes(user_data_dir: str) -> None:
    if os.name != "nt":
        return
    escaped = os.path.abspath(user_data_dir).replace("'", "''")
    ps = (
        "$profile = '" + escaped + "'; "
        "Get-CimInstance Win32_Process -Filter \"name = 'chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    time.sleep(0.5)


def reset_chrome_profile(user_data_dir: str) -> None:
    profile = os.path.abspath(user_data_dir)
    if not is_safe_profile_dir(profile):
        print(f"[!] 为安全起见, 跳过清理非默认 Chrome profile: {profile}")
        return

    stop_chrome_profile_processes(profile)
    if os.path.exists(profile):
        shutil.rmtree(profile)
        print(f"[i] 已清理旧 Chrome 登录记录: {profile}")


def mask_secret(value: str | None, keep: int = 6) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_value(data: dict, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def extract_checkin_meta_candidates(payload) -> list[dict]:
    candidates = []
    today = datetime.now().strftime("%Y-%m-%d")
    for item in walk_dicts(payload):
        form_id = first_value(item, "formId", "form_id")
        cqfbid = first_value(item, "cqfbid", "cqfbId", "cqfBId", "cQFBID")
        business_key = first_value(item, "businessKey", "business_key")
        if not business_key and (form_id or cqfbid):
            possible_id = item.get("id")
            if isinstance(possible_id, str) and len(possible_id) >= 16:
                business_key = possible_id

        qdsj = item.get("qdsj")
        qsqddd = item.get("qsqddd")
        qdbj = item.get("qdbj")
        title = first_value(item, "title", "name", "formName", "bt", "taskName")
        has_checkin_field = any(
            key in item for key in ("qdjg", "$qdjg", "qddz", "$qddz", "qdtj", "dksj", "tsrq")
        )
        if not any((form_id, cqfbid, business_key, qdsj, qsqddd, qdbj, has_checkin_field)):
            continue

        raw_text = json.dumps(item, ensure_ascii=False, default=str)
        score = 0
        score += 5 if form_id else 0
        score += 5 if cqfbid else 0
        score += 5 if business_key else 0
        score += 2 if qdsj else 0
        score += 2 if qsqddd else 0
        score += 1 if qdbj else 0
        score += 2 if has_checkin_field else 0
        score += 2 if today in raw_text else 0
        score += 2 if any(word in raw_text for word in ("签到", "打卡", "晚点名")) else 0

        candidates.append(
            {
                "form_id": form_id,
                "cqfbid": cqfbid,
                "business_key": business_key,
                "qdsj": qdsj,
                "qsqddd": qsqddd,
                "qdbj": qdbj,
                "title": title,
                "score": score,
            }
        )
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def complete_meta(meta: dict | None) -> bool:
    return bool(meta and meta.get("form_id") and meta.get("cqfbid") and meta.get("business_key"))


def save_checkin_meta(meta: dict, username: str | None = None, xh: str | None = None) -> None:
    if not complete_meta(meta):
        return
    cache = load_json_file(CACHE_FILE, {})
    record = {
        **meta,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    cache["latest"] = record
    for key in (username, xh):
        if key:
            cache[str(key)] = record
    save_json_file(CACHE_FILE, cache)
    print(f"[OK] 已缓存签到表单元数据: {CACHE_FILE}")


def load_checkin_meta(username: str | None = None, xh: str | None = None) -> dict | None:
    cache = load_json_file(CACHE_FILE, {})
    today = datetime.now().strftime("%Y-%m-%d")
    for key in (username, xh, "latest"):
        if not key:
            continue
        record = cache.get(str(key))
        if complete_meta(record) and record.get("date") == today:
            return record
    return None


def redact_sensitive(value):
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if any(word in key_text for word in ("token", "password", "cookie", "session")):
                redacted[key] = mask_secret(str(child))
            else:
                redacted[key] = redact_sensitive(child)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(child) for child in value]
    return value


def make_audit_log_path(prefix: str = "checkin") -> str:
    os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
    return os.path.join(
        AUDIT_LOG_DIR,
        f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )


def append_audit_log(path: str | None, event: str, data: dict) -> None:
    if not path:
        return
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "data": redact_sensitive(data),
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def append_jsonl(path: str | None, record: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(redact_sensitive(record), ensure_ascii=False, default=str) + "\n")


def analyze_monitor_log(log_path: str, best_meta: dict | None = None, token_seen: bool = False) -> dict:
    summary = {
        "log_path": log_path,
        "total_records": 0,
        "api_records": 0,
        "console_errors": [],
        "page_errors": [],
        "urls": [],
        "has_auth_user": False,
        "has_baida_api": False,
        "has_form_meta": complete_meta(best_meta),
        "token_seen": token_seen,
        "diagnosis": "",
    }
    if not os.path.exists(log_path):
        summary["diagnosis"] = "没有生成网络日志，通常是 Chrome/CDP 没启动或页面没有发出 /gateway/ 请求。"
        return summary

    seen_urls = set()
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            summary["total_records"] += 1
            try:
                item = json.loads(line)
            except Exception:
                continue
            event = item.get("event")
            url = item.get("url", "")
            if url:
                summary["api_records"] += 1
                if url not in seen_urls:
                    seen_urls.add(url)
                    summary["urls"].append(url)
                if "api/auth/user" in url:
                    summary["has_auth_user"] = True
                if "fighter-baida" in url or "form-instance" in url or "cqlc" in url:
                    summary["has_baida_api"] = True
            if event == "console" and item.get("type") in ("error", "warning"):
                summary["console_errors"].append(item.get("text", "")[:500])
            if event == "pageerror":
                summary["page_errors"].append(item.get("message", "")[:500])

    if summary["has_form_meta"]:
        summary["diagnosis"] = "已捕获完整 formId/cqfbid/businessKey。"
    elif not summary["has_auth_user"]:
        summary["diagnosis"] = "未捕获 auth/user，流程大概率卡在统一认证或 IDM 登录前。"
    elif summary["has_auth_user"] and not summary["has_baida_api"]:
        summary["diagnosis"] = (
            "已登录并捕获 auth/user，但没有触发 fighter-baida/cqlc/form-instance 接口；"
            "当前问题在 baidaForm/#/index 空白页或路由未加载具体打卡任务。"
        )
    else:
        summary["diagnosis"] = (
            "捕获到部分 baida 接口，但未提取到完整 formId/cqfbid/businessKey；"
            "需要根据日志中的具体接口扩展提取规则或进入更具体的打卡详情页。"
        )
    return summary


def print_monitor_analysis(summary: dict) -> None:
    print("\n" + "=" * 60)
    print("[监听分析]")
    print(f"日志: {summary.get('log_path')}")
    print(f"记录数: {summary.get('total_records')}, API 记录: {summary.get('api_records')}")
    print(f"捕获 auth/user: {summary.get('has_auth_user')}")
    print(f"捕获 baida/cqlc/form 接口: {summary.get('has_baida_api')}")
    print(f"捕获完整表单元数据: {summary.get('has_form_meta')}")
    print(f"捕获 token: {summary.get('token_seen')}")
    if summary.get("urls"):
        print("最近接口:")
        for url in summary["urls"][-8:]:
            print(f"  - {url}")
    if summary.get("console_errors"):
        print("Console error/warning:")
        for msg in summary["console_errors"][-5:]:
            print(f"  - {msg}")
    if summary.get("page_errors"):
        print("Page error:")
        for msg in summary["page_errors"][-5:]:
            print(f"  - {msg}")
    print(f"诊断: {summary.get('diagnosis')}")
    print("=" * 60)


def response_to_audit(resp, parsed):
    return {
        "url": resp.url,
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": parsed,
        "text": resp.text[:3000] if not parsed else "",
    }


def print_env_check(debug_port: int = DEBUG_PORT, chrome_exe: str | None = None) -> None:
    print("[环境检查]")
    print(f"Python: {sys.executable}")
    print(f"Version: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("[!] 当前脚本建议使用 Python 3.10+, 例如: py -3.11 login_and_checkin.py")

    try:
        print(f"Chrome: {resolve_chrome_exe(chrome_exe)}")
    except Exception as e:
        print(f"Chrome: 未找到 ({e})")

    for package in ("requests", "playwright", "ddddocr"):
        installed = importlib.util.find_spec(package) is not None
        print(f"{package}: {'OK' if installed else 'MISSING'}")

    print(f"CDP 端口 {debug_port}: {'OPEN' if port_open(debug_port) else 'CLOSED'}")
    print(f"Chrome 独立用户目录: {USER_DATA_DIR}")
    print(f"Chrome 独立用户目录存在: {'YES' if os.path.exists(USER_DATA_DIR) else 'NO'}")
    print(f"缓存文件: {CACHE_FILE}")
    print(f"网络日志目录: {NETWORK_LOG_DIR}")
    print(f"审计日志目录: {AUDIT_LOG_DIR}")



def port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()

