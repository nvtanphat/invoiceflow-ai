import React, { useState } from "react";
import {
  Inbox,
  FileCheck,
  GitCompare,
  Download,
  Building2,
  Shield,
  Sparkles,
  LogOut,
  Lock,
  Mail,
  AlertCircle,
  Loader2,
  FileText,
} from "lucide-react";
import { api, AuthSession } from "../lib/api-client";
import { DocumentInbox } from "../features/inbox/DocumentInbox";
import { InvoiceReview } from "../features/review/InvoiceReview";
import { ReconciliationPanel } from "../features/matching/ReconciliationPanel";
import { ExportModal } from "../features/exports/ExportModal";

type ActiveTab = "inbox" | "review" | "reconcile";

export const App: React.FC = () => {
  const [session, setSession] = useState<AuthSession | null>(api.getSession());
  const [activeTab, setActiveTab] = useState<ActiveTab>("inbox");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [isExportOpen, setIsExportOpen] = useState(false);

  // Login form state
  const [loginEmail, setLoginEmail] = useState("accountant@invoiceflow.vn");
  const [loginPassword, setLoginPassword] = useState("DemoPassword@123");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [inboxNotice, setInboxNotice] = useState<string | null>(null);

  const handleLoginSubmit = async (e?: React.FormEvent, customEmail?: string, customPassword?: string) => {
    if (e) e.preventDefault();
    const email = customEmail || loginEmail;
    const password = customPassword || loginPassword;

    setIsLoggingIn(true);
    setLoginError(null);

    try {
      const s = await api.login(email, password);
      setSession(s);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Đăng nhập thất bại. Vui lòng kiểm tra lại thông tin.";
      setLoginError(msg);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLogout = () => {
    api.logout();
    setSession(null);
    setSelectedInvoiceId(null);
    setActiveTab("inbox");
  };

  const handleSwitchUser = async (role: "admin" | "accountant" | "reviewer" | "viewer") => {
    const email = `${role}@invoiceflow.vn`;
    setIsLoggingIn(true);
    try {
      const s = await api.login(email, "DemoPassword@123");
      setSession(s);
    } catch (err: unknown) {
      alert(`Không thể chuyển sang tài khoản ${role}: ${err instanceof Error ? err.message : "Lỗi xác thực"}`);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleSelectInvoiceFromInbox = async (docId: string) => {
    setInboxNotice(null);
    try {
      const invoices = await api.getInvoices();
      const matched = invoices.find((inv) => inv.document_id === docId);
      if (matched) {
        setSelectedInvoiceId(matched.id);
        setActiveTab("review");
      } else {
        setInboxNotice(
          "Tài liệu này hiện đang trong quá trình xử lý hoặc chưa bóc tách xong hóa đơn. Vui lòng kiểm tra lại sau ít giây."
        );
      }
    } catch {
      setInboxNotice("Không thể kết nối đến máy chủ để kiểm tra trạng thái hóa đơn.");
    }
  };

  // If user is not authenticated, render standard production login screen
  if (!session) {
    return (
      <div className="min-h-screen bg-slate-100 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
        <div className="sm:mx-auto sm:w-full sm:max-w-md">
          <div className="flex justify-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center text-white font-black text-2xl shadow-lg">
              IF
            </div>
          </div>
          <h2 className="mt-4 text-center text-2xl font-black tracking-tight text-slate-900">
            InvoiceFlow AI
          </h2>
          <p className="mt-1 text-center text-xs text-slate-600">
            Hệ thống Xử lý & Đối soát 3 Chiều Hóa đơn Đầu vào Tài chính
          </p>
        </div>

        <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
          <div className="bg-white py-8 px-6 shadow-md rounded-2xl border border-slate-200 sm:px-10">
            <form className="space-y-4" onSubmit={(e) => handleLoginSubmit(e)}>
              {loginError && (
                <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 flex items-start gap-2 text-xs text-rose-700">
                  <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-500 mt-0.5" />
                  <span>{loginError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-700">Địa chỉ Email</label>
                <div className="mt-1 relative rounded-md shadow-xs">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-4 w-4 text-slate-400" />
                  </div>
                  <input
                    type="email"
                    required
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                    placeholder="ten@doanhnghiep.vn"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700">Mật khẩu</label>
                <div className="mt-1 relative rounded-md shadow-xs">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-4 w-4 text-slate-400" />
                  </div>
                  <input
                    type="password"
                    required
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                    placeholder="••••••••"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoggingIn}
                className="w-full flex justify-center items-center gap-2 py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-sky-600 hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sky-500 transition-colors disabled:opacity-50"
              >
                {isLoggingIn && <Loader2 className="w-4 h-4 animate-spin" />}
                Đăng nhập hệ thống
              </button>
            </form>

            <div className="mt-6">
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-slate-200" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="px-2 bg-white text-slate-500">
                    Tài khoản demo kiểm thử xác thực qua API thật
                  </span>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                {(
                  [
                    { role: "accountant", label: "Kế toán viên", email: "accountant@invoiceflow.vn" },
                    { role: "reviewer", label: "Kiểm soát viên", email: "reviewer@invoiceflow.vn" },
                    { role: "admin", label: "Quản trị viên", email: "admin@invoiceflow.vn" },
                    { role: "viewer", label: "Giám đốc duyệt", email: "viewer@invoiceflow.vn" },
                  ] as const
                ).map((u) => (
                  <button
                    key={u.role}
                    type="button"
                    onClick={() => handleLoginSubmit(undefined, u.email, "DemoPassword@123")}
                    disabled={isLoggingIn}
                    className="flex flex-col items-start p-2 border border-slate-200 hover:border-sky-500 hover:bg-sky-50/50 rounded-lg transition-colors text-left"
                  >
                    <span className="font-semibold text-slate-800">{u.label}</span>
                    <span className="text-[10px] text-slate-500 font-mono truncate w-full">{u.email}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Logo & Product Brand */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center text-white font-black text-xl shadow-md">
              IF
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-base tracking-tight text-slate-900">InvoiceFlow AI</span>
                <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold uppercase bg-sky-100 text-sky-800 px-1.5 py-0.5 rounded">
                  <Sparkles className="w-2.5 h-2.5" /> AP Pipeline
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                Tự động hóa & Đối soát 3 Chiều Hóa đơn Tài chính
              </p>
            </div>
          </div>

          {/* Tenant & User Role Switcher & Logout */}
          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-2 text-xs text-slate-600 bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">
              <Building2 className="w-4 h-4 text-slate-500" />
              <span className="font-medium text-slate-800">Công ty Cổ phần Thương mại Alpha VN</span>
            </div>

            {/* Quick RBAC Switcher with real backend auth */}
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs">
              <Shield className="w-3.5 h-3.5 text-slate-500 ml-1.5" />
              {(["admin", "accountant", "reviewer", "viewer"] as const).map((r) => {
                const isActive = session?.role === r;
                return (
                  <button
                    key={r}
                    onClick={() => handleSwitchUser(r)}
                    disabled={isLoggingIn}
                    className={`px-2 py-1 rounded-md capitalize font-medium transition-all ${
                      isActive
                        ? "bg-white text-sky-700 shadow-xs font-semibold"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {r}
                  </button>
                );
              })}
            </div>

            <button
              onClick={handleLogout}
              className="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 transition-colors"
              title="Đăng xuất"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between border-t border-slate-100">
          <nav className="flex space-x-1 py-1">
            <button
              onClick={() => setActiveTab("inbox")}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all ${
                activeTab === "inbox"
                  ? "border-sky-600 text-sky-600"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <Inbox className="w-4 h-4" /> Hộp thư Tiếp nhận Hóa đơn
            </button>

            <button
              onClick={() => {
                if (!selectedInvoiceId) {
                  api.getInvoices().then((invs) => {
                    const target = invs.find((i) => i.status === "MATCHED" || i.status === "READY_FOR_REVIEW") || invs[0];
                    if (target) setSelectedInvoiceId(target.id);
                  });
                }
                setActiveTab("review");
              }}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all ${
                activeTab === "review"
                  ? "border-sky-600 text-sky-600"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <FileCheck className="w-4 h-4" /> Xem xét & Phê duyệt (Review)
            </button>

            <button
              onClick={() => {
                if (!selectedInvoiceId) {
                  api.getInvoices().then((invs) => {
                    if (invs.length > 0) setSelectedInvoiceId(invs[0].id);
                  });
                }
                setActiveTab("reconcile");
              }}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all ${
                activeTab === "reconcile"
                  ? "border-sky-600 text-sky-600"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <GitCompare className="w-4 h-4" /> Đối soát 3 Chiều (3-Way Matching)
            </button>
          </nav>

          <button
            onClick={() => setIsExportOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 rounded-lg transition-colors border border-sky-200"
          >
            <Download className="w-3.5 h-3.5" /> Xuất dữ liệu kế toán
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {inboxNotice && (
          <div className="mb-6 p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-between text-xs text-amber-800">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
              <span>{inboxNotice}</span>
            </div>
            <button
              onClick={() => setInboxNotice(null)}
              className="text-amber-900 font-bold hover:underline ml-4"
            >
              Đóng
            </button>
          </div>
        )}

        {activeTab === "inbox" && (
          <DocumentInbox onSelectInvoice={handleSelectInvoiceFromInbox} />
        )}

        {activeTab === "review" && (
          selectedInvoiceId ? (
            <InvoiceReview
              invoiceId={selectedInvoiceId}
              onBack={() => setActiveTab("inbox")}
              onOpenReconcile={(id) => {
                setSelectedInvoiceId(id);
                setActiveTab("reconcile");
              }}
            />
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
              <FileText className="w-12 h-12 text-slate-300 mx-auto mb-3" />
              <h3 className="text-base font-semibold text-slate-800">Chưa có hóa đơn nào được chọn</h3>
              <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
                Vui lòng chọn một hóa đơn từ Hộp thư để bắt đầu xem xét và duyệt chứng từ.
              </p>
              <button
                onClick={() => setActiveTab("inbox")}
                className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 text-white hover:bg-sky-700"
              >
                <Inbox className="w-3.5 h-3.5" /> Quay lại Hộp thư
              </button>
            </div>
          )
        )}

        {activeTab === "reconcile" && (
          selectedInvoiceId ? (
            <ReconciliationPanel
              invoiceId={selectedInvoiceId}
              onBack={() => setActiveTab("review")}
            />
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
              <GitCompare className="w-12 h-12 text-slate-300 mx-auto mb-3" />
              <h3 className="text-base font-semibold text-slate-800">Chưa có hóa đơn nào để đối soát</h3>
              <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
                Chọn một hóa đơn từ Hộp thư hoặc màn hình Review để thực hiện đối chiếu 3 chiều với PO/GRN.
              </p>
              <button
                onClick={() => setActiveTab("inbox")}
                className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 text-white hover:bg-sky-700"
              >
                <Inbox className="w-3.5 h-3.5" /> Quay lại Hộp thư
              </button>
            </div>
          )
        )}
      </main>

      {/* Export Modal */}
      <ExportModal isOpen={isExportOpen} onClose={() => setIsExportOpen(false)} />

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 py-4 text-center text-xs text-slate-400">
        <p>InvoiceFlow AI • Hệ thống Xử lý Tự động & Đối soát Hóa đơn Tài chính theo Tiêu chuẩn NĐ 123/TT 78</p>
      </footer>
    </div>
  );
};
