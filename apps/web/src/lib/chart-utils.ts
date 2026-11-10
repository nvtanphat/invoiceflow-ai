export const CC = {
  s1: "#2a78d6",
  s2: "#eb6834",
  s3: "#1baf7a",
  s4: "#eda100",
  s5: "#e87ba4",
  grid: "#e8ecf2",
  ax: "#7b869a",
  tx: "#0f1b3d",
  tx2: "#5f6b7e",
  surf: "#ffffff",
};

export const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const fmtM = (n: number) =>
  n >= 1e9
    ? (n / 1e9).toFixed(2).replace(/\.?0+$/, "") + " tỷ"
    : n >= 1e6
    ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + " triệu"
    : fmt(n);

export const esc = (s: unknown) =>
  String(s == null ? "" : s).replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c] || c)
  );

export const pad = (n: number) => String(n).padStart(2, "0");

export const nice = (m: number) => {
  if (!m) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(m)));
  const f = m / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
};

export const axTick = (v: number) =>
  v >= 1e9 ? v / 1e9 + " tỷ" : v >= 1e6 ? v / 1e6 + " tr" : v >= 1e4 ? v / 1e3 + "K" : fmt(v);

export const rtop = (x: number, y: number, w: number, h: number, r: number) => {
  if (h <= 0) return "";
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
};

export const rright = (x: number, y: number, w: number, h: number, r: number) => {
  r = Math.min(r, w, h / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
};

export const tipHTML = (title: string, rows: [string, string, string][]) =>
  `<b>${title}</b>` +
  rows.map((r) => `<br><i style="background:${r[2]}"></i>${r[0]}: <b>${r[1]}</b>`).join("");

export const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);

