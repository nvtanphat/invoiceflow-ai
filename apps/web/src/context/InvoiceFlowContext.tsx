import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import {
  api,
  AuthSession,
  DocumentItem,
  FieldDecision,
  InvoiceItem,
  JobItem,
  ReconciliationResult,
} from "../lib/api-client";
import {
  INITIAL_DOCUMENTS,
  INITIAL_INVOICES,
  ExtendedInvoiceItem,
} from "../lib/seed-data";

export type NavPage =
  | "tong-quan"
  | "xu-ly"
  | "doi-soat"
  | "phe-duyet"
  | "xuat-du-lieu"
  | "bao-cao";

export interface ActivityEvent {
  id: string;
  t: string;
  txt: string;
  icon: string;
  page?: NavPage;
  docId?: string;
  noti?: boolean;
  unread?: boolean;
}

export interface ToastMessage {
  id: string;
  msg: string;
  type: "ok" | "err" | "warn";
}

interface InvoiceFlowContextType {
  session: AuthSession | null;
  activePage: NavPage;
  setActivePage: (page: NavPage) => void;
  documents: DocumentItem[];
  invoices: ExtendedInvoiceItem[];
  jobs: Record<string, JobItem>;
  selectedDocId: string | null;
  setSelectedDocId: (id: string | null) => void;
  selectedInvoice: ExtendedInvoiceItem | null;
  highlightedField: string | null;
  setHighlightedField: (field: string | null) => void;
  reconciliations: Record<string, ReconciliationResult>;
  events: ActivityEvent[];
  toasts: ToastMessage[];
  isExportModalOpen: boolean;
  setIsExportModalOpen: (open: boolean) => void;
  showToast: (msg: string, type?: "ok" | "err" | "warn") => void;
  logEvent: (txt: string, opts?: { icon?: string; page?: NavPage; docId?: string; noti?: boolean }) => void;
  markAllRead: () => void;
  refreshData: () => Promise<void>;
  uploadFiles: (files: FileList | File[]) => Promise<void>;
  approveInvoice: (invoiceId: string, notes?: string) => Promise<boolean>;
  rejectInvoice: (invoiceId: string, reason: string) => Promise<boolean>;
  correctInvoice: (invoiceId: string, corrections: Partial<InvoiceItem>) => Promise<boolean>;
  resolveField: (invoiceId: string, fieldPath: string, decision: FieldDecision, value?: string) => Promise<boolean>;
  runReconcile: (invoiceId: string) => Promise<ReconciliationResult | null>;
  login: (email: string, pass: string) => Promise<void>;
  logout: () => void;
  switchRole: (role: "admin" | "accountant" | "reviewer" | "viewer") => Promise<void>;
}

const InvoiceFlowContext = createContext<InvoiceFlowContextType | undefined>(undefined);

