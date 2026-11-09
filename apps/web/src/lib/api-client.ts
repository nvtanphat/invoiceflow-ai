export interface AuthSession {
  access_token: string;
  token_type: string;
  user_id: string;
  tenant_id: string;
  role: string;
  email: string;
}

export interface DocumentItem {
  id: string;
  tenant_id: string;
  filename: string;
  mime_type: string;
  file_size_bytes: number;
  sha256: string;
  status: string;
  page_count: number;
  created_at: string;
}

export interface JobItem {
  id: string;
  document_id: string;
  status: string;
  stage: string;
  attempt_count: number;
  error_message?: string | null;
}

export interface InvoiceLineItem {
  id?: string;
  line_no: number;
  sku_ref?: string | null;
  description: string;
  unit?: string | null;
  qty: string;
  unit_price: string;
  discount: string;
  tax_rate?: string | null;
  tax: string;
  line_amount: string;
}

export interface FieldEvidenceItem {
  field_name: string;
  source: string;
  page: number;
  bbox_json: string;
  table_id?: string | null;
  cell_id?: string | null;
  confidence: number;
  verification_state?: string | null;
  review_reason?: string | null;
  raw_value: string;
}

export interface InvoiceItem {
  id: string;
  document_id: string;
  revision: number;
  status: string;
  supplier_tax_id?: string | null;
  supplier_name?: string | null;
  buyer_tax_id?: string | null;
  buyer_name?: string | null;
  invoice_number?: string | null;
  invoice_series?: string | null;
  issue_date?: string | null;
  currency: string;
  exchange_rate?: string | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  amount_payable: string;
  signature_status: string;
  tax_authority_status: string;
  lines: InvoiceLineItem[];
  evidence?: FieldEvidenceItem[];
}

export interface MatchingIssue {
  code: string;
  severity: "ERROR" | "WARNING" | "INFO";
  message: string;
  field?: string | null;
  invoice_value?: string | null;
  reference_value?: string | null;
}

export interface ReconciliationResult {
  invoice_id: string;
  status: string;
  is_matched: boolean;
  requires_review: boolean;
  issues: MatchingIssue[];
}

class ApiClient {
  private baseUrl = "/api/v1";
  private session: AuthSession | null = null;

  constructor() {
    const saved = localStorage.getItem("invoiceflow_session");
    if (saved) {
      try {
        this.session = JSON.parse(saved);
      } catch {
        this.session = null;
      }
    }
  }

  public getSession(): AuthSession | null {
    return this.session;
  }

  public setSession(session: AuthSession | null): void {
    this.session = session;
    if (session) {
      localStorage.setItem("invoiceflow_session", JSON.stringify(session));
    } else {
      localStorage.removeItem("invoiceflow_session");
    }
  }

  public logout(): void {
    this.setSession(null);
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const res: Record<string, string> = { ...extra };
    if (this.session?.access_token) {
      res["Authorization"] = `Bearer ${this.session.access_token}`;
    }
    return res;
  }

  public async login(email: string, password: string): Promise<AuthSession> {
    const res = await fetch(`${this.baseUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(err.detail || "Login failed");
    }
    const data: AuthSession = await res.json();
    this.setSession(data);
    return data;
  }

  public async getDocuments(): Promise<DocumentItem[]> {
    const res = await fetch(`${this.baseUrl}/documents`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Failed to fetch documents");
    return res.json();
  }

  public async uploadDocument(file: File): Promise<{ document: DocumentItem; job: JobItem }> {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${this.baseUrl}/documents/upload`, {
      method: "POST",
      headers: this.headers(),
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Upload failed" }));
      throw new Error(err.detail || "Upload failed");
    }
    return res.json();
  }

  public async getJob(jobId: string): Promise<JobItem> {
    const res = await fetch(`${this.baseUrl}/jobs/${jobId}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Failed to fetch job");
    return res.json();
  }

  public async getInvoices(): Promise<InvoiceItem[]> {
    const res = await fetch(`${this.baseUrl}/invoices`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Failed to fetch invoices");
    return res.json();
  }

  public async getInvoice(invoiceId: string): Promise<InvoiceItem> {
    const res = await fetch(`${this.baseUrl}/invoices/${invoiceId}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Failed to fetch invoice details");
    return res.json();
  }

  public async reviewInvoice(
    invoiceId: string,
    action: "approve" | "reject" | "correct",
    revision: number,
    corrections?: Partial<InvoiceItem>,
    notes?: string,
    reason?: string
  ): Promise<InvoiceItem> {
    const headers = this.headers({
      "Content-Type": "application/json",
      "If-Match": `"${revision}"`,
    });
    const res = await fetch(`${this.baseUrl}/invoices/${invoiceId}/review`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        action,
        corrections: corrections || {},
        notes: notes || undefined,
        reason: reason || undefined,
      }),
    });
    if (res.status === 409) {
      throw new Error("Xung đột phiên bản (409 Conflict): Hóa đơn vừa được cập nhật bởi người khác. Vui lòng tải lại.");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Review action failed" }));
      throw new Error(err.detail || "Review action failed");
    }
    return this.getInvoice(invoiceId);
  }

  public async reconcile(invoiceId: string): Promise<ReconciliationResult> {
    const res = await fetch(`${this.baseUrl}/matching/reconcile/${invoiceId}`, {
      method: "POST",
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Failed to execute reconciliation");
    return res.json();
  }

  public async downloadExport(format: "csv" | "xlsx" | "json"): Promise<Blob> {
    const res = await fetch(`${this.baseUrl}/exports/invoices?format=${format}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  }

  public async renderDocumentPage(
    documentId: string,
    pageIndex: number = 0
  ): Promise<{ blobUrl: string; width: number; height: number; pageCount: number }> {
    const res = await fetch(`${this.baseUrl}/documents/${documentId}/pages/${pageIndex}/render`, {
      headers: this.headers(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `Render failed (${res.status})` }));
      throw new Error(err.detail || `Render failed (${res.status})`);
    }
    const width = parseFloat(res.headers.get("X-Page-Width") || "595");
    const height = parseFloat(res.headers.get("X-Page-Height") || "842");
    const pageCount = parseInt(res.headers.get("X-Page-Count") || "1", 10);
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    return { blobUrl, width, height, pageCount };
  }
}

export const api = new ApiClient();
