import React, { useState, useEffect } from "react";

const BACKEND = "http://localhost:8000";

const TIER_COLORS = {
  Foundational: "var(--success)",
  Associate:    "var(--info)",
  Professional: "#a78bfa",
};

const QUESTION_COUNTS = [
  { value: 5,   label: "5",   sublabel: "Quick check" },
  { value: 10,  label: "10",  sublabel: "Short session" },
  { value: 25,  label: "25",  sublabel: "Solid practice" },
  { value: 50,  label: "50",  sublabel: "Deep prep" },
  { value: 100, label: "100", sublabel: "Mock exam" },
];

export default function CertificationsTab() {
  const [certs,    setCerts]    = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail,   setDetail]   = useState(null);
  const [domain,   setDomain]   = useState(null);
  const [quiz,     setQuiz]     = useState(null);

  useEffect(() => {
    fetch(`${BACKEND}/certifications/list`).then(r => r.json()).then(d => setCerts(d.certifications || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    fetch(`${BACKEND}/certifications/${selected}`).then(r => r.json()).then(setDetail).catch(() => {});
  }, [selected]);

  if (quiz) {
    return <QuizMode quiz={quiz} cert={detail} domain={domain}
                     onExit={() => { setQuiz(null); setDomain(null); }} />;
  }

  if (selected && detail && domain) {
    return <DomainDetail
      cert={detail} domain={domain}
      onBack={() => setDomain(null)}
      onStartQuiz={(count) => startQuiz(selected, domain, count, setQuiz)}
    />;
  }

  if (selected && detail) {
    return <CertDetail cert={detail} onBack={() => setSelected(null)} onSelectDomain={setDomain} />;
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <h2 style={{ fontSize: 11, fontWeight: 600, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.06em", margin: "0 0 6px" }}>
        AWS Certifications
      </h2>
      <p style={{ fontSize: 12, color: "var(--text-vfaint)", margin: "0 0 18px" }}>
        Exam-grade practice questions generated live from AWS docs — same style as Tutorials Dojo, AWS sample exams
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {certs.map(c => (
          <button key={c.id} onClick={() => setSelected(c.id)} style={{
            textAlign: "left", padding: "16px 18px", borderRadius: 10,
            background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", cursor: "pointer",
            fontFamily: "inherit", transition: "all 0.12s",
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = `color-mix(in srgb, ${TIER_COLORS[c.tier] || "var(--border-hover)"} 25%, transparent)`}
          onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
              <span style={{
                padding: "2px 8px", borderRadius: 5,
                background: `color-mix(in srgb, ${TIER_COLORS[c.tier]} 8%, transparent)`,
                color: TIER_COLORS[c.tier],
                fontSize: 9, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em",
                border: `1px solid color-mix(in srgb, ${TIER_COLORS[c.tier]} 19%, transparent)`,
              }}>{c.tier}</span>
              <span style={{ fontSize: 10, color: "var(--text-vfaint)", fontFamily: "ui-monospace, monospace" }}>{c.code}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 600, marginBottom: 6 }}>{c.name}</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.5, marginBottom: 12 }}>{c.description}</div>
            <div style={{ display: "flex", gap: 14, fontSize: 10, color: "var(--text-faint)" }}>
              <span>{c.duration}</span>
              <span>{c.questions} questions</span>
              <span>{c.study_hours}</span>
              <span>${c.cost_usd}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

async function startQuiz(certId, dom, count, setQuiz) {
  const s = getSettings();
  setQuiz({ loading: true, progress: { current: 0, total: count, topic: "" } });
  try {
    const resp = await fetch(`${BACKEND}/certifications/quiz`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cert_id: certId, domain_id: dom.id, num_questions: count,
        openai_api_key: s?.llm?.openai_api_key || "",
      }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let questions = [], sources = [], progress = { current: 0, total: count, topic: "" };
    let warnings = [];

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
          if (ev.type === "quiz")          questions = ev.questions;
          if (ev.type === "docs_sources")  sources   = ev.sources;
          if (ev.type === "quiz_progress") progress  = ev;
          if (ev.type === "quiz_warning")  warnings.push(ev.message);
          setQuiz({ loading: !questions.length, progress, sources, warnings });
        } catch {}
      }
    }
    setQuiz({ loading: false, questions, sources, warnings });
  } catch (e) {
    setQuiz({ error: e.message });
  }
}

function getSettings() {
  try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; }
}

function CertDetail({ cert, onBack, onSelectDomain }) {
  const tierColor = TIER_COLORS[cert.tier] || "var(--info)";
  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <button onClick={onBack} style={backBtn}>← Back to certifications</button>

      <div style={{ maxWidth: 820 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 5,
            background: `color-mix(in srgb, ${tierColor} 8%, transparent)`, color: tierColor,
            fontSize: 9, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em",
            border: `1px solid color-mix(in srgb, ${tierColor} 19%, transparent)`,
          }}>{cert.tier}</span>
          <span style={{ fontSize: 10, color: "var(--text-vfaint)", fontFamily: "ui-monospace, monospace" }}>{cert.code}</span>
        </div>
        <h1 style={{ fontSize: 18, color: "var(--text-strong)", margin: "0 0 4px", fontWeight: 600 }}>{cert.name}</h1>
        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "0 0 18px", lineHeight: 1.5 }}>{cert.description}</p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, marginBottom: 22 }}>
          {[
            ["Duration",  cert.duration],
            ["Questions", cert.questions],
            ["Pass",      cert.passing_score],
            ["Cost",      `$${cert.cost_usd}`],
            ["Prep time", cert.study_hours],
          ].map(([label, value]) => (
            <div key={label} style={{ padding: "10px 12px", borderRadius: 8, background: "var(--bg-elevated)", border: "1px solid var(--border-strong)" }}>
              <div style={{ fontSize: 9, color: "var(--text-vfaint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>{label}</div>
              <div style={{ fontSize: 13, color: "var(--text-body)", fontWeight: 500 }}>{value}</div>
            </div>
          ))}
        </div>

        <h3 style={sectionLabel}>Exam Domains</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {cert.domains?.map(d => (
            <button key={d.id} onClick={() => onSelectDomain(d)} style={{
              textAlign: "left", padding: "14px 16px", borderRadius: 9,
              background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", cursor: "pointer",
              fontFamily: "inherit", display: "flex", alignItems: "center", gap: 14,
              transition: "all 0.12s",
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent-border)"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
            >
              <div style={{
                minWidth: 40, height: 36, borderRadius: 7,
                background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 12, fontWeight: 600, color: "var(--accent)",
              }}>{d.weight}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: "var(--text-body)", fontWeight: 500, marginBottom: 3 }}>{d.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>{d.topics.length} topics · {d.key_services?.length || 0} services</div>
              </div>
              <span style={{ color: "var(--text-faint)", fontSize: 14 }}>→</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function DomainDetail({ cert, domain, onBack, onStartQuiz }) {
  const [selectedCount, setSelectedCount] = useState(10);

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <button onClick={onBack} style={backBtn}>← Back to {cert.code}</button>

      <div style={{ maxWidth: 820 }}>
        <div style={{ fontSize: 10, color: "var(--text-vfaint)", marginBottom: 4, fontFamily: "ui-monospace, monospace" }}>
          {cert.code} · {domain.weight} of exam
        </div>
        <h1 style={{ fontSize: 18, color: "var(--text-strong)", margin: "0 0 22px", fontWeight: 600 }}>{domain.name}</h1>

        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 14 }}>
          <div>
            <h3 style={sectionLabel}>Topics covered in this domain</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 18 }}>
              {domain.topics?.map((t, i) => (
                <div key={i} style={{
                  display: "flex", gap: 10, padding: "10px 12px",
                  background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", borderRadius: 7,
                }}>
                  <span style={{ fontSize: 11, color: "var(--text-vfaint)", fontFamily: "ui-monospace, monospace", minWidth: 20 }}>{i + 1}.</span>
                  <span style={{ fontSize: 12, color: "var(--text-body)", lineHeight: 1.5 }}>{t}</span>
                </div>
              ))}
            </div>

            <h3 style={sectionLabel}>How many questions?</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 6, marginBottom: 14 }}>
              {QUESTION_COUNTS.map(opt => {
                const isSelected = selectedCount === opt.value;
                return (
                  <button key={opt.value}
                    onClick={() => setSelectedCount(opt.value)}
                    style={{
                      padding: "10px 8px", borderRadius: 8, cursor: "pointer",
                      background: isSelected ? "var(--accent-bg)" : "var(--bg-elevated)",
                      border: `1px solid ${isSelected ? "var(--accent-border)" : "var(--border-strong)"}`,
                      color: isSelected ? "var(--accent)" : "var(--text-body)",
                      fontFamily: "inherit",
                    }}>
                    <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1 }}>{opt.label}</div>
                    <div style={{ fontSize: 9, color: isSelected ? "var(--accent)" : "var(--text-vfaint)", marginTop: 4, opacity: 0.85 }}>
                      {opt.sublabel}
                    </div>
                  </button>
                );
              })}
            </div>

            <button onClick={() => onStartQuiz(selectedCount)} style={{
              width: "100%", padding: "14px 18px", borderRadius: 10, border: "none", cursor: "pointer",
              background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
              color: "#fff", fontSize: 13, fontWeight: 600, fontFamily: "inherit",
            }}>
              Start {selectedCount}-question practice quiz →
            </button>
            <div style={{ fontSize: 10, color: "var(--text-vfaint)", marginTop: 8, textAlign: "center" }}>
              Questions distributed across all {domain.topics?.length || 0} topics for full coverage
            </div>
          </div>

          <div>
            <h3 style={sectionLabel}>Key services</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {domain.key_services?.map(svc => (
                <span key={svc} style={{
                  fontSize: 10, color: "var(--accent)",
                  padding: "3px 8px", borderRadius: 5,
                  background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
                }}>{svc}</span>
              ))}
            </div>

            <h3 style={{ ...sectionLabel, marginTop: 18 }}>What this practice does</h3>
            <ul style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.7, paddingLeft: 16, margin: 0 }}>
              <li>Scenario-based questions (like the real exam)</li>
              <li>MOST / BEST / LEAST keyword qualifiers</li>
              <li>Distractors based on common exam pitfalls</li>
              <li>Stratified across <strong>all topics</strong> of this domain</li>
              <li>New seed each run → no duplicate questions</li>
              <li>Each answer references the AWS doc URL</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function QuizMode({ quiz, cert, domain, onExit }) {
  const [idx,      setIdx]      = useState(0);
  const [selected, setSelected] = useState(null);
  const [revealed, setRevealed] = useState(false);
  const [score,    setScore]    = useState(0);

  if (quiz.loading) {
    const pct = quiz.progress ? Math.round((quiz.progress.current / quiz.progress.total) * 100) : 0;
    return (
      <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 18, padding: 32 }}>
        <div style={{ display: "flex", gap: 5 }}>
          {[0,1,2].map(i => <div key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)", animation: `pulse 1s ${i*0.18}s infinite` }} />)}
        </div>
        <div style={{ fontSize: 13, color: "var(--text-body)", fontWeight: 500 }}>
          Generating exam-grade questions from AWS docs…
        </div>
        {quiz.progress && quiz.progress.total > 0 && (
          <div style={{ width: 280 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-vfaint)", marginBottom: 5 }}>
              <span>{quiz.progress.current} / {quiz.progress.total}</span>
              <span>{pct}%</span>
            </div>
            <div style={{ width: "100%", height: 4, background: "var(--border-strong)", borderRadius: 2 }}>
              <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 2, transition: "width 0.3s" }} />
            </div>
            {quiz.progress.topic && (
              <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 8, textAlign: "center" }}>
                Currently: <em>{quiz.progress.topic}</em>
              </div>
            )}
          </div>
        )}
        {quiz.sources && quiz.sources.length > 0 && (
          <div style={{ fontSize: 10, color: "var(--text-vfaint)", textAlign: "center" }}>
            Grounded in: {quiz.sources.map(s => s.service).join(", ")}
          </div>
        )}
      </div>
    );
  }

  if (quiz.error) {
    return (
      <div style={{ padding: 32, color: "var(--danger)" }}>
        Quiz generation failed: {quiz.error}
        <button onClick={onExit} style={{ marginLeft: 12, padding: "5px 10px", borderRadius: 5, border: "1px solid var(--border-hover)", background: "transparent", color: "var(--text-dim)", cursor: "pointer" }}>Back</button>
      </div>
    );
  }

  const questions = quiz.questions || [];
  if (questions.length === 0) {
    return (
      <div style={{ padding: 32, color: "var(--text-dim)" }}>
        No questions generated. Check your OpenAI key in Settings, then try again.
        <button onClick={onExit} style={{ marginLeft: 12, padding: "5px 10px", borderRadius: 5, border: "1px solid var(--border-hover)", background: "transparent", color: "var(--text-dim)", cursor: "pointer" }}>Back</button>
      </div>
    );
  }

  if (idx >= questions.length) {
    const pct = Math.round((score / questions.length) * 100);
    const passed = pct >= 70;
    return (
      <div style={{ height: "100%", overflowY: "auto", padding: "32px 32px" }}>
        <button onClick={onExit} style={backBtn}>← Back to domain</button>
        <div style={{ maxWidth: 600, margin: "0 auto", textAlign: "center", paddingTop: 40 }}>
          <div style={{
            fontSize: 48, fontWeight: 700, marginBottom: 8,
            color: passed ? "var(--success)" : "var(--warning)",
            letterSpacing: "-1px",
          }}>{score} / {questions.length}</div>
          <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 24 }}>
            {pct}% — {passed ? "Pass rate met (≥70%)" : "Below pass threshold (70%)"}
          </div>
          <button onClick={() => { setIdx(0); setSelected(null); setRevealed(false); setScore(0); }}
            style={{ padding: "10px 22px", borderRadius: 8, border: "none", cursor: "pointer", background: "var(--accent)", color: "#fff", fontSize: 12, fontFamily: "inherit", fontWeight: 500 }}>
            Retake the same set
          </button>
          <button onClick={onExit}
            style={{ marginLeft: 8, padding: "10px 22px", borderRadius: 8, border: "1px solid var(--border-strong)", cursor: "pointer", background: "transparent", color: "var(--text-dim)", fontSize: 12, fontFamily: "inherit" }}>
            Generate a new batch
          </button>
        </div>
      </div>
    );
  }

  const q = questions[idx];

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "26px 32px" }}>
      <div style={{ maxWidth: 760, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 22 }}>
          <button onClick={onExit} style={backBtn}>← Exit quiz</button>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 11, color: "var(--text-dim)" }}>Question {idx + 1} / {questions.length}</span>
            <div style={{ width: 100, height: 4, background: "var(--border-strong)", borderRadius: 2 }}>
              <div style={{
                width: `${((idx + (revealed ? 1 : 0)) / questions.length) * 100}%`,
                height: "100%", background: "var(--accent)", borderRadius: 2, transition: "width 0.3s",
              }} />
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 10, color: "var(--text-vfaint)", fontFamily: "ui-monospace, monospace" }}>
              {cert?.code} · {domain?.name}
            </span>
            {q.topic_tag && (
              <span style={{ fontSize: 9, color: "var(--accent)", padding: "2px 7px", borderRadius: 4, background: "var(--accent-bg)", border: "1px solid var(--accent-border)" }}>
                {q.topic_tag}
              </span>
            )}
          </div>
          <p style={{ fontSize: 14, color: "var(--text-strong)", lineHeight: 1.65, margin: 0, whiteSpace: "pre-wrap" }}>
            {q.question}
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 18 }}>
          {Object.entries(q.options || {}).map(([letter, opt]) => {
            const isSelected = selected === letter;
            const isCorrect  = revealed && letter === q.correct;
            const isWrong    = revealed && isSelected && letter !== q.correct;
            return (
              <button key={letter}
                onClick={() => !revealed && setSelected(letter)}
                disabled={revealed}
                style={{
                  textAlign: "left", padding: "12px 14px", borderRadius: 8,
                  background: isCorrect ? "rgba(52,211,153,0.07)" : isWrong ? "rgba(248,113,113,0.07)" : isSelected ? "var(--accent-bg)" : "var(--bg-elevated)",
                  border: `1px solid ${isCorrect ? "rgba(52,211,153,0.35)" : isWrong ? "rgba(248,113,113,0.35)" : isSelected ? "var(--accent-border)" : "var(--border-strong)"}`,
                  color: isCorrect ? "var(--success)" : isWrong ? "var(--danger)" : "var(--text-body)",
                  cursor: revealed ? "default" : "pointer",
                  fontFamily: "inherit", display: "flex", gap: 10, alignItems: "flex-start",
                }}>
                <span style={{
                  fontSize: 10, fontWeight: 700,
                  width: 22, height: 22, borderRadius: "50%",
                  background: isCorrect ? "rgba(52,211,153,0.15)" : isWrong ? "rgba(248,113,113,0.15)" : isSelected ? "var(--accent-border)" : "var(--bg-card)",
                  display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                }}>{letter}</span>
                <span style={{ fontSize: 12, lineHeight: 1.55 }}>{opt}</span>
              </button>
            );
          })}
        </div>

        {!revealed ? (
          <button
            onClick={() => { setRevealed(true); if (selected === q.correct) setScore(s => s + 1); }}
            disabled={!selected}
            style={{
              padding: "10px 22px", borderRadius: 8, border: "none", cursor: selected ? "pointer" : "not-allowed",
              background: selected ? "var(--accent)" : "var(--bg-hover)", color: selected ? "#fff" : "var(--text-faint)",
              fontSize: 12, fontFamily: "inherit", fontWeight: 500,
            }}>
            Submit answer
          </button>
        ) : (
          <>
            <div style={{
              padding: "14px 16px", borderRadius: 9, marginBottom: 14,
              background: "rgba(52,211,153,0.05)", border: "1px solid rgba(52,211,153,0.25)",
            }}>
              <div style={{ fontSize: 10, color: "var(--success)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                Explanation
              </div>
              <div style={{ fontSize: 12, color: "var(--text-body)", lineHeight: 1.65, marginBottom: 10, whiteSpace: "pre-wrap" }}>
                {q.explanation}
              </div>
              {q.reference_url && (
                <a href={q.reference_url}
                   onClick={e => { e.preventDefault(); window.electronAPI?.openExternal?.(q.reference_url) || window.open(q.reference_url, "_blank"); }}
                   style={{ fontSize: 10, color: "var(--docs)", fontFamily: "ui-monospace, monospace", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}>
                  ↗ {q.reference_url.replace("https://", "")}
                </a>
              )}
            </div>
            <button
              onClick={() => { setIdx(i => i + 1); setSelected(null); setRevealed(false); }}
              style={{
                padding: "10px 22px", borderRadius: 8, border: "none", cursor: "pointer",
                background: "var(--accent)", color: "#fff", fontSize: 12, fontFamily: "inherit", fontWeight: 500,
              }}>
              {idx === questions.length - 1 ? "See results" : "Next question →"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const backBtn = {
  background: "none", border: "none", color: "var(--text-dim)", fontSize: 11,
  cursor: "pointer", marginBottom: 18, fontFamily: "inherit",
};

const sectionLabel = {
  fontSize: 11, fontWeight: 600, color: "var(--text-dim)",
  textTransform: "uppercase", letterSpacing: "0.06em", margin: "0 0 10px",
};