const pad = (n: number) => String(n).padStart(2, "0");
const nowStr = () => {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// Fixture data and simulated outcomes exist only on the dev server; a production build
// compiles this to `false`, so no URL flag can switch it to fake data or fake success.
const isDemoMode = (): boolean => {
  if (!import.meta.env.DEV || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("demo") === "true";
};

export const InvoiceFlowProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const isDemo = isDemoMode();
  const [session, setSession] = useState<AuthSession | null>(api.getSession());
  const [activePage, setActivePage] = useState<NavPage>("xu-ly");
  const [documents, setDocuments] = useState<DocumentItem[]>(isDemo ? INITIAL_DOCUMENTS : []);
  const [invoices, setInvoices] = useState<ExtendedInvoiceItem[]>(isDemo ? INITIAL_INVOICES : []);
  const [jobs, setJobs] = useState<Record<string, JobItem>>({});
  const [selectedDocId, setSelectedDocId] = useState<string | null>(isDemo ? "INV-DIV-01" : null);
  const [selectedInvoice, setSelectedInvoice] = useState<ExtendedInvoiceItem | null>(isDemo ? INITIAL_INVOICES[0] : null);
  const [highlightedField, setHighlightedField] = useState<string | null>(null);
  const [reconciliations, setReconciliations] = useState<Record<string, ReconciliationResult>>({});
  const [events, setEvents] = useState<ActivityEvent[]>(
    isDemo
      ? [
          { id: "e1", t: "14:32", txt: "Đã phê duyệt CASE-08 – 19,910,000 VND", icon: "circlecheck", page: "phe-duyet", docId: "CASE-08", noti: false, unread: false },
          { id: "e2", t: "14:05", txt: "Từ chối CASE-05 – MST không hợp lệ trên CQT", icon: "circlex", page: "phe-duyet", docId: "CASE-05", noti: true, unread: true },
          { id: "e3", t: "13:48", txt: "Trích xuất xong CASE-03 (99.1%) – đối soát: Khớp", icon: "check", page: "xu-ly", docId: "CASE-03", noti: true, unread: true },
          { id: "e4", t: "13:21", txt: "CASE-07 lệch số lượng so với phiếu nhập kho – cần rà soát", icon: "alert", page: "doi-soat", docId: "CASE-07", noti: true, unread: true },
          { id: "e5", t: "11:10", txt: "Đã xuất 7 bản ghi (Excel) – invoiceflow_export.xlsx", icon: "export", page: "xuat-du-lieu", noti: false, unread: false },
          { id: "e6", t: "09:52", txt: "Tải lên 4 tệp từ hộp thư hóa đơn kế toán", icon: "upcloud", page: "xu-ly", noti: false, unread: false },
        ]
      : []
  );
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((msg: string, type: "ok" | "err" | "warn" = "ok") => {
    const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev.slice(-3), { id, msg, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3800);
  }, []);

  const logEvent = useCallback(
    (txt: string, opts: { icon?: string; page?: NavPage; docId?: string; noti?: boolean } = {}) => {
      const ev: ActivityEvent = {
        id: `ev-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        t: nowStr(),
        txt,
        icon: opts.icon || "check",
        page: opts.page,
        docId: opts.docId,
        noti: opts.noti !== false,
        unread: opts.noti !== false,
      };
      setEvents((prev) => [ev, ...prev.slice(0, 49)]);
    },
    []
  );

  const markAllRead = useCallback(() => {
    setEvents((prev) => prev.map((e) => ({ ...e, unread: false })));
    showToast("Đã đánh dấu tất cả là đã đọc.");
  }, [showToast]);

  const refreshData = useCallback(async () => {
    if (!api.getSession()) return;
    try {
      const [backendDocs, backendInvs] = await Promise.all([api.getDocuments(), api.getInvoices()]);

      if (!isDemo) {
        setDocuments(backendDocs);
        setInvoices(backendInvs as ExtendedInvoiceItem[]);
      } else {
        setDocuments((prevDocs) => {
          const docMap = new Map<string, DocumentItem>();
          prevDocs.forEach((d) => docMap.set(d.id, d));
          backendDocs.forEach((d) => docMap.set(d.id, d));
          return Array.from(docMap.values());
        });

        setInvoices((prevInvs) => {
          const invMap = new Map<string, ExtendedInvoiceItem>();
          prevInvs.forEach((i) => invMap.set(i.id, i));
          backendInvs.forEach((i) => {
            const existing = invMap.get(i.id) || {};
            invMap.set(i.id, { ...existing, ...i });
          });
          return Array.from(invMap.values());
        });
      }
    } catch (err: unknown) {
      if (!isDemo) {
        const msg = err instanceof Error ? err.message : "Lỗi đồng bộ dữ liệu";
        showToast(msg, "err");
      }
    }
  }, [isDemo, showToast]);

  useEffect(() => {
    if (session) {
      refreshData();
    }
  }, [session, refreshData]);

  // Sync selected doc and invoice
  useEffect(() => {
    if (!selectedDocId && documents.length > 0) {
      setSelectedDocId(documents[0].id);
    }
  }, [documents, selectedDocId]);

  useEffect(() => {
    if (!selectedDocId) {
      setSelectedInvoice(null);
      return;
    }
    const matched = invoices.find((inv) => inv.document_id === selectedDocId || inv.id === selectedDocId);
    if (matched) {
      api.getInvoice(matched.id)
        .then((full) => setSelectedInvoice({ ...matched, ...full }))
        .catch(() => setSelectedInvoice(matched));
    } else {
      setSelectedInvoice(null);
    }
  }, [selectedDocId, invoices]);

  // Upload handling with real job tracking
  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileList = Array.from(files);
      if (!fileList.length) return;

      for (const file of fileList) {
        try {
          const res = await api.uploadDocument(file);
          logEvent(`Tải lên ${file.name}`, { icon: "upcloud", page: "xu-ly", docId: res.document.id });
          showToast(`Đã tải lên ${file.name} – đang xếp hàng xử lý.`);
          setJobs((prev) => ({ ...prev, [res.document.id]: res.job }));
          setDocuments((prev) => [res.document, ...prev.filter((d) => d.id !== res.document.id)]);
          setSelectedDocId(res.document.id);
          setActivePage("xu-ly");

          // Poll job status
          const pollInterval = setInterval(async () => {
            try {
              const updatedJob = await api.getJob(res.job.id);
              setJobs((prev) => ({ ...prev, [res.document.id]: updatedJob }));
              if (updatedJob.status === "completed" || updatedJob.status === "failed") {
                clearInterval(pollInterval);
                await refreshData();
                if (updatedJob.status === "completed") {
                  showToast(`Trích xuất hoàn tất: ${file.name}`);
                  logEvent(`Trích xuất hoàn tất ${file.name}`, { icon: "check", page: "xu-ly", docId: res.document.id });
                } else {
                  showToast(`Lỗi xử lý ${file.name}: ${updatedJob.error_message || "Thất bại"}`, "err");
                }
              }
            } catch {
              clearInterval(pollInterval);
            }
          }, 1200);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : "Tải lên thất bại";
          showToast(`Lỗi tải lên ${file.name}: ${msg}`, "err");
          if (!isDemo) {
            continue;
          }
          // Graceful simulated pipeline fallback only for explicit demo mode
          const newDocId = `doc-up-${Date.now()}`;
          const newInvId = `inv-up-${Date.now()}`;
          const newDoc: DocumentItem = {
            id: newDocId,
            tenant_id: "tenant-alpha-001",
            filename: file.name,
            mime_type: file.name.endsWith(".xml") ? "application/xml" : "application/pdf",
            file_size_bytes: file.size,
            sha256: "demo-sha256-" + Date.now(),
            status: "PROCESSING",
            page_count: 1,
            created_at: new Date().toISOString(),
          };
          const mockJob: JobItem = {
            id: `job-${newDocId}`,
            document_id: newDocId,
            status: "running",
            stage: "OCR & Phân tích cấu trúc",
            attempt_count: 1,
          };

          setDocuments((prev) => [newDoc, ...prev]);
          setJobs((prev) => ({ ...prev, [newDocId]: mockJob }));
          setSelectedDocId(newDocId);
          setActivePage("xu-ly");
          logEvent(`Tải lên ${file.name}`, { icon: "upcloud", page: "xu-ly", docId: newDocId });
          showToast(`Đã nhận ${file.name} – đang trích xuất AI...`);

          setTimeout(() => {
            setJobs((prev) => ({
              ...prev,
              [newDocId]: { ...mockJob, stage: "Trích xuất thực thể AI (LLM / OCR)" },
            }));
          }, 900);

          setTimeout(() => {
            setJobs((prev) => ({
              ...prev,
              [newDocId]: { ...mockJob, stage: "Kiểm tra hợp lệ & Đối soát 3-Way" },
            }));
          }, 1800);

          setTimeout(() => {
            const completedDoc: DocumentItem = { ...newDoc, status: "COMPLETED" };
            const invNo = String(Math.floor(1000000 + Math.random() * 9000000));
            const newInvoice: ExtendedInvoiceItem = {
              id: newInvId,
              document_id: newDocId,
              revision: 1,
              status: "READY_FOR_REVIEW",
              supplier_tax_id: "0102345678",
              supplier_name: "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
              buyer_tax_id: "0309876543",
              buyer_name: "Công ty Cổ phần Thương mại Alpha VN",
              invoice_number: invNo,
              invoice_series: "1C26TLL",
              issue_date: new Date().toLocaleDateString("vi-VN"),
              currency: "VND",
              subtotal: "45000000",
              discount_total: "0",
              tax_total: "4500000",
              amount_payable: "49500000",
              signature_status: "VALID",
              tax_authority_status: "ACTIVE",
              po_number: "PO-2026-1188",
              grn_number: "GRN-2026-1188",
              progress: 100,
              lines: [
                {
                  line_no: 1,
                  sku_ref: "TL-SRV-01",
                  description: "Dịch vụ phần mềm quản trị AI Cloud (Gói Doanh nghiệp)",
                  unit: "Tháng",
                  qty: "1",
                  unit_price: "45000000",
                  discount: "0",
                  tax_rate: "10%",
                  tax: "4500000",
                  line_amount: "45000000",
                },
              ],
              evidence: [
                {
                  field_name: "invoice_number",
                  source: "ocr",
                  page: 0,
                  bbox_json: JSON.stringify([450, 115, 610, 145]),
                  confidence: 0.998,
                  raw_value: invNo,
                },
                {
                  field_name: "supplier_tax_id",
                  source: "ocr",
                  page: 0,
                  bbox_json: JSON.stringify([120, 115, 260, 145]),
                  confidence: 0.999,
                  raw_value: "0102345678",
                },
                {
                  field_name: "supplier_name",
                  source: "ocr",
                  page: 0,
                  bbox_json: JSON.stringify([120, 90, 480, 115]),
                  confidence: 0.995,
                  raw_value: "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
                },
                {
                  field_name: "amount_payable",
                  source: "ocr",
                  page: 0,
                  bbox_json: JSON.stringify([460, 480, 620, 510]),
                  confidence: 0.999,
                  raw_value: "49500000",
                },
              ],
            };

            setDocuments((prev) => prev.map((d) => (d.id === newDocId ? completedDoc : d)));
            setInvoices((prev) => [newInvoice, ...prev]);
            setSelectedInvoice(newInvoice);
            setJobs((prev) => {
              const updated = { ...prev };
              delete updated[newDocId];
              return updated;
            });
            showToast(`Trích xuất hoàn tất chứng từ: ${file.name}`);
            logEvent(`Trích xuất hoàn tất ${file.name} - Sẵn sàng phê duyệt`, {
              icon: "circlecheck",
              page: "xu-ly",
              docId: newDocId,
            });
          }, 2700);
        }
      }
      await refreshData();
    },
    [isDemo, logEvent, showToast, refreshData]
  );

  const approveInvoice = useCallback(
    async (invoiceId: string, notes?: string): Promise<boolean> => {
      const inv = invoices.find((i) => i.id === invoiceId) || selectedInvoice;
      if (!inv) return false;
      try {
        const updated = await api.reviewInvoice(invoiceId, "approve", inv.revision, undefined, notes);
        const full = await api.getInvoice(invoiceId).catch(() => ({ ...inv, ...updated }));
        setSelectedInvoice((prev) => (prev && prev.id === invoiceId ? { ...prev, ...full } : prev));
        setInvoices((prev) => prev.map((i) => (i.id === invoiceId ? { ...i, ...full } : i)));
        showToast(`Đã phê duyệt hóa đơn #${inv.invoice_number || inv.id}`);
        logEvent(`Phê duyệt #${inv.invoice_number || inv.id}`, { icon: "circlecheck", page: "phe-duyet", docId: inv.document_id });
        await refreshData();
        return true;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Phê duyệt thất bại";
        showToast(msg, "err");
        if (isDemo && !invoiceId.startsWith("inv-demo-")) {
          setInvoices((prev) =>
            prev.map((i) => (i.id === invoiceId ? { ...i, status: "APPROVED", note: notes || i.note } : i))
          );
          if (selectedInvoice?.id === invoiceId) {
            setSelectedInvoice((prev) => (prev ? { ...prev, status: "APPROVED", note: notes || prev.note } : null));
          }
          return true;
        }
        return false;
      }
    },
    [invoices, selectedInvoice, isDemo, refreshData, showToast, logEvent]
  );

  const rejectInvoice = useCallback(
    async (invoiceId: string, reason: string): Promise<boolean> => {
      const inv = invoices.find((i) => i.id === invoiceId) || selectedInvoice;
      if (!inv) return false;
      try {
        const updated = await api.reviewInvoice(invoiceId, "reject", inv.revision, undefined, undefined, reason);
        const full = await api.getInvoice(invoiceId).catch(() => ({ ...inv, ...updated }));
        setSelectedInvoice((prev) => (prev && prev.id === invoiceId ? { ...prev, ...full } : prev));
        setInvoices((prev) =>
          prev.map((i) => (i.id === invoiceId ? { ...i, ...full, note: reason } : i))
        );
        showToast(`Đã từ chối hóa đơn: ${reason}`, "warn");
        logEvent(`Từ chối #${inv.invoice_number || inv.id}: ${reason}`, { icon: "circlex", page: "phe-duyet", docId: inv.document_id });
        await refreshData();
        return true;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Thao tác thất bại";
        showToast(msg, "err");
        if (isDemo && !invoiceId.startsWith("inv-demo-")) {
          setInvoices((prev) =>
            prev.map((i) => (i.id === invoiceId ? { ...i, status: "REJECTED", note: reason } : i))
          );
          if (selectedInvoice?.id === invoiceId) {
            setSelectedInvoice((prev) => (prev ? { ...prev, status: "REJECTED", note: reason } : null));
          }
          return true;
        }
        return false;
      }
    },
    [invoices, selectedInvoice, isDemo, refreshData, showToast, logEvent]
  );

  const correctInvoice = useCallback(
    async (invoiceId: string, corrections: Partial<InvoiceItem>): Promise<boolean> => {
      const inv = invoices.find((i) => i.id === invoiceId) || selectedInvoice;
      if (!inv) return false;
      try {
        const updated = await api.reviewInvoice(invoiceId, "correct", inv.revision, corrections);
        // Server state wins: it holds the normalised values and the new revision.
        const full = await api.getInvoice(invoiceId).catch(() => ({ ...inv, ...updated }));
        setSelectedInvoice((prev) => (prev && prev.id === invoiceId ? { ...prev, ...full } : prev));
        setInvoices((prev) => prev.map((i) => (i.id === invoiceId ? { ...i, ...full } : i)));
        showToast("Thông tin đính chính đã được lưu thành công.");
        logEvent(`Đính chính hóa đơn #${inv.invoice_number || inv.id} (Rev v${updated.revision || inv.revision + 1})`, {
          icon: "edit",
          page: "xu-ly",
          docId: inv.document_id,
        });
        await refreshData();
        return true;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Đính chính thất bại";
        showToast(msg, "err");
        if (isDemo && !invoiceId.startsWith("inv-demo-")) {
          setInvoices((prev) =>
            prev.map((i) => (i.id === invoiceId ? { ...i, ...corrections, revision: i.revision + 1 } : i))
          );
          if (selectedInvoice?.id === invoiceId) {
            setSelectedInvoice((prev) =>
              prev ? { ...prev, ...corrections, revision: prev.revision + 1 } : null
            );
          }
          return true;
        }
        return false;
      }
    },
    [invoices, selectedInvoice, isDemo, refreshData, showToast, logEvent]
  );

  const resolveField = useCallback(
    async (invoiceId: string, fieldPath: string, decision: FieldDecision, value?: string): Promise<boolean> => {
      const inv = invoices.find((i) => i.id === invoiceId) || selectedInvoice;
      if (!inv) return false;
      try {
        const full = await api.resolveField(invoiceId, inv.revision, fieldPath, decision, value);
        setSelectedInvoice((prev) => (prev && prev.id === invoiceId ? { ...prev, ...full } : prev));
        setInvoices((prev) => prev.map((i) => (i.id === invoiceId ? { ...i, ...full } : i)));
        showToast(`Đã xác nhận trường ${fieldPath}`);
        logEvent(`Xác nhận trường ${fieldPath} (#${inv.invoice_number || inv.id})`, {
          icon: "edit",
          page: "xu-ly",
          docId: inv.document_id,
        });
        return true;
      } catch (err: unknown) {
        showToast(err instanceof Error ? err.message : "Xác nhận trường thất bại", "err");
        return false;
      }
    },
    [invoices, selectedInvoice, showToast, logEvent]
  );

  const runReconcile = useCallback(
    async (invoiceId: string): Promise<ReconciliationResult | null> => {
      try {
        const res = await api.reconcile(invoiceId);
        setReconciliations((prev) => ({ ...prev, [invoiceId]: res }));
        showToast(`Đối soát xong: ${res.is_matched ? "Khớp dữ liệu" : "Có chênh lệch"}`);
        return res;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Lỗi khi chạy đối soát";
        showToast(msg, "err");
        if (isDemo && !invoiceId.startsWith("inv-demo-")) {
          const inv = invoices.find((i) => i.id === invoiceId);
          const isBad = inv?.status === "READY_FOR_REVIEW";
          const res: ReconciliationResult = {
            invoice_id: invoiceId,
            status: isBad ? "DISCREPANCY_DETECTED" : "MATCHED",
            is_matched: !isBad,
            requires_review: isBad,
            issues: [],
          };
          setReconciliations((prev) => ({ ...prev, [invoiceId]: res }));
          return res;
        }
        return null;
      }
    },
    [invoices, isDemo, showToast]
  );

  const login = useCallback(
    async (email: string, pass: string) => {
      try {
        const s = await api.login(email, pass);
        setSession(s);
        showToast(`Đăng nhập thành công (${s.role})`);
      } catch (err: unknown) {
        if (!isDemo) {
          const msg = err instanceof Error ? err.message : "Đăng nhập thất bại";
          showToast(msg, "err");
          throw err;
        }
        // Graceful offline/demo session fallback only when in demo mode
        const role = email.includes("admin")
          ? "admin"
          : email.includes("reviewer")
          ? "reviewer"
          : email.includes("viewer")
          ? "viewer"
          : "accountant";
        const fallbackSession: AuthSession = {
          access_token: `demo-token-${Date.now()}`,
          token_type: "bearer",
          user_id: `user-${email.split("@")[0]}`,
          tenant_id: "tenant-alpha-001",
          role,
          email,
        };
        api.setSession(fallbackSession);
        setSession(fallbackSession);
        showToast(`Đăng nhập thành công (Demo - ${role})`);
      }
    },
    [isDemo, showToast]
  );

  const logout = useCallback(() => {
    api.logout();
    setSession(null);
    setSelectedDocId(null);
    setSelectedInvoice(null);
    showToast("Đã đăng xuất");
  }, [showToast]);

  const switchRole = useCallback(
    async (role: "admin" | "accountant" | "reviewer" | "viewer") => {
      try {
        const s = await api.login(`${role}@invoiceflow.vn`, "DemoPassword@123");
        setSession(s);
        showToast(`Chuyển sang vai trò: ${role}`);
      } catch (err: unknown) {
        if (isDemo && session) {
          const updated: AuthSession = { ...session, role, email: `${role}@invoiceflow.vn` };
          api.setSession(updated);
          setSession(updated);
          showToast(`Chuyển sang vai trò: ${role}`);
        } else {
          const msg = err instanceof Error ? err.message : `Không thể chuyển vai trò sang ${role}`;
          showToast(msg, "err");
        }
      }
    },
    [isDemo, session, showToast]
  );

  return (
    <InvoiceFlowContext.Provider
      value={{
        session,
        activePage,
        setActivePage,
        documents,
        invoices,
        jobs,
        selectedDocId,
        setSelectedDocId,
        selectedInvoice,
        highlightedField,
        setHighlightedField,
        reconciliations,
        events,
        toasts,
        isExportModalOpen,
        setIsExportModalOpen,
        showToast,
        logEvent,
        markAllRead,
        refreshData,
        uploadFiles,
        approveInvoice,
        rejectInvoice,
        correctInvoice,
        resolveField,
        runReconcile,
        login,
        logout,
        switchRole,
      }}
    >
      {children}
    </InvoiceFlowContext.Provider>
  );
};

export const useInvoiceFlow = () => {
  const context = useContext(InvoiceFlowContext);
  if (!context) throw new Error("useInvoiceFlow must be used within InvoiceFlowProvider");
  return context;
};
