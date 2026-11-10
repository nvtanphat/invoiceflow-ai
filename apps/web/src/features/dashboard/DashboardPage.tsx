import React, { useEffect, useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { api, ProcessingSummary } from "../../lib/api-client";
import { CC, fmt, sparkline, colChart, donutChart } from "../../lib/chart-utils";
import { meanConfidence } from "../../lib/confidence";

export const DashboardPage: React.FC = () => {
  const { documents, invoices, events, setActivePage, setSelectedDocId } = useInvoiceFlow();
  const [days, setDays] = useState<number>(14);

  const [summary, setSummary] = useState<ProcessingSummary | null>(null);

  useEffect(() => {
    let active = true;
    api
      .getProcessingSummary(days)
      .then((data) => active && setSummary(data))
      .catch(() => active && setSummary(null));
    return () => {
      active = false;
    };
  }, [days, invoices]);

  const totalDocs = documents.length;
  const ex = invoices;
  const st = {
    ok: ex.filter((d) => d.status === "APPROVED").length,
    pend: ex.filter((d) => d.status === "READY_FOR_REVIEW").length,
    rej: ex.filter((d) => d.status === "REJECTED").length,
    exported: ex.filter((d) => d.status === "EXPORTED").length,
    proc: documents.filter((d) => d.status !== "COMPLETED").length,
  };

  const daily = summary?.days ?? [];
  const auto = daily.map((d) => d.auto_approved);
  const man = daily.map((d) => d.routed_to_review);
  const labels = daily.map((d) => `${d.date.slice(8, 10)}/${d.date.slice(5, 7)}`);
  const received = summary ? summary.totals.received : null;
  const prevReceived = summary ? summary.previous_totals.received : null;
  const receivedDelta =
    received !== null && prevReceived ? ((received - prevReceived) / prevReceived) * 100 : null;
  const stp = summary?.stp_rate != null ? summary.stp_rate * 100 : null;
  const stpDelta =
    summary?.stp_rate != null && summary.previous_stp_rate != null
      ? (summary.stp_rate - summary.previous_stp_rate) * 100
      : null;
  const today = new Date().toLocaleDateString("vi-VN");
  const allEvidences = ex.flatMap((d) => d.evidence || []);
  const measured = meanConfidence(allEvidences);
  const conf = measured !== null ? measured * 100 : null;

  const attn = ex.filter(
    (d) =>
      d.status === "REJECTED" ||
      Boolean(d.issues && d.issues.some((i) => i.severity === "ERROR" || i.severity === "critical")) ||
      (d.lines || []).some(
        (l) =>
          Math.abs(
            (parseFloat(l.qty) || 0) * (parseFloat(l.unit_price) || 0) -
              (parseFloat(l.line_amount) || 0)
          ) > 1.0
      )
  );

  const pmax = Math.max(1, totalDocs);

  const pipe = [
    { name: "Đã tải lên", val: totalDocs, color: CC.s1, page: "xu-ly" as const },
    { name: "Đang trích xuất", val: st.proc, color: "#6da7ec", page: "xu-ly" as const },
    { name: "Cần rà soát / lệch", val: attn.length, color: CC.s4, page: "doi-soat" as const },
    { name: "Chờ phê duyệt", val: st.pend, color: "#256abf", page: "phe-duyet" as const },
    { name: "Đã phê duyệt", val: st.ok, color: CC.s3, page: "phe-duyet" as const },
    { name: "Đã xuất kế toán", val: st.exported, color: "#0d366b", page: "xuat-du-lieu" as const },
  ];

  return (
    <main className="pg col on" id="pg-tong-quan">
      <div className="ph">
        <div>
          <h1>Tổng quan</h1>
          <p className="sub">Tình hình xử lý chứng từ · Hôm nay, {today}</p>
        </div>
        <div className="pha">
          <div className="sg" id="dsg">
            {[7, 14, 30].map((n) => (
              <button
                key={n}
                className={days === n ? "on" : ""}
                onClick={() => setDays(n)}
              >
                {n} ngày
              </button>
            ))}
          </div>
          <button className="bt p" onClick={() => setActivePage("xu-ly")}>
            <Icon name="upcloud" />
            Tải lên chứng từ
          </button>
        </div>
      </div>

      {/* 5 KPIs with sparklines */}
      <div className="kpis">
        <div className="cd kpi">
          <div className="l">Chứng từ đã xử lý</div>
          <div className="v">{received !== null ? fmt(received) : "—"}</div>
          <div className={`dl ${receivedDelta !== null && receivedDelta < 0 ? "dn" : "up"}`}>
            {receivedDelta !== null ? `${receivedDelta >= 0 ? "+" : ""}${receivedDelta.toFixed(1)}%` : "—"}{" "}
            <span>so với kỳ trước</span>
          </div>
          {daily.length > 0 && (
            <div dangerouslySetInnerHTML={{ __html: sparkline(daily.map((d) => d.received)) }} />
          )}
        </div>

        <div className="cd kpi">
          <div className="l">Tỷ lệ tự động hoàn toàn</div>
          <div className="v">
            {stp !== null ? stp.toFixed(1) : "—"}
            <small>%</small>
          </div>
          <div className={`dl ${stpDelta !== null && stpDelta < 0 ? "dn" : "up"}`}>
            {stpDelta !== null ? `${stpDelta >= 0 ? "+" : ""}${stpDelta.toFixed(1)} điểm` : "—"}{" "}
            <span>so với kỳ trước</span>
          </div>
          {daily.length > 0 && <div dangerouslySetInnerHTML={{ __html: sparkline(auto) }} />}
        </div>

        <div className="cd kpi">
          <div className="l">Độ tin cậy trích xuất TB</div>
          <div className="v">
            {conf !== null ? conf.toFixed(1) : "—"}
            <small>%</small>
          </div>
          <div className={`dl ${conf !== null && conf >= 98 ? "up" : "dn"}`}>
            {conf !== null && conf >= 98 && <Icon name="trendup" />}
            Mục tiêu ≥ 98%
          </div>
        </div>

        <div className="cd kpi">
          <div className="l">Cần rà soát / có cảnh báo</div>
          <div className="v">{attn.length}</div>
          <div className="dl nt">
            <span>Từ chối, issue nghiêm trọng hoặc lệch số học</span>
          </div>
        </div>

        <div className="cd kpi">
          <div className="l">Đang chờ phê duyệt</div>
          <div className="v">{st.pend}</div>
          <div className="dl nt">
            <span>Trong hạn mức</span>
          </div>
        </div>
      </div>

      <div className="rows">
        {/* Row 1 */}
        <div className="rw2" style={{ gridTemplateColumns: "1.7fr 1fr 1.1fr", flex: 1.2 }}>
          {/* Chart 1: Daily column */}
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Chứng từ xử lý theo ngày</div>
                <div className="cs">{days} ngày gần nhất</div>
              </div>
              <div className="lg">
                <span>
                  <i style={{ background: CC.s1 }}></i>Tự động hoàn toàn
                </span>
                <span>
                  <i style={{ background: CC.s2 }}></i>Có rà soát thủ công
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
                      { n: "Tự động hoàn toàn", c: CC.s1, v: auto },
                      { n: "Có rà soát thủ công", c: CC.s2, v: man },
                    ],
                    step: days > 14 ? 4 : days > 7 ? 2 : 1,
                  }),
                }}
              />
            </div>
          </div>

          {/* Chart 2: Status Donut */}
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Trạng thái chứng từ</div>
                <div className="cs">Lô hiện tại · {totalDocs} chứng từ</div>
              </div>
            </div>
            <div className="cb">
              <div className="dn-wrap">
                <div
                  dangerouslySetInnerHTML={{
                    __html: donutChart(
                      [
                        { label: "Đã phê duyệt", v: st.ok, c: CC.s1 },
                        { label: "Chờ phê duyệt", v: st.pend, c: CC.s2 },
                        { label: "Đã xuất", v: st.exported, c: CC.s3 },
                        { label: "Từ chối", v: st.rej, c: CC.s4 },
                        { label: "Đang xử lý", v: st.proc, c: CC.s5 },
                      ],
                      { center: totalDocs, sub: "chứng từ" }
                    ),
                  }}
                />
                <div className="dl-list">
                  <div>
                    <i style={{ background: CC.s1 }}></i>Đã phê duyệt <b>{st.ok}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s2 }}></i>Chờ phê duyệt <b>{st.pend}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s3 }}></i>Đã xuất <b>{st.exported}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s4 }}></i>Từ chối <b>{st.rej}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s5 }}></i>Đang xử lý <b>{st.proc}</b>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Card 3: Attention items */}
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Cần chú ý</div>
                <div className="cs">{attn.length} chứng từ có ngoại lệ</div>
              </div>
              <button className="bt s" onClick={() => setActivePage("doi-soat")}>
                Xem đối soát
              </button>
            </div>
            <div className="cb">
              <div className="exl">
                {attn.length ? (
                  attn.slice(0, 5).map((d) => (
                    <div
                      key={d.id}
                      className="exi"
                      onClick={() => {
                        setSelectedDocId(d.document_id);
                        setActivePage("xu-ly");
                      }}
                    >
                      <Icon name="alert" />
                      <div>
                        <b>#{d.invoice_number || d.id}</b>
                        <small>{d.supplier_name || "Nhà cung cấp"}</small>
                      </div>
                      <span className="k k-a">
                        {d.status === "REJECTED"
                          ? "Từ chối"
                          : d.issues && d.issues.length > 0
                          ? "Có issue"
                          : "Lệch số học"}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="empty">
                    <Icon name="circlecheck" />
                    Không có ngoại lệ nào cần xử lý
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Row 2 */}
        <div className="rw2" style={{ gridTemplateColumns: "1.25fr 1fr", flex: 0.8 }}>
          {/* Card 4: Pipeline stages */}
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Tiến trình lô chứng từ</div>
                <div className="cs">
                  Từ tải lên đến xuất sang phần mềm kế toán · nhấn để mở
                </div>
              </div>
            </div>
            <div className="cb">
              <div className="pipe">
                {pipe.map((p, i) => (
                  <div
                    key={i}
                    className="pst"
                    onClick={() => setActivePage(p.page)}
                  >
                    <div className="n">{p.val}</div>
                    <div className="t">{p.name}</div>
                    <div className="bar2">
                      <i
                        style={{
                          width: `${Math.max(6, (p.val / pmax) * 100)}%`,
                          background: p.color,
                        }}
                      ></i>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Card 5: Recent activity */}
          <div className="cd">
            <div className="ch">
              <div>
                <div className="ct">Hoạt động gần đây</div>
              </div>
            </div>
            <div className="cb">
              <div className="act">
                {events.slice(0, 8).map((e) => (
                  <div
                    key={e.id}
                    className="ai"
                    onClick={() => {
                      if (e.docId) setSelectedDocId(e.docId);
                      if (e.page) setActivePage(e.page);
                    }}
                  >
                    <Icon name={e.icon || "check"} />
                    <span>{e.txt}</span>
                    <time>{e.t}</time>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
};
