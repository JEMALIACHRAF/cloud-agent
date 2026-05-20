import { useState, useCallback, useRef } from "react";

let _c = 0;
const uid = () => `${Date.now()}-${++_c}`;
const BACKEND = "http://localhost:8000";

function getStoredSettings() {
  try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; }
}

export function useAgent() {
  const [messages, setMessages]         = useState([]);
  const [isStreaming, setIsStreaming]   = useState(false);
  const [pendingReview, setPendingReview] = useState(null);
  const [activeTools, setActiveTools]   = useState([]);
  const [activeAgent, setActiveAgent]   = useState(null);
  const [userProfile, setUserProfile]   = useState({ level: "intermediate", level_confidence: 0 });
  const threadIdRef = useRef(`t-${Date.now()}`);
  const abortRef = useRef(null);

  const _handleEvent = useCallback((ev, assistantId) => {
    switch (ev.type) {
      case "token":
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, content: (m.content || "") + ev.content } : m
        ));
        break;
      case "profile_update":
        setUserProfile({ level: ev.level, level_confidence: ev.level_confidence });
        break;
      case "docs_sources":
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, docs_sources: ev.sources } : m
        ));
        break;
      case "agent_start":
        setActiveAgent({ name: ev.agent, label: ev.label });
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m;
          const agents = m.agents || [];
          if (agents.find(a => a.name === ev.agent)) return m;
          return { ...m, agents: [...agents, { name: ev.agent, label: ev.label, status: "active", ts: Date.now() }] };
        }));
        break;
      case "agent_end":
        setMessages(prev => prev.map(m =>
          m.id !== assistantId ? m : {
            ...m,
            agents: (m.agents || []).map(a =>
              a.name === ev.agent ? { ...a, status: "done", elapsed: Date.now() - a.ts } : a
            )
          }
        ));
        break;
      case "tool_start":
        setActiveTools(prev => [...prev, { name: ev.tool, args: ev.args, status: "running" }]);
        setMessages(prev => prev.map(m =>
          m.id !== assistantId ? m : {
            ...m,
            tool_calls: [...(m.tool_calls || []), { name: ev.tool, args: ev.args, status: "running" }]
          }
        ));
        break;
      case "tool_end":
        setActiveTools(prev => prev.filter(t => t.name !== ev.tool));
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m;
          const calls = [...(m.tool_calls || [])];
          const i = calls.map(x => x.name).lastIndexOf(ev.tool);
          if (i !== -1) calls[i] = { ...calls[i], result: ev.result, status: "done" };
          return { ...m, tool_calls: calls };
        }));
        break;
      case "human_review_required":   // legacy
      case "approval_required":       // v19 — emitted on graph interrupt
        setPendingReview({
          tool_calls: ev.tool_calls || [],
          message:    ev.message || "Awaiting your approval",
          interrupt:  ev.interrupt || "human_review",
        });
        setActiveAgent(null);
        setIsStreaming(false);
        // Attach the approval prompt to the assistant message so user sees it
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? {
            ...m,
            approval_required: {
              tool_calls: ev.tool_calls || [],
              message:    ev.message || "Awaiting your approval — reply 'approve' to execute, anything else to cancel.",
            }
          } : m
        ));
        break;
      case "status":   // v19 — transient status during long operations
        setActiveAgent({ name: "status", label: ev.label });
        break;
      case "error":    // v19 — surface silent errors
        setActiveAgent(null);
        setIsStreaming(false);
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? {
            ...m,
            error: ev.message,
            error_details: ev.details,
            error_fatal:   ev.fatal,
          } : m
        ));
        break;
      case "run_end":
        setActiveAgent(null);
        if (ev.status === "error") {
          setMessages(prev => prev.map(m =>
            m.id === assistantId ? { ...m, error: ev.error || "Unknown error" } : m
          ));
        }
        break;
    }
  }, []);

  const _stream = useCallback(async (payload) => {
    abortRef.current = new AbortController();
    setIsStreaming(true);
    setActiveTools([]);
    setActiveAgent(null);
    const assistantId = uid();
    setMessages(prev => [...prev, {
      id: assistantId, role: "assistant", content: "",
      tool_calls: [], agents: [], docs_sources: [], ts: new Date().toISOString()
    }]);

    const s = getStoredSettings();
    const fullPayload = {
      ...payload,
      openai_api_key:    s?.llm?.openai_api_key    || "",
      anthropic_api_key: s?.llm?.anthropic_api_key || "",
    };

    try {
      const resp = await fetch(`${BACKEND}/agent/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fullPayload),
        signal: abortRef.current.signal,
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
          try { _handleEvent(JSON.parse(line.slice(6)), assistantId); } catch {}
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, error: err.message } : m
        ));
      }
    } finally {
      setIsStreaming(false);
      setActiveTools([]);
      setActiveAgent(null);
    }
  }, [_handleEvent]);

  const sendMessage = useCallback(async (text, credentials) => {
    setMessages(prev => [...prev, { id: uid(), role: "user", content: text, ts: new Date().toISOString() }]);
    await _stream({ user_input: text, thread_id: threadIdRef.current, credentials: credentials || {} });
  }, [_stream]);

  const approveAction = useCallback(async (credentials) => {
    setPendingReview(null);
    await _stream({ user_input: "", thread_id: threadIdRef.current, credentials: credentials || {}, resume: "approve" });
  }, [_stream]);

  const rejectAction = useCallback(async (credentials) => {
    setPendingReview(null);
    await _stream({ user_input: "", thread_id: threadIdRef.current, credentials: credentials || {}, resume: "reject" });
  }, [_stream]);

  const cancelStream = useCallback(() => { abortRef.current?.abort(); }, []);

  const newThread = useCallback(() => {
    threadIdRef.current = `t-${Date.now()}`;
    setMessages([]);
    setPendingReview(null);
    setActiveTools([]);
    setActiveAgent(null);
  }, []);

  return {
    messages, isStreaming, pendingReview, activeTools, activeAgent,
    userProfile, sendMessage, approveAction, rejectAction,
    cancelStream, newThread, threadId: threadIdRef.current,
  };
}
