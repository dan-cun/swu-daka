import asyncio
import os
from datetime import datetime

from .config import *
from .common import (
    analyze_monitor_log,
    append_jsonl,
    async_playwright,
    complete_meta,
    extract_checkin_meta_candidates,
    print_monitor_analysis,
    redact_sensitive,
    require_playwright,
    reset_chrome_profile,
    save_checkin_meta,
    port_open,
)
from .browser_login import (
    auto_login_for_monitor,
    auto_probe_baida_routes,
    enter_uaaap_if_qr_login,
    launch_chrome,
)

async def monitor_chrome_network(
    debug_port: int = DEBUG_PORT,
    chrome_exe: str | None = None,
    user_data_dir: str = USER_DATA_DIR,
    fresh_profile: bool = True,
    monitor_seconds: int = 0,
    open_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    xh: str | None = None,
    manual_login: bool = False,
    auto_probe: bool = True,
) -> dict | None:
    """连接外部 Chrome, 监听 fighter-baida 响应并尝试提取签到表单元数据."""
    require_playwright()
    chrome_proc = None
    if not port_open(debug_port):
        chrome_proc = launch_chrome(chrome_exe, debug_port, user_data_dir, fresh_profile)
    elif fresh_profile:
        reset_chrome_profile(user_data_dir)
        if not port_open(debug_port):
            chrome_proc = launch_chrome(chrome_exe, debug_port, user_data_dir, False)
        else:
            print("[!] 端口已被占用, 将连接现有 Chrome；如卡住请关闭占用 9222 的 Chrome 后重试")

    os.makedirs(NETWORK_LOG_DIR, exist_ok=True)
    log_path = os.path.join(
        NETWORK_LOG_DIR,
        f"baida_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )
    best_meta = {"value": None}
    token_state = {"value": None}

    async with async_playwright() as p:
        print(f"[i] 连接外部 Chrome CDP: http://127.0.0.1:{debug_port}")
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(resp):
            url_lower = resp.url.lower()
            if not any(word.lower() in url_lower for word in BAIDA_URL_KEYWORDS):
                return
            try:
                data = await resp.json()
            except Exception:
                return

            if "exchange-token" in resp.url and resp.status == 200:
                h = resp.headers.get("fighter-auth-token")
                if h and not token_state["value"]:
                    token_state["value"] = h
                body_data = data.get("data") if isinstance(data, dict) else None
                if body_data and not token_state["value"]:
                    token_state["value"] = body_data
                if token_state["value"]:
                    # 手动登录模式下捕获到 token 即落盘, 供后续 --token 续签签到
                    try:
                        with open(os.path.join(PROJECT_ROOT, "token.txt"), "w",
                                  encoding="utf-8") as f:
                            f.write(token_state["value"])
                        print("[OK] Token 已捕获并保存到 token.txt")
                    except Exception:
                        pass

            record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "url": resp.url,
                "status": resp.status,
                "data": redact_sensitive(data),
            }
            append_jsonl(log_path, record)

            candidates = extract_checkin_meta_candidates(data)
            if not candidates:
                print(f"[API] {resp.status} {resp.url}")
                return

            top = candidates[0]
            old = best_meta["value"]
            if not old or top.get("score", 0) > old.get("score", 0):
                best_meta["value"] = top

            print(f"\n[API] {resp.status} {resp.url}")
            print(
                "[候选] "
                f"score={top.get('score')} "
                f"form_id={top.get('form_id') or '-'} "
                f"cqfbid={top.get('cqfbid') or '-'} "
                f"business_key={top.get('business_key') or '-'}"
            )
            if top.get("qdsj"):
                print(f"       qdsj={top.get('qdsj')}")
            if top.get("qsqddd"):
                print(f"       qsqddd={top.get('qsqddd')}")

            if complete_meta(top):
                save_checkin_meta(top, username=username, xh=xh)

        context.on("response", on_response)
        page.on(
            "console",
            lambda msg: append_jsonl(
                log_path,
                {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "console",
                    "type": msg.type,
                    "text": msg.text,
                },
            ),
        )
        page.on(
            "pageerror",
            lambda err: append_jsonl(
                log_path,
                {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "pageerror",
                    "message": str(err),
                },
            ),
        )

        if open_url:
            try:
                await page.goto(open_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                await enter_uaaap_if_qr_login(page)
            except Exception as e:
                print(f"[!] 打开页面失败: {e}")

        login_task = None
        probe_task = None
        if manual_login:
            print("[i] 手动登录模式: 请在 Chrome 中自行登录和操作，脚本只记录网络/控制台日志。")
        else:
            login_task = asyncio.create_task(
                auto_login_for_monitor(
                    page,
                    username or DEFAULT_USERNAME,
                    password or DEFAULT_PASSWORD,
                    token_state,
                    max_seconds=min(45, monitor_seconds or 45),
                )
            )
        if auto_probe and not manual_login:
            probe_task = asyncio.create_task(auto_probe_baida_routes(page, max_wait_seconds=monitor_seconds or 60))
        print(f"[i] 网络日志: {log_path}")
        if manual_login:
            print("[i] 正在监听你的手动操作。")
        else:
            print("[i] 正在自动登录并探测签到任务接口。")
        if monitor_seconds > 0:
            print(f"[i] 监听 {monitor_seconds}s 后自动结束...")
            await asyncio.sleep(monitor_seconds)
        else:
            print("[i] 持续监听中, 按 Ctrl+C 结束。")
            while True:
                await asyncio.sleep(3600)
        if login_task and not login_task.done():
            login_task.cancel()
        if probe_task and not probe_task.done():
            probe_task.cancel()
        summary = analyze_monitor_log(
            log_path,
            best_meta=best_meta["value"],
            token_seen=bool(token_state["value"]),
        )
        print_monitor_analysis(summary)
        try:
            await browser.close()
        except Exception:
            pass

    if chrome_proc:
        try:
            chrome_proc.terminate()
        except Exception:
            pass
    return best_meta["value"]

