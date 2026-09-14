import type { Health, ServiceMetrics, Topology } from "../types";

const DEFAULT_TOPOLOGY: Topology = {
  nodes: [
    { id: "api-gateway", label: "API Gateway", tier: 0 },
    { id: "user-service", label: "User Service", tier: 1 },
    { id: "payment-service", label: "Payment Service", tier: 1 },
    { id: "notification-service", label: "Notification Service", tier: 1 },
  ],
  edges: [
    { from: "api-gateway", to: "user-service" },
    { from: "api-gateway", to: "payment-service" },
    { from: "api-gateway", to: "notification-service" },
    { from: "user-service", to: "payment-service" },
  ],
};

const POS: Record<string, { x: number; y: number }> = {
  "api-gateway": { x: 330, y: 48 },
  "user-service": { x: 90, y: 188 },
  "payment-service": { x: 330, y: 188 },
  "notification-service": { x: 570, y: 188 },
};

const COLOR: Record<Health, string> = {
  healthy: "#3dd68c",
  degraded: "#f5c542",
  critical: "#ff4d6d",
  unknown: "#6b7385",
};

function statusOf(sample?: ServiceMetrics): Health {
  return sample?.health ?? "unknown";
}

function edgeHealth(from?: ServiceMetrics, to?: ServiceMetrics): Health {
  const states = [statusOf(from), statusOf(to)];
  if (states.includes("critical")) return "critical";
  if (states.includes("degraded")) return "degraded";
  if (states.includes("unknown")) return "unknown";
  return "healthy";
}

export default function TopologyMap({
  topology,
  services,
  selected,
  onSelect,
}: {
  topology: Topology | undefined;
  services: Record<string, ServiceMetrics>;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const nodes = (topology?.nodes?.length ? topology.nodes : DEFAULT_TOPOLOGY.nodes);
  const edges = (topology?.edges?.length ? topology.edges : DEFAULT_TOPOLOGY.edges);

  return (
    <section className="card topology">
      <div className="topology-head">
        <div className="kicker">LIVE SERVICE TOPOLOGY</div>
        <div className="legend">
          <span><i className="swatch" style={{ background: COLOR.healthy }} />Healthy</span>
          <span><i className="swatch" style={{ background: COLOR.degraded }} />Degraded</span>
          <span><i className="swatch" style={{ background: COLOR.critical }} />Critical</span>
        </div>
      </div>
      <svg className="topo-svg" viewBox="0 0 660 250">
        {edges.map((e) => {
          const a = POS[e.from];
          const b = POS[e.to];
          if (!a || !b) return null;
          const health = edgeHealth(services[e.from], services[e.to]);
          return (
            <path
              key={`${e.from}-${e.to}`}
              d={`M${a.x} ${a.y + 18} C ${a.x} ${(a.y + b.y) / 2}, ${b.x} ${(a.y + b.y) / 2}, ${b.x} ${b.y - 22}`}
              className={`edge flow ${health}`}
            />
          );
        })}
        {nodes.map((n) => {
          const p = POS[n.id] ?? { x: 0, y: 0 };
          const sample = services[n.id];
          const health = statusOf(sample);
          const color = COLOR[health];
          const active = selected === n.id;
          const rps = sample?.request_rate?.toFixed(1) ?? "0.0";
          return (
            <g key={n.id} className="node-hit" onClick={() => onSelect(n.id)}>
              <circle cx={p.x} cy={p.y} r={active ? 22 : 18} fill="rgba(13,18,28,0.95)" stroke={color} strokeWidth={active ? 3 : 2} />
              <circle cx={p.x} cy={p.y} r={6} fill={color}>
                {health === "critical" && (
                  <animate attributeName="opacity" values="1;0.35;1" dur="1s" repeatCount="indefinite" />
                )}
              </circle>
              {health === "critical" && (
                <circle cx={p.x} cy={p.y} r="18" fill="none" stroke={color} opacity="0.35">
                  <animate attributeName="r" values="16;28" dur="1.4s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.45;0" dur="1.4s" repeatCount="indefinite" />
                </circle>
              )}
              <text className="node-label" x={p.x} y={p.y + 36} textAnchor="middle">{n.label}</text>
              <text className="node-sub" x={p.x} y={p.y + 50} textAnchor="middle">{rps} rps · {health}</text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}
