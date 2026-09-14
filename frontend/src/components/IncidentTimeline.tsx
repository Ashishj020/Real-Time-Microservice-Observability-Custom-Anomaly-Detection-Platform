import { useEffect, useRef } from "react";
import type { FeedEvent } from "../types";

function time(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour12: false });
  } catch {
    return ts;
  }
}

export default function IncidentTimeline({
  events,
  onSelectIncident,
}: {
  events: FeedEvent[];
  onSelectIncident?: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [events[0]?.timestamp]);

  return (
    <section className="card panel">
      <h2>INCIDENT TIMELINE</h2>
      <div className="feed" ref={ref}>
        {events.length === 0 && <div className="empty">Waiting for live events from the anomaly engine.</div>}
        {events.map((event, idx) => (
          <article
            key={`${event.timestamp}-${idx}`}
            className={`event ${event.severity ?? event.type}`}
            onClick={() => event.incident_id && onSelectIncident?.(event.incident_id)}
            style={{ cursor: event.incident_id ? "pointer" : "default" }}
          >
            <div className="time">{time(event.timestamp)}</div>
            <div>
              <div className="title">{event.title}</div>
              <div className="meta">
                {event.service} {event.detail ? `· ${event.detail}` : ""}
                {event.mttd_seconds != null ? ` · MTTD ${event.mttd_seconds.toFixed(2)}s` : ""}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
