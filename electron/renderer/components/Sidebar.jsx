import React, { useState, useEffect } from "react";
import {
  IconChat, IconGraduation, IconShield, IconMap, IconSettings,
  IconSun, IconMoon, IconCloud,
} from "../Icons";

const BACKEND = "http://localhost:8000";

const NAV = [
  { id: "chat",     label: "Chat",     Icon: IconChat       },
  { id: "learn",    label: "Learn",    Icon: IconGraduation },
  { id: "audit",    label: "Audit",    Icon: IconShield     },
  { id: "manifest", label: "Manifest", Icon: IconMap        },
  { id: "settings", label: "Settings", Icon: IconSettings   },
];

const LEVEL_COLORS = {
  beginner:     "var(--success)",
  intermediate: "var(--info)",
  architect:    "#a78bfa",
  cto:          "var(--warning)",
};

export default function Sidebar({ activeView, onNavigate, userProfile, theme, onToggleTheme }) {
  const [alerts, setAlerts] = useState({ critical: 0, high: 0, total: 0 });
  const [online, setOnline] = useState(null);

  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(2000) });
        setOnline(r.ok);
      } catch { setOnline(false); }
    };
    check();
    const id = setInterval(check, 12000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch(`${BACKEND}/agent/scan/results`);
        if (!r.ok) return;
        const d = await r.json();
        const a = d.alerts || [];
        setAlerts({
          critical: a.filter(x => x.severity === "critical").length,
          high:     a.filter(x => x.severity === "high").length,
          total:    a.length,
        });
      } catch {}
    };
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  const level = userProfile?.level || "intermediate";
  const levelColor = LEVEL_COLORS[level] || "var(--info)";

  return (
    <div style={{
      width: 200, minWidth: 200, height: "100%",
      background: "var(--bg-deep)", borderRight: "1px solid var(--border)",
      display: "flex", flexDirection: "column",
      fontFamily: "ui-sans-serif, system-ui, sans-serif",
      transition: "background 0.15s, border-color 0.15s",
    }}>
      {/* Logo */}
      <div style={{ padding: "18px 16px 14px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", flexShrink: 0,
          }}>
            <IconCloud size={16} />
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.2px", lineHeight: 1 }}>
              CloudAgent
            </div>
            <div style={{ fontSize: 10, color: "var(--text-vfaint)", marginTop: 3, fontFamily: "ui-monospace, monospace" }}>
              AWS · v2
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "10px 8px" }}>
        {NAV.map(({ id, label, Icon }) => {
          const isActive = activeView === id;
          const hasBadge = id === "audit" && alerts.total > 0;
          return (
            <button
              key={id}
              onClick={() => onNavigate(id)}
              style={{
                width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "8px 10px", borderRadius: 7, border: "none", cursor: "pointer",
                background: isActive ? "var(--accent-bg)" : "transparent",
                color: isActive ? "var(--accent)" : "var(--text-dim)",
                fontSize: 13, fontWeight: isActive ? 500 : 400,
                marginBottom: 2, transition: "all 0.1s", fontFamily: "inherit",
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = "var(--text-medium)"; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = "var(--text-dim)"; }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <Icon size={15} />
                <span>{label}</span>
              </span>
              {hasBadge && (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 9,
                  background: alerts.critical > 0 ? "rgba(239,68,68,0.15)" : "rgba(245,158,11,0.12)",
                  color: alerts.critical > 0 ? "var(--danger)" : "var(--warning)",
                  border: `1px solid ${alerts.critical > 0 ? "rgba(239,68,68,0.25)" : "rgba(245,158,11,0.2)"}`,
                }}>{alerts.critical > 0 ? alerts.critical : alerts.total}</span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={{ padding: "10px 12px 14px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 8 }}>
        {/* Level */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 2px" }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: levelColor, flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
            <span style={{ color: levelColor }}>{level.charAt(0).toUpperCase() + level.slice(1)}</span>
            <span style={{ color: "var(--text-vfaint)" }}> · auto</span>
          </span>
        </div>
        {/* Backend status */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 2px" }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
            background: online === true ? "var(--success)" : online === false ? "var(--danger)" : "var(--text-faint)",
          }} />
          <span style={{ fontSize: 11, color: "var(--text-vfaint)" }}>
            {online === true ? "Backend online" : online === false ? "Backend offline" : "Connecting"}
          </span>
        </div>
        {/* Theme toggle */}
        <button
          onClick={onToggleTheme}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
            padding: "7px 10px", borderRadius: 7, border: "1px solid var(--border-strong)",
            background: "transparent", cursor: "pointer",
            color: "var(--text-dim)", fontSize: 11, fontFamily: "inherit",
            transition: "all 0.1s", marginTop: 2,
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--border-hover)"; e.currentTarget.style.color = "var(--text-medium)"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.color = "var(--text-dim)"; }}
        >
          {theme === "dark"
            ? <><IconSun size={13} /><span>Light mode</span></>
            : <><IconMoon size={13} /><span>Dark mode</span></>
          }
        </button>
      </div>
    </div>
  );
}
