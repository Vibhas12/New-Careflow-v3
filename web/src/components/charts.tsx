/** SVG charts – same geometry, colours and legend as V2 barChart() / lineChart() (frontend/src/04-ui.js). */
const SER = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)']
type Series = { name: string; values: (number | null)[] }

function scale(series: Series[], max?: number) {
  const m = max ?? Math.max(1, ...series.flatMap((s) => s.values.map((v) => v ?? 0)))
  const step = Math.pow(10, Math.floor(Math.log10(m)))
  return Math.ceil(m / step) * step || 1
}

function Legend({ names }: { names: string[] }) {
  return names.length > 1 ? <div className="legend">{names.map((n, i) => <span key={n}><i style={{ background: SER[i % 4] }} />{n}</span>)}</div> : null
}

function Grid({ top, L, R, W, Tp, ih, fmt }: { top: number; L: number; R: number; W: number; Tp: number; ih: number; fmt: (v: number) => string }) {
  return <>{[0, 1, 2, 3, 4].map((i) => { const y = Tp + ih - (ih * i) / 4; return <g key={i}><line x1={L} x2={W - R} y1={y} y2={y} stroke="#e3eaf2" />
    <text x={L - 6} y={y + 4} textAnchor="end" fontSize="10.5" fill="#5b6b7c">{fmt(Math.round(((top * i) / 4) * 10) / 10)}</text></g> })}</>
}

export function BarChart({ title, labels, series, max, fmt = String, h = 210 }: { title: string; labels: string[]; series: Series[]; max?: number; fmt?: (v: number) => string; h?: number }) {
  const W = 640, H = h, L = 38, B = 26, Tp = 10, R = 26, n = Math.max(1, labels.length), k = series.length
  const top = scale(series, max), iw = W - L - R, ih = H - B - Tp, gw = iw / n, bw = Math.min(34, (gw * 0.7) / k)
  return (
    <div className="chartbox"><svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}>
      <Grid top={top} L={L} R={R} W={W} Tp={Tp} ih={ih} fmt={fmt} />
      {labels.map((lb, i) => { const cx = L + gw * i + gw / 2; return <g key={i}>
        <text x={cx} y={H - 8} textAnchor="middle" fontSize="10.5" fill="#5b6b7c">{lb}</text>
        {series.map((s, j) => { const v = s.values[i] ?? 0, hh = (ih * v) / top, x = cx - (bw * k + 2 * (k - 1)) / 2 + j * (bw + 2)
          return <rect key={j} x={x} y={Tp + ih - hh} width={bw} height={Math.max(hh, v ? 1 : 0)} rx="3" fill={SER[j % 4]}><title>{`${lb} · ${s.name}: ${fmt(v)}`}</title></rect> })}
      </g> })}
    </svg><Legend names={series.map((s) => s.name)} /></div>
  )
}

export function LineChart({ title, labels, series, max, fmt = String, h = 210 }: { title: string; labels: string[]; series: Series[]; max?: number; fmt?: (v: number) => string; h?: number }) {
  const W = 640, H = h, L = 38, B = 26, Tp = 10, R = 30, n = labels.length
  const top = scale(series, max), iw = W - L - R, ih = H - B - Tp
  const X = (i: number) => L + (n < 2 ? iw / 2 : (iw * i) / (n - 1)), Y = (v: number) => Tp + ih - (ih * v) / top
  return (
    <div className="chartbox"><svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}>
      <Grid top={top} L={L} R={R} W={W} Tp={Tp} ih={ih} fmt={fmt} />
      {labels.map((lb, i) => <text key={i} x={X(i)} y={H - 8} textAnchor="middle" fontSize="10.5" fill="#5b6b7c">{lb}</text>)}
      {series.map((s, j) => <g key={j}>
        <polyline fill="none" stroke={SER[j % 4]} strokeWidth="2" strokeLinejoin="round"
          points={s.values.map((v, i) => (v == null ? null : `${X(i)},${Y(v)}`)).filter(Boolean).join(' ')} />
        {s.values.map((v, i) => v == null ? null : <circle key={i} cx={X(i)} cy={Y(v)} r="4.5" fill={SER[j % 4]} stroke="#fff" strokeWidth="2"><title>{`${labels[i]} · ${s.name}: ${fmt(v)}`}</title></circle>)}
      </g>)}
    </svg><Legend names={series.map((s) => s.name)} /></div>
  )
}
