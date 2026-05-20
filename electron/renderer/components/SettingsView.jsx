import React, { useState, useEffect } from "react";
import {
  IconKey, IconCloud, IconCpu, IconShield, IconRefresh,
  IconCheck, IconActivity, IconServer, IconSettings, IconCheckCircle,
  IconAlertTriangle, IconBox, IconZap, IconLayers, IconChevronRight,
} from "../Icons";

const BACKEND = "http://localhost:8000";

const MODELS = [
  { id: "gpt-4o",                    label: "GPT-4o",           badge: "Recommended",  provider: "OpenAI"    },
  { id: "gpt-4o-mini",               label: "GPT-4o Mini",      badge: "Fast · cheap", provider: "OpenAI"    },
  { id: "claude-sonnet-4-20250514",  label: "Claude Sonnet 4",  badge: "Powerful",     provider: "Anthropic" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5", badge: "Fast",         provider: "Anthropic" },
];

const REGIONS = [
  "us-east-1","us-east-2","us-west-1","us-west-2","ca-central-1",
  "eu-west-1","eu-west-2","eu-west-3","eu-central-1","eu-north-1","eu-south-1",
  "ap-northeast-1","ap-northeast-2","ap-southeast-1","ap-southeast-2","ap-south-1",
  "sa-east-1","me-south-1","af-south-1",
];

const LEVEL_OPTIONS = [
  { id: "auto",         label: "Auto-detect",  Icon: IconRefresh,  desc: "Detect level from your questions" },
  { id: "beginner",     label: "Beginner",     Icon: IconBox,      desc: "Simple explanations, step-by-step" },
  { id: "intermediate", label: "Intermediate", Icon: IconZap,      desc: "Technical depth, trade-offs" },
  { id: "architect",    label: "Architect",    Icon: IconLayers,   desc: "Full HA/DR, FinOps, best practices" },
  { id: "cto",          label: "C-Level",      Icon: IconActivity, desc: "Executive summary, TCO, strategy" },
];

export default function SettingsView({ onSave }) {
  const [creds, setCreds] = useState({
    aws_access_key_id: "", aws_secret_access_key: "", aws_session_token: "",
    aws_region: "us-east-1", profile: "default",
  });
  const [llm, setLlm] = useState({
    openai_api_key: "", anthropic_api_key: "", default_model: "gpt-4o",
  });
  const [levelOverride,    setLevelOverride]    = useState("auto");
  const [proactiveEnabled, setProactiveEnabled] = useState(true);
  const [dryRun,           setDryRun]           = useState(false);
  const [saved,            setSaved]            = useState(false);
  const [testing,          setTesting]          = useState(false);
  const [testResult,       setTestResult]       = useState(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("ca_settings");
      if (stored) {
        const s = JSON.parse(stored);
        if (s.creds) setCreds(prev => ({ ...prev, ...s.creds }));
        if (s.llm)   setLlm(prev  => ({ ...prev, ...s.llm }));
        if (s.levelOverride)    setLevelOverride(s.levelOverride);
        if (s.proactiveEnabled !== undefined) setProactiveEnabled(s.proactiveEnabled);
        if (s.dryRun !== undefined) setDryRun(s.dryRun);
      }
    } catch {}
  }, []);

  const save = () => {
    const settings = { creds, llm, levelOverride, proactiveEnabled, dryRun };
    try { localStorage.setItem("ca_settings", JSON.stringify(settings)); } catch {}
    onSave?.(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2200);
  };

  const testAws = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await fetch(`${BACKEND}/agent/tool`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_name: "iam_get_account_summary",
          credentials: creds, args: {},
        }),
      });
      const d = await r.json();
      if (d.ok) setTestResult({ ok: true, message: "AWS credentials valid" });
      else      setTestResult({ ok: false, message: d.error || "Test failed" });
    } catch (e) { setTestResult({ ok: false, message: e.message }); }
    finally { setTesting(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)", fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      <div style={{ padding: "18px 28px", borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)" }}>
        <h1 style={{ fontSize: 16, fontWeight: 600, color: "var(--text-strong)", margin: 0, letterSpacing: "-0.2px" }}>
          Settings
        </h1>
        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "4px 0 0" }}>
          AWS credentials, LLM provider, agent behaviour
        </p>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "22px 28px" }}>
        <div style={{ maxWidth: 800, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>

          {/* AWS credentials */}
          <Section Icon={IconCloud} title="AWS Credentials" desc="IAM keys with the permissions the agent needs (read-only minimum + ce:GetCostAndUsage for cost).">
            <Row label="Access Key ID">
              <input type="text" value={creds.aws_access_key_id}
                onChange={e => setCreds(c => ({ ...c, aws_access_key_id: e.target.value }))}
                placeholder="AKIA..." style={inputStyle} />
            </Row>
            <Row label="Secret Access Key">
              <input type="password" value={creds.aws_secret_access_key}
                onChange={e => setCreds(c => ({ ...c, aws_secret_access_key: e.target.value }))}
                placeholder="••••••••••••" style={inputStyle} />
            </Row>
            <Row label="Session Token" hint="Optional, only if using STS">
              <input type="password" value={creds.aws_session_token}
                onChange={e => setCreds(c => ({ ...c, aws_session_token: e.target.value }))}
                placeholder="(optional)" style={inputStyle} />
            </Row>
            <Row label="Default Region">
              <select value={creds.aws_region}
                onChange={e => setCreds(c => ({ ...c, aws_region: e.target.value }))}
                style={inputStyle}>
                {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </Row>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
              <button onClick={testAws} disabled={testing || !creds.aws_access_key_id}
                style={{ ...btnSecondary, opacity: (testing || !creds.aws_access_key_id) ? 0.4 : 1 }}>
                {testing
                  ? <><Spinner /> Testing</>
                  : <><IconCheck size={13} /> Test credentials</>}
              </button>
              {testResult && (
                <span style={{
                  display: "flex", alignItems: "center", gap: 6, fontSize: 11,
                  color: testResult.ok ? "var(--success)" : "var(--danger)",
                }}>
                  {testResult.ok ? <IconCheckCircle size={13} /> : <IconAlertTriangle size={13} />}
                  {testResult.message}
                </span>
              )}
            </div>
          </Section>

          {/* LLM */}
          <Section Icon={IconKey} title="LLM Provider" desc="One key minimum. The agent uses your key — Anthropic / OpenAI bill you directly.">
            <Row label="OpenAI API Key">
              <input type="password" value={llm.openai_api_key}
                onChange={e => setLlm(l => ({ ...l, openai_api_key: e.target.value }))}
                placeholder="sk-..." style={inputStyle} />
            </Row>
            <Row label="Anthropic API Key" hint="Optional, for Claude models">
              <input type="password" value={llm.anthropic_api_key}
                onChange={e => setLlm(l => ({ ...l, anthropic_api_key: e.target.value }))}
                placeholder="sk-ant-..." style={inputStyle} />
            </Row>
            <Row label="Default model">
              <select value={llm.default_model}
                onChange={e => setLlm(l => ({ ...l, default_model: e.target.value }))}
                style={inputStyle}>
                {MODELS.map(m => <option key={m.id} value={m.id}>{m.label} ({m.provider}) — {m.badge}</option>)}
              </select>
            </Row>
          </Section>

          {/* Expertise level */}
          <Section Icon={IconCpu} title="Default Expertise Level" desc="Override or let the agent auto-detect from your questions.">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 6 }}>
              {LEVEL_OPTIONS.map(opt => {
                const isSelected = levelOverride === opt.id;
                return (
                  <button key={opt.id} onClick={() => setLevelOverride(opt.id)}
                    style={{
                      padding: "12px 10px", borderRadius: 8, cursor: "pointer",
                      background: isSelected ? "var(--accent-bg)" : "var(--bg-card)",
                      border: `1px solid ${isSelected ? "var(--accent-border)" : "var(--border-strong)"}`,
                      color: isSelected ? "var(--accent)" : "var(--text-dim)",
                      fontFamily: "inherit", textAlign: "center",
                    }}>
                    <div style={{ display: "flex", justifyContent: "center", marginBottom: 6 }}>
                      <opt.Icon size={16} />
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 600 }}>{opt.label}</div>
                    <div style={{ fontSize: 9, color: isSelected ? "var(--accent)" : "var(--text-vfaint)", marginTop: 3, opacity: 0.9, lineHeight: 1.3 }}>
                      {opt.desc}
                    </div>
                  </button>
                );
              })}
            </div>
          </Section>

          {/* Behaviour */}
          <Section Icon={IconShield} title="Agent Behaviour" desc="Safety controls and proactive features.">
            <Toggle
              label="Proactive infrastructure scan"
              hint="Background scan for public S3, stale keys, open SSH (every 30 min)"
              checked={proactiveEnabled}
              onChange={setProactiveEnabled}
            />
            <Toggle
              label="Dry-run mode"
              hint="Show what destructive actions would do, but don't execute them"
              checked={dryRun}
              onChange={setDryRun}
            />
          </Section>

          {/* Save */}
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, marginTop: 4 }}>
            {saved && (
              <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--success)" }}>
                <IconCheckCircle size={13} /> Saved
              </span>
            )}
            <button onClick={save} style={btnPrimary}>
              <IconCheck size={13} /> Save settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function Section({ Icon, title, desc, children }) {
  return (
    <div style={{
      padding: "18px 20px", borderRadius: 10,
      background: "var(--bg-elevated)", border: "1px solid var(--border-strong)",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 7,
          background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
          display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)",
          flexShrink: 0,
        }}>
          <Icon size={16} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-strong)" }}>{title}</div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 3, lineHeight: 1.5 }}>{desc}</div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{children}</div>
    </div>
  );
}

