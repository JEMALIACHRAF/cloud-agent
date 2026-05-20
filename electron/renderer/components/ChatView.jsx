import React, { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAgent } from "../hooks/useAgent";
import { useCredentials } from "../hooks/useCredentials";
import RichMessage from "./RichMessage";

const LEVEL_LABELS = { beginner: "Beginner", intermediate: "Mid", architect: "Architect", cto: "C-Level" };
const LEVEL_COLORS = { beginner: "var(--success)", intermediate: "var(--info)", architect: "#a78bfa", cto: "var(--warning)" };

const AGENT_LABELS = {
  docs_researcher: "AWS Docs",
  supervisor:      "Routing",
  infra_agent:     "Infrastructure",
  security_agent:  "Security",
  cost_agent:      "Cost & Pricing",
  data_agent:      "Data",
  devops_agent:    "DevOps",
  general_agent:   "Generalist",
};

const AGENT_COLORS = {
  docs_researcher: "var(--docs)",
  supervisor:      "var(--text-medium)",
  infra_agent:     "#3b82f6",
  security_agent:  "#ef4444",
  cost_agent:      "#10b981",
  data_agent:      "#a855f7",
  devops_agent:    "#f59e0b",
  general_agent:  "#6366f1",
};

const EXAMPLES = {
  beginner:     ["What is Amazon S3?", "How much does an EC2 t3.small cost?", "Difference between EC2 and Lambda?", "Secure my AWS account: where to start?"],
  intermediate: ["List my EC2 instances and their costs", "Audit security groups for SSH open to the world", "Show S3 buckets without encryption", "What's my AWS spend this month, top 5 services?"],
  architect:    ["Audit IAM for overly permissive policies", "List CloudWatch alarms in ALARM state", "Find unencrypted RDS instances across regions", "Compute monthly cost of switching m5.xlarge to Spot"],
  cto:          ["Executive summary of my AWS infrastructure", "3-year TCO if we add 50% more EC2 capacity", "Critical compliance gaps (CIS/SOC2)", "Top cost drivers and savings opportunities"],
};

