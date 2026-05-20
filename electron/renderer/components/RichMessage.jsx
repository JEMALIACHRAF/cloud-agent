import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * RichMessage — turns the agent's markdown into structured, prioritized UI cards.
 *
 * Detects section types by H2 heading and renders each appropriately:
 *   Summary / TL;DR / Executive Summary → blue accent card at top
 *   Findings / Risks / Issues          → list with severity icons
 *   Resources / Created / Inventory    → table with Console links
 *   Cost / Pricing / Estimate          → large number cards
 *   Next Steps / Actions / Recommend   → checklist
 *   Sources / References               → link cards
 *   * (anything else)                  → standard markdown
 *
 * Also detects in body:
 *   - AWS resource IDs (i-xxx, sg-xxx, vol-xxx, vpc-xxx, arn:aws:…)
 *   - Console URLs (console.aws.amazon.com) → render as buttons
 *   - Cost figures ($X/month, $X/hour) → highlighted
 */

const SECTION_PATTERNS = {
  summary:   /^(summary|executive\s+summary|tl;?dr|overview)\b/i,
  findings:  /^(findings?|issues?|risks?|alerts?|problems?)\b/i,
  resources: /^(resources?|created|inventory|results?)\b/i,
  cost:      /^(cost|pricing|estimate|budget|tco|monthly\s+cost)\b/i,
  actions:   /^(next\s+steps?|action|recommend|to\s+do|recommendations?)\b/i,
  sources:   /^(sources?|references?|docs?|documentation|see\s+also)\b/i,
  architecture: /^(architecture|design|diagram)\b/i,
  domain_breakdown: /^(domain|coverage|breakdown)\b/i,
};


// ── Parser ─────────────────────────────────────────────────────────────────────