export function colChart({
  labels,
  series,
  W = 640,
  H = 215,
  step = 1,
}: {
  labels: string[];
  series: { n: string; c: string; v: number[] }[];
  W?: number;
  H?: number;
  step?: number;
}): string {
  const m = { l: 40, r: 6, t: 10, b: 26 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;
  const n = labels.length;
  const tot = labels.map((_, i) => sum(series.map((s) => s.v[i])));
  const mx = nice(Math.max(...tot) * 1.04);
  const sc = ih / mx;
  const band = iw / n;
  const bw = Math.min(24, band * 0.62);
  let g = "";

  for (let k = 0; k <= 4; k++) {
    const v = (mx / 4) * k;
    const y = m.t + ih - v * sc;
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${CC.grid}"/><text x="${m.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="${CC.ax}">${axTick(v)}</text>`;
  }

  labels.forEach((lb, i) => {
    const cx = m.l + band * i + band / 2;
    const x = cx - bw / 2;
    let y0 = m.t + ih;
    const segs = series.map((s) => ({ s, v: s.v[i] })).filter((o) => o.v > 0);
    segs.forEach((o, j) => {
      const h = o.v * sc;
      const last = j === segs.length - 1;
      g += `<path d="${last ? rtop(x, y0 - h, bw, h, 4) : `M${x},${y0}V${y0 - h + 2}H${x + bw}V${y0}Z`}" fill="${o.s.c}"/>`;
      y0 -= h;
    });
    if (i % step === 0) {
      g += `<text x="${cx}" y="${H - 8}" text-anchor="middle" font-size="11" fill="${CC.ax}">${lb}</text>`;
    }
  });

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}</svg>`;
}

export function lineChart({
  labels,
  vals,
  W = 520,
  H = 215,
  color = CC.s1,
  unit = "%",
  min,
  max,
  step = 1,
  dec = 1,
}: {
  labels: string[];
  vals: number[];
  W?: number;
  H?: number;
  color?: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  name?: string;
  dec?: number;
}): string {
  const m = { l: 40, r: 44, t: 14, b: 26 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;
  const n = vals.length;
  const lo = min != null ? min : Math.floor(Math.min(...vals) - 2);
  const hi = max != null ? max : Math.ceil(Math.max(...vals) + 2);
  const X = (i: number) => m.l + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const Y = (v: number) => m.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
  let g = "";

  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) / 4) * k;
    const y = Y(v);
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${CC.grid}"/><text x="${m.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="${CC.ax}">${v.toFixed(0)}${unit}</text>`;
  }

  const pts = vals.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`);
  g += `<path d="M${pts.join("L")}L${X(n - 1)},${m.t + ih}L${X(0)},${m.t + ih}Z" fill="${color}" opacity=".1"/><polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;

  labels.forEach((lb, i) => {
    if (i % step === 0) {
      g += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="${CC.ax}">${lb}</text>`;
    }
    g += `<circle cx="${X(i)}" cy="${Y(vals[i])}" r="4.5" fill="${color}" stroke="${CC.surf}" stroke-width="2"/>`;
  });

  const lx = X(n - 1);
  const ly = Y(vals[n - 1]);
  g += `<circle cx="${lx}" cy="${ly}" r="4.5" fill="${color}" stroke="${CC.surf}" stroke-width="2"/><text x="${lx + 9}" y="${ly + 4}" font-size="12" font-weight="700" fill="${CC.tx}">${vals[n - 1].toFixed(dec)}${unit}</text>`;

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}</svg>`;
}

export function donutChart(
  items: { label: string; v: number; c: string }[],
  { center = "", sub = "" }: { center?: string | number; sub?: string } = {}
): string {
  const r = 64;
  const sw = 22;
  const C = 2 * Math.PI * r;
  const total = sum(items.map((i) => i.v)) || 1;
  let off = 0;
  let g = `<circle cx="85" cy="85" r="${r}" fill="none" stroke="#eef1f6" stroke-width="${sw}"/>`;

  items.forEach((it) => {
    if (!it.v) return;
    const len = (it.v / total) * C;
    const gap = items.filter((x) => x.v).length > 1 ? 2 : 0;
    g += `<circle class="seg2" cx="85" cy="85" r="${r}" fill="none" stroke="${it.c}" stroke-width="${sw}" stroke-dasharray="${Math.max(0, len - gap)} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 85 85)"/>`;
    off += len;
  });

  g += `<text x="85" y="86" text-anchor="middle" font-size="26" font-weight="800" fill="${CC.tx}">${center}</text><text x="85" y="104" text-anchor="middle" font-size="11.5" fill="${CC.tx2}">${sub}</text>`;
  return `<svg viewBox="0 0 170 170">${g}</svg>`;
}

export function hbarChart(
  items: { label: string; v: number }[],
  { W = 520, H = 230, color = CC.s1 }: { W?: number; H?: number; color?: string } = {}
): string {
  const m = { l: 172, r: 76, t: 6, b: 6 };
  const ih = H - m.t - m.b;
  const n = items.length || 1;
  const band = ih / n;
  const bh = Math.min(22, band * 0.6);
  const mx = nice(Math.max(...items.map((i) => i.v), 1) * 1.02);
  const iw = W - m.l - m.r;
  let g = "";

  items.forEach((it, i) => {
    const cy = m.t + band * i + band / 2;
    const w = Math.max(4, (it.v / mx) * iw);
    const sl = it.label.replace(/^CÔNG TY /, "");
    const lb = sl.length > 21 ? sl.slice(0, 20) + "…" : sl;
    g += `<text x="${m.l - 10}" y="${cy + 4}" text-anchor="end" font-size="12" fill="${CC.tx}">${esc(lb)}</text><path d="${rright(m.l, cy - bh / 2, w, bh, 4)}" fill="${color}"/><text x="${m.l + w + 8}" y="${cy + 4}" font-size="12" font-weight="700" fill="${CC.tx}">${fmtM(it.v)}</text>`;
  });

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}</svg>`;
}

export function sparkline(vals: number[], color = CC.s1): string {
  const W = 88;
  const H = 34;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const X = (i: number) => 3 + ((W - 10) * i) / (vals.length - 1);
  const Y = (v: number) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 10);
  const p = vals.map((v, i) => X(i).toFixed(1) + "," + Y(v).toFixed(1));
  return `<svg class="sp" viewBox="0 0 ${W} ${H}"><polyline points="${p.join(" ")}" fill="none" stroke="#b9c9e6" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${X(vals.length - 1)}" cy="${Y(vals[vals.length - 1])}" r="4" fill="${color}" stroke="#fff" stroke-width="2"/></svg>`;
}
