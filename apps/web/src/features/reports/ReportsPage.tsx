import React, { useEffect, useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { api, ProcessingCounts, ProcessingSummary } from "../../lib/api-client";
import { CC, fmt, sparkline, colChart, lineChart, donutChart, hbarChart, sum } from "../../lib/chart-utils";

type Period = "week" | "month" | "quarter";

const PERIODS: Record<Period, { days: number; label: string; step: number; weekly: boolean }> = {
  week: { days: 7, label: "7 ngày qua", step: 1, weekly: false },
  month: { days: 30, label: "30 ngày qua", step: 5, weekly: false },
  quarter: { days: 91, label: "13 tuần qua", step: 2, weekly: true },
};

type Bucket = ProcessingCounts & { label: string };

const COUNT_KEYS: (keyof ProcessingCounts)[] = [
  "received",
  "auto_approved",
  "routed_to_review",
  "manual_approved",
  "rejected",
];

// Every figure on this page comes from recorded decisions (processing-summary API) or the
// invoice list; nothing is estimated, generated or padded.
const toBuckets = (summary: ProcessingSummary | null, weekly: boolean): Bucket[] => {
  const days = summary?.days ?? [];
  if (!weekly) {
    return days.map((d) => ({ ...d, label: `${d.date.slice(8, 10)}/${d.date.slice(5, 7)}` }));
  }
  const weeks: Bucket[] = [];
  for (let i = 0; i < days.length; i += 7) {
    const slice = days.slice(i, i + 7);
    const bucket = { label: `T${weeks.length + 1}` } as Bucket;
    COUNT_KEYS.forEach((k) => {
      bucket[k] = sum(slice.map((d) => d[k]));
    });
    weeks.push(bucket);
  }
  return weeks;
};

const delta = (current: number | null | undefined, previous: number | null | undefined, asPoints: boolean) => {
  if (current == null || previous == null) return null;
  if (asPoints) return (current - previous) * 100;
  return previous > 0 ? ((current - previous) / previous) * 100 : null;
};

const fmtDelta = (value: number | null, unit: string) =>
  value === null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}${unit}`;

export const ReportsPage: React.FC = () => {
  const { invoices, showToast } = useInvoiceFlow();
  const [period, setPeriod] = useState<Period>("month");
  const [summary, setSummary] = useState<ProcessingSummary | null>(null);
  const cfg = PERIODS[period];

  useEffect(() => {
    let active = true;
    api
      .getProcessingSummary(cfg.days)
      .then((data) => active && setSummary(data))
      .catch(() => active && setSummary(null));
    return () => {
      active = false;
    };
  }, [cfg.days]);

  const buckets = toBuckets(summary, cfg.weekly);
  const labels = buckets.map((b) => b.label);
  const totals = summary?.totals ?? null;
  const decidedBuckets = buckets.filter((b) => b.auto_approved + b.routed_to_review > 0);
  const stpSeries = decidedBuckets.map(
    (b) => +((b.auto_approved / (b.auto_approved + b.routed_to_review)) * 100).toFixed(1)
  );

  const windowStart = summary?.days[0]?.date ?? null;
  const supplierTotals: Record<string, number> = {};
  invoices
    .filter((inv) => windowStart !== null && inv.issue_date && inv.issue_date >= windowStart)
    .forEach((inv) => {
      const name = inv.supplier_name || inv.supplier_tax_id || "Không rõ nhà cung cấp";
      supplierTotals[name] = (supplierTotals[name] || 0) + (parseFloat(inv.amount_payable) || 0);
    });
  const topSuppliers = Object.entries(supplierTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([label, v]) => ({ label, v }));

  const outcomes = totals
    ? [
        { label: "Tự động duyệt (STP)", c: CC.s1, v: totals.auto_approved },
        { label: "Duyệt sau rà soát", c: CC.s2, v: totals.manual_approved },
        { label: "Chuyển rà soát", c: CC.s3, v: totals.routed_to_review },
        { label: "Từ chối", c: CC.s4, v: totals.rejected },
      ]
    : [];
  const outcomeTotal = sum(outcomes.map((o) => o.v));

  const handleExportCsv = () => {
    const header = ["Kỳ", "Chứng từ nhận", "Tự động duyệt", "Chuyển rà soát", "Duyệt sau rà soát", "Từ chối"];
    const rows = buckets.map((b) => [
      b.label,
      b.received,
      b.auto_approved,
      b.routed_to_review,
      b.manual_approved,
      b.rejected,
    ]);
    const csv = "﻿" + [header, ...rows].map((r) => r.join(",")).join("\r\n");
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    const name = `bao_cao_${period}_${stamp}.csv`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Đã xuất ${name}`);
  };

  const kpis = [
    {
      label: "Chứng từ nhận",
      value: totals ? fmt(totals.received) : "—",
      unit: "",
      trend: fmtDelta(delta(totals?.received, summary?.previous_totals.received, false), "%"),
      spark: buckets.map((b) => b.received),
    },
    {
      label: "Tỷ lệ tự động hóa (STP)",
      value: summary?.stp_rate != null ? (summary.stp_rate * 100).toFixed(1) : "—",
      unit: "%",
      trend: fmtDelta(delta(summary?.stp_rate, summary?.previous_stp_rate, true), " điểm"),
      spark: buckets.map((b) => b.auto_approved),
    },
    {
      label: "Chuyển rà soát thủ công",
      value: totals ? fmt(totals.routed_to_review) : "—",
      unit: "",
      trend: fmtDelta(delta(totals?.routed_to_review, summary?.previous_totals.routed_to_review, false), "%"),
      spark: buckets.map((b) => b.routed_to_review),
    },
    {
      label: "Đã phê duyệt / từ chối",
      value: totals ? `${fmt(totals.auto_approved + totals.manual_approved)} / ${fmt(totals.rejected)}` : "—",
      unit: "",
      trend: null,
      spark: buckets.map((b) => b.auto_approved + b.manual_approved),
    },
  ];

  return (
    <main className="pg col on" id="pg-bao-cao">
      <div className="ph">
        <div>
          <h1>Báo cáo</h1>
          <p className="sub">Hiệu suất xử lý chứng từ · {cfg.label}</p>
        </div>
        <div className="pha">
          <div className="sg">
            {(
              [
                { k: "week", l: "Tuần" },
                { k: "month", l: "Tháng" },
                { k: "quarter", l: "Quý" },
              ] as { k: Period; l: string }[]
            ).map((p) => (
              <button key={p.k} className={period === p.k ? "on" : ""} onClick={() => setPeriod(p.k)}>
                {p.l}
              </button>
            ))}
          </div>
          <button className="bt" onClick={handleExportCsv} disabled={buckets.length === 0}>
            <Icon name="dl" />
            Xuất báo cáo (CSV)
          </button>
        </div>
      </div>

      <div className="rpk">
        {kpis.map((k) => (
          <div className="cd kpi" key={k.label}>
            <div className="l">{k.label}</div>
            <div className="v">
              {k.value}
              {k.unit && <small>{k.unit}</small>}
            </div>
            <div className="dl nt">
              {k.trend !== null ? (
                <>
                  {k.trend} <span>so với kỳ trước</span>
                </>
              ) : (
                <span>Trong kỳ</span>
              )}
            </div>
            {k.spark.length > 0 && <div dangerouslySetInnerHTML={{ __html: sparkline(k.spark) }} />}
          </div>
        ))}
      </div>

      <div className="rows">
        <div className="rw2" style={{ gridTemplateColumns: "1.55fr 1fr", flex: 1 }}>
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Kết quả xử lý</div>
                <div className="cs">{cfg.weekly ? "Theo tuần" : "Theo ngày"} (UTC)</div>
              </div>
              <div className="lg">
                <span>
                  <i style={{ background: CC.s1 }}></i>Tự động duyệt
                </span>
                <span>
                  <i style={{ background: CC.s2 }}></i>Chuyển rà soát
                </span>
                <span>
                  <i style={{ background: CC.s4 }}></i>Từ chối
                </span>
              </div>
            </div>
            <div className="cb">
              {buckets.length > 0 ? (
                <div
                  className="chart"
                  dangerouslySetInnerHTML={{
                    __html: colChart({
                      labels,
                      series: [
                        { n: "Tự động duyệt", c: CC.s1, v: buckets.map((b) => b.auto_approved) },
                        { n: "Chuyển rà soát", c: CC.s2, v: buckets.map((b) => b.routed_to_review) },
                        { n: "Từ chối", c: CC.s4, v: buckets.map((b) => b.rejected) },
                      ],
                      step: cfg.step,
                    }),
                  }}
                />
              ) : (
                <div className="empty">Chưa có dữ liệu xử lý trong kỳ</div>
              )}
            </div>
          </div>

          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Tỷ lệ tự động hóa hoàn toàn (STP)</div>
                <div className="cs">Chỉ các kỳ có quyết định của pipeline</div>
              </div>
            </div>
            <div className="cb">
              {stpSeries.length > 0 ? (
                <div
                  className="chart"
                  dangerouslySetInnerHTML={{
                    __html: lineChart({
                      labels: decidedBuckets.map((b) => b.label),
                      vals: stpSeries,
                      min: 0,
                      max: 100,
                      step: cfg.step,
                      name: "STP",
                    }),
                  }}
                />
              ) : (
                <div className="empty">Chưa có quyết định tự động/rà soát trong kỳ</div>
              )}
            </div>
          </div>
        </div>

        <div className="rw2" style={{ gridTemplateColumns: "1.15fr 1fr", flex: 1 }}>
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Top 5 nhà cung cấp theo giá trị</div>
                <div className="cs">Tổng thanh toán (VND) theo ngày lập trong kỳ</div>
              </div>
            </div>
            <div className="cb">
              {topSuppliers.length > 0 ? (
                <div className="chart" dangerouslySetInnerHTML={{ __html: hbarChart(topSuppliers) }} />
              ) : (
                <div className="empty">Chưa có hóa đơn trong kỳ</div>
              )}
            </div>
          </div>

          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Phân bổ quyết định</div>
                <div className="cs">{outcomeTotal} quyết định trong kỳ</div>
              </div>
            </div>
            <div className="cb">
              {outcomeTotal > 0 ? (
                <div className="dn-wrap" style={{ gap: "16px" }}>
                  <div
                    dangerouslySetInnerHTML={{
                      __html: donutChart(outcomes, { center: outcomeTotal, sub: "quyết định" }),
                    }}
                  />
                  <div className="dl-list">
                    {outcomes.map((o) => (
                      <div key={o.label}>
                        <i style={{ background: o.c }}></i>
                        {o.label}
                        <b>{o.v}</b>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="empty">Chưa có quyết định trong kỳ</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
};