function parseSections(content) {
  if (!content) return [];

  // Split by H2 (## heading) — keep heading with content
  const lines = content.split("\n");
  const sections = [];
  let current = { type: "intro", title: "", body: [] };

  for (const line of lines) {
    const h2 = line.match(/^##\s+(.+?)\s*$/);
    if (h2) {
      if (current.body.length > 0 || current.title) sections.push(current);
      const title = h2[1].replace(/^[🎯💰⚠️🔍📋📚🏗️✅⚡🛡️🟢🟠🔴]+\s*/, "").trim();
      let type = "generic";
      for (const [t, re] of Object.entries(SECTION_PATTERNS)) {
        if (re.test(title)) { type = t; break; }
      }
      current = { type, title, body: [] };
    } else {
      current.body.push(line);
    }
  }
  if (current.body.length > 0 || current.title) sections.push(current);
  return sections.map(s => ({ ...s, body: s.body.join("\n").trim() }));
}


// ── Pattern detectors ──────────────────────────────────────────────────────────

const RX = {
  consoleUrl: /https?:\/\/[a-z0-9.-]*console\.aws\.amazon\.com[^\s)"'`<>]+/gi,
  docsUrl:    /https?:\/\/docs\.aws\.amazon\.com[^\s)"'`<>]+/gi,
  resourceId: /\b((i|vol|sg|vpc|subnet|ami|eipalloc)-[a-f0-9]{8,17})\b/g,
  awsArn:     /\barn:aws:[a-z0-9-]+:[a-z0-9-]*:\d*:[^\s"`'<>]+/g,
  cost:       /\$\s?\d+(?:[.,]\d{1,2})?(?:\s?\/\s?(?:month|mo|hour|hr|year|yr|day))?/gi,
  severity:   /^(?:[-*]\s+)?(?:🔴|🟠|🟡|🟢|⚠️|❌|✅|✓|✗)\s*(?:\[?(?:CRITICAL|HIGH|MEDIUM|LOW|OK)\]?:?\s*)?/i,
};


function extractMetrics(content) {
  const metrics = [];
  // Find $X/mo or $X.XX/month patterns
  const costMatches = [...content.matchAll(/\*\*?\$\s?(\d+(?:[.,]\d{1,2})?)\s?\/\s?(month|mo|hour|hr|year|yr)\*\*?/gi)];
  for (const m of costMatches.slice(0, 3)) {
    metrics.push({ kind: "cost", value: `$${m[1]}`, unit: `/${m[2].toLowerCase()}` });
  }
  // Find counts: "X instances", "X buckets", "X alerts"
  const countMatches = [...content.matchAll(/\*\*?(\d+)\*\*?\s+(instances?|buckets?|alerts?|alarms?|users?|functions?|tables?|certificates?)/gi)];
  for (const m of countMatches.slice(0, 4)) {
    if (!metrics.find(x => x.kind === "count" && x.label === m[2])) {
      metrics.push({ kind: "count", value: m[1], label: m[2] });
    }
  }
  return metrics;
}


// ── Main component ────────────────────────────────────────────────────────────

export default function RichMessage({ content }) {
  const { sections, metrics } = useMemo(() => {
    const secs = parseSections(content);
    const mets = extractMetrics(content);
    return { sections: secs, metrics: mets };
  }, [content]);

  if (!content) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Top metrics row */}
      {metrics.length > 0 && <MetricsRow metrics={metrics} />}

      {sections.map((sec, i) => {
        if (!sec.body.trim() && !sec.title) return null;
        switch (sec.type) {
          case "intro":          return sec.body.trim() ? <IntroBlock key={i} body={sec.body} /> : null;
          case "summary":        return <SummaryCard key={i} title={sec.title} body={sec.body} />;
          case "findings":       return <FindingsBlock key={i} title={sec.title} body={sec.body} />;
          case "resources":      return <ResourcesBlock key={i} title={sec.title} body={sec.body} />;
          case "cost":           return <CostBlock key={i} title={sec.title} body={sec.body} />;
          case "actions":        return <ActionsBlock key={i} title={sec.title} body={sec.body} />;
          case "sources":        return <SourcesBlock key={i} title={sec.title} body={sec.body} />;
          case "architecture":   return <ArchitectureBlock key={i} title={sec.title} body={sec.body} />;
          default:               return <GenericSection key={i} title={sec.title} body={sec.body} />;
        }
      })}
    </div>
  );
}


// ── Section components ────────────────────────────────────────────────────────

function IntroBlock({ body }) {
  return (
    <div className="md-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
    </div>
  );
}