function Row({ label, hint, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 11, color: "var(--text-medium)", fontWeight: 500 }}>
        {label}
        {hint && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--text-vfaint)", fontWeight: 400 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0" }}>
      <div>
        <div style={{ fontSize: 12, color: "var(--text-body)", fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 10, color: "var(--text-vfaint)", marginTop: 2 }}>{hint}</div>
      </div>
      <button
        onClick={() => onChange(!checked)}
        style={{
          width: 36, height: 20, borderRadius: 10, border: "none", padding: 2,
          background: checked ? "var(--accent)" : "var(--border-hover)",
          cursor: "pointer", position: "relative", transition: "all 0.15s",
        }}>
        <div style={{
          width: 16, height: 16, borderRadius: "50%", background: "#fff",
          transform: `translateX(${checked ? 16 : 0}px)`, transition: "transform 0.15s",
        }} />
      </button>
    </div>
  );
}

function Spinner() {
  return (
    <div style={{
      width: 11, height: 11, border: "2px solid var(--border-strong)",
      borderTopColor: "var(--accent)", borderRadius: "50%",
      animation: "sv-spin 0.7s linear infinite",
    }}>
      <style>{`@keyframes sv-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "7px 10px", borderRadius: 6,
  background: "var(--bg-card)", border: "1px solid var(--border-strong)",
  color: "var(--text)", fontSize: 12, fontFamily: "inherit", outline: "none",
};

const btnPrimary = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "8px 14px", borderRadius: 7, border: "none", cursor: "pointer",
  background: "var(--accent)", color: "#fff",
  fontSize: 12, fontWeight: 500, fontFamily: "inherit",
};

const btnSecondary = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "6px 12px", borderRadius: 6, cursor: "pointer",
  background: "var(--bg-card)", border: "1px solid var(--border-strong)",
  color: "var(--text-body)", fontSize: 11, fontFamily: "inherit",
};