export default function ChatView() {
  const [input,   setInput]   = useState("");
  const [rightPanel, setRightPanel] = useState("sources");
  const [selMsg,  setSelMsg]  = useState(null);
  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  const {
    messages, isStreaming, pendingReview, activeTools, activeAgent,
    userProfile, sendMessage, approveAction, rejectAction, cancelStream, newThread,
  } = useAgent();
  const { getCredentials } = useCredentials();

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, activeTools]);

  // Auto-select latest assistant message for source panel
  useEffect(() => {
    const lastAssistant = [...messages].reverse().find(m => m.role === "assistant");
    if (lastAssistant && lastAssistant.id !== selMsg?.id) setSelMsg(lastAssistant);
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    inputRef.current?.focus();
    const creds = await getCredentials();
    await sendMessage(text, creds);
  }, [input, isStreaming, sendMessage, getCredentials]);

  const level = userProfile.level || "intermediate";
  const levelColor = LEVEL_COLORS[level] || "var(--info)";
  const examples = EXAMPLES[level] || EXAMPLES.intermediate;

  const hasSidePanel = selMsg && (selMsg.docs_sources?.length > 0 || selMsg.tool_calls?.length > 0);

  return (
    <div style={{ display: "flex", height: "100%", background: "var(--bg)", fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* Header */}
        <div style={styles.header}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, color: "var(--text-vfaint)", fontFamily: "ui-monospace, monospace", letterSpacing: "0.04em" }}>
              CLOUD AGENT
            </span>
            {activeAgent && (
              <ActiveAgentPill agent={activeAgent} />
            )}
            {activeTools.length > 0 && (
              <ActiveToolPill tool={activeTools[activeTools.length - 1]} />
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ padding: "3px 9px", borderRadius: 5, background: "rgba(255,255,255,0.03)", border: "1px solid #1f1f1f", display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: levelColor }} />
              <span style={{ fontSize: 10, color: levelColor }}>{LEVEL_LABELS[level]}</span>
            </div>
            <button onClick={() => { newThread(); setSelMsg(null); }} style={styles.btn}>New thread</button>
            {isStreaming && <button onClick={cancelStream} style={{...styles.btn, color: "var(--danger)", borderColor: "var(--border-strong)"}}>Stop</button>}
          </div>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px" }}>
          {messages.length === 0 && <EmptyState level={level} examples={examples} onExample={t => { setInput(t); inputRef.current?.focus(); }} />}

          <div style={{ maxWidth: 820, margin: "0 auto", display: "flex", flexDirection: "column", gap: 22 }}>
            {messages.map(msg => (
              <Msg key={msg.id} message={msg}
                onSelect={() => msg.role === "assistant" && setSelMsg(msg)}
                isSelected={selMsg?.id === msg.id}
              />
            ))}

            {pendingReview && (
              <ReviewCard
                review={pendingReview}
                onApprove={async () => { const c = await getCredentials(); approveAction(c); }}
                onReject ={async () => { const c = await getCredentials(); rejectAction(c); }}
              />
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div style={{ borderTop: "1px solid #141414", background: "var(--bg-elevated)", padding: "14px 32px 16px" }}>
          <div style={{ maxWidth: 820, margin: "0 auto" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="Ask anything — agents will search AWS docs first"
                rows={1}
                disabled={isStreaming || !!pendingReview}
                style={{
                  flex: 1, resize: "none", background: "var(--bg-hover)", border: "1px solid #222",
                  borderRadius: 10, padding: "10px 14px", fontSize: 13, color: "var(--text-body)",
                  fontFamily: "ui-sans-serif, system-ui, sans-serif", outline: "none",
                  lineHeight: 1.5, maxHeight: 140,
                  opacity: (isStreaming || !!pendingReview) ? 0.4 : 1,
                }}
                onFocus={e => e.target.style.borderColor = "#333"}
                onBlur ={e => e.target.style.borderColor = "var(--border-strong)"}
              />
              <button
                onClick={handleSend}
                disabled={isStreaming || !input.trim() || !!pendingReview}
                style={{
                  width: 38, height: 38, borderRadius: 9, border: "none", cursor: "pointer",
                  background: (isStreaming || !input.trim()) ? "var(--border-strong)" : "var(--accent)",
                  color: "#fff", fontSize: 16, display: "flex", alignItems: "center",
                  justifyContent: "center", flexShrink: 0,
                }}
              >
                {isStreaming
                  ? <div style={{ width: 14, height: 14, border: "2px solid #444", borderTopColor: "var(--text-medium)", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                  : "↑"}
              </button>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, padding: "0 2px" }}>
              <span style={{ fontSize: 10, color: "var(--border-hover)" }}>Enter to send · Shift+Enter newline</span>
              <span style={{ fontSize: 10, color: "var(--border-hover)" }}>Docs-first · {level} mode · persistent memory</span>
            </div>
          </div>
        </div>
      </div>

      {/* Right panel: sources + tools */}
      {hasSidePanel && (
        <RightPanel
          message={selMsg}
          activeTab={rightPanel}
          onTabChange={setRightPanel}
        />
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
        textarea::placeholder { color: #2d2d2d; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-thumb { background: #1a1a1a; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #2a2a2a; }
      `}</style>
    </div>
  );
}

// ── Active agent pill ──────────────────────────────────────────────────────────

function ActiveAgentPill({ agent }) {
  const color = AGENT_COLORS[agent.name] || "#6366f1";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, padding: "3px 10px",
      borderRadius: 12, background: `color-mix(in srgb, ${color} 6%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 19%, transparent)`,
    }}>
      <div style={{ width: 5, height: 5, borderRadius: "50%", background: color, animation: "pulse 1.4s infinite" }} />
      <span style={{ fontSize: 11, color, fontWeight: 500 }}>
        {AGENT_LABELS[agent.name] || agent.label}
      </span>
    </div>
  );
}

function ActiveToolPill({ tool }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, padding: "3px 10px",
      borderRadius: 12, background: "var(--bg-card)", border: "1px solid #2a2010",
    }}>
      <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--warning)", animation: "pulse 0.8s infinite" }} />
      <span style={{ fontSize: 10, color: "var(--warning)", fontFamily: "ui-monospace, monospace" }}>{tool.name}</span>
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────────

function EmptyState({ level, examples, onExample }) {
  const levelColor = LEVEL_COLORS[level] || "var(--info)";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 420, textAlign: "center", maxWidth: 560, margin: "0 auto" }}>
      <div style={{
        width: 44, height: 44, borderRadius: 12,
        background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
        display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: 18, color: "#fff", fontWeight: 700, fontSize: 18,
        boxShadow: "0 8px 24px rgba(79,70,229,0.25)",
      }}>C</div>
      <h2 style={{ fontSize: 16, fontWeight: 600, color: "var(--text)", margin: "0 0 6px", letterSpacing: "-0.2px" }}>
        AWS Agent
      </h2>
      <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "0 0 6px", lineHeight: 1.6 }}>
        Every answer is grounded in <span style={{ color: "var(--docs)" }}>official AWS documentation</span>
      </p>
      <p style={{ fontSize: 11, color: "var(--text-vfaint)", margin: "0 0 26px" }}>
        Mode: <span style={{ color: levelColor }}>{LEVEL_LABELS[level]}</span> · adapts from your questions
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, width: "100%" }}>
        {examples.map((ex, i) => (
          <button key={i} onClick={() => onExample(ex)} style={{
            textAlign: "left", padding: "10px 13px", borderRadius: 8,
            background: "var(--bg-card)", border: "1px solid #1a1a1a",
            color: "var(--text-dim)", fontSize: 12, cursor: "pointer",
            lineHeight: 1.4, fontFamily: "inherit", transition: "all 0.12s",
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor="var(--border-hover)"; e.currentTarget.style.color="var(--text-medium)"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor="var(--border-strong)"; e.currentTarget.style.color="var(--text-dim)"; }}
          >{ex}</button>
        ))}
      </div>
    </div>
  );
}

// ── Message ────────────────────────────────────────────────────────────────────

function Msg({ message, onSelect, isSelected }) {
  if (message.role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{
          maxWidth: "72%", background: "var(--accent-bg)", border: "1px solid #232340",
          borderRadius: "12px 12px 4px 12px", padding: "10px 14px",
          fontSize: 13, color: "var(--text-body)", lineHeight: 1.6,
        }}>{message.content}</div>
      </div>
    );
  }

  return (
    <div style={{ cursor: message.content ? "pointer" : "default" }} onClick={onSelect}>
      {message.agents?.length > 0 && <AgentPipeline agents={message.agents} />}

      {(message.tool_calls?.length > 0 || message.docs_sources?.length > 0) && (
        <CompactSummary
          toolCount={message.tool_calls?.filter(c => c.status === "done").length || 0}
          sourceCount={message.docs_sources?.length || 0}
          runningTools={message.tool_calls?.filter(c => c.status === "running") || []}
        />
      )}

      {/* v19 — Approval-required card with Approve/Cancel buttons */}
      {message.approval_required && (
        <div style={{
          padding: "14px 16px", borderRadius: 10, background: "var(--bg-card)",
          border: "1px solid var(--warning, #b58b00)",
          marginBottom: 10, fontSize: 13,
        }}>
          <div style={{ fontWeight: 600, color: "var(--warning, #b58b00)", marginBottom: 6 }}>
            ⏸ Awaiting your approval
          </div>
          <div style={{ color: "var(--text-secondary)", marginBottom: 10, lineHeight: 1.5 }}>
            {message.approval_required.message}
          </div>
          {message.approval_required.tool_calls?.length > 0 && (
            <div style={{
              background: "var(--bg-elevated)", padding: 10, borderRadius: 6,
              fontFamily: "monospace", fontSize: 11, marginBottom: 12, overflow: "auto",
            }}>
              {message.approval_required.tool_calls.map((tc, i) => (
                <div key={i} style={{ marginBottom: i < message.approval_required.tool_calls.length - 1 ? 8 : 0 }}>
                  <div style={{ color: "var(--accent)", fontWeight: 600 }}>{tc.name}</div>
                  <div style={{ color: "var(--text-secondary)", marginLeft: 8 }}>
                    {JSON.stringify(tc.args, null, 2).split("\n").map((line, j) => (
                      <div key={j}>{line}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={async () => {
              const creds = getCredentials();
              await sendMessage("approve", creds);
            }} style={{
              padding: "6px 14px", background: "var(--accent)", color: "white", border: "none",
              borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}>Approve & Execute</button>
            <button onClick={async () => {
              const creds = getCredentials();
              await sendMessage("cancel", creds);
            }} style={{
              padding: "6px 14px", background: "transparent", color: "var(--text-secondary)",
              border: "1px solid var(--border-strong)", borderRadius: 6, fontSize: 12, cursor: "pointer",
            }}>Cancel</button>
          </div>
        </div>
      )}

      {/* v19 — Error display with details */}
      {message.error && (
        <div style={{
          padding: "12px 14px", borderRadius: 8, background: "var(--bg-card)",
          border: "1px solid #3a1515", marginBottom: 8, fontSize: 12,
        }}>
          <div style={{ color: "var(--danger)", fontWeight: 600, marginBottom: 6 }}>
            {message.error_fatal ? "✕ Error" : "⚠ Warning"}
          </div>
          <div style={{ color: "var(--text-secondary)", marginBottom: message.error_details ? 8 : 0 }}>
            {message.error}
          </div>
          {message.error_details && (
            <details style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
              <summary style={{ cursor: "pointer", marginBottom: 4 }}>Stack trace</summary>
              <pre style={{
                background: "var(--bg-elevated)", padding: 8, borderRadius: 4,
                overflow: "auto", fontFamily: "monospace", whiteSpace: "pre-wrap",
              }}>{message.error_details}</pre>
            </details>
          )}
        </div>
      )}

      {message.content && (
        <div style={{
          background: "var(--bg-card)", border: `1px solid ${isSelected ? "var(--accent-border)" : "var(--border-strong)"}`,
          borderRadius: "4px 12px 12px 12px", padding: "16px 18px",
          transition: "border-color 0.15s",
        }}>
          <RichMessage
            content={message.content}
            onConfirm={async () => {
              const creds = getCredentials();
              await sendMessage("confirm — proceed with the plan as proposed", creds);
            }}
            onCancel={async () => {
              const creds = getCredentials();
              await sendMessage("cancel — do not create anything", creds);
            }}
          />
        </div>
      )}

      {!message.content && !message.error && (
        <div style={{ display: "flex", gap: 4, padding: "14px 4px" }}>
          {[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#333", animation: `pulse 1.2s ${i*0.2}s infinite` }} />)}
        </div>
      )}
    </div>
  );
}

// ── Agent pipeline (horizontal) ────────────────────────────────────────────────

function AgentPipeline({ agents }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 10, flexWrap: "wrap" }}>
      {agents.map((agent, i) => {
        const color = AGENT_COLORS[agent.name] || "var(--text-dim)";
        const isDone = agent.status === "done";
        return (
          <React.Fragment key={i}>
            {i > 0 && <span style={{ color: "var(--border-hover)", fontSize: 10 }}>›</span>}
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "3px 9px", borderRadius: 5,
              background: isDone ? "var(--bg-card)" : `color-mix(in srgb, ${color} 7%, transparent)`,
              border: `1px solid ${isDone ? "var(--border-strong)" : `color-mix(in srgb, ${color} 19%, transparent)`}`,
            }}>
              {!isDone && <div style={{ width: 5, height: 5, borderRadius: "50%", background: color, animation: "pulse 1.2s infinite" }} />}
              {isDone  && <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--border-hover)" }} />}
              <span style={{ fontSize: 10, color: isDone ? "var(--text-faint)" : color, fontWeight: 500 }}>
                {AGENT_LABELS[agent.name] || agent.name}
                {isDone && agent.elapsed > 0 && (
                  <span style={{ color: "var(--border-hover)", marginLeft: 4, fontWeight: 400 }}>{(agent.elapsed/1000).toFixed(1)}s</span>
                )}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── Compact summary (sources + tools count) ────────────────────────────────────

function CompactSummary({ toolCount, sourceCount, runningTools }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
      {sourceCount > 0 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 5,
          padding: "3px 9px", borderRadius: 5,
          background: "var(--bg-card)", border: "1px solid #2a1810",
          fontSize: 10, color: "var(--docs)",
        }}>
          <span>📚</span>
          {sourceCount} AWS doc{sourceCount > 1 ? "s" : ""} cited
        </div>
      )}
      {toolCount > 0 && (
        <div style={{
          padding: "3px 9px", borderRadius: 5,
          background: "var(--bg-card)", border: "1px solid #103018",
          fontSize: 10, color: "var(--success)", fontFamily: "ui-monospace, monospace",
        }}>
          ✓ {toolCount} AWS call{toolCount > 1 ? "s" : ""}
        </div>
      )}
      {runningTools.map((tc, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 5,
          padding: "3px 9px", borderRadius: 5,
          background: "var(--bg-card)", border: "1px solid #2a2010",
          fontSize: 10, color: "var(--warning)", fontFamily: "ui-monospace, monospace",
        }}>
          <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--warning)", animation: "pulse 0.8s infinite" }} />
          {tc.name}
        </div>
      ))}
    </div>
  );
}

// ── Review card ────────────────────────────────────────────────────────────────

function ReviewCard({ review, onApprove, onReject }) {
  return (
    <div style={{ padding: "16px 18px", borderRadius: 10, background: "var(--bg-card)", border: "1px solid #2a2010" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--warning)", marginBottom: 12 }}>⚠ Action requires your approval</div>
      <div style={{ marginBottom: 14 }}>
        {review.pending_tool_calls?.map((tc, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <span style={{ color: "var(--warning)", fontSize: 11 }}>→</span>
            <div>
              <span style={{ fontSize: 11, color: "var(--warning)", fontFamily: "ui-monospace, monospace", fontWeight: 600 }}>{tc.name}</span>
              {tc.args && Object.keys(tc.args).length > 0 && (
                <pre style={{ fontSize: 10, color: "var(--text-dim)", margin: "4px 0 0", fontFamily: "ui-monospace, monospace" }}>
                  {JSON.stringify(tc.args, null, 2)}
                </pre>
              )}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={onApprove} style={{ flex: 1, padding: "8px", borderRadius: 7, border: "1px solid #1a3a1a", background: "var(--bg-card)", color: "var(--success)", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>Approve</button>
        <button onClick={onReject}  style={{ flex: 1, padding: "8px", borderRadius: 7, border: "1px solid #222",   background: "var(--bg-hover)", color: "var(--text-dim)",    fontSize: 12, cursor: "pointer" }}>Reject</button>
      </div>
    </div>
  );
}

// ── Right panel ────────────────────────────────────────────────────────────────

function RightPanel({ message, activeTab, onTabChange }) {
  const sources = message.docs_sources || [];
  const tools   = message.tool_calls || [];

  return (
    <div style={{ width: 320, flexShrink: 0, borderLeft: "1px solid #141414", background: "var(--bg-deep)", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", borderBottom: "1px solid #141414" }}>
        {sources.length > 0 && (
          <button
            onClick={() => onTabChange("sources")}
            style={{
              flex: 1, padding: "12px 14px", border: "none", background: "transparent",
              color: activeTab === "sources" ? "var(--docs)" : "var(--text-vfaint)",
              fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em",
              cursor: "pointer", borderBottom: activeTab === "sources" ? "1px solid #f97316" : "1px solid transparent",
            }}
          >
            AWS Docs · {sources.length}
          </button>
        )}
        {tools.length > 0 && (
          <button
            onClick={() => onTabChange("tools")}
            style={{
              flex: 1, padding: "12px 14px", border: "none", background: "transparent",
              color: activeTab === "tools" ? "#a78bfa" : "var(--text-vfaint)",
              fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em",
              cursor: "pointer", borderBottom: activeTab === "tools" ? "1px solid #a78bfa" : "1px solid transparent",
            }}
          >
            Tools · {tools.length}
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
        {activeTab === "sources" && sources.map((s, i) => (
          <a key={i}
             href={s.url}
             onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(s.url) || window.open(s.url, "_blank"); }}
             style={{
               display: "block", padding: "10px 12px", marginBottom: 6,
               borderRadius: 7, background: "var(--bg-card)", border: "1px solid #1a1a1a",
               textDecoration: "none", cursor: "pointer", transition: "all 0.1s",
             }}
             onMouseEnter={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
             onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
          >
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--docs)", marginBottom: 4 }}>
              {s.service}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-faint)", fontFamily: "ui-monospace, monospace", wordBreak: "break-all", lineHeight: 1.4 }}>
              {s.url.replace("https://", "")}
            </div>
          </a>
        ))}

        {activeTab === "tools" && tools.map((tc, i) => (
          <ToolCallCard key={i} tc={tc} />
        ))}
      </div>
    </div>
  );
}

function ToolCallCard({ tc }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 6, borderRadius: 7, border: "1px solid #1a1a1a", overflow: "hidden" }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", background: "var(--bg-card)", border: "none", cursor: "pointer", textAlign: "left" }}
      >
        <span style={{ fontSize: 10, color: tc.status === "done" ? "var(--success)" : "var(--warning)" }}>
          {tc.status === "done" ? "✓" : "•"}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "ui-monospace, monospace", flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{tc.name}</span>
        <span style={{ fontSize: 10, color: "var(--border-hover)" }}>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid #141414", background: "var(--bg-deep)" }}>
          {tc.args && (
            <>
              <div style={{ fontSize: 9, color: "var(--border-hover)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Input</div>
              <pre style={{ fontSize: 9, color: "var(--text-dim)", margin: "0 0 8px", fontFamily: "ui-monospace, monospace", overflow: "auto", maxHeight: 120 }}>
                {JSON.stringify(tc.args, null, 2)}
              </pre>
            </>
          )}
          {tc.result && (
            <>
              <div style={{ fontSize: 9, color: "var(--border-hover)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Output</div>
              <pre style={{ fontSize: 9, color: "var(--text-dim)", margin: 0, fontFamily: "ui-monospace, monospace", overflow: "auto", maxHeight: 200, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {typeof tc.result === "string" ? tc.result.slice(0, 1500) : JSON.stringify(tc.result, null, 2).slice(0, 1500)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const styles = {
  header: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "11px 22px", borderBottom: "1px solid #141414",
    background: "var(--bg-elevated)", flexShrink: 0, minHeight: 48,
  },
  btn: {
    padding: "5px 11px", borderRadius: 6, border: "1px solid #1f1f1f",
    background: "transparent", color: "var(--text-dim)", fontSize: 11, cursor: "pointer",
    fontFamily: "inherit", transition: "all 0.1s",
  },
};
