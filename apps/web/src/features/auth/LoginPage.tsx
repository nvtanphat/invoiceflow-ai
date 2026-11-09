import React, { useState } from "react";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { Icon } from "../../components/SvgIcons";

export const LoginPage: React.FC = () => {
  const { login } = useInvoiceFlow();
  const [email, setEmail] = useState("accountant@invoiceflow.vn");
  const [password, setPassword] = useState("DemoPassword@123");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e?: React.FormEvent, customEmail?: string) => {
    if (e) e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      await login(customEmail || email, password);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại.");
    } finally {
      setIsLoading(false);
    }
  };

  const demoAccounts = [
    { role: "accountant", label: "Kế toán viên", email: "accountant@invoiceflow.vn" },
    { role: "reviewer", label: "Kiểm soát viên", email: "reviewer@invoiceflow.vn" },
    { role: "admin", label: "Quản trị viên", email: "admin@invoiceflow.vn" },
    { role: "viewer", label: "Giám đốc duyệt", email: "viewer@invoiceflow.vn" },
  ];

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
      }}
    >
      <div
        className="cd"
        style={{
          width: "440px",
          padding: "32px 36px",
          borderRadius: "16px",
          boxShadow: "0 12px 36px rgba(15,27,61,.12)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "24px" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "8px",
            }}
          >
            <svg width="42" height="30" viewBox="0 0 52 36" aria-hidden="true">
              <defs>
                <linearGradient id="login-grad" x1="0" y1="1" x2="1" y2="0">
                  <stop offset="0" stopColor="#1b3fb8" />
                  <stop offset="1" stopColor="#2f8cff" />
                </linearGradient>
              </defs>
              <path d="M3 34 15 4h9L12 34Z" fill="url(#login-grad)" />
              <path
                d="M20 34 32 4h18l-3 7.5H37.5l-1.8 4.5H46l-3 7.5H32.7L29 34Z"
                fill="url(#login-grad)"
              />
            </svg>
            <span style={{ fontSize: "22px", fontWeight: 800, color: "var(--navy)" }}>
              InvoiceFlow <b style={{ color: "var(--blue)" }}>AI</b>
            </span>
          </div>
          <div style={{ fontSize: "13px", color: "var(--muted)", fontWeight: 500 }}>
            Hệ thống Document AI cho Kế toán & Tài chính Doanh nghiệp
          </div>
        </div>

        {error && (
          <div
            style={{
              padding: "10px 14px",
              background: "#fde8e8",
              color: "#c02a2a",
              borderRadius: "8px",
              fontSize: "12.5px",
              marginBottom: "16px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Icon name="alert" style={{ width: "16px", height: "16px" }} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={(e) => handleSubmit(e)}>
          <div style={{ marginBottom: "16px" }}>
            <label
              style={{
                display: "block",
                fontSize: "13px",
                fontWeight: 600,
                color: "#3b4557",
                marginBottom: "6px",
              }}
            >
              Địa chỉ Email
            </label>
            <input
              type="email"
              required
              className="inp"
              style={{ width: "100%", height: "42px" }}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ten@doanhnghiep.vn"
            />
          </div>

          <div style={{ marginBottom: "22px" }}>
            <label
              style={{
                display: "block",
                fontSize: "13px",
                fontWeight: 600,
                color: "#3b4557",
                marginBottom: "6px",
              }}
            >
              Mật khẩu
            </label>
            <input
              type="password"
              required
              className="inp"
              style={{ width: "100%", height: "42px" }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="bt p"
            style={{ width: "100%", height: "44px", fontSize: "14.5px" }}
          >
            {isLoading ? "Đang xử lý..." : "Đăng nhập hệ thống"}
          </button>
        </form>

        <div style={{ marginTop: "24px", paddingTop: "18px", borderTop: "1px solid var(--line)" }}>
          <div
            style={{
              fontSize: "12px",
              color: "var(--muted)",
              marginBottom: "10px",
              textAlign: "center",
              fontWeight: 500,
            }}
          >
            Tài khoản demo kiểm thử xác thực:
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
            {demoAccounts.map((acc) => (
              <button
                key={acc.role}
                type="button"
                className="bt s"
                style={{
                  justifyContent: "flex-start",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  height: "auto",
                  padding: "6px 10px",
                }}
                onClick={() => {
                  setEmail(acc.email);
                  handleSubmit(undefined, acc.email);
                }}
              >
                <b style={{ fontSize: "12px", color: "var(--navy)" }}>{acc.label}</b>
                <span style={{ fontSize: "10.5px", color: "var(--muted)" }}>{acc.email}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
