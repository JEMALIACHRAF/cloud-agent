import React, { useState, useEffect, useCallback } from "react";
import {
  IconServer, IconBox, IconZap, IconDatabase, IconGlobe, IconLock,
  IconShield, IconKey, IconRefresh, IconCheckCircle, IconExternal,
} from "../Icons";

const BACKEND = "http://localhost:8000";

// All AWS commercial regions
const AWS_REGIONS = [
  { id: "us-east-1",      label: "US East (N. Virginia)" },
  { id: "us-east-2",      label: "US East (Ohio)" },
  { id: "us-west-1",      label: "US West (N. California)" },
  { id: "us-west-2",      label: "US West (Oregon)" },
  { id: "ca-central-1",   label: "Canada (Central)" },
  { id: "eu-west-1",      label: "Europe (Ireland)" },
  { id: "eu-west-2",      label: "Europe (London)" },
  { id: "eu-west-3",      label: "Europe (Paris)" },
  { id: "eu-central-1",   label: "Europe (Frankfurt)" },
  { id: "eu-north-1",     label: "Europe (Stockholm)" },
  { id: "eu-south-1",     label: "Europe (Milan)" },
  { id: "ap-northeast-1", label: "Asia Pacific (Tokyo)" },
  { id: "ap-northeast-2", label: "Asia Pacific (Seoul)" },
  { id: "ap-southeast-1", label: "Asia Pacific (Singapore)" },
  { id: "ap-southeast-2", label: "Asia Pacific (Sydney)" },
  { id: "ap-south-1",     label: "Asia Pacific (Mumbai)" },
  { id: "sa-east-1",      label: "South America (São Paulo)" },
  { id: "me-south-1",     label: "Middle East (Bahrain)" },
  { id: "af-south-1",     label: "Africa (Cape Town)" },
];

const GROUPS = [
  {
    id: "compute", label: "Compute", Icon: IconServer,
    description: "Servers, containers, and serverless functions",
    tools: [
      { name: "EC2 Instances",    tool: "ec2_list_instances",    Icon: IconServer },
      { name: "ECS Clusters",     tool: "ecs_list_clusters",     Icon: IconBox    },
      { name: "Lambda Functions", tool: "lambda_list_functions", Icon: IconZap    },
    ],
  },
  {
    id: "database", label: "Database", Icon: IconDatabase,
    description: "Relational, NoSQL, and in-memory data stores",
    tools: [
      { name: "RDS Instances",    tool: "rds_list_instances",    Icon: IconDatabase },
      { name: "DynamoDB Tables",  tool: "dynamodb_list_tables",  Icon: IconZap     },
      { name: "ElastiCache",      tool: "elasticache_list_clusters", Icon: IconDatabase },
    ],
  },
  {
    id: "network", label: "Network", Icon: IconGlobe,
    description: "VPCs, security groups, DNS, IPs",
    tools: [
      { name: "VPCs",            tool: "ec2_list_vpcs",                Icon: IconLock   },
      { name: "Security Groups", tool: "ec2_list_security_groups",     Icon: IconShield },
      { name: "Elastic IPs",     tool: "ec2_list_elastic_ips",         Icon: IconGlobe  },
      { name: "Route53 Zones",   tool: "route53_list_hosted_zones",    Icon: IconGlobe  },
    ],
  },
  {
    id: "storage", label: "Storage", Icon: IconBox,
    description: "Object and file storage",
    tools: [
      { name: "S3 Buckets", tool: "s3_list_buckets", Icon: IconBox },
    ],
  },
  {
    id: "security", label: "Security & Identity", Icon: IconShield,
    description: "Users, roles, certificates",
    tools: [
      { name: "IAM Users",    tool: "iam_list_users",        Icon: IconShield },
      { name: "IAM Roles",    tool: "iam_list_roles",        Icon: IconShield },
      { name: "Certificates", tool: "acm_list_certificates", Icon: IconKey    },
    ],
  },
];

function getSettings() {
  try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; }
}

