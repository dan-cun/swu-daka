# -*- coding: utf-8 -*-
"""打卡助手：GUI 一键打卡 + 每日自动打卡（Windows 计划任务）

运行模式：
  双击 / 无参数        -> 打开图形界面
  --headless          -> 无界面模式：读取已保存凭据执行一次打卡，结果写入日志
                         （供计划任务在每天定时时无窗口运行）
  --task-create       -> 创建每日自动打卡计划任务（可加 --time HH:MM，默认 21:00）
  --task-delete       -> 删除自动打卡计划任务
  --task-status       -> 查询自动打卡计划任务状态

凭据保存位置（仅本机）：%APPDATA%\\swu-daka\\config.json（Base64 混淆，非加密）
自动打卡日志：%APPDATA%\\swu-daka\\auto_checkin.log
"""

import argparse
import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if IS_FROZEN else Path(__file__).resolve().parent
CLI_SCRIPT = APP_DIR / "login_and_checkin.py"

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "swu-daka"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTO_LOG_FILE = CONFIG_DIR / "auto_checkin.log"

TASK_NAME = "SWU_Daka_Auto"
DEFAULT_AUTO_TIME = "21:00"


# ============================== 基础工具 ==============================

def find_python() -> list:
    """返回调用项目 Python 的命令前缀（py 启动器优先）。"""
    def has(name: str, extra: list) -> bool:
        try:
            subprocess.run([name, *extra, "--version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            return True
        except Exception:
            return False

    if has("py", ["-3.11"]):
        return ["py", "-3.11"]
    if has("py", ["-3.10"]):
        return ["py", "-3.10"]
    if has("py", []):
        return ["py"]
    if has("python", []):
        return ["python"]
    raise RuntimeError("未找到 Python（py 启动器或 python），请先安装 Python 3.10+")


def save_config(username: str, password: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "username": base64.b64encode(username.encode("utf-8")).decode("ascii"),
        "password": base64.b64encode(password.encode("utf-8")).decode("ascii"),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return {
            "username": base64.b64decode(raw.get("username", "")).decode("utf-8"),
            "password": base64.b64decode(raw.get("password", "")).decode("utf-8"),
        }
    except Exception:
        return {}


def _run(cmd: list, timeout: int = 30) -> tuple:
    """运行命令，返回 (returncode, decoded_output)；解码兼容 GBK 控制台。"""
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    out = proc.stdout or b""
    err = proc.stderr or b""
    text = out.decode("utf-8", "replace")
    try:
        text = out.decode("gbk")
    except Exception:
        pass
    text += err.decode("utf-8", "replace")
    return proc.returncode, text.strip()


# ============================== 计划任务（自动打卡） ==============================

def _task_tr() -> str:
    """计划任务要执行的命令：打包后是 exe --headless，开发期是 py 脚本 --headless。"""
    if IS_FROZEN:
        return f'"{sys.executable}" --headless'
    py = find_python()
    return f'"{py[0]}" {" ".join(py[1:])} "{APP_DIR / "daka_gui.py"}" --headless'


def task_create(time_str: str = DEFAULT_AUTO_TIME) -> tuple:
    if not re.fullmatch(r"\d{1,2}:\d{2}", time_str):
        return False, "时间格式应为 HH:MM（如 21:00）"
    code, out = _run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", time_str,
                      "/TN", TASK_NAME, "/TR", _task_tr()])
    if code == 0:
        return True, f"已创建每日 {time_str} 自动打卡任务（{TASK_NAME}）"
    return False, f"创建计划任务失败: {out[:300]}"


def task_delete() -> tuple:
    code, out = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    if code == 0:
        return True, "已删除自动打卡任务"
    if "找不到" in out or "not found" in out.lower():
        return True, "自动打卡任务本就不存在"
    return False, f"删除计划任务失败: {out[:300]}"


def task_status() -> tuple:
    code, out = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV", "/NH"])
    if code != 0 or TASK_NAME not in out:
        return False, None
    m = re.search(r"\d{2}:\d{2}:\d{2}", out)
    return True, (m.group(0)[:5] if m else None)


# ============================== 打卡执行 ==============================

def run_checkin(username: str, password: str, line_cb) -> int:
    """调用 CLI 执行 登录→同步→打卡，逐行回调输出，返回退出码。"""
    py = find_python()
    env = dict(os.environ)
    env["SWU_USERNAME"] = username
    env["SWU_PASSWORD"] = password
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [py[0], *py[1:], str(CLI_SCRIPT), "--cqtj-checkin"],
        cwd=str(APP_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                line_cb(line)
        proc.wait()
    finally:
        proc.stdout.close()
    return proc.returncode


def append_auto_log(text: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(AUTO_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text)


def headless_main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = load_config()
    if not cfg.get("username") or not cfg.get("password"):
        append_auto_log(f"[{stamp}] 自动打卡跳过：未保存凭据（请先在界面填写并点“自动打卡”）\n")
        return 0
    lines = []

    def cb(line: str):
        lines.append(line)

    append_auto_log(f"===== [{stamp}] 自动打卡开始（账号 {cfg['username'][:3]}***）=====\n")
    try:
        rc = run_checkin(cfg["username"], cfg["password"], cb)
    except Exception as exc:
        rc = -1
        lines.append(f"[!] 执行异常: {exc}")
    append_auto_log("\n".join(lines) + f"\n[exit code] {rc}\n")
    return 0 if rc == 0 else 1


# ============================== GUI ==============================

def main_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    root = tk.Tk()
    root.title("打卡助手 · 西南大学查寝")
    root.geometry("760x520")
    root.minsize(640, 440)

    font = ("Microsoft YaHei UI", 10)
    big = ("Microsoft YaHei UI", 11, "bold")

    body = tk.Frame(root, padx=14, pady=10)
    body.pack(fill="both", expand=True)

    # ---- 账号 / 密码 ----
    top = tk.Frame(body)
    top.pack(fill="x")
    top.columnconfigure(1, weight=1)

    tk.Label(top, text="校园网账号：", font=font).grid(row=0, column=0, sticky="e", pady=2)
    ent_user = tk.Entry(top, font=font)
    ent_user.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

    tk.Label(top, text="校园网密码：", font=font).grid(row=1, column=0, sticky="e", pady=2)
    ent_pass = tk.Entry(top, font=font, show="*")
    ent_pass.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)

    tk.Label(top, text="自动时间：", font=font).grid(row=2, column=0, sticky="e", pady=2)
    row_time = tk.Frame(top)
    row_time.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=2)
    ent_time = tk.Entry(row_time, font=font, width=8)
    ent_time.insert(0, DEFAULT_AUTO_TIME)
    ent_time.pack(side="left")
    tk.Label(row_time, text="（24 小时制，查寝时段一般为 21:00-23:30）",
             font=("Microsoft YaHei UI", 8), fg="#888").pack(side="left", padx=(8, 0))

    # ---- 按钮 ----
    btns = tk.Frame(body)
    btns.pack(fill="x", pady=(10, 6))

    btn_once = tk.Button(btns, text="一次打卡", font=big, width=14,
                         bg="#2f6fb2", fg="white", activebackground="#3d7fc4")
    btn_once.pack(side="left", padx=(0, 10))

    btn_auto = tk.Button(btns, text="自动打卡", font=big, width=14,
                         bg="#2e8b57", fg="white", activebackground="#3aa06a")
    btn_auto.pack(side="left", padx=(0, 10))

    btn_off = tk.Button(btns, text="关闭自动打卡", font=big, width=14,
                        bg="#a0522d", fg="white", activebackground="#b2633c")
    btn_off.pack(side="left", padx=(0, 10))

    btn_log = tk.Button(btns, text="查看自动日志", font=font, width=12)
    btn_log.pack(side="right")

    # ---- 日志区 ----
    log = scrolledtext.ScrolledText(body, font=("Consolas", 9), state="disabled",
                                    bg="#1e1e1e", fg="#d4d4d4", wrap="word", height=16)
    log.pack(fill="both", expand=True)

    status = tk.Label(root, text="正在查询自动打卡状态...", font=font, anchor="w",
                      bg="#f0f0f0", padx=10, pady=3)
    status.pack(fill="x", side="bottom")

    q = queue.Queue()
    running = {"flag": False}

    def log_line(text: str = ""):
        q.put(text)

    def pump():
        try:
            while True:
                log_line_item = q.get_nowait()
                log.configure(state="normal")
                log.insert("end", log_line_item + "\n")
                log.see("end")
                log.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(100, pump)

    def refresh_task_status():
        on, t = task_status()
        if on:
            status.configure(text=f"自动打卡：已开启（每天 {t or DEFAULT_AUTO_TIME}，由 Windows 计划任务 {TASK_NAME} 执行）", bg="#e8f5e9")
        else:
            status.configure(text="自动打卡：未开启", bg="#f0f0f0")

    def current_credentials():
        cfg = load_config()
        u = ent_user.get().strip() or cfg.get("username", "")
        p = ent_pass.get().strip() or cfg.get("password", "")
        return u, p

    def set_buttons(state: str):
        for b in (btn_once, btn_auto, btn_off):
            b.configure(state=state)

    def worker_once():
        u, p = current_credentials()
        if not u or not p:
            q.put("[!] 请先填写校园网账号和密码")
            running["flag"] = False
            return
        q.put(f"===== 开始一次打卡（账号 {u[:3]}***）=====")
        q.put("[i] 将打开 Chrome 完成统一认证登录（验证码自动识别，失败可人工处理）...")
        try:
            rc = run_checkin(u, p, q.put)
        except Exception as exc:
            q.put(f"[!] 执行异常: {exc}")
            rc = -1
        q.put(f"===== 结束（exit code {rc}）：{'成功' if rc == 0 else '失败，请查看上方日志'} =====")
        running["flag"] = False

    def on_once():
        if running["flag"]:
            messagebox.showinfo("提示", "正在打卡中，请等待完成")
            return
        u, p = current_credentials()
        if not u or not p:
            messagebox.showwarning("提示", "请先填写校园网账号和密码")
            return
        running["flag"] = True
        set_buttons("disabled")
        threading.Thread(target=worker_once, daemon=True).start()

    def on_auto():
        if running["flag"]:
            return
        u, p = current_credentials()
        if not u or not p:
            messagebox.showwarning("提示", "自动打卡需要账号密码，请先填写")
            return
        time_str = ent_time.get().strip()
        try:
            h, m = time_str.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
        except Exception:
            messagebox.showwarning("提示", "自动时间格式应为 HH:MM（如 21:00）")
            return
        save_config(u, p)
        ok, msg = task_create(time_str)
        q.put(msg if ok else f"[!] {msg}")
        if ok:
            q.put("[i] 提示：计划任务在本机每天定时运行，无需保持本窗口打开；"
                  "当天需在签到点范围内、且 Python/Chrome 环境可用。")
        refresh_task_status()

    def on_off():
        ok, msg = task_delete()
        q.put(msg if ok else f"[!] {msg}")
        refresh_task_status()

    def on_view_log():
        if AUTO_LOG_FILE.exists():
            os.startfile(str(AUTO_LOG_FILE))
        else:
            messagebox.showinfo("提示", "还没有自动打卡日志（自动任务运行后会生成）")

    btn_once.configure(command=on_once)
    btn_auto.configure(command=on_auto)
    btn_off.configure(command=on_off)
    btn_log.configure(command=on_view_log)

    # 启动时回填已保存凭据 + 查询任务状态
    cfg = load_config()
    if cfg.get("username"):
        ent_user.insert(0, cfg["username"])
        ent_pass.insert(0, cfg["password"])
    log_line("欢迎使用打卡助手。填写账号密码后：")
    log_line("  · “一次打卡” 立即执行（会弹出 Chrome 登录窗口）")
    log_line("  · “自动打卡” 按设定时间每天自动执行（Windows 计划任务，无需保持本窗口打开）")
    refresh_task_status()
    pump()
    root.mainloop()


# ============================== 入口 ==============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="打卡助手")
    parser.add_argument("--headless", action="store_true", help="无界面模式（计划任务用）")
    parser.add_argument("--task-create", action="store_true", help="创建每日自动打卡任务")
    parser.add_argument("--task-delete", action="store_true", help="删除自动打卡任务")
    parser.add_argument("--task-status", action="store_true", help="查询自动打卡任务")
    parser.add_argument("--time", default=DEFAULT_AUTO_TIME, help="自动打卡时间 HH:MM（默认 21:00）")
    args = parser.parse_args()

    if args.headless:
        sys.exit(headless_main())
    if args.task_create:
        ok, msg = task_create(args.time)
        print(msg)
        sys.exit(0 if ok else 1)
    if args.task_delete:
        ok, msg = task_delete()
        print(msg)
        sys.exit(0 if ok else 1)
    if args.task_status:
        on, t = task_status()
        print(f"自动打卡：{'已开启（每天 ' + str(t or DEFAULT_AUTO_TIME) + '）' if on else '未开启'}")
        sys.exit(0)
    main_gui()
