import asyncio
import os
import subprocess
import time

from .config import *
from .common import (
    async_playwright,
    mask_secret,
    port_open,
    require_playwright,
    reset_chrome_profile,
    resolve_chrome_exe,
)

def launch_chrome(
    chrome_exe: str | None = None,
    debug_port: int = DEBUG_PORT,
    user_data_dir: str = USER_DATA_DIR,
    fresh_profile: bool = True,
):
    if fresh_profile:
        reset_chrome_profile(user_data_dir)
    if port_open(debug_port):
        print(f"[i] 端口 {debug_port} 已被占用, 直接连接现有 Chrome")
        if fresh_profile:
            print("[!] 端口仍被占用, 当前连接可能不是干净 profile")
        return None
    chrome_path = resolve_chrome_exe(chrome_exe)
    os.makedirs(user_data_dir, exist_ok=True)
    args = [
        chrome_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    print(f"[i] 启动 Chrome: {chrome_path}")
    print(f"[i] CDP 端口: {debug_port}, 用户目录: {user_data_dir}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if port_open(debug_port):
            time.sleep(0.5)
            return proc
        time.sleep(0.25)
    raise RuntimeError("Chrome 调试端口未就绪")


def load_ocr():
    try:
        import ddddocr
        return ddddocr.DdddOcr(show_ad=False)
    except Exception as e:
        print(f"[!] ddddocr 加载失败({e}), 回退到手动输入验证码")
        return None


async def detect_login_failure(page) -> str | None:
    try:
        text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return None
    if not text:
        return None
    if not any(keyword in text for keyword in LOGIN_FAILURE_KEYWORDS):
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[:3])[:300]


async def login_once(page, ocr, username: str, password: str) -> bool:
    await page.wait_for_selector("#loginName", timeout=60000)
    await page.fill("#loginName", "")
    await page.fill("#loginName", username)
    await page.fill("#password", "")
    await page.fill("#password", password)

    captcha_el = await page.query_selector("#kaptchaImage")
    if not captcha_el:
        print("[!] 找不到验证码图片")
        return False

    img_bytes = await captcha_el.screenshot()
    if ocr:
        code = (ocr.classification(img_bytes) or "").strip()
        print(f"[OCR] 识别验证码: {code}")
    else:
        with open("captcha.png", "wb") as f:
            f.write(img_bytes)
        code = input("请查看 captcha.png 并输入验证码: ").strip()

    if len(code) != 4:
        print(f"[!] 验证码长度异常 (got {len(code)}), 刷新重试")
        await page.click("#kaptchaImage")
        await asyncio.sleep(1)
        return False

    await page.fill("#validateCode", "")
    await page.type("#validateCode", code, delay=50)
    await asyncio.sleep(1.5)

    tishi_src = await page.evaluate(
        "() => document.getElementById('tishi')?.getAttribute('src') || ''"
    )
    if "code_error" in tishi_src:
        print("[!] 验证码校验失败, 刷新重试")
        await page.click("#kaptchaImage")
        await asyncio.sleep(1)
        return False

    print("[*] 验证码正确, 提交登录...")
    await page.click("#button")
    return True


async def do_login(
    username: str,
    password: str,
    chrome_exe: str | None = None,
    debug_port: int = DEBUG_PORT,
    user_data_dir: str = USER_DATA_DIR,
    fresh_profile: bool = True,
) -> str | None:
    """执行完整登录流程, 返回 fighter-auth-token."""
    require_playwright()
    ocr = load_ocr()
    chrome_proc = launch_chrome(chrome_exe, debug_port, user_data_dir, fresh_profile)
    token = {"value": None}

    async with async_playwright() as p:
        print(f"[i] 连接 CDP http://localhost:{debug_port}")
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{debug_port}")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(resp):
            if "exchange-token" in resp.url and resp.status == 200:
                h = resp.headers.get("fighter-auth-token")
                if h and not token["value"]:
                    token["value"] = h
                    print(f"[OK] 响应头捕获 Token: {mask_secret(h)}")
                    return
                try:
                    body = await resp.json()
                    if body.get("code") == 200 and body.get("data") and not token["value"]:
                        token["value"] = body["data"]
                        print(f"[OK] 响应体捕获 Token: {mask_secret(body['data'])}")
                except Exception:
                    pass

        page.on("response", on_response)

        print("[1] 访问 CAS 初始页...")
        try:
            await page.goto(INIT_URL, wait_until="commit", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        print("[2] 跳转 uaaap CAS 选择页...")
        try:
            await page.goto(FEDERAL_URL, wait_until="commit", timeout=30000)
        except Exception:
            pass
        try:
            await page.wait_for_url("**/uaaap.swu.edu.cn/cas/login**", timeout=30000)
            await page.wait_for_load_state("domcontentloaded")
        except Exception:
            print(f"[!] 未到达 uaaap 选择页, 当前: {page.url}")

        await asyncio.sleep(2)

        print("[3] 触发联邦认证 -> idm.swu.edu.cn ...")
        try:
            has_fn = await page.evaluate("() => typeof _goLogin === 'function'")
        except Exception:
            has_fn = False
        if has_fn:
            await page.evaluate("_goLogin()")
        else:
            current = page.url
            federal_trigger = current + ("&" if "?" in current else "?") + "federalEnable=true"
            try:
                await page.goto(federal_trigger, wait_until="commit", timeout=30000)
            except Exception:
                pass

        try:
            await page.wait_for_url("**/idm.swu.edu.cn/am/UI/Login**", timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            print("[4] 已到达 IDM 登录页")
        except Exception as e:
            print(f"[!] 等待 IDM 页超时: {e}")
            print("    请在浏览器内手动处理, 脚本等待 60s 捕获 Token...")
            for _ in range(120):
                if token["value"]:
                    break
                await asyncio.sleep(0.5)
            try:
                await browser.close()
            except Exception:
                pass
            return token["value"]

        await asyncio.sleep(2)

        for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
            if token["value"]:
                break
            print(f"\n--- 登录尝试 #{attempt} ---")
            failure = await detect_login_failure(page)
            if failure:
                print(f"[!] 登录失败: {failure}")
                break
            try:
                ok = await login_once(page, ocr, username, password)
            except Exception as e:
                failure = await detect_login_failure(page)
                if failure:
                    print(f"[!] 登录失败: {failure}")
                    break
                raise e
            if not ok:
                continue
            for _ in range(40):
                if token["value"]:
                    break
                await asyncio.sleep(0.5)
                failure = await detect_login_failure(page)
                if failure:
                    print(f"[!] 登录失败: {failure}")
                    break
                if "idm.swu.edu.cn/am/UI/Login" not in page.url:
                    break
            if failure:
                break
            if token["value"]:
                break
            if "idm.swu.edu.cn/am/UI/Login" in page.url:
                print("[!] 登录未跳转, 重试")
                continue
            for _ in range(30):
                if token["value"]:
                    break
                await asyncio.sleep(0.5)

        for _ in range(20):
            if token["value"]:
                break
            await asyncio.sleep(0.5)

        await asyncio.sleep(1)
        try:
            await browser.close()
        except Exception:
            pass

    if chrome_proc:
        try:
            chrome_proc.terminate()
        except Exception:
            pass

    return token["value"]


async def enter_uaaap_if_qr_login(page, fallback_url: str = BAIDAFORM_FEDERAL_URL) -> bool:
    """of.swu CAS 扫码页出现时, 自动进入 uaaap 联邦认证页."""
    try:
        url = page.url
    except Exception:
        return False
    if "of.swu.edu.cn/cas/login" not in url:
        return False

    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""
    if "请在指定应用内扫码" not in body_text and "统一身份认证平台" not in body_text:
        return False

    print("[i] 检测到 of.swu 扫码页, 自动进入 uaaap 校内认证...")
    selectors = [
        "#federal",
        "#federal a",
        "a[href*='SWU_CAS2_FEDERAL']",
        "a[href*='uaaap.swu.edu.cn']",
        "img.login-img",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(timeout=3000, force=True)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            await asyncio.sleep(1)
            if "uaaap.swu.edu.cn" in page.url or "idm.swu.edu.cn" in page.url:
                print(f"[i] 已进入认证页: {page.url}")
                return True
        except Exception:
            continue

    print("[i] 页面点击入口失败, 使用联邦认证 URL 直接跳转")
    try:
        await page.goto(fallback_url, wait_until="commit", timeout=30000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    await asyncio.sleep(1)
    return "uaaap.swu.edu.cn" in page.url or "idm.swu.edu.cn" in page.url


async def select_uaaap_unified_login(page) -> bool:
    """在 uaaap 登录方式选择页点击“统一认证登录”."""
    try:
        url = page.url
    except Exception:
        return False
    if "uaaap.swu.edu.cn/cas/login" not in url:
        return False

    print("[i] 检测到 uaaap 登录方式选择页, 选择统一认证登录...")
    try:
        has_fn = await page.evaluate("() => typeof _goLogin === 'function'")
    except Exception:
        has_fn = False
    if has_fn:
        try:
            await page.evaluate("_goLogin()")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
            return True
        except Exception:
            pass

    selectors = [
        "text=统一认证登录",
        "img[src*='unified_button']",
        "div[onclick*='_goLogin']",
        ".loginMethd",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(timeout=3000, force=True)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
            return True
        except Exception:
            continue
    print("[!] 未能自动点击统一认证登录")
    return False


async def auto_login_for_monitor(page, username: str, password: str, token_state: dict, max_seconds: int = 45) -> None:
    """监听模式内自动完成 uaaap -> IDM 登录, 不负责最终签到提交."""
    ocr = load_ocr()
    deadline = time.time() + max_seconds
    attempt = 0
    while time.time() < deadline and not token_state.get("value"):
        url = page.url
        if "of.swu.edu.cn/cas/login" in url:
            await enter_uaaap_if_qr_login(page)
        elif "uaaap.swu.edu.cn/cas/login" in url:
            await select_uaaap_unified_login(page)
        elif "idm.swu.edu.cn/am/UI/Login" in url:
            attempt += 1
            print(f"[i] IDM 自动登录尝试 #{attempt}")
            ok = await login_once(page, ocr, username, password)
            if not ok:
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(3)
        elif "of.swu.edu.cn" in url and "/cas/" not in url:
            return
        else:
            await asyncio.sleep(1)


async def auto_probe_baida_routes(page, max_wait_seconds: int = 120) -> None:
    """登录回到 of.swu 后, 自动访问几个 baidaForm 候选路由以触发任务接口."""
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        url = page.url
        if (
            "of.swu.edu.cn" in url
            and "/cas/" not in url
            and "uaaap.swu.edu.cn" not in url
            and "idm.swu.edu.cn" not in url
        ):
            print(f"[i] 检测到已回到 of.swu: {url}")
            break
        await asyncio.sleep(2)
    else:
        print("[!] 等待回到 of.swu 超时, 未自动探测 baidaForm 路由")
        return

    for url in BAIDAFORM_DISCOVERY_URLS:
        try:
            print(f"[i] 探测页面: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(8)
        except Exception as e:
            print(f"[!] 探测页面失败: {url} ({e})")


