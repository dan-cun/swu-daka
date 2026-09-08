import { FormEvent, useEffect, useState } from "react";

import TermsConsentModal from "../components/TermsConsentModal";
import { apiGet, apiPost } from "../services/api";

const TERMS_STORAGE_KEY = "checkin_terms_agreed_at";

function readStoredAgreement(): boolean {
  try {
    return Boolean(window.localStorage.getItem(TERMS_STORAGE_KEY));
  } catch {
    return false;
  }
}

type CheckinRunResponse = {
  status: string;
  detail: string;
  audit_log_path?: string | null;
  log_tail: string[];
};

type AutoCheckinStatusResponse = {
  enabled: boolean;
  status: string;
  detail: string;
  schedule_time: string;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_result?: CheckinRunResponse | null;
};

export default function CheckinPage() {
  const [schoolAccount, setSchoolAccount] = useState("");
  const [schoolPassword, setSchoolPassword] = useState("");
  const [isTermsOpen, setIsTermsOpen] = useState(false);
  const [hasAgreed, setHasAgreed] = useState(readStoredAgreement);
  const [message, setMessage] = useState("");
  const [logTail, setLogTail] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isScheduling, setIsScheduling] = useState(false);
  const [autoStatus, setAutoStatus] = useState<AutoCheckinStatusResponse | null>(null);

  useEffect(() => {
    apiGet<AutoCheckinStatusResponse>("/api/checkin/auto")
      .then((result) => setAutoStatus(result))
      .catch(() => {
        // Status is best-effort; check-in actions still report their own errors.
      });
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasAgreed) {
      setIsTermsOpen(true);
      return;
    }
    setIsSubmitting(true);
    setLogTail([]);
    setMessage("正在打卡，请等待登录、同步任务和定位校验完成...");
    try {
      const result = await apiPost<CheckinRunResponse>("/api/checkin/runs", {
        school_username: schoolAccount,
        school_password: schoolPassword,
      });
      setMessage(result.detail);
      setLogTail(result.log_tail ?? []);
    } catch {
      setMessage("打卡请求失败，请确认后端已启动并查看后端日志");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function enableAutoCheckin() {
    if (!hasAgreed) {
      setIsTermsOpen(true);
      return;
    }
    setIsScheduling(true);
    setMessage("正在开启每日 21:00 自动打卡...");
    try {
      const result = await apiPost<AutoCheckinStatusResponse>("/api/checkin/auto", {
        school_username: schoolAccount,
        school_password: schoolPassword,
      });
      setAutoStatus(result);
      setMessage(result.next_run_at ? `${result.detail}，下次执行：${result.next_run_at}` : result.detail);
    } catch {
      setMessage("自动打卡开启失败，请确认后端已启动并查看后端日志");
    } finally {
      setIsScheduling(false);
    }
  }

  function rememberAgreement(agreedAt: string) {
    try {
      window.localStorage.setItem(TERMS_STORAGE_KEY, agreedAt);
    } catch {
      // Local persistence is best-effort; the current page state still records consent.
    }
    setHasAgreed(true);
    setIsTermsOpen(false);
  }

  return (
    <main className="checkin-shell">
      <form className="checkin-form" onSubmit={submit}>
        <label className="field-label" htmlFor="school-account">
          校园网账号
        </label>
        <input
          id="school-account"
          className="line-input"
          value={schoolAccount}
          onChange={(event) => setSchoolAccount(event.target.value)}
          autoComplete="username"
        />

        <label className="field-label" htmlFor="school-password">
          校园网密码
        </label>
        <input
          id="school-password"
          className="line-input"
          type="password"
          value={schoolPassword}
          onChange={(event) => setSchoolPassword(event.target.value)}
          autoComplete="current-password"
        />

        <a className="terms-link" href="/terms">
          用户须知
        </a>
        <div className="terms-actions">
          <button className="agree-button" type="button" onClick={() => setIsTermsOpen(true)}>
            {hasAgreed ? "已同意" : "同意"}
          </button>
          <button
            className="auto-checkin-button"
            type="button"
            disabled={!schoolAccount || !schoolPassword || !hasAgreed || isSubmitting || isScheduling}
            onClick={enableAutoCheckin}
          >
            {isScheduling ? "开启中..." : autoStatus?.enabled ? "自动打卡已开" : "自动打卡"}
          </button>
        </div>

        <button className="checkin-button" type="submit" disabled={!schoolAccount || !schoolPassword || isSubmitting}>
          {isSubmitting ? "打卡中..." : "打卡"}
        </button>

        {message ? <p className="status-text">{message}</p> : null}
        {logTail.length ? (
          <pre className="log-tail">
            {logTail.join("\n")}
          </pre>
        ) : null}
      </form>

      {isTermsOpen ? (
        <TermsConsentModal
          onAgreed={(result) => rememberAgreement(result.agreedAt)}
          onClose={() => setIsTermsOpen(false)}
        />
      ) : null}
    </main>
  );
}
