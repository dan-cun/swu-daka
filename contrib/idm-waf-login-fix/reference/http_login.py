"""纯 HTTP 客户端登录（绕开 idm.swu.edu.cn 前置「瑞数」类动态 WAF 对浏览器 POST 的拦截）。

================================================================================
为什么需要这个模块（根因）
================================================================================
idm.swu.edu.cn 前面挂了一层瑞数（RiverSecurity）类动态 WAF。它会给页面里
fetch/XHR 的 URL 自动补一个动态令牌（形如 ``?ZUY2FAwZ=...``），但同时会把
**浏览器内一切「带 body 的 POST 到 /am/」** 直接拦成 HTTP 400，响应体只有
``\r\n\r\n\r\n``（即一个空白页）。实测被拦的请求包括：

  * 页面自己的验证码预校验  POST /am/validatecode/verify.do
  * 登录表单的正式提交      POST /am/UI/Login   ← form.submit() / fetch 都一样
  * 补过动态令牌的页面内 fetch 提交

由此产生的连锁反应，正是「验证码永远循环、图片裂图」的真正原因：

  1. 键盘输入第 4 位验证码 -> onkeyup -> verify.do 被 WAF 打成 400
  2. 页面 error 分支把全局 ``state`` 置 false
  3. 点登录 -> ``portalLogin()`` 开头 ``if (state == false) { getKaptcha(); return; }``
     -> **只换图，永不提交**
  4. ``getKaptcha()`` 换图请求同样被 400 -> 图片裂成「看不清，换一张」占位
  5. 脚本据此再刷新 -> 回到第 3 步，死循环

也就是说：**问题不在「脚本填得太快触发风控」，而在于浏览器发出的 POST 根本到不了
服务端。** 因此「拟人逐字输入」「人工手动输入」能缓解，但无法根治自动化目标。

================================================================================
解决思路
================================================================================
纯 HTTP 客户端（requests）**不被这层 WAF 拦截**：

  * GET  /am/validate.code   -> 200 image/jpeg（约 2KB，ddddocr 可读准 4 位数字）
  * POST /am/UI/Login        -> 200/302，并返回真实鉴权结果头 ``X-AuthErrorCode``

所以把职责拆开：

  浏览器   : 只负责走 SSO 链路（CAS -> uaaap -> 联邦认证）与持有会话、导出表单字段
  requests : 只负责「取验证码 + 提交账号密码」这一步

登录成功后把 requests 会话拿到的 cookie 灌回浏览器，再走一遍 SSO 收尾，
从 ``exchange-token`` 响应头取到 ``fighter-auth-token``。

另外两个实测结论：

  * **账号密码明文提交即可**，页面那套 ``strEnc`` 加密是历史包袱
    （用 strEnc 提交反而会被判「用户名或密码错误」）。
  * 成功判据是响应头 ``X-AuthErrorCode == "0"``（配合 HTTP 302）。

================================================================================
本文件定位
================================================================================
这是**新增文件**，不修改 ``browser_login.py`` 的任何既有逻辑——那个文件里
人工手动输入 / 拟人逐字输入 / token.txt 复用等改动全部保留、互不影响。
只有显式加上 ``--http-login`` 参数时才会走到这里。
"""

import asyncio
import re
import time

from .config import *  # noqa: F401,F403
from .common import (
    async_playwright,
    mask_secret,
    require_playwright,
    require_requests,
)
from .browser_login import launch_chrome, load_ocr

IDM_BASE = "https://idm.swu.edu.cn"
IDM_LOGIN_URL = IDM_BASE + "/am/UI/Login"
IDM_CAPTCHA_URL = IDM_BASE + "/am/validate.code"

IDM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

# 从页面导出登录表单的全部隐藏字段与 action。
# 注意：这些字段（goto / encoded / SunQueryParamsString 等）是 SSO 回跳所必需的，
# 不能凭记忆硬编码，必须每次从当前页面取。
_FORM_INFO_JS = """() => {
    const f = document.forms['Login'];
    const out = { fields: {}, action: null, pageurl: location.href };
    if (!f) return out;
    Array.from(f.elements).forEach(el => { if (el.name) out.fields[el.name] = el.value; });
    out.action = f.action;
    return out;
}"""


