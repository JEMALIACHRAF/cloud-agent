import React, { useState, useEffect, useCallback } from "react";
import {
  IconShield, IconDollar, IconRefresh, IconZap,
  IconAlertTriangle, IconCircleAlert, IconInfo, IconCheckCircle,
  IconList, IconActivity, IconTerminal,
} from "../Icons";

const BACKEND = "http://localhost:8000";

const SEV_CONFIG = {
  critical: { label: "CRITICAL", color: "var(--danger)",  bg: "rgba(248,113,113,0.08)", border: "rgba(248,113,113,0.25)", Icon: IconCircleAlert    },
  high:     { label: "HIGH",     color: "#fb923c",        bg: "rgba(251,146,60,0.08)",  border: "rgba(251,146,60,0.25)",  Icon: IconAlertTriangle  },
  medium:   { label: "MEDIUM",   color: "var(--warning)", bg: "rgba(251,191,36,0.08)",  border: "rgba(251,191,36,0.25)",  Icon: IconAlertTriangle  },
  low:      { label: "LOW",      color: "var(--info)",    bg: "rgba(96,165,250,0.08)",  border: "rgba(96,165,250,0.25)",  Icon: IconInfo            },
};

const CATEGORY_ICONS = {
  security:     IconShield,
  cost:         IconDollar,
  hygiene:      IconRefresh,
  availability: IconZap,
};

