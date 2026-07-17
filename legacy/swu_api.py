import json
import time
from datetime import datetime

from .config import *
from .common import (
    append_audit_log,
    complete_meta,
    response_to_audit,
    save_checkin_meta,
)
from .common import require_requests as _require_requests

requests = None

def require_requests():
    global requests
    requests = _require_requests()
    return requests

def fetch_user_info(token: str) -> dict:
    """获取用户信息 (含学号/真实姓名)."""
    require_requests()
    r = requests.get(
        "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user",
        params={"appType": "fighter-portal"},
        headers={
            "Accept": "application/json, text/plain, */*",
            "fighter-auth-token": token,
            "Referer": "https://of.swu.edu.cn/",
        },
        timeout=15,
    )
    try:
        return r.json().get("data", {}).get("subject", {})
    except Exception:
        return {}


def make_baida_headers(token: str, json_content: bool = True) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "fighter-auth-token": token,
        "User-Agent": DINGTALK_USER_AGENT,
        "Origin": "https://of.swu.edu.cn",
        "X-Requested-With": DINGTALK_X_REQUESTED_WITH,
        "Referer": "https://of.swu.edu.cn/baidaForm/",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cookie": f"SESSION=SESSION; access_token={token}",
    }
    if json_content:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


def extract_dormitory_fields(dormitory_response: dict) -> dict:
    data = dormitory_response.get("data") if isinstance(dormitory_response, dict) else {}
    column_list = data.get("columnList") if isinstance(data, dict) else []
    result = {}
    for item in column_list or []:
        if not isinstance(item, dict):
            continue
        prop = item.get("prop")
        if prop == "qsqddd" and item.get("value"):
            result["qsqddd"] = item.get("value")
        elif prop == "qdbj" and item.get("value"):
            result["qdbj"] = item.get("value")
        if item.get("address") and not result.get("qsqddd"):
            result["qsqddd"] = item.get("address")
        if item.get("qdbj") and not result.get("qdbj"):
            result["qdbj"] = f"{item.get('qdbj')}米"
        if item.get("latitude"):
            result["dorm_latitude"] = item.get("latitude")
        if item.get("longitude"):
            result["dorm_longitude"] = item.get("longitude")
    return result


