export type Health = "healthy" | "degraded" | "critical" | "unknown";

export interface ServiceMetrics {
  service: string;
  request_count: number;
  error_count_window: number;
  error_rate: number;
  request_rate: number;
  p95_latency: number;
  health_value: number;
  injection_active: boolean;
  success_count: number;
  error_count: number;
  timestamp: string;
  z_score: number;
  baseline: number;
  sigma: number;
  health: Health;
  in_incident: boolean;
  breach_streak: number;
}

export interface TimelineStep {
  status: string;
  at: string | null;
  label: string;
}

export interface Incident {
  id: string;
  service: string;
  metric: string;
  status: string;
  severity: string;
  value: number;
  baseline: number;
  z_score: number;
  reason: string;
  injected_at: string | null;
  detected_at: string | null;
  alerted_at: string | null;
  recovered_at: string | null;
  mttd_seconds: number | null;
  slack: Record<string, unknown>;
  injection: Record<string, unknown>;
  timeline: TimelineStep[];
  timestamp?: string;
}

export interface FeedEvent {
  type: string;
  service?: string;
  severity?: string;
  title: string;
  detail?: string;
  incident_id?: string;
  value?: number;
  z_score?: number;
  mttd_seconds?: number | null;
  timestamp: string;
}

export interface MttdSummary {
  current: number | null;
  previous: number | null;
  history: number[];
  improvement_pct: number | null;
  count: number;
}

export interface Topology {
  nodes: { id: string; label: string; tier: number }[];
  edges: { from: string; to: string }[];
}

export interface EngineConfig {
  profile: string;
  window: number;
  z_threshold: number;
  min_request_count: number;
  consecutive_breaches: number;
  sample_interval?: number;
}

export interface Snapshot {
  services: Record<string, ServiceMetrics>;
  history: Record<string, ServiceMetrics[]>;
  incidents: Incident[];
  open_incidents: string[];
  events: FeedEvent[];
  mttd: MttdSummary;
  topology: Topology;
  config: EngineConfig;
}
