# idm 登录「瑞数 WAF」根因定位与纯 HTTP 客户端绕行方案

> 本目录是**纯新增内容**，不修改仓库里任何既有文件。
> 接入方式见「四、如何接入」——只需复制一个文件 + 打一个 80 行的小补丁。

---

## 一、问题现象

在 `idm.swu.edu.cn` 登录页做自动化时，会出现一条**看起来像「验证码识别不准」的死循环**：

```
[OCR] 识别验证码: 8268
[!] 验证码校验失败, 刷新重试
[OCR] 识别验证码: 看不清，换一张        ← 变成占位文字
[!] 验证码长度异常 (got 7), 刷新重试
[OCR] 识别验证码: 看不清，换一张
...                                      ← 刷到重试上限
```

伴随两个特征：

1. **验证码图片"裂图"**，OCR 读到的其实是「看不清，换一张」这行占位文字（7 个字符）。
2. 即使验证码**肉眼可见是输对的**，点登录后页面也只是**换一张图**，从不真正提交。

因为现象高度像"OCR 不准"，很容易被误判为识别问题或"脚本填太快触发风控"，
从而走上「换 OCR 引擎 / 加拟人输入 / 改成人工手动输入」的方向——**但都治不到根上**。

---

## 二、根因定位

### 结论

`idm.swu.edu.cn` 前面挂了一层**瑞数（RiverSecurity）类动态 WAF**。它会给页面内
`fetch`/XHR 的 URL 自动补一个动态令牌（形如 `?ZUY2FAwZ=...`），**但同时会把
「浏览器内一切带 body 的 POST 到 `/am/`」直接拦成 HTTP 400**，响应体只有
`\r\n\r\n\r\n`（即一个空白页）。

被拦的请求包括：

| 请求 | 发起方 | 结果 |
|---|---|---|
| `POST /am/validatecode/verify.do` | 页面自己的验证码预校验 | **400** |
| `POST /am/UI/Login` | `form.submit()` / 页面内 `fetch` | **400** |
| `GET /am/validate.code`（补了令牌） | 页面内 fetch | 200 |

### 连锁反应（死循环的真正成因）

1. 键盘输入第 4 位验证码 → `onkeyup` → `verifyCode()` → `verify.do` 被 WAF 打成 **400**
2. 页面 error 分支把全局 `state` 置为 **false**
3. 点登录 → `portalLogin()` 开头就是
   `if (state == false) { poplert(...); getKaptcha(); return; }`
   → **只换图，永不提交**
4. `getKaptcha()` 的换图请求同样被 **400** → 图片裂成「看不清，换一张」占位
5. 脚本据此判定"验证码错误" → 再刷新 → 回到第 3 步，**死循环**

### 已验证的排除项

| 假设 | 实测结果 |
|---|---|
| HTTP/2 导致 | ❌ `--disable-http2 --disable-quic` 下 `nextHopProtocol: http/1.1`，POST 仍 400 |
| 脚本填得太快触发风控 | ❌ 用 JS 直接赋值（不触发任何键盘事件）绕过 `onkeyup` 后，`portalLogin()` **确实走到了 `form.submit()`**，`POST /am/UI/Login` 依然 400 |
| 动态令牌无效 | ❌ 同会话内 `GET /am/cloudSign/getMssgValid.do?ZUY2FAwZ=...` 返回 **200**，令牌有效 |
| 验证码识别不准 | ❌ 用纯 HTTP 客户端拉图，OCR 稳定读出 4 位数字 |

**关键判断：问题不在"脚本怎么填"，而在"浏览器发出的 POST 根本到不了服务端"。**

---

## 三、解决方案

突破口：**纯 HTTP 客户端（`requests`）不被这层 WAF 拦截。**

| 请求（由 requests 发出） | 结果 |
|---|---|
| `GET  https://idm.swu.edu.cn/am/validate.code` | 200 `image/jpeg`（约 2KB，OCR 可读准 4 位） |
| `POST https://idm.swu.edu.cn/am/UI/Login` | **200/302**，响应头给出真实鉴权结果 `X-AuthErrorCode` |

于是把职责拆开：

```
浏览器   : 只负责走 SSO 链路（CAS → uaaap → 联邦认证）与持有会话、导出表单字段
requests : 只负责「取验证码 + 提交账号密码」这一步
```

完整流程：

1. 浏览器走 SSO 链到 `idm.swu.edu.cn/am/UI/Login`，导出 `document.forms['Login']`
   的全部隐藏字段（`goto` / `encoded` / `SunQueryParamsString` 等，**必须实时取，不能硬编码**）
   与当前会话 cookie
2. `requests` 带同一份 cookie：`GET /am/validate.code` → ddddocr 识别 → **明文**
   提交 `POST /am/UI/Login`
3. 成功判据：响应头 **`X-AuthErrorCode == "0"`**（配合 HTTP 302）
4. 把 requests 会话拿到的 cookie 灌回浏览器（domain=`.swu.edu.cn`），
   再走一遍 SSO 收尾
5. 从 `exchange-token` 响应头捕获 `fighter-auth-token`

### 两个顺带确认的重要事实

- **账号密码明文提交即可**，页面那套 `strEnc` 加密是历史包袱。
  用 `strEnc` 提交反而会被服务端判「用户名或密码错误」，**让人误以为密码错了**。
