import { useState } from "react";
import { api } from "../api/client";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setError("");
    if (!email.endsWith("@constelli.com")) {
      setError("Only @constelli.com email addresses are allowed.");
      return;
    }
    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }
    setLoading(true);
    try {
      const data = await api.login(email, name);
      onLogin(data.user, data.access_token);
    } catch (e) {
      setError(e.detail || "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>🔭 Constelli Knowledge Base</h1>
        <p style={styles.subtitle}>Internal Project Intelligence System</p>
        <input style={styles.input} placeholder="Your name" value={name} onChange={e => setName(e.target.value)} />
        <input style={styles.input} placeholder="your.name@constelli.com" value={email} onChange={e => setEmail(e.target.value)} />
        {error && <p style={styles.error}>{error}</p>}
        <button style={styles.button} onClick={handleSubmit} disabled={loading}>
          {loading ? "Signing in..." : "Sign In"}
        </button>
      </div>
    </div>
  );
}

const styles = {
  container: { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#0f172a" },
  card: { background: "#1e293b", padding: "40px", borderRadius: "16px", width: "360px", display: "flex", flexDirection: "column", gap: "16px" },
  title: { color: "#f8fafc", fontSize: "22px", margin: 0, textAlign: "center" },
  subtitle: { color: "#94a3b8", fontSize: "14px", margin: 0, textAlign: "center" },
  input: { padding: "12px", borderRadius: "8px", border: "1px solid #334155", background: "#0f172a", color: "#f8fafc", fontSize: "14px" },
  button: { padding: "12px", borderRadius: "8px", background: "#6366f1", color: "white", border: "none", fontWeight: "bold", cursor: "pointer", fontSize: "16px" },
  error: { color: "#f87171", fontSize: "13px", margin: 0 }
};