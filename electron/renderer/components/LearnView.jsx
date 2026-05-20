import React, { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CertificationsTab from "./CertificationsTab";
import {
  IconLayers, IconBook, IconList, IconGraduation, IconCloud, IconExternal,
  IconShoppingCart, IconCpu, IconZap, IconGlobe, IconBox, IconDatabase, IconServer,
} from "../Icons";

const BACKEND = "http://localhost:8000";

const TABS = [
  { id: "advisor",        label: "Architecture Advisor" },
  { id: "templates",      label: "Templates" },
  { id: "explorer",       label: "Service Reference" },
  { id: "certifications", label: "Certifications" },
];

const LEVELS = [
  { id: "beginner",     label: "Beginner",     color: "var(--success)" },
  { id: "intermediate", label: "Intermediate", color: "var(--info)" },
  { id: "architect",    label: "Architect",    color: "#a78bfa" },
  { id: "cto",          label: "C-Level",      color: "var(--warning)" },
];

const AGENT_LABELS = {
  docs:       "AWS Docs",
  classifier: "Intent",
  architect:  "Architect",
  comparator: "Comparator",
  explainer:  "Explainer",
  cost:       "Pricing API",
  iac:        "Terraform + CDK",
};

const AGENT_COLORS = {
  docs:       "var(--docs)",
  classifier: "var(--text-medium)",
  architect:  "#6366f1",
  comparator: "#a78bfa",
  explainer:  "var(--info)",
  cost:       "var(--success)",
  iac:        "var(--warning)",
};

export default function LearnView() {
  const [tab,   setTab]   = useState("advisor");
  const [level, setLevel] = useState("intermediate");

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)", fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)", paddingLeft: 22, alignItems: "center" }}>
        <span style={{ fontSize: 10, color: "var(--border-hover)", fontFamily: "ui-monospace, monospace", letterSpacing: "0.06em", marginRight: 18 }}>LEARN</span>
        <div style={{ display: "flex", flex: 1 }}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: "14px 16px", border: "none", background: "transparent", cursor: "pointer",
              borderBottom: `2px solid ${tab === t.id ? "#6366f1" : "transparent"}`,
              color: tab === t.id ? "var(--text-body)" : "var(--text-faint)",
              fontSize: 12, fontWeight: 500, fontFamily: "inherit",
            }}>{t.label}</button>
          ))}
        </div>
        {/* Level selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 14px", borderLeft: "1px solid var(--border)" }}>
          <span style={{ fontSize: 10, color: "var(--border-hover)", marginRight: 4 }}>Mode</span>
          {LEVELS.map(l => (
            <button key={l.id} onClick={() => setLevel(l.id)} style={{
              padding: "3px 9px", borderRadius: 5, border: `1px solid ${level === l.id ? `color-mix(in srgb, ${l.color} 25%, transparent)` : "transparent"}`,
              background: level === l.id ? `color-mix(in srgb, ${l.color} 6%, transparent)` : "transparent",
              color: level === l.id ? l.color : "var(--text-faint)",
              fontSize: 10, cursor: "pointer", fontFamily: "inherit",
            }}>{l.label}</button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflow: "hidden" }}>
        {tab === "advisor"        && <AdvisorTab level={level} />}
        {tab === "templates"      && <TemplatesTab />}
        {tab === "explorer"       && <ExplorerTab level={level} />}
        {tab === "certifications" && <CertificationsTab level={level} />}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-thumb { background: #1a1a1a; border-radius: 3px; }
      `}</style>
    </div>
  );
}

// ── Advisor ────────────────────────────────────────────────────────────────────

const USE_CASES = [
  { id: "ecommerce", label: "E-Commerce" },
  { id: "batch",     label: "Batch / ETL" },
  { id: "api",       label: "API" },
  { id: "ml",        label: "ML / AI" },
  { id: "realtime",  label: "Real-time" },
  { id: "saas",      label: "SaaS" },
  { id: "custom",    label: "Custom" },
];

const STARTERS = {
  ecommerce: "I'm building an e-commerce platform expecting 50k users/day with cart, payments, and product catalog. Budget ~$2,000/month.",
  batch:     "Process 500GB of CSV files daily, transform, and load into a data warehouse for BI.",
  api:       "REST API for a mobile app: user auth, 10k req/min peak, relational DB.",
  ml:        "Train NLP models on 1TB of text, serve predictions at <100ms for 1000 req/sec.",
  realtime:  "Ingest IoT sensor data from 100k devices, real-time dashboards under 2 seconds.",
  saas:      "B2B SaaS with 500 enterprise tenants, hard isolation, custom domains, per-tenant billing.",
  custom:    "",
};

function AdvisorTab({ level }) {
  const [useCase, setUseCase] = useState("custom");
  const [input,   setInput]   = useState("");
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [steps,    setSteps]    = useState([]);
  const [sources, setSources]   = useState([]);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { if (useCase !== "custom") setInput(STARTERS[useCase] || ""); }, [useCase]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, steps]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setSteps([]);
    setSources([]);
    setMessages(prev => [...prev, { role: "user", content: text }]);
    const assistantId = `m-${Date.now()}`;
    setMessages(prev => [...prev, { id: assistantId, role: "assistant", content: "" }]);
    setStreaming(true);

    const s = (() => { try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; } })();

    try {
      const resp = await fetch(`${BACKEND}/learn/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text, thread_id: `l-${Date.now()}`,
          use_case: useCase, user_level: level,
          openai_api_key:    s?.llm?.openai_api_key    || "",
          anthropic_api_key: s?.llm?.anthropic_api_key || "",
        }),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "token") {
              setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: (m.content || "") + ev.content } : m));
            } else if (ev.type === "docs_sources") {
              setSources(ev.sources);
              setSourcesOpen(true);
            } else if (ev.type === "agent_start") {
              setSteps(prev => {
                const exists = prev.find(s => s.name === ev.agent);
                if (exists) return prev.map(s => s.name === ev.agent ? { ...s, status: "active" } : s);
                return [...prev, { name: ev.agent, status: "active", ts: Date.now() }];
              });
            } else if (ev.type === "agent_end") {
              setSteps(prev => prev.map(s =>
                s.name === ev.agent ? { ...s, status: "done", elapsed: Date.now() - s.ts } : s
              ));
            }
          } catch {}
        }
      }
    } catch (e) {
      setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, error: e.message } : m));
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, useCase, level]);

  return (
    <div style={{ display: "flex", height: "100%", position: "relative" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* Use case bar */}
        <div style={{ padding: "10px 22px", borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "var(--border-hover)", marginRight: 4 }}>Use case:</span>
          {USE_CASES.map(uc => (
            <button key={uc.id} onClick={() => setUseCase(uc.id)} style={{
              padding: "3px 9px", borderRadius: 5, border: `1px solid ${useCase === uc.id ? "var(--accent-border)" : "transparent"}`,
              background: useCase === uc.id ? "var(--accent-bg)" : "transparent",
              color: useCase === uc.id ? "var(--accent)" : "var(--text-faint)",
              fontSize: 10, cursor: "pointer", fontFamily: "inherit",
            }}>{uc.label}</button>
          ))}
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "22px 28px" }}>
          {messages.length === 0 && (
            <div style={{ textAlign: "center", padding: "60px 0", maxWidth: 480, margin: "0 auto" }}>
              <div style={{ fontSize: 14, color: "var(--text-medium)", marginBottom: 8, fontWeight: 500 }}>Architecture Advisor</div>
              <p style={{ fontSize: 12, color: "var(--text-vfaint)", lineHeight: 1.6 }}>
                Describe your workload. The system will fetch official AWS docs, design an architecture,
                compute real costs via the Price List API, and generate Terraform.
              </p>
            </div>
          )}

          <div style={{ maxWidth: 800, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
            {messages.map((msg, i) => {
              if (msg.role === "user") {
                return (
                  <div key={i} style={{ display: "flex", justifyContent: "flex-end" }}>
                    <div style={{ maxWidth: "75%", background: "var(--accent-bg)", border: "1px solid var(--accent-border)", borderRadius: "12px 12px 4px 12px", padding: "10px 14px", fontSize: 13, color: "var(--text-body)", lineHeight: 1.6 }}>
                      {msg.content}
                    </div>
                  </div>
                );
              }
              return (
                <div key={i}>
                  {i === messages.length - 1 && steps.length > 0 && <Pipeline steps={steps} />}
                  {msg.error && (
                    <div style={{ padding: "10px 14px", borderRadius: 8, background: "var(--bg-card)", border: "1px solid color-mix(in srgb, var(--danger) 30%, transparent)", color: "var(--danger)", fontSize: 12 }}>
                      {msg.error}
                    </div>
                  )}
                  {msg.content && (
                    <SectionedResponse content={msg.content} />
                  )}
                  {streaming && i === messages.length - 1 && !msg.content && (
                    <div style={{ display: "flex", gap: 4, padding: "12px 4px", alignItems: "center" }}>
                      {[0,1,2].map(j => <div key={j} style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-vfaint)", animation: `pulse 1.2s ${j*0.2}s infinite` }} />)}
                      <span style={{ fontSize: 11, color: "var(--text-faint)", marginLeft: 6 }}>
                        {steps.find(s => s.status === "active")?.name === "docs" ? "Searching docs.aws.amazon.com…" : "Processing…"}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--border)", background: "var(--bg-elevated)", padding: "14px 28px 16px" }}>
          <div style={{ maxWidth: 800, margin: "0 auto", display: "flex", gap: 10, alignItems: "flex-end" }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Describe your architecture needs…"
              rows={2}
              disabled={streaming}
              style={{
                flex: 1, resize: "none", background: "var(--bg-hover)", border: "1px solid var(--border-strong)",
                borderRadius: 10, padding: "10px 14px", fontSize: 13, color: "var(--text-body)",
                fontFamily: "ui-sans-serif, system-ui, sans-serif", outline: "none",
                lineHeight: 1.5, maxHeight: 140, opacity: streaming ? 0.4 : 1,
              }}
            />
            {messages.length > 0 && !streaming && (
              <button onClick={() => { setMessages([]); setSteps([]); setSources([]); setInput(""); }}
                title="Start a new design session"
                style={{
                  padding: "10px 14px", borderRadius: 9, cursor: "pointer",
                  background: "transparent", border: "1px solid var(--border-strong)",
                  color: "var(--text-dim)", fontSize: 12, fontFamily: "inherit",
                  height: 38, flexShrink: 0,
                }}>↺ New</button>
            )}
            <button onClick={send} disabled={streaming || !input.trim()} style={{
              padding: "10px 16px", borderRadius: 9, border: "none", cursor: "pointer",
              background: (streaming || !input.trim()) ? "var(--border-strong)" : "var(--accent)",
              color: "#fff", fontSize: 12, fontWeight: 500, fontFamily: "inherit",
              minWidth: 80, height: 38, flexShrink: 0,
            }}>{streaming ? "…" : "Design"}</button>
          </div>
        </div>
      </div>

      {/* Sources side panel — closable */}
      {sources.length > 0 && sourcesOpen && (
        <div style={{ width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)", background: "var(--bg-deep)", display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "11px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--docs)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              AWS Docs · {sources.length}
            </span>
            <button onClick={() => setSourcesOpen(false)} title="Close sources panel"
              style={{
                width: 22, height: 22, padding: 0, border: "none", borderRadius: 4,
                background: "transparent", color: "var(--text-faint)", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "inherit",
              }}
              onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-hover)"; e.currentTarget.style.color = "var(--text)"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-faint)"; }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
          <div style={{ padding: 12, overflowY: "auto" }}>
            {sources.map((s, i) => (
              <a key={i} href={s.url}
                 onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(s.url) || window.open(s.url, "_blank"); }}
                 style={{
                   display: "block", padding: "10px 12px", marginBottom: 6,
                   borderRadius: 7, background: "var(--bg-card)", border: "1px solid var(--border-strong)",
                   textDecoration: "none", cursor: "pointer",
                 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--docs)", marginBottom: 4 }}>{s.service}</div>
                <div style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "ui-monospace, monospace", wordBreak: "break-all", lineHeight: 1.4 }}>
                  {s.url.replace("https://", "")}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Reopen tab when sources panel is closed */}
      {sources.length > 0 && !sourcesOpen && (
        <button onClick={() => setSourcesOpen(true)}
          title={`Show AWS Docs (${sources.length})`}
          style={{
            position: "absolute", right: 0, top: 100,
            padding: "10px 8px", borderRadius: "8px 0 0 8px",
            background: "var(--bg-elevated)", border: "1px solid var(--border-strong)",
            borderRight: "none", cursor: "pointer", fontFamily: "inherit",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 7,
            color: "var(--docs)", fontSize: 10, fontWeight: 600,
            textTransform: "uppercase", letterSpacing: "0.05em",
            writingMode: "vertical-rl",
          }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ writingMode: "horizontal-tb" }}>
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Docs · {sources.length}
        </button>
      )}
    </div>
  );
}

function Pipeline({ steps }) {
  return (
    <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 8, background: "var(--bg-deep)", border: "1px solid #141414", display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
      <span style={{ fontSize: 9, color: "var(--border-hover)", letterSpacing: "0.06em", marginRight: 4 }}>PIPELINE</span>
      {steps.map((step, i) => {
        const color = AGENT_COLORS[step.name] || "var(--text-dim)";
        const isDone = step.status === "done";
        return (
          <React.Fragment key={i}>
            {i > 0 && <div style={{ width: 8, height: 1, background: "var(--border-strong)" }} />}
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "2px 8px", borderRadius: 5,
              background: isDone ? "transparent" : `color-mix(in srgb, ${color} 7%, transparent)`,
              border: `1px solid ${isDone ? "var(--border-strong)" : `color-mix(in srgb, ${color} 19%, transparent)`}`,
            }}>
              {!isDone && <div style={{ width: 5, height: 5, borderRadius: "50%", background: color, animation: "pulse 1.2s infinite" }} />}
              {isDone  && <span style={{ color: "var(--success)", fontSize: 9 }}>✓</span>}
              <span style={{ fontSize: 10, color: isDone ? "var(--text-faint)" : color }}>
                {AGENT_LABELS[step.name] || step.name}
                {isDone && step.elapsed && <span style={{ color: "var(--border-hover)", marginLeft: 4 }}>{(step.elapsed/1000).toFixed(1)}s</span>}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── Templates ──────────────────────────────────────────────────────────────────

const TEMPLATE_ICONS = {
  ecommerce: IconShoppingCart, batch: IconLayers, api: IconCloud,
  ml: IconCpu, realtime: IconZap, saas: IconGlobe,
};

function TemplatesTab() {
  const [selected, setSelected] = useState(null);
  const [templates, setTemplates] = useState([]);

  useEffect(() => {
    fetch(`${BACKEND}/learn/templates`).then(r => r.json()).then(d => setTemplates(d.templates || [])).catch(() => {});
  }, []);

  if (selected) {
    const t = templates.find(x => x.id === selected);
    if (!t) return null;
    return (
      <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
        <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", color: "var(--text-dim)", fontSize: 11, cursor: "pointer", marginBottom: 18, fontFamily: "inherit" }}>← Back</button>
        <div style={{ maxWidth: 760 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 9,
              background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
              display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)",
            }}>
              {(() => { const TI = TEMPLATE_ICONS[t.id] || IconBox; return <TI size={20} />; })()}
            </div>
            <div>
              <h2 style={{ fontSize: 17, color: "var(--text-strong)", margin: 0, fontWeight: 600 }}>{t.name}</h2>
              <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "4px 0 0" }}>{t.description}</p>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 18 }}>
            {[["Traffic", t.traffic], ["Cost", t.estimated_cost], ["Complexity", t.complexity]].map(([k, v]) => (
              <div key={k} style={{ padding: 12, borderRadius: 8, background: "var(--bg-card)", border: "1px solid var(--border-strong)" }}>
                <div style={{ fontSize: 9, color: "var(--text-vfaint)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{k}</div>
                <div style={{ fontSize: 13, color: "var(--text-body)", fontWeight: 500 }}>{v}</div>
              </div>
            ))}
          </div>

          <pre style={{ padding: 16, borderRadius: 8, background: "var(--bg)", border: "1px solid var(--border-strong)", fontSize: 11, color: "var(--success)", fontFamily: "ui-monospace, monospace", overflow: "auto" }}>
            {t.diagram_text}
          </pre>

          <h3 style={{ fontSize: 11, fontWeight: 600, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.06em", margin: "22px 0 10px" }}>Services</h3>
          {t.services.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 12, padding: "10px 12px", marginBottom: 5, background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: 7 }}>
              <div style={{ width: 110, flexShrink: 0, fontSize: 12, color: "var(--accent)", fontFamily: "ui-monospace, monospace", fontWeight: 500 }}>{s.name}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, color: "var(--text-medium)", marginBottom: 2 }}>{s.role}</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>{s.why}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <h2 style={{ fontSize: 11, fontWeight: 600, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.06em", margin: "0 0 14px" }}>Architecture Templates</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        {templates.map(t => {
          const TIcon = TEMPLATE_ICONS[t.id] || IconBox;
          return (
            <button key={t.id} onClick={() => setSelected(t.id)} style={{
              textAlign: "left", padding: 16, borderRadius: 10,
              background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", cursor: "pointer",
              fontFamily: "inherit", display: "flex", flexDirection: "column", gap: 10,
              transition: "all 0.12s",
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent-border)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-strong)"; e.currentTarget.style.transform = "translateY(0)"; }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 7,
                  background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
                  display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)",
                }}>
                  <TIcon size={16} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
                  <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "ui-monospace, monospace" }}>{t.complexity}</span>
                  <span style={{ fontSize: 9, color: "var(--text-faint)" }}>{t.estimated_cost}</span>
                </div>
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>{t.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.5, marginBottom: 8 }}>{t.description}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {t.tags?.map(tag => (
                    <span key={tag} style={{
                      fontSize: 9, color: "var(--text-medium)", padding: "1px 7px", borderRadius: 4,
                      background: "var(--bg-card)", border: "1px solid var(--border-strong)",
                    }}>{tag}</span>
                  ))}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Explorer ───────────────────────────────────────────────────────────────────

const SERVICES = [
  { name: "EC2",            category: "Compute"   },
  { name: "Lambda",         category: "Compute"   },
  { name: "ECS Fargate",    category: "Compute"   },
  { name: "EKS",            category: "Compute"   },
  { name: "S3",             category: "Storage"   },
  { name: "RDS Aurora",     category: "Database"  },
  { name: "DynamoDB",       category: "Database"  },
  { name: "ElastiCache",    category: "Database"  },
  { name: "CloudFront",     category: "Network"   },
  { name: "API Gateway",    category: "Network"   },
  { name: "VPC",            category: "Network"   },
  { name: "IAM",            category: "Security"  },
  { name: "Cognito",        category: "Security"  },
  { name: "KMS",            category: "Security"  },
  { name: "Kinesis",        category: "Streaming" },
  { name: "MSK",            category: "Streaming" },
  { name: "SQS",            category: "Messaging" },
  { name: "SNS",            category: "Messaging" },
  { name: "Step Functions", category: "Orchestration" },
  { name: "Glue",           category: "Data"      },
  { name: "Athena",         category: "Data"      },
  { name: "Redshift",       category: "Data"      },
  { name: "SageMaker",      category: "ML/AI"     },
  { name: "Bedrock",        category: "ML/AI"     },
  { name: "CloudWatch",     category: "Operations"},
  { name: "CloudFormation", category: "Operations"},
];

function ExplorerTab({ level }) {
  const [search, setSearch] = useState("");
  const [cat,    setCat]    = useState("All");
  const [asking, setAsking] = useState(null);
  const [result, setResult] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sources, setSources] = useState([]);

  const cats = ["All", ...new Set(SERVICES.map(s => s.category))];
  const filtered = SERVICES.filter(s =>
    (cat === "All" || s.category === cat) &&
    (s.name.toLowerCase().includes(search.toLowerCase()))
  );

  const explain = async (svc) => {
    setAsking(svc); setResult(""); setSources([]); setStreaming(true);
    const s = (() => { try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; } })();
    try {
      const resp = await fetch(`${BACKEND}/learn/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `Explain AWS ${svc} in depth.`,
          thread_id: `exp-${svc}-${Date.now()}`,
          user_level: level,
          openai_api_key:    s?.llm?.openai_api_key    || "",
          anthropic_api_key: s?.llm?.anthropic_api_key || "",
        }),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "token") setResult(prev => prev + ev.content);
            if (ev.type === "docs_sources") setSources(ev.sources);
          } catch {}
        }
      }
    } finally {
      setStreaming(false);
    }
  };

  if (asking) {
    return (
      <div style={{ display: "flex", height: "100%" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: "26px 32px" }}>
          <button onClick={() => { setAsking(null); setResult(""); setSources([]); }} style={{ background: "none", border: "none", color: "var(--text-dim)", fontSize: 11, cursor: "pointer", marginBottom: 18, fontFamily: "inherit" }}>← Back</button>
          <h2 style={{ fontSize: 17, color: "var(--text)", margin: "0 0 18px", fontWeight: 600 }}>{asking}</h2>
          <div style={{ maxWidth: 760, background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: 10, padding: 18 }}>
            {result
              ? <div className="md-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown></div>
              : <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-dim)", fontSize: 12 }}>
                  {[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-vfaint)", animation: `pulse 1.2s ${i*0.2}s infinite` }} />)}
                  Fetching official AWS docs for {asking}…
                </div>}
          </div>
        </div>
        {sources.length > 0 && (
          <div style={{ width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)", background: "var(--bg-deep)" }}>
            <div style={{ padding: "13px 14px", borderBottom: "1px solid var(--border)" }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--docs)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                AWS Docs · {sources.length}
              </span>
            </div>
            <div style={{ padding: 12 }}>
              {sources.map((s, i) => (
                <a key={i} href={s.url}
                   onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(s.url) || window.open(s.url, "_blank"); }}
                   style={{ display: "block", padding: "10px 12px", marginBottom: 6, borderRadius: 7, background: "var(--bg-card)", border: "1px solid var(--border-strong)", textDecoration: "none" }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--docs)", marginBottom: 4 }}>{s.service}</div>
                  <div style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "ui-monospace, monospace", wordBreak: "break-all", lineHeight: 1.4 }}>
                    {s.url.replace("https://", "")}
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <input
          value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search services"
          style={{
            background: "var(--bg-hover)", border: "1px solid var(--border-strong)", borderRadius: 7,
            padding: "6px 12px", fontSize: 12, color: "var(--text-body)", outline: "none",
            width: 220, fontFamily: "inherit",
          }}
        />
        <div style={{ display: "flex", gap: 4 }}>
          {cats.map(c => (
            <button key={c} onClick={() => setCat(c)} style={{
              padding: "4px 10px", borderRadius: 5,
              background: cat === c ? "var(--accent-bg)" : "transparent",
              color: cat === c ? "var(--accent)" : "var(--text-faint)",
              border: `1px solid ${cat === c ? "var(--accent-border)" : "var(--border-strong)"}`,
              fontSize: 10, cursor: "pointer", fontFamily: "inherit",
            }}>{c}</button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 6 }}>
        {filtered.map(s => (
          <button key={s.name} onClick={() => explain(s.name)} style={{
            textAlign: "left", padding: "10px 12px", borderRadius: 7,
            background: "var(--bg-card)", border: "1px solid var(--border-strong)", cursor: "pointer", fontFamily: "inherit",
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent-border)"}
          onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
          >
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-body)", marginBottom: 2 }}>{s.name}</div>
            <div style={{ fontSize: 9, color: "var(--text-vfaint)" }}>{s.category}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Sectioned response with sub-tabs ──────────────────────────────────────────
function SectionedResponse({ content }) {
  const sections = React.useMemo(() => parseSections(content), [content]);
  const [active, setActive] = React.useState(0);

  // Reset to first tab when content changes (new response)
  React.useEffect(() => { setActive(0); }, [sections.length]);

  // If only one section (or none), render flat
  if (sections.length <= 1) {
    return (
      <div style={{
        background: "var(--bg-card)", border: "1px solid var(--border-strong)",
        borderRadius: "4px 12px 12px 12px", padding: "16px 18px",
      }}>
        <div className="md-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      background: "var(--bg-card)", border: "1px solid var(--border-strong)",
      borderRadius: "4px 12px 12px 12px", overflow: "hidden",
    }}>
      {/* Tab bar */}
      <div style={{
        display: "flex", flexWrap: "wrap", borderBottom: "1px solid var(--border-strong)",
        background: "var(--bg-elevated)", padding: "0 6px",
      }}>
        {sections.map((s, i) => (
          <button key={i} onClick={() => setActive(i)} style={{
            padding: "10px 14px", border: "none", background: "transparent",
            cursor: "pointer", fontFamily: "inherit",
            borderBottom: `2px solid ${active === i ? "var(--accent)" : "transparent"}`,
            color: active === i ? "var(--text-strong)" : "var(--text-dim)",
            fontSize: 11, fontWeight: active === i ? 600 : 500,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{
              fontSize: 9, fontWeight: 700,
              padding: "1px 6px", borderRadius: 4,
              background: active === i ? "var(--accent-bg)" : "var(--bg-hover)",
              color: active === i ? "var(--accent)" : "var(--text-vfaint)",
              minWidth: 18, textAlign: "center",
            }}>{i + 1}</span>
            {s.title}
          </button>
        ))}
      </div>

      {/* Active section content */}
      <div style={{ padding: "18px 20px" }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: "var(--text-vfaint)",
          textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10,
        }}>
          Section {active + 1} of {sections.length}
        </div>
        <div className="md-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{sections[active]?.content || ""}</ReactMarkdown>
        </div>

        {/* Footer nav: prev/next */}
        <div style={{
          marginTop: 24, paddingTop: 14, borderTop: "1px solid var(--border-strong)",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <button
            onClick={() => setActive(a => Math.max(0, a - 1))}
            disabled={active === 0}
            style={{
              padding: "6px 12px", borderRadius: 6, fontFamily: "inherit",
              background: "transparent", border: "1px solid var(--border-strong)",
              color: active === 0 ? "var(--text-vfaint)" : "var(--text-dim)",
              fontSize: 11, cursor: active === 0 ? "default" : "pointer",
              opacity: active === 0 ? 0.4 : 1,
            }}>← Previous</button>
          <span style={{ fontSize: 10, color: "var(--text-vfaint)" }}>
            {sections[active]?.title}
          </span>
          <button
            onClick={() => setActive(a => Math.min(sections.length - 1, a + 1))}
            disabled={active === sections.length - 1}
            style={{
              padding: "6px 12px", borderRadius: 6, fontFamily: "inherit",
              background: active === sections.length - 1 ? "transparent" : "var(--accent)",
              border: `1px solid ${active === sections.length - 1 ? "var(--border-strong)" : "var(--accent)"}`,
              color: active === sections.length - 1 ? "var(--text-vfaint)" : "#fff",
              fontSize: 11, cursor: active === sections.length - 1 ? "default" : "pointer",
              opacity: active === sections.length - 1 ? 0.4 : 1,
            }}>Next →</button>
        </div>
      </div>
    </div>
  );
}

function parseSections(markdown) {
  // Split by H2 headings (## Title) — these are the major sections from the architect/cost/iac
  if (!markdown || !markdown.includes("##")) return [];

  const SECTION_ICONS = {
    "architecture overview":  "🌐",
    "requirements":           "📋",
    "requirements analysis":  "📋",
    "component specification":"🧩",
    "component plan":         "🧩",
    "design principles":      "⚖️",
    "data flow":              "🔀",
    "implementation roadmap": "🗺️",
    "trade-offs":             "⚠️",
    "sources":                "📚",
    "cost breakdown":         "💰",
    "cost estimate":          "💰",
    "💰 cost estimate (calculated from full component plan)": "💰",
    "budget check":           "💰",
    "optimization":           "📉",
    "cost optimization opportunities": "📉",
    "3-year tco projection":  "📈",
    "infrastructure as code": "🏗️",
    "🏗️ infrastructure as code": "🏗️",
    "terraform":              "📦",
    "aws cdk":                "📦",
    "aws cdk v2 (python)":    "📦",
    "deploy":                 "🚀",
    "what it is":             "📖",
    "core concepts":          "📖",
    "how it works internally":"⚙️",
    "when to use it":         "✅",
    "when to use it / when not to":"✅",
    "pricing model":          "💰",
    "integration patterns":   "🔌",
    "head-to-head":           "⚖️",
    "decision framework":     "🤔",
    "verdict":                "✅",
  };

  const lines = markdown.split("\n");
  const sections = [];
  let current = null;
  let preamble = "";

  for (const line of lines) {
    const m = line.match(/^##\s+(.+)/);
    if (m) {
      if (current) sections.push(current);
      const title = m[1].trim().replace(/^[💰🏗️🌐📋🧩⚖️🔀🗺️⚠️📚📉📈📦🚀📖⚙️✅🔌🤔]\s*/g, "");
      const key = title.toLowerCase();
      current = { title, icon: SECTION_ICONS[key] || "", content: "" };
    } else {
      if (current) current.content += line + "\n";
      else         preamble += line + "\n";
    }
  }
  if (current) sections.push(current);

  if (preamble.trim() && sections.length > 0) {
    sections.unshift({ title: "Intro", icon: "", content: preamble });
  }

  // Filter out internal/technical sections that aren't useful for the end user:
  //   - "Component Plan (JSON for cost calculation)" — internal payload for the cost tool
  //   - Sections that are >70% JSON code block (also internal)
  const isInternal = (s) => {
    const titleLc = s.title.toLowerCase();
    if (titleLc.includes("component plan") || titleLc.includes("json for cost")) return true;
    // Section dominated by a ```json block
    const jsonBlocks = (s.content.match(/```json[\s\S]*?```/g) || []).join("");
    if (jsonBlocks.length > 0 && jsonBlocks.length / Math.max(s.content.length, 1) > 0.6) return true;
    return false;
  };

  return sections.filter(s => (s.content.trim() || s.title) && !isInternal(s));
}