def sync_cqtj_checkin_meta(
    token: str,
    xh: str | None = None,
    username: str | None = None,
    audit_log_path: str | None = None,
    save_cache: bool = True,
) -> dict | None:
    """从手机钉钉查寝链路同步当天任务元数据, 不提交签到."""
    require_requests()
    today = datetime.now().strftime("%Y-%m-%d")
    dksj_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    headers = make_baida_headers(token, json_content=False)

    print("[i] 同步今日查寝任务: cqtj/getTransitionByToday")
    r1 = requests.post(
        CQTJ_TODAY_URL,
        headers=headers,
        files={"pageNum": (None, "1"), "pageSize": (None, "5")},
        timeout=20,
    )
    try:
        d1 = r1.json()
    except Exception:
        d1 = {}
    append_audit_log(
        audit_log_path,
        "cqtj_getTransitionByToday",
        response_to_audit(r1, d1),
    )

    records = (((d1.get("data") or {}).get("records")) or []) if isinstance(d1, dict) else []
    if d1.get("code") != 200:
        print(f"[!] 今日查寝任务查询失败: {d1.get('msg') or r1.text[:300]}")
        return None
    if not records:
        print("[i] 今日查寝任务为空")
        return None

    def score_record(record: dict) -> int:
        raw = json.dumps(record, ensure_ascii=False, default=str)
        score = 0
        score += 5 if record.get("tsrq") == today else 0
        score += 4 if "查寝" in raw else 0
        score += 3 if record.get("qdzt") == "进行中" else 0
        score += 2 if record.get("formId") else 0
        score += 2 if record.get("id") else 0
        return score

    task = sorted([r for r in records if isinstance(r, dict)], key=score_record, reverse=True)[0]
    form_id = task.get("formId") or DEFAULT_FORM_ID
    business_key = task.get("id")
    task_title = task.get("cqzmc") or task.get("title") or task.get("name") or ""
    task_status = task.get("qdzt") or ""
    task_date = task.get("tsrq") or today
    if not business_key:
        print("[!] 今日任务缺少 id/businessKey, 无法继续")
        return None

    print(
        "[i] 今日任务: "
        f"title={task_title or '-'}, status={task_status or '-'}, "
        f"date={task_date}, business_key={business_key}"
    )

    select_headers = make_baida_headers(token, json_content=False)
    r2 = requests.get(
        FORM_INSTANCE_SELECT_URL,
        headers=select_headers,
        params={"dataId": business_key, "formId": form_id, "procDefId": ""},
        timeout=20,
    )
    try:
        d2 = r2.json()
    except Exception:
        d2 = {}
    append_audit_log(
        audit_log_path,
        "form_instance_select",
        response_to_audit(r2, d2),
    )
    selected = d2.get("data") if isinstance(d2.get("data"), dict) else {}
    cqfbid = selected.get("cqfbid") or DEFAULT_CQFBID
    qdsj = selected.get("qdsj") or [
        task.get("qdkssj") or DEFAULT_QDSJ[0],
        task.get("qdjssj") or DEFAULT_QDSJ[1],
    ]
    selected_xh = selected.get("xh") or xh
    qdjg = str(selected.get("qdjg", ""))
    is_signed = qdjg == DEFAULT_CHECKIN_RESULT_VALUE

    dormitory_payload = {
        "formId": selected.get("formId", ""),
        "isArchive": selected.get("isArchive", ""),
        "qdjg": selected.get("qdjg", "0"),
        "tsrq": selected.get("tsrq") or task_date,
        "qsqddd": selected.get("qsqddd", ""),
        "qdbj": selected.get("qdbj", ""),
        "xh": selected_xh or "",
        "dksj": selected.get("dksj") or dksj_str,
        "selectMap": selected.get("selectMap", ""),
        "ycdksfcl": selected.get("ycdksfcl", ""),
        "id": business_key,
        "cqfbid": cqfbid,
        "qdtj": selected.get("qdtj", "1"),
        "qddz": selected.get("qddz", ""),
        "qdsj": qdsj,
    }
    r3 = requests.post(
        f"{CQLC_BASE_URL}/getDormitory",
        headers=make_baida_headers(token, json_content=True),
        json=dormitory_payload,
        timeout=20,
    )
    try:
        d3 = r3.json()
    except Exception:
        d3 = {}
    append_audit_log(
        audit_log_path,
        "cqlc_getDormitory_for_sync",
        {
            "request": {"url": f"{CQLC_BASE_URL}/getDormitory", "payload": dormitory_payload},
            "response": response_to_audit(r3, d3),
        },
    )

    dormitory_fields = extract_dormitory_fields(d3)
    meta = {
        "source": "cqtj",
        "form_id": form_id,
        "cqfbid": cqfbid,
        "business_key": business_key,
        "dormitory_form_id": selected.get("formId", ""),
        "qdsj": qdsj,
        "qsqddd": dormitory_fields.get("qsqddd") or selected.get("qsqddd") or DEFAULT_QSQDDD,
        "qdbj": dormitory_fields.get("qdbj") or selected.get("qdbj") or DEFAULT_QDBJ,
        "title": task_title,
        "task_status": task_status,
        "task_date": task_date,
        "qdjg": qdjg,
        "is_signed": is_signed,
        "xh": selected_xh,
        "dorm_latitude": dormitory_fields.get("dorm_latitude"),
        "dorm_longitude": dormitory_fields.get("dorm_longitude"),
    }
    append_audit_log(audit_log_path, "cqtj_synced_meta", meta)

    print(
        "[OK] 已同步查寝任务元数据: "
        f"form_id={meta['form_id']}, cqfbid={meta['cqfbid']}, "
        f"business_key={meta['business_key']}, qdjg={meta['qdjg'] or '-'}"
    )
    print(f"[i] 签到地点: {meta['qsqddd']}, 半径: {meta['qdbj']}, 时段: {meta['qdsj']}")
    if is_signed:
        print("[i] 当前任务状态显示为已签到, 默认不重复提交")

    if save_cache and complete_meta(meta):
        save_checkin_meta(meta, username=username, xh=selected_xh or xh)
    return meta


