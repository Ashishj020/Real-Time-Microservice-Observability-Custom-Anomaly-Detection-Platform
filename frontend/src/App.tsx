import { useMemo } from "react";
import IncidentDetail from "./components/IncidentDetail";
import IncidentTimeline from "./components/IncidentTimeline";
import LiveChart, { toSeries } from "./components/LiveChart";
import MttdHero from "./components/MttdHero";
import TopologyMap from "./components/Topology";
import { useEngine } from "./useEngine";

function pct(n: number | undefined): string {
  return `${((n ?? 0) * 100).toFixed(1)}%`;
}

export default function App() {
  const engine = useEngine();
  const snap = engine.snapshot;
  const selected = snap?.services[engine.selectedService];
  const history = snap?.history[engine.selectedService] ?? [];
  const open = snap?.incidents.find((i) => i.status !== "recovered" && i.service === engine.injectionService);
  const detecting = Boolean(engine.injectingUntil && engine.injectingUntil > Date.now() && !open?.detected_at);
  const detected = Boolean(open?.detected_at || (engine.injectingUntil && snap?.mttd.current != null && open));

  const injectedAt = useMemo(() => {
    if (!engine.injectingUntil) return null;
    return engine.injectingUntil - 45000;
  }, [engine.injectingUntil]);

  const errorSeries = toSeries(history, "error_rate");
  const rpsSeries = toSeries(history, "request_rate");
  const latSeries = toSeries(history, "p95_latency");
  const failSeries = toSeries(history, "error_count");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="mark" />
          <div>
            <h1>AETHER OBSERVABILITY</h1>
            <p>Custom anomaly engine · live microservice cluster</p>
          </div>
        </div>
        <div className="actions">
          <div className="live-pill">
            <span className={`dot ${engine.connected ? "" : "off"}`} />
            {engine.connected ? "LIVE STREAM" : "RECONNECTING"}
          </div>
          <button className="btn danger" onClick={() => engine.inject("payment-service")}>
            Inject payment failure
          </button>
          <button className="btn ghost" onClick={() => engine.recover("payment-service")}>
            Recover
          </button>
        </div>
      </header>

      <div className="hero-grid">
        <MttdHero
          mttd={snap?.mttd}
          injecting={Boolean(engine.injectingUntil && engine.injectingUntil > Date.now())}
          detected={Boolean(open?.detected_at)}
          injectedAt={injectedAt}
        />
        <TopologyMap
          topology={snap?.topology}
          services={snap?.services ?? {}}
          selected={engine.selectedService}
          onSelect={engine.setSelectedService}
        />
      </div>

      <section className="metrics">
        <LiveChart
          title="ERROR RATE"
          value={pct(selected?.error_rate)}
          series={errorSeries}
          color="#ff4d6d"
          anomaly={selected?.in_incident || (selected?.error_rate ?? 0) > 0.15}
        />
        <LiveChart
          title="REQUEST RATE"
          value={`${(selected?.request_rate ?? 0).toFixed(1)} rps`}
          series={rpsSeries}
          color="#7aa2ff"
        />
        <LiveChart
          title="P95 LATENCY"
          value={`${((selected?.p95_latency ?? 0) * 1000).toFixed(0)} ms`}
          series={latSeries}
          color="#67e8f9"
        />
        <LiveChart
          title="FAILED REQUESTS"
          value={`${Math.round(selected?.error_count ?? 0)}`}
          series={failSeries}
          color="#f5c542"
        />
      </section>

      <div className="lower">
        <IncidentTimeline
          events={snap?.events ?? []}
          onSelectIncident={(id) => {
            const found = snap?.incidents.find((item) => item.id === id);
            if (found) engine.setSelectedIncident(found);
          }}
        />
        <IncidentDetail
          incident={engine.selectedIncident}
          service={engine.selectedIncident ? snap?.services[engine.selectedIncident.service] : selected}
        />
      </div>

      <div style={{ color: "#5c6578", fontSize: 12 }}>
        Viewing {engine.selectedService}
        {selected ? ` · z=${selected.z_score} · baseline=${pct(selected.baseline)} · profile=${snap?.config.profile}` : ""}
        {detecting ? " · detection in progress" : detected ? " · anomaly captured" : ""}
      </div>
    </div>
  );
}
