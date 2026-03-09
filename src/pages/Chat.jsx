import { useState, useEffect, useRef } from "react";
import { api } from "../api/client";

const STORAGE_KEY = "chat_messages";

// ── File icons ───────────────────────────────────────────────────────────────────
const FILE_ICONS = {
  pdf: "📕", xlsx: "📊", xls: "📊", docx: "📄", doc: "📄",
  pptx: "📋", csv: "📊", txt: "📝", md: "📝",
};
const fileIcon = (fn) => FILE_ICONS[fn?.split(".").pop()?.toLowerCase()] || "📄";

// ── Intent colours ───────────────────────────────────────────────────────────────
const INTENT_STYLE = {
  PERSON:       { bg: "#1e3a5f", color: "#60a5fa",  border: "#2563eb30" },
  AGGREGATE:    { bg: "#0d2d1a", color: "#4ade80",  border: "#16a34a30" },
  STATUS:       { bg: "#2d200a", color: "#fbbf24",  border: "#d9770630" },
  NEGATION:     { bg: "#2d1010", color: "#f87171",  border: "#dc262630" },
  INTERSECTION: { bg: "#1e1030", color: "#c084fc",  border: "#9333ea30" },
  SOLO:         { bg: "#0a2020", color: "#2dd4bf",  border: "#0d948030" },
  TEMPORAL:     { bg: "#1a2030", color: "#94a3b8",  border: "#47556930" },
  COMPARATIVE:  { bg: "#2d1a08", color: "#fb923c",  border: "#ea580c30" },
  CAUSAL:       { bg: "#2a1808", color: "#f59e0b",  border: "#b4530930" },
  DEFINITION:   { bg: "#0a1e2d", color: "#38bdf8",  border: "#0284c730" },
  GENERAL:      { bg: "#151f30", color: "#94a3b8",  border: "#33415530" },
};

// ── Inline renderer: **bold** and [Source N] ─────────────────────────────────────
function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*|\[Source\s*\d+\])/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i} style={{ color: "#f1f5f9", fontWeight: "600" }}>{part.slice(2, -2)}</strong>;
    if (/^\[Source\s*\d+\]$/.test(part))
      return <sup key={i} style={{
        color: "#6366f1", fontSize: "9px", fontWeight: "700",
        background: "#1e1b4b", padding: "0 4px", borderRadius: "3px",
        margin: "0 1px", verticalAlign: "super", letterSpacing: "0.02em",
      }}>{part}</sup>;
    return part;
  });
}

