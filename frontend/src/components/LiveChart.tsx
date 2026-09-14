import { useId, useMemo } from "react";
import type { ServiceMetrics } from "../types";

type Point = { t: number; v: number };

function pathFrom(points: Point[], w: number, h: number, min: number, max: number): string {
  if (!points.length) return "";
  const span = Math.max(max - min, 1e-6);
  return points
    .map((p, i) => {
      const x = points.length === 1 ? 0 : (i / (points.length - 1)) * w;
      const y = h - ((p.v - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export default function LiveChart({
  title,
  value,
  series,
  color,
  format,
  anomaly,
}: {
  title: string;
  value: string;
  series: Point[];
  color: string;
  format?: (n: number) => string;
  anomaly?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const w = 320;
  const h = 88;
  const stats = useMemo(() => {
    const vals = series.map((p) => p.v);
    const min = Math.min(0, ...vals);
    const max = Math.max(...vals, 0.001);
    return { min, max: max * 1.08 };
  }, [series]);
  const d = pathFrom(series, w, h, stats.min, stats.max);
  const area = d ? `${d} L${w} ${h} L0 ${h} Z` : "";

  return (
    <article className="card chart-card">
      <h3>{title}</h3>
      <div className="stat" style={{ color }}>{value}</div>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="92" role="img" aria-label={title}>
        <defs>
          <linearGradient id={`g-${id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {anomaly && <rect x="0" y="0" width={w} height={h} fill="rgba(255,77,109,0.08)" />}
        <path d={area} fill={`url(#g-${id})`} />
        <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {format && series.length > 1 && (
          <text x="8" y="14" fill="#5c6578" fontSize="10" fontFamily="IBM Plex Mono, monospace">
            {format(stats.max)}
          </text>
        )}
      </svg>
    </article>
  );
}

export function toSeries(samples: ServiceMetrics[] | undefined, key: keyof ServiceMetrics): Point[] {
  return (samples ?? []).map((s, i) => ({ t: i, v: Number(s[key] ?? 0) }));
}
