import { useEffect, useMemo, useState } from "react";
import type { MttdSummary } from "../types";

function fmt(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—.—";
  return seconds.toFixed(2) + "s";
}

export default function MttdHero({
  mttd,
  injecting,
  detected,
  injectedAt,
}: {
  mttd: MttdSummary | undefined;
  injecting: boolean;
  detected: boolean;
  injectedAt: number | null;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!injecting || detected || !injectedAt) return;
    let raf = 0;
    const tick = () => {
      setElapsed((Date.now() - injectedAt) / 1000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [injecting, detected, injectedAt]);

  const display = useMemo(() => {
    if (detected && mttd?.current != null) return mttd.current;
    if (injecting) return elapsed;
    return mttd?.current ?? null;
  }, [detected, injecting, elapsed, mttd?.current]);

  const phase = injecting && !detected ? "Detecting injected failure" : detected ? "Detection latency" : "Awaiting next injection";
  const cls = injecting && !detected ? "live" : display != null ? "done" : "";
  const improvement = mttd?.improvement_pct;

  return (
    <section className="card mttd">
      <div className="kicker">MEAN TIME TO DETECT</div>
      <div className={`mttd-value ${cls}`}>{display == null ? "00.00s" : fmt(display)}</div>
      <div className="sub">{injecting && !detected ? "FAILURE INJECTED — timer running" : phase}</div>
      <div className="compare">
        <div>
          <div className="label">CURRENT MTTD</div>
          <div className="num">{fmt(mttd?.current)}</div>
        </div>
        <div>
          <div className="label">PREVIOUS MTTD</div>
          <div className="num">{fmt(mttd?.previous)}</div>
        </div>
      </div>
      {improvement != null && (
        <div className="delta">
          {improvement >= 0 ? `↓ ${improvement}% faster` : `↑ ${Math.abs(improvement)}% slower`} than previous detection
        </div>
      )}
    </section>
  );
}
