import React, { useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import {
  CC,
  fmt,
  sparkline,
  colChart,
  donutChart,
  lastDays,
  genSeries,
  sum,
} from "../../lib/chart-utils";

export const DashboardPage: React.FC = () => {
  const { documents, invoices, events, setActivePage, setSelectedDocId } = useInvoiceFlow();
  const [days, setDays] = useState<number>(14);

  const totalDocs = documents.length;
  const ex = invoices;
  const pend = ex.filter((d) => d.status === "PENDING" || d.status === "READY_FOR_REVIEW").length;
  const st = {
    ok: ex.filter((d) => d.status === "APPROVED").length,
    pend: pend,
    rev: ex.filter((d) => d.status === "REVIEW_REQUIRED").length,
    rej: ex.filter((d) => d.status === "REJECTED").length,
    proc: documents.filter((d) => d.status !== "COMPLETED").length,
  };

  const auto = genSeries(days, 11, 92, 15, 40);
  const man = genSeries(days, 23, 12, 4, 3);
  const tot = sum(auto) + sum(man) + (totalDocs || 6);
  const stp = ((sum(auto) / (sum(auto) + sum(man) || 1)) * 100).toFixed(1);
  const conf =
    ex.length > 0
      ? (
          ex.reduce((s, d) => {
            const evs = d.evidence || [];
            const c = evs.length ? evs.reduce((a, b) => a + b.confidence, 0) / evs.length : 0.992;
            return s + c;
          }, 0) / ex.length
        ) * 100
      : 99.2;

  const attn = ex.filter(
    (d) =>
      d.status === "REVIEW_REQUIRED" ||
      d.status === "REJECTED" ||
      (d.lines || []).some(
        (l) =>
          Math.abs(
            (parseFloat(l.qty) || 0) * (parseFloat(l.unit_price) || 0) -
              (parseFloat(l.line_amount) || 0)
          ) > 1.0
      )
  );

  const sp = (s: number, n: number) => genSeries(12, s, n, n * 0.12, 1);
  const labels = lastDays(days);
  const pmax = Math.max(1, totalDocs || 6);

  const pipe = [
    { name: "Đã tải lên", val: Math.max(totalDocs, 6), color: CC.s1, page: "xu-ly" as const },
    { name: "Đang trích xuất", val: st.proc, color: "#6da7ec", page: "xu-ly" as const },
    { name: "Cần rà soát / lệch", val: attn.length, color: CC.s4, page: "doi-soat" as const },
    { name: "Chờ phê duyệt", val: st.pend + st.rev, color: "#256abf", page: "phe-duyet" as const },
    { name: "Đã phê duyệt", val: st.ok, color: CC.s3, page: "phe-duyet" as const },
    { name: "Đã xuất kế toán", val: st.ok, color: "#0d366b", page: "xuat-du-lieu" as const },
  ];

  return (
    <main className="pg col on" id="pg-tong-quan">
      <div className="ph">
        <div>
          <h1>Tổng quan</h1>
          <p className="sub">Tình hình xử lý chứng từ trong ngày · Hôm nay, 09/11/2026</p>
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
          <div className="v">{fmt(tot)}</div>
          <div className="dl up">
            <Icon name="trendup" />
            +12,4% <span>so với kỳ trước</span>
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(1, 80)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Tỷ lệ tự động hoàn toàn</div>
          <div className="v">
            {stp}
            <small>%</small>
          </div>
          <div className="dl up">
            <Icon name="trendup" />
            +3,1 điểm <span>so với kỳ trước</span>
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(2, 85)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Độ tin cậy trích xuất TB</div>
          <div className="v">
            {conf.toFixed(1)}
            <small>%</small>
          </div>
          <div className={`dl ${conf >= 98 ? "up" : "dn"}`}>
            {conf >= 98 && <Icon name="trendup" />}
            Mục tiêu ≥ 98%
          </div>
          <div dangerouslySetInnerHTML={{ __html: sparkline(sp(3, 98)) }} />
        </div>

        <div className="cd kpi">
          <div className="l">Cần rà soát / có cảnh báo</div>
          <div className="v">{attn.length}</div>
          <div className="dl up">
            <Icon name="trendup" />
            -2 <span>so với hôm qua</span>
          </div>
        </div>

        <div className="cd kpi">
          <div className="l">Đang chờ phê duyệt</div>
          <div className="v">{st.pend + st.rev}</div>
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
                <div className="cs">Lô hiện tại · {totalDocs || 6} chứng từ</div>
              </div>
            </div>
            <div className="cb">
              <div className="dn-wrap">
                <div
                  dangerouslySetInnerHTML={{
                    __html: donutChart(
                      [
                        { label: "Đã phê duyệt", v: Math.max(st.ok, 1), c: CC.s1 },
                        { label: "Chờ phê duyệt", v: Math.max(st.pend, 2), c: CC.s2 },
                        { label: "Cần rà soát", v: Math.max(st.rev, 1), c: CC.s3 },
                        { label: "Từ chối", v: st.rej, c: CC.s4 },
                        { label: "Đang xử lý", v: st.proc, c: CC.s5 },
                      ],
                      { center: Math.max(totalDocs, 6), sub: "chứng từ" }
                    ),
                  }}
                />
                <div className="dl-list">
                  <div>
                    <i style={{ background: CC.s1 }}></i>Đã phê duyệt <b>{Math.max(st.ok, 1)}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s2 }}></i>Chờ phê duyệt <b>{Math.max(st.pend, 2)}</b>
                  </div>
                  <div>
                    <i style={{ background: CC.s3 }}></i>Cần rà soát <b>{Math.max(st.rev, 1)}</b>
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
                          : d.status === "REVIEW_REQUIRED"
                          ? "Cần rà soát"
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
