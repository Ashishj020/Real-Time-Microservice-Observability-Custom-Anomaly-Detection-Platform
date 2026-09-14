import type { Incident, ServiceMetrics } from "../types";

const STEPS = ["INJECTED", "DETECTED", "ALERTED", "RECOVERED"] as const;

function fmt(ts: string | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleTimeString([], { hour12: false });
}

export default function IncidentDetail({
  incident,
  service,
}: {
  incident: Incident | null;
  service?: ServiceMetrics;
}) {
  if (!incident) {
    return (
      <section className="card panel">
        <h2>INCIDENT DETAIL</h2>
        <div className="empty">No incident selected. Inject a failure to generate one.</div>
      </section>
    );
  }

  const reached = new Set(incident.timeline.map((s) => s.status));
  const slack = incident.slack as { sent?: boolean; reason?: string };

  return (
    <section className="card panel">
      <h2>INCIDENT DETAIL</h2>
      <div style={{ fontFamily: "IBM Plex Mono, monospace", marginBottom: 8 }}>{incident.id}</div>
      <div className="lifecycle">
        {STEPS.map((step) => (
          <span key={step} className={`chip ${reached.has(step) ? (step === "RECOVERED" ? "done" : "on") : ""}`}>
            {step}
          </span>
        ))}
      </div>
      <dl className="kv">
        <dt>Service</dt>
        <dd>{incident.service}</dd>
        <dt>Severity</dt>
        <dd>{incident.severity.toUpperCase()}</dd>
        <dt>Error rate</dt>
        <dd>{(incident.value * 100).toFixed(1)}%</dd>
        <dt>Baseline</dt>
        <dd>{(incident.baseline * 100).toFixed(1)}%</dd>
        <dt>Z-score</dt>
        <dd>{incident.z_score}</dd>
        <dt>Injected</dt>
        <dd>{fmt(incident.injected_at)}</dd>
        <dt>Detected</dt>
        <dd>{fmt(incident.detected_at)}</dd>
        <dt>Alerted</dt>
        <dd>{fmt(incident.alerted_at)}</dd>
        <dt>Recovered</dt>
        <dd>{fmt(incident.recovered_at)}</dd>
        <dt>MTTD</dt>
        <dd>{incident.mttd_seconds != null ? `${incident.mttd_seconds.toFixed(2)}s` : "pending"}</dd>
        <dt>Slack</dt>
        <dd>{slack?.sent ? "sent" : slack?.reason ?? "n/a"}</dd>
        <dt>Injection</dt>
        <dd>
          {String(incident.injection?.mode ?? "http_500")} @ {String(incident.injection?.rate ?? "—")}
        </dd>
      </dl>
      {service && (
        <div className="meta" style={{ marginTop: 14, color: "#8b95a8", fontSize: 12 }}>
          Live: {(service.error_rate * 100).toFixed(1)}% errors · z={service.z_score} · {service.health}
        </div>
      )}
    </section>
  );
}