// ── Answer formatter ─────────────────────────────────────────────────────────────
function formatAnswer(text) {
  if (!text) return null;
  const lines = text.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const t   = raw.trim();

    // Numbered list  1. / 2.
    if (/^\d+\.\s/.test(t)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      out.push(
        <ol key={out.length} style={{ margin: "8px 0", paddingLeft: "20px", color: "#e2e8f0" }}>
          {items.map((item, j) => (
            <li key={j} style={{ marginBottom: "6px", fontSize: "15px", lineHeight: "1.75", color: "#e2e8f0" }}>
              {renderInline(item)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Bullet list  * / - / •
    if (/^[\*\-•]\s/.test(t)) {
      const items = [];
      while (i < lines.length && /^[\*\-•]\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[\*\-•]\s+/, ""));
        i++;
      }
      out.push(
        <ul key={out.length} style={{ margin: "8px 0", paddingLeft: "18px", color: "#e2e8f0" }}>
          {items.map((item, j) => (
            <li key={j} style={{ marginBottom: "6px", fontSize: "15px", lineHeight: "1.75", color: "#cbd5e1" }}>
              {renderInline(item)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Blank line
    if (!t) { out.push(<div key={out.length} style={{ height: "8px" }} />); i++; continue; }

    // Heading-like line (short, ends with colon, no source refs)
    if (t.endsWith(":") && t.length < 60 && !t.includes("[Source")) {
      out.push(
        <p key={out.length} style={{ margin: "10px 0 4px", fontSize: "13px", fontWeight: "700",
          color: "#64748b", letterSpacing: "0.05em", textTransform: "uppercase" }}>
          {renderInline(t)}
        </p>
      );
      i++; continue;
    }

    // Paragraph
    out.push(
      <p key={out.length} style={{ margin: "0 0 8px", lineHeight: "1.78", fontSize: "15px", color: "#e2e8f0" }}>
        {renderInline(raw)}
      </p>
    );
    i++;
  }
  return <>{out}</>;
}

// ── Thinking dots ────────────────────────────────────────────────────────────────
function ThinkingDots() {
  return (
    <>
      <style>{`
        @keyframes dot-up {
          0%,80%,100% { transform:translateY(0); opacity:.3; }
          40%          { transform:translateY(-6px); opacity:1; }
        }
      `}</style>
      <div style={{ display: "flex", gap: "5px", alignItems: "center", padding: "3px 0" }}>
        {[0,1,2].map(i => (
          <div key={i} style={{
            width: "6px", height: "6px", borderRadius: "50%",
            background: "#6366f1",
            animation: `dot-up 1.4s ease-in-out ${i*0.22}s infinite`,
          }} />
        ))}
      </div>
    </>
  );
}

// ── Collapsible source section ───────────────────────────────────────────────────
function Sources({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources?.length) return null;
  return (
    <div style={{ marginTop: "10px", paddingTop: "8px", borderTop: "1px solid #1e293b20" }}>
      {/* Toggle row */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: "none", border: "none", cursor: "pointer", padding: 0,
          display: "flex", alignItems: "center", gap: "5px",
        }}
      >
        <span style={{ color: "#334155", fontSize: "10px" }}>{open ? "▾" : "▸"}</span>
        <span style={{ color: "#334155", fontSize: "10px", letterSpacing: "0.05em" }}>
          {sources.length} source{sources.length > 1 ? "s" : ""}
        </span>
      </button>

      {/* Expanded source list */}
      {open && (
        <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
          {sources.slice(0, 5).map((s, i) => {
            const pct = Math.round((s.relevance ?? 0) * 100);
            const col = pct >= 70 ? "#4ade80" : pct >= 40 ? "#fbbf24" : "#475569";
            return (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: "6px",
                background: "#0d1526", borderRadius: "6px", padding: "5px 8px",
              }}>
                <span style={{ fontSize: "11px", flexShrink: 0 }}>{fileIcon(s.filename)}</span>
                <span style={{
                  flex: 1, color: "#64748b", fontSize: "10px",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>{s.filename}</span>
                <span style={{ color: col, fontSize: "9px", fontWeight: "700", flexShrink: 0 }}>{pct}%</span>
                {/* Mini bar */}
                <div style={{ width: "28px", height: "2px", background: "#1e293b", borderRadius: "99px", flexShrink: 0, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${pct}%`, background: col, borderRadius: "99px" }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Intent badge ─────────────────────────────────────────────────────────────────
function IntentBadge({ intent }) {
  if (!intent) return null;
  const s = INTENT_STYLE[intent] || INTENT_STYLE.GENERAL;
  return (
    <span style={{
      fontSize: "9px", fontWeight: "700", letterSpacing: "0.07em",
      padding: "2px 7px", borderRadius: "99px",
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      textTransform: "uppercase",
    }}>{intent}</span>
  );
}

// ── Copy button ───────────────────────────────────────────────────────────────────
function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => navigator.clipboard?.writeText(text).then(() => {
        setCopied(true); setTimeout(() => setCopied(false), 2000);
      })}
      title="Copy"
      style={{
        background: "none", border: "none", cursor: "pointer",
        color: copied ? "#4ade80" : "#334155", fontSize: "12px",
        padding: "1px 5px", borderRadius: "3px", transition: "color 0.2s",
      }}
    >{copied ? "✓" : "⎘"}</button>
  );
}

const fmtTime = ts => ts
  ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  : "";

// ── Main Chat ────────────────────────────────────────────────────────────────────
export default function Chat({ user }) {
  const [messages, setMessages] = useState(() => {
    try { const s = localStorage.getItem(STORAGE_KEY); if (s) return JSON.parse(s); } catch {}
    return [{
      role: "assistant",
      text: `Hi ${user.name}! Ask me anything about ongoing projects, who's working on what, or any work uploaded to the knowledge base.`,
      ts: Date.now(),
    }];
  });
  const [input, setInput]     = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef             = useRef(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const q = input.trim();
    setInput("");
    setMessages(m => [...m, { role: "user", text: q, ts: Date.now() }]);
    setLoading(true);
    try {
      const res = await api.query(q);
      setMessages(m => [...m, {
        role: "assistant", text: res.answer,
        sources: res.sources, intent: res.query_intent, ts: Date.now(),
      }]);
    } catch {
      setMessages(m => [...m, { role: "assistant", text: "Error fetching response. Please try again.", ts: Date.now() }]);
    } finally { setLoading(false); }
  };

  const clearChat = () => setMessages([{
    role: "assistant",
    text: `Hi ${user.name}! Ask me anything about ongoing projects, who's working on what, or any work uploaded to the knowledge base.`,
    ts: Date.now(),
  }]);

  return (
    <>
      <style>{`
        @keyframes msg-r { from{opacity:0;transform:translateX(12px)} to{opacity:1;transform:none} }
        @keyframes msg-l { from{opacity:0;transform:translateX(-12px)} to{opacity:1;transform:none} }
        .msg-user { animation: msg-r 0.2s ease-out; }
        .msg-ai   { animation: msg-l 0.2s ease-out; }
        .chat-input:focus { border-color: #4f46e5 !important; outline: none; box-shadow: 0 0 0 3px #4f46e515 !important; }
        .send-btn:hover:not(:disabled) { background: linear-gradient(135deg,#4338ca,#7c3aed) !important; }
        .src-toggle:hover span { color: #6366f1 !important; }
      `}</style>

      <div style={S.container}>

        {/* Header */}
        <div style={S.header}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div style={S.dot} />
            <span style={S.headerLabel}>CONSTELLI INTELLIGENCE</span>
          </div>
          <button onClick={clearChat} style={S.clearBtn}>Clear</button>
        </div>

        {/* Messages */}
        <div style={S.messages}>
          {messages.map((msg, i) => (
            <div key={i}
              className={msg.role === "user" ? "msg-user" : "msg-ai"}
              style={{ ...S.row, justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}
            >
              {msg.role === "assistant" && <div style={S.avatar}>🔭</div>}

              <div style={{ ...S.bubble, ...(msg.role === "user" ? S.userBubble : S.aiBubble) }}>

                {/* AI header */}
                {msg.role === "assistant" && (
                  <div style={S.aiHeader}>
                    <div style={{ display: "flex", gap: "5px" }}>
                      {msg.intent && <IntentBadge intent={msg.intent} />}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "2px" }}>
                      {msg.ts && <span style={S.ts}>{fmtTime(msg.ts)}</span>}
                      {msg.text && <CopyBtn text={msg.text} />}
                    </div>
                  </div>
                )}

                {/* User timestamp */}
                {msg.role === "user" && msg.ts && (
                  <div style={{ textAlign: "right", marginBottom: "4px" }}>
                    <span style={{ ...S.ts, color: "#a5b4fc60" }}>{fmtTime(msg.ts)}</span>
                  </div>
                )}

                {/* Body */}
                <div style={msg.role === "user" ? S.userText : S.aiText}>
                  {msg.role === "assistant" ? formatAnswer(msg.text) : msg.text}
                </div>

                {/* Collapsible sources */}
                <Sources sources={msg.sources} />
              </div>
            </div>
          ))}

          {loading && (
            <div className="msg-ai" style={{ ...S.row, justifyContent: "flex-start" }}>
              <div style={S.avatar}>🔭</div>
              <div style={{ ...S.bubble, ...S.aiBubble }}><ThinkingDots /></div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={S.inputRow}>
          <div style={{ flex: 1, position: "relative" }}>
            <input
              className="chat-input"
              style={{ ...S.input, opacity: loading ? 0.65 : 1 }}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="Ask about projects, team, status…"
              disabled={loading}
            />
            {input.length > 0 && (
              <span style={S.charCount}>{input.length}</span>
            )}
          </div>
          <button
            className="send-btn"
            style={{
              ...S.sendBtn,
              opacity: (loading || !input.trim()) ? 0.5 : 1,
              cursor: (loading || !input.trim()) ? "not-allowed" : "pointer",
            }}
            onClick={send}
            disabled={loading || !input.trim()}
          >
            {loading ? "…" : "Send"}
          </button>
        </div>
      </div>
    </>
  );
}

const S = {
  container:  { display: "flex", flexDirection: "column", height: "calc(100vh - 108px)" },
  header:     { display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: "12px", marginBottom: "4px", borderBottom: "1px solid #1a2540" },
  dot:        { width: "7px", height: "7px", borderRadius: "50%", background: "#4ade80", boxShadow: "0 0 7px #4ade8090" },
  headerLabel:{ color: "#2d3f5c", fontSize: "10.5px", fontWeight: "700", letterSpacing: "0.1em" },
  clearBtn:   { background: "none", border: "1px solid #1e293b", color: "#2d3f5c", fontSize: "10px", padding: "4px 10px", borderRadius: "5px", cursor: "pointer" },
  messages:   { flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px", paddingBottom: "10px" },
  row:        { display: "flex", alignItems: "flex-end", gap: "8px" },
  avatar:     { width: "28px", height: "28px", borderRadius: "50%", flexShrink: 0, background: "linear-gradient(135deg,#4338ca,#7c3aed)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px", boxShadow: "0 0 10px #6366f130" },
  bubble:     { maxWidth: "80%", padding: "13px 16px", borderRadius: "16px" },
  userBubble: { background: "linear-gradient(135deg,#3730a3,#6366f1)", borderBottomRightRadius: "3px", boxShadow: "0 3px 14px #6366f125" },
  aiBubble:   { background: "#0f1a2e", border: "1px solid #1e293b", borderBottomLeftRadius: "3px", boxShadow: "0 3px 16px rgba(0,0,0,0.3)" },
  aiHeader:   { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" },
  ts:         { color: "#2d3f5c", fontSize: "9.5px" },
  userText:   { color: "#fff", fontSize: "15px", lineHeight: "1.7", whiteSpace: "pre-wrap" },
  aiText:     { color: "#cbd5e1" },
  inputRow:   { display: "flex", gap: "9px", paddingTop: "14px", borderTop: "1px solid #1a2540" },
  input:      { width: "100%", padding: "13px 48px 13px 15px", borderRadius: "10px", border: "1px solid #1e293b", background: "#0f1a2e", color: "#f1f5f9", fontSize: "15px", boxSizing: "border-box", transition: "border-color 0.2s, box-shadow 0.2s" },
  charCount:  { position: "absolute", right: "13px", top: "50%", transform: "translateY(-50%)", color: "#2d3f5c", fontSize: "10px", pointerEvents: "none" },
  sendBtn:    { padding: "13px 22px", background: "linear-gradient(135deg,#4338ca,#6366f1)", color: "white", border: "none", borderRadius: "10px", fontWeight: "700", fontSize: "14px", boxShadow: "0 3px 12px #6366f125", transition: "background 0.2s, opacity 0.2s", whiteSpace: "nowrap" },
};
