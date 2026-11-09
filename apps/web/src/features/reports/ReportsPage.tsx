import React, { useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import {
  CC,
  fmt,
  sparkline,
  colChart,
  lineChart,
  donutChart,
  hbarChart,
  genSeries,
  lastDays,
  sum,
  rng,
  hash,
} from "../../lib/chart-utils";

export const ReportsPage: React.FC = () => {
  const { documents, invoices, showToast } = useInvoiceFlow();
  const [period, setPeriod] = useState<"week" | "month" | "quarter">("month");

  const RP = {
    week: { n: 7, lbl: "7 ngày qua", step: 1, m: 1 },
    month: { n: 30, lbl: "30 ngày qua", step: 5, m: 1 },
    quarter: { n: 13, lbl: "Quý 4/2026 (13 tuần)", step: 2, m: 7 },
  };

  const c = RP[period];
  const n = c.n;
  const labels = period === "quarter" ? Array.from({ length: n }, (_, i) => "T" + (i + 1)) : lastDays(n);
  const s1 = genSeries(n, 31, 60 * c.m, 10 * c.m, 5);
  const s2 = genSeries(n, 41, 22 * c.m, 5 * c.m, 2);
  const s3 = genSeries(n, 51, 14 * c.m, 4 * c.m, 1);
  const r = rng(61);
  const stp = Array.from({ length: n }, (_, i) => +(84 + (i / n) * 5 + (r() - 0.5) * 3).toFixed(1));
  const total = sum(s1) + sum(s2) + sum(s3) + documents.length;

  const f = { week: 0.25, month: 1, quarter: 3.1 }[period];
  const sup: Record<string, number> = {};
  invoices.forEach((d) => {
    const sName = d.supplier_name || "CÔNG TY ALPHA";
    const amt = parseFloat(d.amount_payable) || 0;
    sup[sName] = (sup[sName] || 0) + amt;
  });

  // Default vendor entries if sparse
  if (Object.keys(sup).length < 5) {
    sup["CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG"] = 125000000;
    sup["CÔNG TY TNHH PHẦN MỀM THỜI ĐẠI SỐ"] = 89000000;
    sup["CÔNG TY CP THIẾT BỊ VĂN PHÒNG MIỀN BẮC"] = 74500000;
    sup["CÔNG TY TNHH VẬT TƯ CÔNG NGHIỆP AN PHÁT"] = 46000000;
    sup["CÔNG TY CP TIẾP VẬN VÀ PHÂN PHỐI TOÀN CẦU"] = 38000000;
  }

  const top = Object.entries(sup)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([label, v]) => ({
      label,
      v: Math.round((v * f * (0.9 + rng(hash(label + period))() * 0.25)) / 1000) * 1000,
    }));

  const rr = rng(hash("exc" + period));
  const exc = [
    { label: "Lệch số lượng", c: CC.s1, v: Math.round((4 + rr() * 16) * c.m * (period === "week" ? 0.7 : 1)) },
    { label: "Lệch đơn giá", c: CC.s2, v: Math.round((4 + rr() * 16) * c.m * (period === "week" ? 0.7 : 1)) },
    { label: "Thiếu PO/GRN", c: CC.s3, v: Math.round((4 + rr() * 16) * c.m * (period === "week" ? 0.7 : 1)) },
    { label: "MST không hợp lệ", c: CC.s4, v: Math.round((4 + rr() * 16) * c.m * (period === "week" ? 0.7 : 1)) },
    { label: "Độ tin cậy thấp", c: CC.s5, v: Math.round((4 + rr() * 16) * c.m * (period === "week" ? 0.7 : 1)) },
  ];

  const acc: [string, number][] = [
    ["MST nhà cung cấp", 99.6],
    ["Số hóa đơn", 99.3],
    ["Ngày lập", 99.1],
    ["Tên người mua", 98.4],
    ["Dòng hàng", 96.9],
    ["Tổng thanh toán", 99.7],
  ].map(([l, v]) => [
    l as string,
    Math.min(99.9, +(Number(v) + (rng(hash(l + period))() - 0.5) * 0.8).toFixed(1)),
  ]);

  const avgAcc = sum(acc.map((x) => x[1])) / acc.length;
  const avgStp = sum(stp) / stp.length;
  const hours = (total * 3.5) / 60;
  const sp = (s: number, nVal: number) => genSeries(12, s, nVal, nVal * 0.12, 1);

  const handleExportCsv = () => {
    const rows = [
      ["Kỳ", ...labels],
      ["Hóa đơn GTGT", ...s1],
      ["Phiếu nhập kho", ...s2],
      ["Đơn đặt hàng", ...s3],
      ["STP (%)", ...stp],
    ];
    const t =
      "\ufeff" +
      rows.map((rLine) => rLine.map((val) => (/[",\n]/.test(String(val)) ? `"${String(val).replace(/"/g, '""')}"` : val)).join(",")).join("\r\n");
    const name = `bao_cao_${period}_20261109.csv`;
    const blob = new Blob([t], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    showToast(`Đã xuất ${name}`);
  };

  return (
    <main className="pg col on" id="pg-bao-cao">
      <div className="ph">
        <div>
          <h1>Báo cáo</h1>
          <p className="sub">Hiệu suất xử lý chứng từ · {c.lbl}</p>
        </div>
        <div className="pha">
          <div className="sg">
            {[
              { k: "week", l: "Tuần" },
              { k: "month", l: "Tháng" },
              { k: "quarter", l: "Quý" },
            ].map((p) => (
              <button
                key={p.k}
                className={period === p.k ? "on" : ""}
                onClick={() => setPeriod(p.k as any)}
              >
                {p.l}
              </button>
            ))}
          </div>
          <button className="bt" onClick={handleExportCsv}>
            <Icon name="dl" />
            Xuất báo cáo (CSV)
          </button>
        </div>
      </div>

      {/* 4 KPIs with sparklines */}
      <div className="rpk">
        <div className="cd kpi">
          <div className="l">Tổng chứng từ</div>
          <div className="v">{fmt(total)}</div>
          <div className="dl up">
            <Icon name="trendup" />
            +9,8% <span>so với kỳ trước</span>
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(11, 45)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Tỷ lệ tự động hóa (STP)</div>
          <div className="v">
            {avgStp.toFixed(1)}
            <small>%</small>
          </div>
          <div className="dl up">
            <Icon name="trendup" />
            +2,3 điểm <span>so với kỳ trước</span>
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(13, 30)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Độ chính xác trích xuất</div>
          <div className="v">
            {avgAcc.toFixed(1)}
            <small>%</small>
          </div>
          <div className={`dl ${avgAcc >= 97 ? "up" : "dn"}`}>
            {avgAcc >= 97 && <Icon name="trendup" />}
            Mục tiêu ≥ 97%
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(15, 50)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Giờ công tiết kiệm</div>
          <div className="v">
            {fmt(hours)}
            <small> giờ</small>
          </div>
          <div className="dl nt">
            <span>Ước tính 3,5 phút/chứng từ</span>
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(17, 20)) }} />
        </div>
      </div>

      <div className="rows">
        {/* Row 1 */}
        <div className="rw2" style={{ gridTemplateColumns: "1.55fr 1fr", flex: 1 }}>
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Khối lượng chứng từ theo loại</div>
                <div className="cs">{period === "quarter" ? "Theo tuần" : "Theo ngày"}</div>
              </div>
              <div className="lg">
                <span>
                  <i style={{ background: CC.s1 }}></i>Hóa đơn GTGT
                </span>
                <span>
                  <i style={{ background: CC.s2 }}></i>Phiếu nhập kho
                </span>
                <span>
                  <i style={{ background: CC.s3 }}></i>Đơn đặt hàng
                </span>
              </div>
            </div>
            <div className="cb">
              <div
                className="chart"
                dangerouslySetInnerHTML={{
                  __html: colChart({
                    labels,
                    series: [
                      { n: "Hóa đơn GTGT", c: CC.s1, v: s1 },
                      { n: "Phiếu nhập kho", c: CC.s2, v: s2 },
                      { n: "Đơn đặt hàng", c: CC.s3, v: s3 },
                    ],
                    step: c.step,
                  }),
                }}
              />
            </div>
          </div>

          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Tỷ lệ tự động hóa hoàn toàn (STP)</div>
                <div className="cs">Chứng từ không cần can thiệp thủ công</div>
              </div>
            </div>
            <div className="cb">
              <div
                className="chart"
                dangerouslySetInnerHTML={{
                  __html: lineChart({
                    labels,
                    vals: stp,
                    min: 70,
                    max: 100,
                    step: c.step,
                    name: "STP",
                  }),
                }}
              />
            </div>
          </div>
        </div>

        {/* Row 2 */}
        <div className="rw2" style={{ gridTemplateColumns: "1.15fr .95fr 1fr", flex: 1 }}>
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Top 5 nhà cung cấp theo giá trị</div>
                <div className="cs">Tổng thanh toán (VND)</div>
              </div>
            </div>
            <div className="cb">
              <div
                className="chart"
                dangerouslySetInnerHTML={{
                  __html: hbarChart(top),
                }}
              />
            </div>
          </div>

          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Phân bổ ngoại lệ</div>
                <div className="cs">{sum(exc.map((e) => e.v))} ngoại lệ trong kỳ</div>
              </div>
            </div>
            <div className="cb">
              <div className="dn-wrap" style={{ gap: "16px" }}>
                <div
                  dangerouslySetInnerHTML={{
                    __html: donutChart(exc, {
                      center: sum(exc.map((e) => e.v)),
                      sub: "ngoại lệ",
                    }),
                  }}
                />
                <div className="dl-list">
                  {exc.map((x, i) => (
                    <div key={i}>
                      <i style={{ background: x.c }}></i>
                      {x.label}
                      <b>{x.v}</b>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Độ chính xác theo trường</div>
                <div className="cs">Tỷ lệ trường khớp với kết quả kiểm tra</div>
              </div>
            </div>
            <div className="cb" style={{ justifyContent: "center" }}>
              {acc.map((a, i) => (
                <div key={i} className="acc">
                  <span>{a[0]}</span>
                  <div className="meter">
                    <i style={{ width: `${a[1]}%` }}></i>
                  </div>
                  <b>{a[1].toFixed(1)}%</b>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
};
