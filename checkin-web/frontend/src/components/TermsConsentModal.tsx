import { useEffect, useState } from "react";

import { apiPost } from "../services/api";

type TermsAgreementResponse = {
  user_id: number;
  has_agreed_terms: boolean;
  agreed_at: string;
};

export type TermsAgreementResult = {
  agreedAt: string;
  persistedToBackend: boolean;
  userId?: number;
};

type TermsConsentModalProps = {
  userId?: number;
  countdownSeconds?: number;
  termsHref?: string;
  onAgreed: (result: TermsAgreementResult) => void;
  onClose: () => void;
};

export default function TermsConsentModal({
  userId,
  countdownSeconds = 5,
  termsHref = "/terms",
  onAgreed,
  onClose,
}: TermsConsentModalProps) {
  const [secondsLeft, setSecondsLeft] = useState(countdownSeconds);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (secondsLeft <= 0) {
      return;
    }
    const timer = window.setTimeout(() => setSecondsLeft((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [secondsLeft]);

  async function agree() {
    if (secondsLeft > 0 || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setError("");
    try {
      let agreedAt = new Date().toISOString();
      let persistedToBackend = false;

      if (userId !== undefined) {
        const response = await apiPost<TermsAgreementResponse>(`/api/users/${userId}/terms/agree`);
        agreedAt = response.agreed_at;
        persistedToBackend = response.has_agreed_terms;
      }

      onAgreed({ agreedAt, persistedToBackend, userId });
    } catch {
      setError("同意记录写入失败，请确认后端已启动后重试");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <div className="terms-modal" role="dialog" aria-modal="true" aria-labelledby="terms-title">
        <button className="modal-close" type="button" aria-label="关闭" onClick={onClose}>
          ×
        </button>
        <h2 id="terms-title">风险提示</h2>
        <p className="risk-text">
          本系统为非官方辅助工具，不保证 100% 打卡成功率。每次打卡后请自行前往钉钉端或官方系统复核最终状态。
        </p>
        <p>
          账号、密码、数据库和日志均属于敏感信息。未完成正式加密前，不应在公开环境或多人共用设备中保存真实凭据。
        </p>
        <a className="modal-terms-link" href={termsHref} target="_blank" rel="noreferrer">
          查看完整用户须知
        </a>
        {error ? <p className="modal-error">{error}</p> : null}
        <button className="modal-agree" type="button" disabled={secondsLeft > 0 || isSubmitting} onClick={agree}>
          {isSubmitting ? "记录中..." : secondsLeft > 0 ? `请阅读 ${secondsLeft}s` : "我已阅读并同意"}
        </button>
      </div>
    </div>
  );
}
