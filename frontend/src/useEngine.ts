import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FeedEvent, Incident, MttdSummary, ServiceMetrics, Snapshot } from "./types";

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

export interface EngineState {
  connected: boolean;
  snapshot: Snapshot | null;
  selectedService: string;
  selectedIncident: Incident | null;
  injectingUntil: number | null;
  injectionService: string | null;
  setSelectedService: (id: string) => void;
  setSelectedIncident: (incident: Incident | null) => void;
  inject: (service?: string) => Promise<void>;
  recover: (service?: string) => Promise<void>;
}

const EMPTY_MTTD: MttdSummary = {
  current: null,
  previous: null,
  history: [],
  improvement_pct: null,
  count: 0,
};

function emptySnapshot(): Snapshot {
  return {
    services: {},
    history: {},
    incidents: [],
    open_incidents: [],
    events: [],
    mttd: EMPTY_MTTD,
    topology: { nodes: [], edges: [] },
    config: {
      profile: "baseline",
      window: 60,
      z_threshold: 3,
      min_request_count: 20,
      consecutive_breaches: 3,
    },
  };
}

export function useEngine(): EngineState {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [selectedService, setSelectedService] = useState("payment-service");
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [injectingUntil, setInjectingUntil] = useState<number | null>(null);
  const [injectionService, setInjectionService] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retry: number | undefined;
    let poll: number | undefined;
    let ws: WebSocket | null = null;

    const applyFull = (data: Snapshot) => {
      setSnapshot(data);
      setSelectedIncident((current) => {
        const preferred =
          data.incidents.find((item) => item.mttd_seconds != null) ?? data.incidents[0] ?? null;
        if (current) {
          return data.incidents.find((item) => item.id === current.id) ?? preferred;
        }
        return preferred;
      });
    };

    const fetchSnapshot = () => {
      fetch("/api/snapshot")
        .then((r) => r.json())
        .then((data: Snapshot) => {
          if (!cancelled) applyFull(data);
        })
        .catch(() => undefined);
    };

    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        if (!cancelled) setConnected(true);
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data) as {
          type: string;
          payload: unknown;
          mttd?: MttdSummary;
        };
        if (msg.type === "snapshot") {
          applyFull(msg.payload as Snapshot);
          return;
        }
        setSnapshot((prev) => {
          const base = prev ?? emptySnapshot();
          if (msg.type === "metrics") {
            const payload = msg.payload as {
              services: Record<string, ServiceMetrics>;
              mttd: MttdSummary;
              timestamp: string;
              config: Snapshot["config"];
            };
            const history = { ...base.history };
            for (const [name, sample] of Object.entries(payload.services)) {
              history[name] = [...(history[name] ?? []), sample].slice(-180);
            }
            return {
              ...base,
              services: payload.services,
              history,
              mttd: payload.mttd,
              config: payload.config ?? base.config,
            };
          }
          if (msg.type === "incident") {
            const incident = msg.payload as Incident;
            if (incident.mttd_seconds != null) {
              setSelectedIncident(incident);
            }
            return {
              ...base,
              incidents: [incident, ...base.incidents.filter((i) => i.id !== incident.id)],
              mttd: msg.mttd ?? base.mttd,
            };
          }
          if (msg.type === "recovery") {
            const incident = msg.payload as Incident;
            return {
              ...base,
              incidents: base.incidents.map((i) => (i.id === incident.id ? incident : i)),
            };
          }
          if (msg.type === "injection") {
            const payload = msg.payload as {
              service: string;
              timestamp: string;
              recover?: boolean;
            };
            if (!payload.recover) {
              setInjectionService(payload.service);
              setInjectingUntil(Date.now() + 45000);
            } else {
              setInjectingUntil(null);
              setInjectionService(null);
            }
            const feed: FeedEvent = {
              type: "injection",
              service: payload.service,
              title: payload.recover ? "Injection cleared" : "Failure injected",
              timestamp: payload.timestamp,
              severity: "warning",
            };
            return { ...base, events: [feed, ...base.events].slice(0, 80) };
          }
          return base;
        });
      };
      ws.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        retry = window.setTimeout(connect, 2000);
      };
    };

    connect();
    fetchSnapshot();
    poll = window.setInterval(fetchSnapshot, 5000);

    return () => {
      cancelled = true;
      if (retry) window.clearTimeout(retry);
      if (poll) window.clearInterval(poll);
      ws?.close();
    };
  }, []);

  const inject = useCallback(async (service = selectedService) => {
    setInjectionService(service);
    setInjectingUntil(Date.now() + 45000);
    await fetch("/api/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service,
        mode: "http_500",
        rate: 0.8,
        duration: 45,
      }),
    });
  }, [selectedService]);

  const recover = useCallback(async (service = selectedService) => {
    setInjectingUntil(null);
    setInjectionService(null);
    await fetch("/api/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service, recover: true }),
    });
  }, [selectedService]);

  return useMemo(
    () => ({
      connected,
      snapshot,
      selectedService,
      selectedIncident,
      injectingUntil,
      injectionService,
      setSelectedService,
      setSelectedIncident,
      inject,
      recover,
    }),
    [
      connected,
      snapshot,
      selectedService,
      selectedIncident,
      injectingUntil,
      injectionService,
      inject,
      recover,
    ]
  );
}
