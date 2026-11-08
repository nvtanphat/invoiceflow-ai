import React, { useState, useEffect } from "react";
import {
  Inbox,
  FileCheck,
  GitCompare,
  Download,
  Building2,
  Shield,
  Sparkles,
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

  // Auto-login with default accountant if not logged in for smooth demo experience
  useEffect(() => {
    if (!session) {
      api.login("accountant@invoiceflow.vn", "DemoPassword@123")
        .then((s) => setSession(s))
        .catch(() => {
          // Fallback demo session
          const demoSession: AuthSession = {
            access_token: "demo-token",
            token_type: "bearer",
            user_id: "user-accountant-02",
            tenant_id: "tenant-alpha-001",
            role: "accountant",
            email: "accountant@invoiceflow.vn",
          };
          api.setSession(demoSession);
          setSession(demoSession);
        });
    }
  }, []);

  const handleSwitchUser = async (role: "admin" | "accountant" | "reviewer" | "viewer") => {
    const email = `${role}@invoiceflow.vn`;
    try {
      const s = await api.login(email, "DemoPassword@123");
      setSession(s);
    } catch {
      const s: AuthSession = {
        access_token: `demo-token-${role}`,
        token_type: "bearer",
        user_id: `user-${role}`,
        tenant_id: "tenant-alpha-001",
        role,
        email,
      };
      api.setSession(s);
      setSession(s);
    }
  };

  const handleSelectInvoiceFromInbox = async (docId: string) => {
    try {
      const invoices = await api.getInvoices();
      const matched = invoices.find((inv) => inv.document_id === docId);
      if (matched) {
        setSelectedInvoiceId(matched.id);
        setActiveTab("review");
      } else if (invoices.length > 0) {
        setSelectedInvoiceId(invoices[0].id);
        setActiveTab("review");
      } else {
        alert("Chưa có hóa đơn nào được trích xuất cho tài liệu này.");
      }
    } catch {
      alert("Không thể tải danh sách hóa đơn.");
    }
  };

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

          {/* Tenant & User Role Switcher */}
          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-2 text-xs text-slate-600 bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">
              <Building2 className="w-4 h-4 text-slate-500" />
              <span className="font-medium text-slate-800">Công ty Cổ phần Thương mại Alpha VN</span>
            </div>

            {/* Quick RBAC Switcher */}
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs">
              <Shield className="w-3.5 h-3.5 text-slate-500 ml-1.5" />
              {(["admin", "accountant", "reviewer", "viewer"] as const).map((r) => {
                const isActive = session?.role === r;
                return (
                  <button
                    key={r}
                    onClick={() => handleSwitchUser(r)}
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
                    if (invs.length > 0) setSelectedInvoiceId(invs[0].id);
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
        {activeTab === "inbox" && (
          <DocumentInbox onSelectInvoice={handleSelectInvoiceFromInbox} />
        )}

        {activeTab === "review" && (
          <InvoiceReview
            invoiceId={selectedInvoiceId || "inv-demo-001"}
            onBack={() => setActiveTab("inbox")}
            onOpenReconcile={(id) => {
              setSelectedInvoiceId(id);
              setActiveTab("reconcile");
            }}
          />
        )}

        {activeTab === "reconcile" && (
          <ReconciliationPanel
            invoiceId={selectedInvoiceId || "inv-demo-001"}
            onBack={() => setActiveTab("review")}
          />
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
