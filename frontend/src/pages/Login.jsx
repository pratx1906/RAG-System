import { useState } from "react";
import { api } from "../api/client";

export default function Login({ onLogin }) {
  const [name, setName]         = useState("");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);

  const handleSubmit = async () => {
    setError("");
    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }
    if (!email.endsWith("@constelli.com")) {
      setError("Only @constelli.com email addresses are allowed.");
      return;
    }
    if (!password) {
      setError("Please enter the organization password.");
      return;
    }
    setLoading(true);
    try {
      const data = await api.login(email, name, password);
      onLogin(data.user, data.access_token);
    } catch (e) {
      setError(e.detail || "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleKey = e => { if (e.key === "Enter") handleSubmit(); };

  return (
    <div style={s.container}>
      <div style={s.card}>

        {/* Title */}
        <div style={s.titleRow}>
          <span style={{ fontSize: 28 }}>🔭</span>
          <h1 style={s.title}>Constelli Knowledge Base</h1>
        </div>
        <p style={s.subtitle}>Internal Project Intelligence System</p>

        {/* Fields */}
        <div style={s.fields}>
          <input
            style={s.input}
            placeholder="Your name"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={handleKey}
            autoComplete="name"
          />
          <input
            style={s.input}
            placeholder="your.name@constelli.com"
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            onKeyDown={handleKey}
            autoComplete="email"
          />

          {/* Password with show/hide toggle */}
          <div style={{ position: "relative" }}>
            <input
              style={{ ...s.input, paddingRight: 44 }}
              placeholder="Organization password"
              type={showPw ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={handleKey}
              autoComplete="current-password"
            />
            <button
              style={s.eyeBtn}
              onClick={() => setShowPw(v => !v)}
              tabIndex={-1}
              type="button"
            >
              {showPw ? "🙈" : "👁"}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={s.errorBox}>
            <span>⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* Submit */}
        <button
          style={{ ...s.button, opacity: loading ? 0.7 : 1 }}
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading
            ? <span style={{ display:"flex", alignItems:"center", justifyContent:"center", gap:8 }}><Spinner /> Signing in…</span>
            : "Sign In"
          }
        </button>

        <p style={s.hint}>
          Access restricted to <strong style={{ color:"#94a3b8" }}>@constelli.com</strong> members
        </p>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <>
      <style>{`@keyframes _spin { to { transform: rotate(360deg); } }`}</style>
      <span style={{
        display:"inline-block", width:14, height:14,
        border:"2px solid rgba(255,255,255,.3)",
        borderTopColor:"#fff", borderRadius:"50%",
        animation:"_spin .7s linear infinite",
      }} />
    </>
  );
}

const s = {
  container: {
    minHeight:"100vh",
    display:"flex", alignItems:"center", justifyContent:"center",
    background:"#0f172a",
  },
  card: {
    background:"#1e293b",
    border:"1px solid #334155",
    padding:"40px 36px",
    borderRadius:18,
    width:380,
    display:"flex", flexDirection:"column", gap:0,
    boxShadow:"0 24px 64px rgba(0,0,0,.6)",
    boxSizing:"border-box",
  },
  titleRow: {
    display:"flex", alignItems:"center", justifyContent:"center",
    gap:10, marginBottom:8,
  },
  title: {
    color:"#f8fafc", fontSize:20, fontWeight:800,
    margin:0, textAlign:"center", lineHeight:1.25,
  },
  subtitle: {
    color:"#64748b", fontSize:13, margin:"0 0 28px", textAlign:"center",
  },
  fields: {
    display:"flex", flexDirection:"column", gap:12, marginBottom:16,
  },
  input: {
    padding:"12px 14px",
    borderRadius:8,
    border:"1px solid #334155",
    background:"#0f172a",
    color:"#f8fafc",
    fontSize:14,
    outline:"none",
    width:"100%",
    boxSizing:"border-box",
  },
  eyeBtn: {
    position:"absolute", right:12, top:"50%", transform:"translateY(-50%)",
    background:"none", border:"none", cursor:"pointer",
    fontSize:16, padding:0, lineHeight:1, opacity:0.55,
  },
  errorBox: {
    display:"flex", alignItems:"flex-start", gap:8,
    background:"#450a0a", border:"1px solid #7f1d1d",
    color:"#fca5a5", borderRadius:8,
    padding:"10px 14px", fontSize:13,
    marginBottom:16,
  },
  button: {
    padding:"13px",
    borderRadius:8,
    background:"#6366f1",
    color:"#fff",
    border:"none",
    fontWeight:700,
    cursor:"pointer",
    fontSize:15,
    marginBottom:16,
  },
  hint: {
    color:"#475569", fontSize:12, textAlign:"center", margin:0,
  },
};
