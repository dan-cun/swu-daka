# 定位「验证码死循环」的真正根因：idm 侧 WAF 拦截浏览器 POST（附纯 HTTP 客户端绕行方案）

## 背景

`idm.swu.edu.cn` 登录页做自动化时会出现一条**看似 OCR 不准的死循环**：验证码图片裂图成
「看不清，换一张」，即使肉眼可见输对了，点登录也只换图、从不提交，一直刷到重试上限。

仓库在 `af5ad05` / `ba4e7b4` / `c8b96a9` 三个提交里已经围绕这个现象做了改进
（修死循环 → 拟人逐字输入 → 默认改为人工手动输入）。这些改动是有效的缓解，
但**根因还没有被指出**。这个 PR 补上根因定位，并提供一条**不冲突的旁路自动方案**。

## 根因

`idm.swu.edu.cn` 前置了**瑞数（RiverSecurity）类动态 WAF**。它会给页面内 fetch/XHR
自动补动态令牌，但**会把「浏览器内一切带 body 的 POST 到 `/am/`」直接拦成 HTTP 400**
（响应体仅 `\r\n\r\n\r\n`）。被拦的包括：

- `POST /am/validatecode/verify.do` —— 页面自己的验证码预校验
- `POST /am/UI/Login` —— `form.submit()` 和页面内 `fetch` 都一样

连锁反应正是死循环的成因：

1. 输入第 4 位 → `onkeyup` → `verify.do` 被 400
2. 页面 error 分支把全局 `state` 置 `false`
3. 点登录 → `portalLogin()` 开头 `if (state == false) { getKaptcha(); return; }` → **只换图**
4. 换图请求同样 400 → 图片裂成「看不清，换一张」占位
5. 脚本判定"验证码错误" → 再刷新 → 回到第 3 步，**死循环**

已排除的假设：

| 假设 | 实测 |
|---|---|
| HTTP/2 导致 | `--disable-http2 --disable-quic` 下 `http/1.1`，POST 仍 400 |
| 脚本填太快触发风控 | 用 JS 直接赋值绕过全部键盘事件后，`form.submit()` **真实发生**，仍 400 |
| 动态令牌无效 | 同会话 `GET /am/cloudSign/getMssgValid.do?ZUY2FAwZ=...` 返回 **200** |
| OCR 不准 | 用 requests 直连拉图，OCR 稳定读出 4 位数字 |

**所以问题不在"浏览器里怎么填"，而在"浏览器发出的 POST 到不了服务端"。**

## 方案

**纯 HTTP 客户端（requests）不被这层 WAF 拦截**：`GET /am/validate.code` 返回
200 `image/jpeg`，`POST /am/UI/Login` 返回 200/302 并给出真实鉴权头 `X-AuthErrorCode`。

于是拆开职责：浏览器只走 SSO 链并导出表单字段与 cookie；**登录那一次 POST 交给 requests**。

- 成功判据：响应头 `X-AuthErrorCode == "0"`（配合 302）
- 成功后把 requests 会话的 cookie 灌回浏览器，重走 SSO 收尾，从 `exchange-token`
  响应头取 `fighter-auth-token`
- 两个顺带结论：**账号密码明文提交即可**（页面那套 `strEnc` 是历史包袱，
  用了反而被判「用户名或密码错误」）；**会话提交失败即失效**，必须在同一会话外重走 SSO

## 改动范围

**纯新增，不改动任何既有文件**：

| 文件 | 说明 |
|---|---|
| `contrib/idm-waf-login-fix/README.md` | 根因 / 方案 / 实测 / 局限的完整说明 |
| `contrib/idm-waf-login-fix/reference/http_login.py` | 新增模块，复制为 `legacy/http_login.py` |
| `contrib/idm-waf-login-fix/patch/cli_http_login.patch` | 针对 `legacy/cli.py` 的接入补丁（加 import + `--http-login` 开关 + 分发，共 80 行，基线 `c8b96a9` 可干净应用） |
| `contrib/idm-waf-login-fix/optional/auto_checkin_task.py` | 可选：定时打卡 + 结果邮件通知的外层包装，与本方案无关 |

**既有行为完全不变**：人工手动输入（默认）、`--auto-login`、`token.txt` 复用、
`browser_login.py` 的任何逻辑，一行未动。三种登录模式并存，互不影响。

## 实测

在**本仓库当前基线 `c8b96a9`** 上，应用补丁 + 装载模块后，跑真实 CLI：

```
$ python login_and_checkin.py --http-login --login-only --force-login
[i] 纯 HTTP 客户端登录模式
[1] 访问 CAS 初始页...
[2] 跳转 uaaap CAS 选择页...
[3] 触发联邦认证 -> idm.swu.edu.cn ...
[4] 已到达 IDM 登录页

--- 登录尝试 #1 ---
[*] 用纯 HTTP 客户端提交登录（绕开 WAF）...
[OCR] 识别验证码: ####
[*] POST /am/UI/Login -> HTTP 302, X-AuthErrorCode=0
[OK] 认证通过（纯 HTTP 客户端提交，WAF 未拦）
[i] 已把 6 个 cookie 注入浏览器
[5] 重走 SSO 完成登录链路...
[OK] 响应头捕获 Token: ******
[4] 链路已放行, 当前: https://of.swu.edu.cn/#/appCenter
[OK] 登录成功
```

**尝试 #1 一次通过，零重试**；先后复跑共 4 次，均为一次通过。

## 关于「机器瞬填触发风控」

补充一条实测观察，供维护者判断：本次**未能复现"瞬填导致拒绝"**——用 JS 直接赋值
绕过全部键盘事件后，`form.submit()` 是真实发生的，只是被 WAF 拦在 400。
「瞬填触发风控」与「WAF 拦截 POST」可能是两个独立现象；本方案不需要对抗前者，
因为 requests 不渲染页面、不产生键盘事件。这一点请以维护者自身的线上观察为准。

## 局限

- 依赖 `ddddocr`，缺失时明确报错返回，不静默降级
- 站点若再改 WAF 策略或换验证码类型，需要重新探测
- 只解决**登录**；签到仍走仓库原有的真实坐标提交，**不涉及任何伪造定位**

## 脱敏

本目录全部内容已脱敏：无学号、密码、姓名、邮箱、SMTP 授权码、宿舍楼名、
经纬度坐标、Token 片段、主机名与绝对路径。两个 `.py` 均通过 `py_compile`。