function SummaryCard({ title, body }) {
  return (
    <div style={{
      padding: "14px 16px", borderRadius: 10,
      background: "var(--accent-bg)",
      border: "1px solid var(--accent-border)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <div style={{ width: 3, height: 14, background: "var(--accent)", borderRadius: 2 }} />
        <span style={{ fontSize: 10, color: "var(--accent)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          {title}
        </span>
      </div>
      <div className="md-content" style={{ fontSize: 13 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
      </div>
    </div>
  );
}

function FindingsBlock({ title, body }) {
  // Try to extract list items with severity
  const lines = body.split("\n").filter(l => l.trim());
  const items = lines
    .filter(l => /^[-*]\s/.test(l) || /^\d+\./.test(l))
    .map(l => l.replace(/^[-*]\s+|^\d+\.\s+/, ""));

  if (items.length === 0) {
    return <GenericSection title={title} body={body} color="#ef4444" />;
  }

  return (
    <SectionShell title={title} color="#ef4444">
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {items.map((item, i) => <FindingItem key={i} text={item} />)}
      </div>
    </SectionShell>
  );
}

function FindingItem({ text }) {
  const sev = detectSeverity(text);
  const clean = text.replace(RX.severity, "").trim();
  return (
    <div style={{
      display: "flex", gap: 9, padding: "8px 10px", borderRadius: 7,
      background: `color-mix(in srgb, ${sev.color} 3%, transparent)`, border: `1px solid color-mix(in srgb, ${sev.color} 14%, transparent)`,
    }}>
      <div style={{ width: 3, background: sev.color, borderRadius: 2, flexShrink: 0 }} />
      <div style={{ flex: 1, fontSize: 12, color: "var(--text-body)", lineHeight: 1.5 }}>
        {sev.label && (
          <span style={{ fontSize: 9, fontWeight: 700, color: sev.color, marginRight: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {sev.label}
          </span>
        )}
        <span className="md-inline">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES_INLINE}>{clean}</ReactMarkdown>
        </span>
      </div>
    </div>
  );
}

function detectSeverity(text) {
  const t = text.toLowerCase();
  if (/🔴|critical/.test(t))         return { label: "CRITICAL", color: "#ef4444" };
  if (/🟠|\bhigh\b/.test(t))          return { label: "HIGH",     color: "#fb923c" };
  if (/🟡|⚠️|\bmedium\b|warning/.test(t)) return { label: "MEDIUM", color: "var(--warning)" };
  if (/🟢|✅|✓|\bok\b/.test(t))       return { label: "OK",       color: "var(--success)" };
  return { label: "", color: "var(--info)" };
}

function ResourcesBlock({ title, body }) {
  // Find resource items - lines with resource IDs or ARNs
  const lines = body.split("\n").filter(l => l.trim() && (RX.resourceId.test(l) || RX.awsArn.test(l) || /\bs3:\/\//.test(l) || /console\.aws/.test(l)));
  RX.resourceId.lastIndex = 0; RX.awsArn.lastIndex = 0;

  if (lines.length === 0) {
    return <GenericSection title={title} body={body} color="var(--success)" />;
  }

  return (
    <SectionShell title={title} color="var(--success)">
      <div className="md-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
      </div>
    </SectionShell>
  );
}

function CostBlock({ title, body }) {
  return (
    <SectionShell title={title} color="var(--warning)">
      <div className="md-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
      </div>
    </SectionShell>
  );
}

function ActionsBlock({ title, body }) {
  const lines = body.split("\n").filter(l => /^[-*]\s|^\d+\./.test(l.trim()))
    .map(l => l.replace(/^[-*]\s+|^\d+\.\s+/, "").trim())
    .filter(Boolean);

  if (lines.length === 0) {
    return <GenericSection title={title} body={body} color="#a78bfa" />;
  }

  return (
    <SectionShell title={title} color="#a78bfa">
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {lines.map((step, i) => (
          <div key={i} style={{
            display: "flex", gap: 9, padding: "8px 10px", borderRadius: 7,
            background: "var(--bg-card)", border: "1px solid #1a1a1a",
          }}>
            <div style={{
              width: 18, height: 18, borderRadius: "50%",
              background: "var(--accent-bg)", border: "1px solid #2a2a50",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, color: "var(--accent)", flexShrink: 0, fontWeight: 600,
            }}>{i + 1}</div>
            <div style={{ flex: 1, fontSize: 12, color: "var(--text-body)", lineHeight: 1.5 }}>
              <span className="md-inline">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES_INLINE}>{step}</ReactMarkdown>
              </span>
            </div>
          </div>
        ))}
      </div>
    </SectionShell>
  );
}

function SourcesBlock({ title, body }) {
  // Extract URLs
  const urls = [...new Set([...body.matchAll(RX.docsUrl)].map(m => m[0]))];
  if (urls.length === 0) {
    return <GenericSection title={title} body={body} color="var(--docs)" />;
  }
  return (
    <SectionShell title={title} color="var(--docs)">
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {urls.map((url, i) => (
          <a key={i} href={url}
             onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(url) || window.open(url, "_blank"); }}
             style={{
               display: "flex", alignItems: "center", gap: 9, padding: "8px 10px", borderRadius: 7,
               background: "var(--bg-card)", border: "1px solid #2a1810",
               textDecoration: "none", transition: "all 0.1s",
             }}
             onMouseEnter={e => e.currentTarget.style.borderColor = "var(--border-hover)"}
             onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
          >
            <span style={{ color: "var(--docs)", fontSize: 11, fontWeight: 600 }}>↗</span>
            <span style={{ fontSize: 10, color: "var(--docs)", fontFamily: "ui-monospace, monospace", wordBreak: "break-all" }}>
              {url.replace("https://", "")}
            </span>
          </a>
        ))}
      </div>
    </SectionShell>
  );
}

function ArchitectureBlock({ title, body }) {
  return (
    <SectionShell title={title} color="var(--info)">
      <div className="md-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
      </div>
    </SectionShell>
  );
}

function GenericSection({ title, body, color = "var(--text-dim)" }) {
  return (
    <SectionShell title={title} color={color}>
      <div className="md-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_OVERRIDES}>{body}</ReactMarkdown>
      </div>
    </SectionShell>
  );
}

function SectionShell({ title, color, children }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, marginTop: 4 }}>
        <div style={{ width: 3, height: 14, background: color, borderRadius: 2 }} />
        <span style={{ fontSize: 10, color, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}


// ── Metrics row at top ────────────────────────────────────────────────────────

function MetricsRow({ metrics }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(metrics.length, 4)}, 1fr)`, gap: 8 }}>
      {metrics.slice(0, 4).map((m, i) => (
        <div key={i} style={{
          padding: "12px 14px", borderRadius: 9,
          background: m.kind === "cost" ? "var(--bg-card)" : "var(--bg-card)",
          border: `1px solid ${m.kind === "cost" ? "var(--border-hover)" : "var(--accent-bg)"}`,
        }}>
          <div style={{
            fontSize: 20, fontWeight: 700,
            color: m.kind === "cost" ? "var(--warning)" : "var(--accent)",
            letterSpacing: "-0.5px",
          }}>
            {m.value}
            {m.unit && <span style={{ fontSize: 11, color: "var(--text-dim)", fontWeight: 400, marginLeft: 3 }}>{m.unit}</span>}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {m.label || (m.kind === "cost" ? "estimate" : "")}
          </div>
        </div>
      ))}
    </div>
  );
}


// ── Markdown overrides ────────────────────────────────────────────────────────

const MD_OVERRIDES = {
  a: ({ href, children }) => {
    const isConsole = href && /console\.aws\.amazon\.com/.test(href);
    const isDocs    = href && /docs\.aws\.amazon\.com/.test(href);
    if (isConsole) return <ConsoleLink href={href}>{children}</ConsoleLink>;
    if (isDocs)    return <DocsLink href={href}>{children}</DocsLink>;
    return <a href={href}
              onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(href) || window.open(href, "_blank"); }}
              style={{ color: "#a78bfa", textDecoration: "none" }}>{children}</a>;
  },
  code: ({ inline, className, children }) => {
    if (inline) return <code className={className}>{children}</code>;
    // Block code — keep default rendering
    return <pre><code className={className}>{children}</code></pre>;
  },
};

const MD_OVERRIDES_INLINE = {
  ...MD_OVERRIDES,
  p: ({ children }) => <>{children}</>,  // no <p> wrapping in inline contexts
};


function ConsoleLink({ href, children }) {
  return (
    <a href={href}
       onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(href) || window.open(href, "_blank"); }}
       style={{
         display: "inline-flex", alignItems: "center", gap: 4,
         padding: "1px 8px", borderRadius: 5,
         background: "var(--bg-card)", border: "1px solid #1a3a4a",
         color: "var(--console)", textDecoration: "none",
         fontSize: 11, fontWeight: 500,
       }}>
      <span style={{ fontSize: 9 }}>↗</span>
      <span>{children}</span>
    </a>
  );
}

function DocsLink({ href, children }) {
  return (
    <a href={href}
       onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(href) || window.open(href, "_blank"); }}
       style={{
         color: "var(--docs)", textDecoration: "none",
         borderBottom: "1px dotted #f97316",
       }}>
      {children}
    </a>
  );
}
