import os

# ============================== 默认配置 ==============================
DEFAULT_USERNAME = os.environ.get("SWU_USERNAME", "")
DEFAULT_PASSWORD = os.environ.get("SWU_PASSWORD", "")

# 签到表单相关 ID (若换签到, 需要同步修改)
DEFAULT_FORM_ID = "03acfcb3ccda4138bc017587f211cc30"
DEFAULT_CQFBID = "128c549bd26e4aa08b2dace3271b13f4"
DEFAULT_BUSINESS_KEY = "a49252033b2611f18ce10242ac130002"

# 默认签到位置 (来自 2026-07-08 手机钉钉查寝页面抓包)
DEFAULT_LAT = 29.816799
DEFAULT_LNG = 106.421665
DEFAULT_ADDRESS = "重庆市北碚区融汇南路8号靠近北碚区公安分局(西南大学综合服务大厅)"
DEFAULT_PROVINCE = "重庆市"
DEFAULT_CITY = "重庆市"
DEFAULT_DISTRICT = "北碚区"
DEFAULT_ROAD = "融汇南路"
DEFAULT_QSQDDD = "重庆市北碚区天生街道2号"
DEFAULT_QDBJ = "800米"
DEFAULT_QDSJ = ["21:00", "23:30"]

# Chrome 启动配置
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEBUG_PORT = 9222
USER_DATA_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "ChromeSwuLoginProfile")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(PROJECT_ROOT, "checkin_cache.json")
NETWORK_LOG_DIR = os.path.join(PROJECT_ROOT, "network_logs")
AUDIT_LOG_DIR = os.path.join(PROJECT_ROOT, "audit_logs")
BAIDA_URL_KEYWORDS = (
    "/gateway/",
    "exchange-token",
    "fighter-baida",
    "fighter-middle",
    "cqlc",
    "form-instance",
    "businessKey",
    "formId",
    "cqfbid",
)
BAIDAFORM_DISCOVERY_URLS = (
    "https://of.swu.edu.cn/baidaForm/#/index",
    "https://of.swu.edu.cn/baidaForm/#/",
    "https://of.swu.edu.cn/baidaForm/",
    "https://of.swu.edu.cn/#/appCenter",
    "https://of.swu.edu.cn/#/casLogin?from=%2Findex",
)
SIGNED_QDJG_VALUE = "1"
DEFAULT_SUBMIT_QDJG_VALUE = "0"
DEFAULT_SUBMIT_QDJG_TEXT = "未签到"
DEFAULT_SUCCESS_MSG_KEYWORD = "保存成功"

# 服务器保存成功后返回 qdjg=1；手机钉钉实际提交时仍发送 qdjg=0/$qdjg=未签到。
DEFAULT_CHECKIN_RESULT_VALUE = SIGNED_QDJG_VALUE
DEFAULT_CHECKIN_RESULT_TEXT = "已签到"

# 登录入口
SERVICE = (
    "https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate"
    "%2Fuaap%2Fcas%2Fresolve-cas-return%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn"
    "%252F%2523%252FcasLogin%253Ffrom%253D%25252FappCenter"
)
INIT_URL = f"https://of.swu.edu.cn/cas/login?service={SERVICE}"
FEDERAL_URL = f"https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL?service={SERVICE}"
BAIDAFORM_SERVICE = (
    "https%3A%2F%2Fof.swu.edu.cn%2Fgateway%2Ffighter-middle%2Fapi%2Fintegrate"
    "%2Fuaap%2Fcas%2Fresolve-cas-return%3Fnext%3Dhttps%253A%252F%252Fof.swu.edu.cn"
    "%252FbaidaForm%252F%2523%252FcasLogin%253Ffrom%253D%25252Findex"
)
BAIDAFORM_INIT_URL = f"https://of.swu.edu.cn/cas/login?service={BAIDAFORM_SERVICE}"
BAIDAFORM_FEDERAL_URL = (
    f"https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL?service={BAIDAFORM_SERVICE}"
)

CQTJ_TODAY_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqtj/getTransitionByToday"
FORM_INSTANCE_SELECT_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/select"
CQLC_BASE_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqlc"
FORM_INSTANCE_SAVE_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
DINGTALK_USER_AGENT = (
    "Mozilla/5.0 (Linux; U; Android 12; zh-CN; ALN-AL80 Build/HUAWEIALN-AL80) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/100.0.4896.58 "
    "UWS/5.12.11.0 Mobile Safari/537.36 AliApp(DingTalk/7.8.5.1) "
    "com.alibaba.android.rimet.diswu/PIS756181878951764992 "
    "Channel/exclusive_dingtalk_263387052 language/zh-CN 2ndType/exclusive abi/64 "
    "Hmos/4.2.0 xpn/huawei UT4Aplus/0.2.25 colorScheme/light"
)
DINGTALK_X_REQUESTED_WITH = "com.alibaba.android.rimet.diswu"

MAX_CAPTCHA_RETRY = 8
LOGIN_FAILURE_KEYWORDS = (
    "用户名或密码错误",
    "账号或密码错误",
    "验证失败",
    "帐户将被锁定",
    "账户将被锁定",
)