export default function AuditView({ credentials }) {
  const [tab,       setTab]       = useState("alerts");
  const [alerts,    setAlerts]    = useState([]);
  const [logs,      setLogs]      = useState([]);
  const [scanning,  setScanning]  = useState(false);
  const [scannedAt, setScannedAt] = useState(null);
  const [filter,    setFilter]    = useState("all");

  const loadAlerts = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/agent/scan/results`);
      if (!r.ok) return;
      const data = await r.json();
      setAlerts(data.alerts || []);
      if (data.scanned_at) setScannedAt(new Date(data.scanned_at));
    } catch {}
  }, []);

  const loadLogs = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/audit/logs?limit=200`);
      if (!r.ok) return;
      const data = await r.json();
      setLogs(data.logs || []);
    } catch {}
  }, []);

  useEffect(() => { loadAlerts(); loadLogs(); }, [loadAlerts, loadLogs]);

  const triggerScan = async () => {
    if (!credentials?.aws_access_key_id) return;
    setScanning(true);
    try {
      await fetch(`${BACKEND}/agent/scan`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credentials }),
      });
      setTimeout(loadAlerts, 1500);
    } finally { setScanning(false); }
  };

  const filtered = filter === "all" ? alerts : alerts.filter(a => a.severity === filter);
  const counts = {
    critical: alerts.filter(a => a.severity === "critical").length,
    high:     alerts.filter(a => a.severity === "high").length,
    medium:   alerts.filter(a => a.severity === "medium").length,
    low:      alerts.filter(a => a.severity === "low").length,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)", fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      {/* Header */}
      <div style={{
        padding: "18px 28px", borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16,
      }}>
        <div>
          <h1 style={{ fontSize: 16, fontWeight: 600, color: "var(--text-strong)", margin: "0 0 4px", letterSpacing: "-0.2px" }}>
            Audit
          </h1>
          <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>
            Proactive security scan + execution audit trail
            {scannedAt && <span style={{ marginLeft: 10, color: "var(--text-vfaint)" }}>· last scan {scannedAt.toLocaleTimeString()}</span>}
          </p>
        </div>
        <button onClick={triggerScan} disabled={scanning || !credentials?.aws_access_key_id} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "7px 14px", borderRadius: 7, border: "none", cursor: "pointer",
          background: "var(--accent)", color: "#fff", fontSize: 12, fontWeight: 500, fontFamily: "inherit",
          opacity: (scanning || !credentials?.aws_access_key_id) ? 0.5 : 1,
        }}>
          {scanning ? <Spinner /> : <IconRefresh size={13} />}
          {scanning ? "Scanning…" : "Rescan now"}
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)", paddingLeft: 22 }}>
        {[
          { id: "alerts", label: "Alerts", Icon: IconAlertTriangle, badge: alerts.length },
          { id: "logs",   label: "Activity log", Icon: IconTerminal,   badge: null },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            display: "flex", alignItems: "center", gap: 7,
            padding: "12px 16px", border: "none", background: "transparent", cursor: "pointer",
            borderBottom: `2px solid ${tab === t.id ? "var(--accent)" : "transparent"}`,
            color: tab === t.id ? "var(--text-body)" : "var(--text-faint)",
            fontSize: 12, fontWeight: 500, fontFamily: "inherit",
          }}>
            <t.Icon size={13} /> {t.label}
            {t.badge !== null && t.badge > 0 && (
              <span style={{
                fontSize: 9, fontWeight: 700, padding: "1px 7px", borderRadius: 9,
                background: "var(--bg-card)", border: "1px solid var(--border-strong)", color: "var(--text-dim)",
              }}>{t.badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>
        {tab === "alerts" && (
          <div style={{ maxWidth: 920, margin: "0 auto" }}>
            {/* Severity filter chips */}
            <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
              <FilterChip label="All" count={alerts.length}    active={filter === "all"}      onClick={() => setFilter("all")} />
              <FilterChip label="Critical" count={counts.critical} active={filter === "critical"} onClick={() => setFilter("critical")} color="var(--danger)"  />
              <FilterChip label="High"     count={counts.high}     active={filter === "high"}     onClick={() => setFilter("high")}     color="#fb923c"        />
              <FilterChip label="Medium"   count={counts.medium}   active={filter === "medium"}   onClick={() => setFilter("medium")}   color="var(--warning)" />
              <FilterChip label="Low"      count={counts.low}      active={filter === "low"}      onClick={() => setFilter("low")}      color="var(--info)"    />
            </div>

            {filtered.length === 0 ? (
              <div style={{ padding: "60px 0", textAlign: "center" }}>
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 12, color: "var(--success)" }}>
                  <IconCheckCircle size={28} />
                </div>
                <div style={{ fontSize: 13, color: "var(--text-body)", fontWeight: 500, marginBottom: 4 }}>
                  No alerts to show
                </div>
                <div style={{ fontSize: 11, color: "var(--text-vfaint)" }}>
                  {alerts.length === 0 ? "Click \"Rescan now\" to scan your AWS account" : "Try a different severity filter"}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {filtered.map((alert, i) => <AlertCard key={i} alert={alert} />)}
              </div>
            )}
          </div>
        )}

        {tab === "logs" && (
          <div style={{ maxWidth: 920, margin: "0 auto" }}>
            {logs.length === 0 ? (
              <div style={{ padding: "60px 0", textAlign: "center", fontSize: 12, color: "var(--text-vfaint)" }}>
                No activity logged yet
              </div>
            ) : (
              <div style={{ borderRadius: 8, border: "1px solid var(--border-strong)", overflow: "hidden", background: "var(--bg-elevated)" }}>
                {logs.map((log, i) => <LogRow key={i} log={log} isLast={i === logs.length - 1} />)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function FilterChip({ label, count, active, onClick, color }) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 6,
      padding: "5px 11px", borderRadius: 6, cursor: "pointer", fontFamily: "inherit",
      background: active ? (color ? `color-mix(in srgb, ${color} 8%, transparent)` : "var(--accent-bg)") : "transparent",
      border: `1px solid ${active ? (color || "var(--accent-border)") : "var(--border-strong)"}`,
      color: active ? (color || "var(--accent)") : "var(--text-dim)",
      fontSize: 11, fontWeight: 500,
    }}>
      {label}
      <span style={{ fontSize: 10, opacity: 0.75 }}>{count}</span>
    </button>
  );
}

function AlertCard({ alert }) {
  const sev = SEV_CONFIG[alert.severity] || SEV_CONFIG.low;
  const CatIcon = CATEGORY_ICONS[alert.category] || IconActivity;
  const SevIcon = sev.Icon;

  return (
    <div style={{
      padding: "12px 14px", borderRadius: 8,
      background: sev.bg, border: `1px solid ${sev.border}`,
      display: "flex", gap: 12, alignItems: "flex-start",
    }}>
      <div style={{ color: sev.color, marginTop: 1, flexShrink: 0 }}>
        <SevIcon size={14} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
            background: `color-mix(in srgb, ${sev.color} 12%, transparent)`, color: sev.color, letterSpacing: "0.04em",
          }}>{sev.label}</span>
          {alert.category && (
            <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--text-vfaint)" }}>
              <CatIcon size={11} /> {alert.category}
            </span>
          )}
          {alert.resource_id && (
            <span style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "ui-monospace, monospace" }}>
              {alert.resource_id}
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-body)", fontWeight: 500, lineHeight: 1.5, marginBottom: 4 }}>
          {alert.title || alert.message}
        </div>
        {alert.detail && (
          <div style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.55 }}>
            {alert.detail}
          </div>
        )}
        {alert.remediation && (
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6, padding: "6px 8px", borderRadius: 5, background: "var(--bg-deep)", border: "1px solid var(--border-strong)" }}>
            <span style={{ fontSize: 9, color: "var(--text-vfaint)", textTransform: "uppercase", letterSpacing: "0.05em", marginRight: 6 }}>Fix:</span>
            {alert.remediation}
          </div>
        )}
      </div>
    </div>
  );
}

function LogRow({ log, isLast }) {
  return (
    <div style={{
      display: "flex", gap: 10, padding: "8px 14px",
      borderBottom: isLast ? "none" : "1px solid var(--border)",
      alignItems: "center", fontSize: 11, color: "var(--text-dim)", fontFamily: "ui-monospace, monospace",
    }}>
      <span style={{ color: "var(--text-vfaint)", minWidth: 90 }}>
        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "—"}
      </span>
      <span style={{ color: "var(--accent)", minWidth: 110 }}>{log.event || log.action}</span>
      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {log.tool && <span style={{ color: "var(--text-body)" }}>{log.tool}</span>}
        {log.input && <span> · {String(log.input).slice(0, 80)}</span>}
        {log.status && <span style={{ marginLeft: 8, color: log.status === "success" ? "var(--success)" : "var(--danger)" }}>{log.status}</span>}
      </span>
    </div>
  );
}

function Spinner() {
  return (
    <div style={{
      width: 11, height: 11, border: "2px solid rgba(255,255,255,0.3)",
      borderTopColor: "#fff", borderRadius: "50%",
      animation: "av-spin 0.7s linear infinite",
    }}>
      <style>{`@keyframes av-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