export default function ManifestView({ credentials }) {
  const [resources, setResources] = useState({});
  const [loading,   setLoading]   = useState({});
  const [expanded,  setExpanded]  = useState({});
  const [region,    setRegion]    = useState(credentials?.aws_region || "us-east-1");

  const fetchResource = useCallback(async (toolName) => {
    setLoading(prev => ({ ...prev, [toolName]: true }));
    try {
      // Direct tool execution — NO LLM call, NO token cost, instant.
      const resp = await fetch(`${BACKEND}/agent/tool`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_name:   toolName,
          credentials: credentials || {},
          args:        { region },
        }),
      });
      const data = await resp.json();
      if (data.error) {
        setResources(prev => ({ ...prev, [toolName]: { error: data.error } }));
      } else {
        setResources(prev => ({ ...prev, [toolName]: { data: data.result, loaded_at: new Date().toISOString() } }));
      }
    } catch (e) {
      setResources(prev => ({ ...prev, [toolName]: { error: e.message } }));
    } finally {
      setLoading(prev => ({ ...prev, [toolName]: false }));
    }
  }, [credentials, region]);

  const loadAll = async () => {
    // Sequential with small delay → smooth UI, avoids AWS throttling
    for (const g of GROUPS) {
      for (const t of g.tools) {
        fetchResource(t.tool);
        await new Promise(r => setTimeout(r, 150));
      }
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)", fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      {/* Header */}
      <div style={{
        padding: "18px 28px", borderBottom: "1px solid var(--border)",
        background: "var(--bg-elevated)", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16,
      }}>
        <div>
          <h1 style={{ fontSize: 16, fontWeight: 600, color: "var(--text-strong)", margin: "0 0 4px", letterSpacing: "-0.2px" }}>
            Infrastructure Manifest
          </h1>
          <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5, maxWidth: 600 }}>
            Live read-only inventory of your AWS resources. Click a service to load it from your account — useful for quick audit, debugging, and cost overview without leaving the app.
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <select
            value={region}
            onChange={e => setRegion(e.target.value)}
            style={{
              padding: "7px 10px", borderRadius: 7, fontSize: 12,
              background: "var(--bg-card)", border: "1px solid var(--border-strong)",
              color: "var(--text-body)", fontFamily: "inherit", outline: "none", cursor: "pointer",
              minWidth: 200,
            }}
          >
            {AWS_REGIONS.map(r => <option key={r.id} value={r.id}>{r.id} — {r.label}</option>)}
          </select>
          <button onClick={loadAll} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "7px 14px", borderRadius: 7, border: "none", cursor: "pointer",
            background: "var(--accent)", color: "#fff", fontSize: 12, fontWeight: 500, fontFamily: "inherit",
          }}>
            <IconRefresh size={13} /> Load all
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>
        <div style={{ maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {GROUPS.map(group => (
            <ResourceGroup
              key={group.id}
              group={group}
              resources={resources}
              loading={loading}
              expanded={expanded}
              onToggle={tn => setExpanded(p => ({ ...p, [tn]: !p[tn] }))}
              onFetch={fetchResource}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function ResourceGroup({ group, resources, loading, expanded, onToggle, onFetch }) {
  const G = group;
  const allLoaded = G.tools.every(t => resources[t.tool] && !loading[t.tool]);

  return (
    <div style={{ borderRadius: 10, background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", overflow: "hidden" }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "12px 16px", borderBottom: "1px solid var(--border)",
        background: "var(--bg-card)",
      }}>
        <div style={{ color: "var(--accent)" }}><G.Icon size={16} /></div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: "var(--text)", fontWeight: 600 }}>{G.label}</div>
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 1 }}>{G.description}</div>
        </div>
        <button onClick={() => G.tools.forEach(t => onFetch(t.tool))} style={{
          fontSize: 10, padding: "4px 10px", borderRadius: 5,
          background: "transparent", border: "1px solid var(--border-strong)",
          color: "var(--text-dim)", cursor: "pointer", fontFamily: "inherit",
        }}>Load all in group</button>
      </div>

      <div>
        {G.tools.map(tool => {
          const res = resources[tool.tool];
          const isLoading  = loading[tool.tool];
          const isExpanded = expanded[tool.tool];
          const T = tool;

          return (
            <div key={tool.tool} style={{ borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 16px" }}>
                <div style={{ color: "var(--text-dim)" }}><T.Icon size={14} /></div>
                <span style={{ flex: 1, fontSize: 12, color: "var(--text-body)" }}>{T.name}</span>

                {isLoading && <Spinner />}
                {!isLoading && res && (
                  <>
                    <ResourceCount data={res.data} />
                    <button onClick={() => onToggle(T.tool)} style={iconBtn}>
                      {isExpanded ? "−" : "+"}
                    </button>
                  </>
                )}
                {!isLoading && !res && (
                  <button onClick={() => onFetch(T.tool)} style={{
                    fontSize: 10, padding: "3px 10px", borderRadius: 5,
                    background: "transparent", border: "1px solid var(--border-strong)",
                    color: "var(--text-dim)", cursor: "pointer", fontFamily: "inherit",
                  }}>Load</button>
                )}
              </div>
              {isExpanded && res && (
                <div style={{ padding: "0 16px 14px", background: "var(--bg-deep)" }}>
                  <ResourceData data={res.data} toolName={T.tool} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div style={{
      width: 12, height: 12, border: "2px solid var(--border-strong)",
      borderTopColor: "var(--accent)", borderRadius: "50%",
      animation: "ms-spin 0.8s linear infinite",
    }}>
      <style>{`@keyframes ms-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const iconBtn = {
  background: "transparent", border: "1px solid var(--border-strong)", color: "var(--text-dim)",
  width: 22, height: 22, borderRadius: 5, fontSize: 14, lineHeight: 1, cursor: "pointer", display: "flex",
  alignItems: "center", justifyContent: "center", fontFamily: "inherit",
};

function ResourceCount({ data }) {
  if (!data) return null;
  let count = null, riskFlag = null;
  try {
    const parsed = typeof data === "string" ? JSON.parse(data) : data;
    count = parsed.count
      ?? parsed.instances?.length ?? parsed.buckets?.length ?? parsed.users?.length
      ?? parsed.tables?.length ?? parsed.functions?.length ?? parsed.security_groups?.length
      ?? parsed.clusters?.length ?? parsed.zones?.length ?? parsed.certificates?.length
      ?? parsed.addresses?.length ?? parsed.vpcs?.length;
    if (parsed.high_risk_count > 0)    riskFlag = `${parsed.high_risk_count} at risk`;
    if (parsed.unassociated_count > 0) riskFlag = `${parsed.unassociated_count} unused`;
  } catch {}
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {count != null && (
        <span style={{ fontSize: 11, color: "var(--text-body)", padding: "2px 8px", borderRadius: 9, background: "var(--bg-card)", border: "1px solid var(--border-strong)" }}>{count}</span>
      )}
      {riskFlag && (
        <span style={{ fontSize: 9, color: "var(--warning)", padding: "1px 6px", borderRadius: 5, background: "rgba(251,191,36,0.1)", border: "1px solid rgba(251,191,36,0.25)" }}>{riskFlag}</span>
      )}
    </div>
  );
}

function ResourceData({ data, toolName }) {
  try {
    const parsed = typeof data === "string" ? JSON.parse(data) : data;
    const list = parsed.instances || parsed.buckets || parsed.users || parsed.security_groups
      || parsed.functions || parsed.tables || parsed.vpcs || parsed.clusters || parsed.zones
      || parsed.addresses || parsed.certificates;

    if (Array.isArray(list) && list.length > 0) {
      const cols = Object.keys(list[0]).filter(k => !Array.isArray(list[0][k]) && typeof list[0][k] !== "object").slice(0, 5);
      return (
        <table style={{ width: "100%", marginTop: 10, fontSize: 11, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              {cols.map(c => <th key={c} style={{ textAlign: "left", padding: "6px 8px", color: "var(--text-dim)", fontWeight: 500, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {list.slice(0, 30).map((row, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                {cols.map(c => (
                  <td key={c} style={{ padding: "6px 8px", color: "var(--text-body)", fontFamily: typeof row[c] === "string" && /^[a-z]+-[a-z0-9]+/.test(row[c]) ? "ui-monospace, monospace" : "inherit", fontSize: 10 }}>
                    {String(row[c] ?? "—").slice(0, 60)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    return <pre style={{ marginTop: 10, fontSize: 10, color: "var(--text-dim)", fontFamily: "ui-monospace, monospace", overflow: "auto", maxHeight: 200 }}>
      {JSON.stringify(parsed, null, 2).slice(0, 1500)}
    </pre>;
  } catch {
    return <pre style={{ marginTop: 10, fontSize: 10, color: "var(--text-dim)" }}>{String(data).slice(0, 800)}</pre>;
  }
}