- 会话一旦提交失败即失效，**同一会话内重试没有意义**，必须重走 SSO 换新会话
  （所以 `http_submit_login()` 只在"验证码没识别出来、根本没发出 POST"时才原地重试）。

---

## 四、如何接入

三处改动，全部是"旁路接入"，不触碰既有登录逻辑：

### 1. 复制模块

```bash
cp contrib/idm-waf-login-fix/reference/http_login.py legacy/http_login.py
```

### 2. 打 CLI 补丁

```bash
git apply contrib/idm-waf-login-fix/patch/cli_http_login.patch
```

补丁只做三件事：加一行 import、加一个 `--http-login` 开关、在 `main()` 里按开关分发。
`--auto-login` / 人工手动输入 / `token.txt` 复用等既有行为**完全不变**。

### 3. 运行

```bash
python login_and_checkin.py --http-login --cqtj-checkin
```

| 模式 | 行为 |
|---|---|
| 默认（不加参数） | 人工手动输入（维持现状） |
| `--auto-login` | 机器拟人逐字输入 + OCR |
| **`--http-login`** | **纯 HTTP 客户端提交，全自动、无需人工介入** |

三种模式可以并存，互不影响。

---

## 五、实测结果

### 本次实测（基线 `c8b96a9`，集成跑真实 CLI）

```
[i] 纯 HTTP 客户端登录模式, 账号: 2***********2
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

**尝试 #1 一次通过，零重试。** 在另一时间点先后复跑 4 次，同样都是尝试 #1 一次通过。

### 与「现象」的对照

|  | 现象 | 本方案 |
|---|---|---|
| 验证码图片 | 频繁裂图成「看不清，换一张」 | 由 requests 直连取图，稳定 200 |
| 登录提交 | 只有换图，从不提交 | `POST /am/UI/Login` 返回 302 / `X-AuthErrorCode=0` |
| 重试 | 死循环到上限 | 0 次重试 |

---

## 六、与仓库近期改动的定位关系（重要）

仓库在 `af5ad05` / `ba4e7b4` / `c8b96a9` 三个提交里，围绕**同一个登录页**做了
「修复验证码死循环 → 拟人逐字输入 → 默认改为人工手动输入」的演进。本方案与它们的关系：

- **不冲突**：本方案是**旁路新增**，`browser_login.py` 一行未改；
  人工手动输入（默认）、`--auto-login`、`token.txt` 复用全部保留。
- **不重复**：那三个提交解决的是"在浏览器里怎么填才能不被拒"；
  本方案指出的是"**浏览器发出的 POST 会被 WAF 打成 400，怎么填都到不了服务端**"，
  并给出绕过该层的办法。
- **可互补**：如果 `--http-login` 因为任何原因不可用（比如站点改版），
  回落到人工手动输入即可——两者共用同一套 SSO 链路代码，切换成本为零。

关于「机器瞬填触发风控」这一判断：本次实测**未能复现"瞬填导致拒绝"**——
用 JS 直接赋值绕过全部键盘事件后，`form.submit()` 是真实发生的，
只是被 WAF 拦在 400。所以"瞬填触发风控"与"WAF 拦截 POST"是两个独立的现象，
前者可能是真的（本方案没有去验证它），但**本方案不需要对抗它**：
requests 根本不渲染页面、不产生键盘事件。

---

## 七、局限与注意事项

1. **依赖 `ddddocr`**。未安装时本模式直接返回失败并提示，不会静默降级。
2. **站点改版可能失效**。若 WAF 策略变化（例如开始校验 `Origin`/`Referer` 之外的
   指纹）或换验证码类型，需要重新探测。核心探测手段见 `http_login.py` 顶部注释。
3. **只在 Windows + Chrome + CDP 9222 下实测**，与仓库既有环境假设一致。
4. **首次运行会清理 Chrome 独立用户目录**（沿用仓库既有行为，可用 `--keep-profile` 关闭）。
5. **不适用于绕过定位**。本方案只解决**登录**环节，签到仍然使用仓库原有的
   真实坐标提交逻辑，不涉及任何伪造定位。

---

## 八、脱敏说明

本目录全部内容已脱敏，**不含**任何：

- 学号 / 账号（示例一律写作 `2***********2`）
- 密码、SMTP 授权码
- 真实姓名、QQ 邮箱地址
- 宿舍楼名、经纬度坐标、街道地址
- 验证码识别结果、Token 片段（写作 `####` / `******`）
- 本机主机名、绝对路径、运行日志原文

`reference/http_login.py` 与 `optional/auto_checkin_task.py` 均通过 `py_compile`。

---

## 九、目录说明

| 文件 | 作用 |
|---|---|
| `README.md` | 本文档 |
| `PULL_REQUEST.md` | 可直接粘贴的 PR 标题与正文 |
| `reference/http_login.py` | 新增模块，复制为 `legacy/http_login.py` 即可 |
| `patch/cli_http_login.patch` | 针对 `legacy/cli.py` 的接入补丁（基线 `c8b96a9`，可干净应用） |
| `optional/auto_checkin_task.py` | 可选：定时打卡 + 结果邮件通知的外层包装脚本，与本方案无关，按需取用 |