def do_checkin(
    token: str,
    xh: str,
    lat: float,
    lng: float,
    address: str,
    province: str,
    city: str,
    district: str,
    road: str,
    qsqddd: str,
    qdbj: str,
    qdsj: list,
    form_id: str,
    cqfbid: str,
    business_key: str,
    dormitory_form_id: str | None = None,
    audit_log_path: str | None = None,
    submit_qdjg_value: str = DEFAULT_SUBMIT_QDJG_VALUE,
    submit_qdjg_text: str = DEFAULT_SUBMIT_QDJG_TEXT,
    success_qdjg_value: str = SIGNED_QDJG_VALUE,
) -> bool:
    """执行签到流程. 返回是否成功."""
    require_requests()
    base = CQLC_BASE_URL
    now = datetime.now()
    ts_ms = int(time.time() * 1000)
    date_str = now.strftime("%Y-%m-%d")
    dksj_str = now.strftime("%Y-%m-%d %H:%M")

    headers = make_baida_headers(token, json_content=True)
    dormitory_form_id_value = form_id if dormitory_form_id is None else dormitory_form_id

    map_data = {
        "errorCode": 0,
        "errorMessage": "",
        "locationType": 5,
        "accuracy": 56,
        "latitude": lat,
        "longitude": lng,
        "province": province,
        "city": city,
        "district": district,
        "road": road,
        "address": address,
        "netType": "wifi",
        "operatorType": "CUCC",
        "imei": "imei",
        "time": ts_ms,
        "provider": "lbs",
        "isFromMock": False,
        "isGpsEnabled": True,
        "isWifiEnabled": True,
        "isMobileEnabled": True,
        "isOffset": True,
        "cityAdCode": "023",
        "districtAdCode": "500109",
        "LBSWuaCacheId": str(int(time.time() * 1000))[-10:],
    }

    if audit_log_path:
        print(f"[i] 审计日志: {audit_log_path}")
    append_audit_log(
        audit_log_path,
        "checkin_start",
        {
            "xh": xh,
            "form_id": form_id,
            "cqfbid": cqfbid,
            "business_key": business_key,
            "dormitory_form_id": dormitory_form_id_value,
            "date_str": date_str,
            "dksj_str": dksj_str,
            "qdsj": qdsj,
            "qsqddd": qsqddd,
            "qdbj": qdbj,
            "submit_qdjg_value": submit_qdjg_value,
            "submit_qdjg_text": submit_qdjg_text,
            "success_qdjg_value": success_qdjg_value,
            "map_data": map_data,
        },
    )

    def show(name, resp):
        print(f"\n{'='*40}\n[{name}] Status: {resp.status_code}")
        try:
            data = resp.json()
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return data
        except Exception:
            print(resp.text)
            return {}

    # Step 1: getDormitory
    get_dormitory_payload = {
        "formId": dormitory_form_id_value,
        "isArchive": "",
        "qdjg": "0",
        "tsrq": date_str,
        "qsqddd": qsqddd,
        "qdbj": qdbj,
        "xh": xh,
        "dksj": dksj_str,
        "selectMap": json.dumps(
            {"$qdjg": "未签到", "$qddz": address}, ensure_ascii=False
        ),
        "ycdksfcl": "",
        "id": business_key,
        "cqfbid": cqfbid,
        "qdtj": "1",
        "qddz": map_data,
        "qdsj": qdsj,
    }
    append_audit_log(
        audit_log_path,
        "request_getDormitory",
        {"url": f"{base}/getDormitory", "payload": get_dormitory_payload},
    )
    r1 = requests.post(
        f"{base}/getDormitory",
        headers=headers,
        json=get_dormitory_payload,
    )
    d1 = show("getDormitory", r1)
    append_audit_log(audit_log_path, "response_getDormitory", response_to_audit(r1, d1))

    # Step 2: verify
    verify_payload = {"mapData": map_data}
    append_audit_log(
        audit_log_path,
        "request_verify",
        {
            "url": f"{base}/verify",
            "params": {"businessKey": business_key},
            "payload": verify_payload,
        },
    )
    r2 = requests.post(
        f"{base}/verify",
        headers=headers,
        params={"businessKey": business_key},
        json=verify_payload,
    )
    d2 = show("verify", r2)
    append_audit_log(audit_log_path, "response_verify", response_to_audit(r2, d2))

    is_area = d2.get("data", {}).get("isArea", False)
    tip = d2.get("data", {}).get("tip", "")
    print(f"\n定位结果: {tip}")
    if not is_area:
        print("[!] 不在签到范围内，签到中止")
        return False
    print("[OK] 在签到范围内，继续提交...")

    # Step 3: form-instance/save
    map_area = {**map_data, "isArea": True, "tip": "当前在签到范围内"}
    save_payload = {
        "id": business_key,
        "qdjg": submit_qdjg_value,
        "$qdjg": submit_qdjg_text,
        "cqfbid": cqfbid,
        "formId": form_id,
        "qdtj": "1",
        "tsrq": date_str,
        "ycdksfcl": "",
        "isArchive": "",
        "xh": xh,
        "dksj": dksj_str,
        "qdsj": qdsj,
        "qsqddd": qsqddd,
        "qdbj": qdbj,
        "qddz": map_area,
        "businessKey": business_key,
    }
    append_audit_log(
        audit_log_path,
        "pre_submit_snapshot",
        {
            "getDormitory_response": d1,
            "verify_response": d2,
            "save_payload": save_payload,
        },
    )
    append_audit_log(
        audit_log_path,
        "request_form_instance_save",
        {
            "url": FORM_INSTANCE_SAVE_URL,
            "params": {"formId": form_id, "isSubmitProcess": "false"},
            "payload": save_payload,
        },
    )
    r3 = requests.post(
        FORM_INSTANCE_SAVE_URL,
        headers=headers,
        params={"formId": form_id, "isSubmitProcess": "false"},
        json=save_payload,
    )
    d3 = show("form-instance/save", r3)
    append_audit_log(audit_log_path, "response_form_instance_save", response_to_audit(r3, d3))

    saved_data = d3.get("data") if isinstance(d3.get("data"), dict) else {}
    saved_text = saved_data.get("$qdjg", "")
    saved_value = str(saved_data.get("qdjg", ""))
    server_msg = str(d3.get("msg") or "")
    http_ok = r3.status_code == 200 and d3.get("code") == 200
    local_success = (
        http_ok
        and (
            saved_value == str(success_qdjg_value)
            or DEFAULT_SUCCESS_MSG_KEYWORD in server_msg
        )
    )
    append_audit_log(
        audit_log_path,
        "local_result",
        {
            "success": local_success,
            "submit_qdjg": submit_qdjg_value,
            "submit_qdjg_text": submit_qdjg_text,
            "expected_success_qdjg": success_qdjg_value,
            "saved_qdjg": saved_value,
            "saved_qdjg_text": saved_text,
            "server_msg": server_msg,
        },
    )
    if d3.get("code") == 200 and not local_success:
        print(
            "[!] 接口返回 code=200, 但未识别为签到成功: "
            f"qdjg={saved_value}, $qdjg={saved_text}, msg={server_msg}"
        )
    return local_success

