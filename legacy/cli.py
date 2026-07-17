import argparse
import asyncio
import json
import sys
from datetime import datetime

from .config import *
from .browser_login import do_login
from .common import load_checkin_meta, make_audit_log_path, mask_secret, print_env_check
from .monitor import monitor_chrome_network
from .swu_api import do_checkin, fetch_user_info, sync_cqtj_checkin_meta

def parse_args():
    p = argparse.ArgumentParser(
        description="西南大学一键登录+签到",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # 环境/Chrome
    p.add_argument("--env-check", action="store_true", help="检查 Python/Chrome/依赖/端口环境后退出")
    p.add_argument("--debug-port", type=int, default=DEBUG_PORT, help="Chrome CDP 调试端口")
    p.add_argument("--chrome-exe", default=CHROME_EXE, help="chrome.exe 完整路径")
    p.add_argument("--user-data-dir", default=USER_DATA_DIR, help="Chrome 独立用户数据目录")
    p.add_argument("--keep-profile", action="store_true", help="保留 Chrome 独立用户目录, 不清理旧登录记录")
    p.add_argument("--monitor-chrome", action="store_true", help="连接外部 Chrome, 监听 fighter-baida 接口并缓存表单元数据")
    p.add_argument("--monitor-seconds", type=int, default=60, help="监听秒数, 0 表示持续监听直到 Ctrl+C")
    p.add_argument("--manual-login", action="store_true", help="监听模式下不自动填账号密码, 由用户手动登录操作")
    p.add_argument("--no-auto-probe", action="store_true", help="监听模式下不自动探测 baidaForm/appCenter 路由")
    p.add_argument("--open-url", default=BAIDAFORM_INIT_URL, help="监听模式启动后自动打开的页面 URL")
    p.add_argument("--sync-cqtj", action="store_true", help="只同步手机钉钉查寝任务元数据, 不提交签到")
    p.add_argument("--cqtj-checkin", action="store_true", help="先同步今日查寝任务, 再使用同步到的参数执行签到")
    p.add_argument("--force-submit", action="store_true", help="即使同步状态显示已签到也继续提交, 默认不建议使用")
    p.add_argument("--no-cache-meta", action="store_true", help="不读取 checkin_cache.json 中的表单元数据")
    p.add_argument("--audit-log", default=None, help="签到链路审计日志路径, 不填则自动生成")

    # 账号
    p.add_argument("--username", "-u", default=DEFAULT_USERNAME, help="登录账号")
    p.add_argument("--password", "-p", default=DEFAULT_PASSWORD, help="登录密码")
    p.add_argument("--xh", default=None, help="学号 (不填则从用户信息 API 自动获取)")

    # 位置
    p.add_argument("--lat", type=float, default=DEFAULT_LAT, help="签到纬度")
    p.add_argument("--lng", type=float, default=DEFAULT_LNG, help="签到经度")
    p.add_argument("--address", default=DEFAULT_ADDRESS, help="地址描述")
    p.add_argument("--province", default=DEFAULT_PROVINCE, help="省")
    p.add_argument("--city", default=DEFAULT_CITY, help="市")
    p.add_argument("--district", default=DEFAULT_DISTRICT, help="区/县")
    p.add_argument("--road", default=DEFAULT_ROAD, help="街道/路")
    p.add_argument("--qsqddd", default=None, help="签到点详细地址描述 (不填则优先读缓存, 再用内置默认值)")
    p.add_argument("--qdbj", default=None, help="签到半径, 如 500米 (不填则优先读缓存, 再用内置默认值)")
    p.add_argument(
        "--qdsj",
        default=None,
        help="签到时段, 逗号分隔, 如 21:00,23:30 (不填则优先读缓存, 再用内置默认值)",
    )

    # 表单 ID
    p.add_argument("--form-id", default=None, help="签到表单 FormID (不填则优先读缓存, 再用内置默认值)")
    p.add_argument("--cqfbid", default=None, help="CQFBID (不填则优先读缓存, 再用内置默认值)")
    p.add_argument("--business-key", default=None, help="BusinessKey (不填则优先读缓存, 再用内置默认值)")
    p.add_argument(
        "--submit-qdjg-value",
        default=DEFAULT_SUBMIT_QDJG_VALUE,
        help="提交给 form-instance/save 的 qdjg 值；手机钉钉成功抓包为 0",
    )
    p.add_argument(
        "--submit-qdjg-text",
        default=DEFAULT_SUBMIT_QDJG_TEXT,
        help="提交给 form-instance/save 的 $qdjg 文本；手机钉钉成功抓包为 未签到",
    )
    p.add_argument(
        "--success-qdjg-value",
        default=SIGNED_QDJG_VALUE,
        help="服务器保存成功后返回 data.qdjg 的成功值",
    )

    # 仅登录不签到
    p.add_argument("--login-only", action="store_true", help="只登录, 不签到")
    # 外部提供 token, 跳过登录
    p.add_argument("--token", default=None, help="已有 Token, 直接签到 (跳过登录)")

    return p.parse_args()


def main():
    args = parse_args()

    if args.env_check:
        print_env_check(args.debug_port, args.chrome_exe)
        return

    if args.monitor_chrome:
        try:
            asyncio.run(
                monitor_chrome_network(
                    debug_port=args.debug_port,
                    chrome_exe=args.chrome_exe,
                    user_data_dir=args.user_data_dir,
                    fresh_profile=not args.keep_profile,
                    monitor_seconds=args.monitor_seconds,
                    open_url=args.open_url,
                    username=args.username,
                    password=args.password,
                    xh=args.xh,
                    manual_login=args.manual_login,
                    auto_probe=not args.no_auto_probe,
                )
            )
        except KeyboardInterrupt:
            print("\n[i] 已停止监听")
        return

    # Step 1: 获取 Token
    if args.token:
        token = args.token
        print(f"[i] 使用外部提供的 Token: {mask_secret(token)}")
    else:
        if not args.username or not args.password:
            print("[!] 缺少登录账号或密码。请设置环境变量 SWU_USERNAME/SWU_PASSWORD，或使用 --username/--password。")
            sys.exit(1)
        print(f"[i] 开始登录, 账号: {args.username}")
        token = asyncio.run(
            do_login(
                args.username,
                args.password,
                chrome_exe=args.chrome_exe,
                debug_port=args.debug_port,
                user_data_dir=args.user_data_dir,
                fresh_profile=not args.keep_profile,
            )
        )
        if not token:
            print("\n[!] 登录失败, 未获取到 Token")
            sys.exit(1)
        # 保存到 token.txt 方便下次使用
        with open("token.txt", "w", encoding="utf-8") as f:
            f.write(token)
        print(f"\n[OK] 登录成功, Token: {mask_secret(token)} (已保存到 token.txt)")

    if args.login_only:
        print("[i] --login-only, 跳过签到")
        return

    # Step 2: 自动获取学号
    xh = args.xh
    if not xh:
        print("\n[i] 获取用户学号...")
        info = fetch_user_info(token)
        xh = info.get("username") or info.get("loginName") or ""
        if not xh:
            print("[!] 未能获取学号, 请用 --xh 手动指定")
            sys.exit(1)
        print(f"[i] 学号: {xh}, 姓名: {info.get('realname', '?')}")

    audit_log_path = args.audit_log or make_audit_log_path("cqtj" if (args.sync_cqtj or args.cqtj_checkin) else "checkin")
    synced_meta = None
    if args.sync_cqtj or args.cqtj_checkin:
        synced_meta = sync_cqtj_checkin_meta(
            token=token,
            xh=xh,
            username=args.username,
            audit_log_path=audit_log_path,
            save_cache=True,
        )
        if args.sync_cqtj and not args.cqtj_checkin:
            print("[i] --sync-cqtj 只同步任务元数据, 不提交签到")
            return
        if not synced_meta:
            print("[!] 未同步到今日查寝任务, 不执行提交")
            sys.exit(1)
        if synced_meta.get("is_signed") and not args.force_submit:
            print("[i] 同步结果显示任务已签到, 不重复提交；如需强制提交请加 --force-submit")
            return
        if synced_meta.get("task_date") and synced_meta.get("task_date") != datetime.now().strftime("%Y-%m-%d"):
            print(f"[!] 同步任务日期不是今天: {synced_meta.get('task_date')}, 不执行提交")
            sys.exit(1)
        task_text = json.dumps(synced_meta, ensure_ascii=False, default=str)
        if "查寝" not in task_text:
            print("[!] 同步任务未识别为查寝任务, 不执行提交")
            sys.exit(1)

    # Step 3: 签到
    cached_meta = synced_meta or (None if args.no_cache_meta else load_checkin_meta(args.username, xh))
    if cached_meta:
        print(
            "[i] 使用当天缓存的表单元数据: "
            f"form_id={cached_meta.get('form_id')}, "
            f"cqfbid={cached_meta.get('cqfbid')}, "
            f"business_key={cached_meta.get('business_key')}"
        )

    form_id = args.form_id or (cached_meta or {}).get("form_id") or DEFAULT_FORM_ID
    cqfbid = args.cqfbid or (cached_meta or {}).get("cqfbid") or DEFAULT_CQFBID
    business_key = args.business_key or (cached_meta or {}).get("business_key") or DEFAULT_BUSINESS_KEY
    dormitory_form_id = (cached_meta or {}).get("dormitory_form_id") if cached_meta else None
    qsqddd = args.qsqddd or (cached_meta or {}).get("qsqddd") or DEFAULT_QSQDDD
    qdbj = args.qdbj or (cached_meta or {}).get("qdbj") or DEFAULT_QDBJ
    qdsj_value = args.qdsj or (cached_meta or {}).get("qdsj") or DEFAULT_QDSJ

    if isinstance(qdsj_value, list):
        qdsj_list = [str(s).strip() for s in qdsj_value if str(s).strip()]
    else:
        qdsj_list = [s.strip() for s in str(qdsj_value).split(",") if s.strip()]
    ok = do_checkin(
        token=token,
        xh=xh,
        lat=args.lat,
        lng=args.lng,
        address=args.address,
        province=args.province,
        city=args.city,
        district=args.district,
        road=args.road,
        qsqddd=qsqddd,
        qdbj=qdbj,
        qdsj=qdsj_list,
        form_id=form_id,
        cqfbid=cqfbid,
        business_key=business_key,
        dormitory_form_id=dormitory_form_id,
        audit_log_path=audit_log_path,
        submit_qdjg_value=args.submit_qdjg_value,
        submit_qdjg_text=args.submit_qdjg_text,
        success_qdjg_value=args.success_qdjg_value,
    )

    print("\n" + "=" * 60)
    if ok:
        print("[OK] 签到成功!")
    else:
        print("[!] 签到失败")
    print("=" * 60)