def _plain_text(html: str) -> str:
    """粗洗 HTML 取可见文本，用于读出服务端的错误文案。"""
    t = re.sub(r"<script[\s\S]*?</script>", " ", html or "", flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def http_submit_login(info: dict, cookies: dict, username: str, password: str,
                      ocr, tries: int = 4) -> tuple[bool, dict]:
    """用 requests 提交 IDM 登录表单（绕开 WAF 对浏览器 POST 的 400 拦截）。

    返回 ``(是否成功, 成功时的新 cookies 字典)``。

    仅在验证码 OCR 结果不可用（没真正发出 POST）时才在同会话内换一张重试；
    一旦 POST 被服务端拒绝，该会话即已失效，直接返回 False 交给上层重走 SSO
    （不要指望在同一会话里重试能成功）。
    """
    requests = require_requests()

    action = info.get("action") or IDM_LOGIN_URL
    page_url = info.get("pageurl") or IDM_LOGIN_URL

    s = requests.Session()
    s.headers.update({
        "User-Agent": IDM_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": page_url,
        "Origin": IDM_BASE,
    })
    # 关键：带上浏览器当前会话的 cookie，服务端才认这是同一个 SSO 会话
    s.cookies.update(cookies or {})

    for _ in range(1, max(1, tries) + 1):
        try:
            r = s.get(IDM_CAPTCHA_URL, timeout=25,
                      headers={"Accept": "image/*,*/*;q=0.8"})
        except Exception as exc:
            print(f"[!] 取验证码失败: {exc}")
            return False, {}
        if r.status_code != 200:
            print(f"[!] 取验证码 HTTP {r.status_code}")
            return False, {}

        code = (ocr.classification(r.content) or "").strip() if ocr else ""
        print(f"[OCR] 识别验证码: {code}")
        if len(code) != 4:
            print(f"[!] 验证码识别不可用 (got {len(code)})，换一张重试")
            continue

        body = dict(info.get("fields") or {})
        # ★ 明文提交即可，不需要 strEnc；用 strEnc 反而会被判「用户名或密码错误」
        body["IDToken1"] = username
        body["IDToken2"] = password
        body["IDToken3"] = ""
        body["validateCode"] = code

        try:
            r2 = s.post(action, data=body, timeout=30, allow_redirects=False)
        except Exception as exc:
            print(f"[!] 提交登录失败: {exc}")
            return False, {}

        err = r2.headers.get("X-AuthErrorCode")
        print(f"[*] POST /am/UI/Login -> HTTP {r2.status_code}, X-AuthErrorCode={err}")
        if err == "0":
            print("[OK] 认证通过（纯 HTTP 客户端提交，WAF 未拦）")
            return True, s.cookies.get_dict()

        print(f"[!] 认证未通过: {_plain_text(r2.text)[:160]}")
        return False, {}

    return False, {}


async def goto_sso(page) -> str:
    """走一遍 CAS -> uaaap -> 联邦认证 链路，返回最终停留的 URL。

    两种终点都算正常：
      * 停在 ``/am/UI/Login``      -> 还没登录，需要提交账号密码
      * 停在 of.swu.edu.cn 应用页  -> 登录已完成，等 exchange-token 回调

    ⚠ 绝对不要直接 goto / reload 登录页：实测会被 WAF 返回 400（空白页），
      页面再也回不到登录表单。只有走这条链路才是安全的。
    """
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
        try:
            await page.evaluate("_goLogin()")
        except Exception:
            pass
    else:
        current = page.url
        federal_trigger = current + ("&" if "?" in current else "?") + "federalEnable=true"
        try:
            await page.goto(federal_trigger, wait_until="commit", timeout=30000)
        except Exception:
            pass

    url = ""
    for _ in range(140):
        try:
            url = page.url
        except Exception:
            await asyncio.sleep(0.5)
            continue
        if "/am/UI/Login" in url:
            break
        # 会话已建立时链路会一路放行，直接落到 of.swu 应用页
        if "of.swu.edu.cn" in url and "/cas/" not in url:
            break
        await asyncio.sleep(0.5)

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    await asyncio.sleep(2.0)
    try:
        url = page.url
    except Exception:
        pass
    if "/am/UI/Login" in url:
        print("[4] 已到达 IDM 登录页")
    else:
        print(f"[4] 链路已放行, 当前: {url[:110]}")
    return url


async def do_login_http(
    username: str,
    password: str,
    chrome_exe: str | None = None,
    debug_port: int = DEBUG_PORT,
    user_data_dir: str = USER_DATA_DIR,
    fresh_profile: bool = True,
) -> str | None:
    """纯 HTTP 客户端登录，返回 ``fighter-auth-token``。

    与 ``browser_login.do_login(manual=True)`` 的区别：全自动，无需人工介入；
    与 ``do_login(manual=False)`` 的区别：不做拟人逐字输入，而是干脆让
    requests 去发那个 POST，从根上避开 WAF 对浏览器 POST 的拦截。
    """
    require_playwright()
    ocr = load_ocr()
    if ocr is None:
        print("[!] 未安装 ddddocr，--http-login 无法自动识别验证码")
        return None

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

        async def wait_token(rounds: int = 90) -> bool:
            for _ in range(rounds):
                if token["value"]:
                    return True
                await asyncio.sleep(0.5)
            return False

        url = await goto_sso(page)

        if "/am/UI/Login" not in url:
            # 会话本来就已建立（例如 profile 未清理），链路直接放行 -> 等 Token
            print("[i] 链路未停在登录页，直接等待 Token...")
            if not await wait_token():
                print("[!] 未获取到 Token")

        for attempt in range(1, MAX_CAPTCHA_RETRY + 1):  # noqa: F405
            if token["value"]:
                break
            print(f"\n--- 登录尝试 #{attempt} ---")

            info = await page.evaluate(_FORM_INFO_JS)
            if not (info or {}).get("fields"):
                print("[!] 当前页面没有登录表单（可能已被 WAF 打成空白页），重走 SSO...")
                await goto_sso(page)
                continue

            cookies = {c["name"]: c["value"]
                       for c in await context.cookies(IDM_BASE)}
            print("[*] 用纯 HTTP 客户端提交登录（绕开 WAF）...")
            try:
                ok, new_cookies = http_submit_login(info, cookies, username, password, ocr)
            except Exception as exc:
                print(f"[!] HTTP 登录异常: {exc}")
                ok, new_cookies = False, {}

            if not ok:
                print("[i] 换全新会话与验证码：重走 SSO...")
                if "/am/UI/Login" not in await goto_sso(page) and await wait_token():
                    break
                continue

            # 把 HTTP 会话拿到的 cookie 灌回浏览器，让浏览器走完剩余 SSO 链
            inject = [{"name": k, "value": v, "domain": ".swu.edu.cn", "path": "/"}
                      for k, v in (new_cookies or {}).items()]
            try:
                await context.add_cookies(inject)
                print(f"[i] 已把 {len(inject)} 个 cookie 注入浏览器")
            except Exception as exc:
                print(f"[!] 注入 cookie 失败: {exc}")

            print("[5] 重走 SSO 完成登录链路...")
            await goto_sso(page)
            if await wait_token(120):
                break
            print("[!] 链路已放行但未捕获到 Token")

        await wait_token(20)
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


async def auto_login_for_monitor_http(page, username: str, password: str,
                                      token_state: dict, max_seconds: int = 45) -> None:
    """监听模式的纯 HTTP 版本：在 uaaap/idm 页之间推进并自动登录，不负责最终提交。

    与 ``browser_login.auto_login_for_monitor`` 的差别仅在于登录那一步改用
    ``http_submit_login``（其余链路推进逻辑保持一致）。
    """
    from .browser_login import enter_uaaap_if_qr_login, select_uaaap_unified_login

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
            print(f"[i] IDM 纯 HTTP 登录尝试 #{attempt}")
            info = await page.evaluate(_FORM_INFO_JS)
            if not (info or {}).get("fields"):
                await asyncio.sleep(1)
                continue
            cookies = {}
            try:
                cookies = {c["name"]: c["value"]
                           for c in await page.context.cookies(IDM_BASE)}
            except Exception:
                pass
            ok, _ = http_submit_login(info, cookies, username, password, ocr)
            await asyncio.sleep(3 if ok else 1)
        elif "of.swu.edu.cn" in url and "/cas/" not in url:
            return
        else:
            await asyncio.sleep(1)
