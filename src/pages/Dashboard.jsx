import { useState } from "react";
import Upload from "./Upload";
import Chat from "./Chat";
import Projects from "./Projects";

const TABS = ["Chat", "Upload", "Projects"];

export default function Dashboard({ user, onLogout }) {
  const [tab, setTab] = useState("Chat");

  return (
    <div style={styles.shell}>
      <nav style={styles.nav}>
        <span style={styles.brand}>🔭 Constelli KB</span>
        <div style={styles.tabs}>
          {TABS.map(t => (
            <button key={t} style={{ ...styles.tab, ...(tab === t ? styles.activeTab : {}) }} onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        <div style={styles.userInfo}>
          <span style={styles.userText}>{user.name}</span>
          <button style={styles.logout} onClick={onLogout}>Logout</button>
        </div>
      </nav>
      <main style={styles.main}>
        <div style={{ display: tab === "Chat" ? "block" : "none" }}><Chat user={user} /></div>
        <div style={{ display: tab === "Upload" ? "block" : "none" }}><Upload user={user} /></div>
        <div style={{ display: tab === "Projects" ? "block" : "none" }}><Projects /></div>
      </main>
    </div>
  );
}

const styles = {
  shell: { minHeight: "100vh", background: "#0f172a", display: "flex", flexDirection: "column" },
  nav: { background: "#1e293b", padding: "0 24px", display: "flex", alignItems: "center", height: "60px", borderBottom: "1px solid #334155" },
  brand: { color: "#f8fafc", fontWeight: "bold", fontSize: "18px", marginRight: "32px" },
  tabs: { display: "flex", gap: "4px", flex: 1 },
  tab: { padding: "8px 20px", background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", borderRadius: "6px", fontSize: "14px" },
  activeTab: { background: "#334155", color: "#f8fafc" },
  userInfo: { display: "flex", alignItems: "center", gap: "12px" },
  userText: { color: "#94a3b8", fontSize: "13px" },
  logout: { padding: "6px 14px", background: "transparent", border: "1px solid #475569", color: "#94a3b8", borderRadius: "6px", cursor: "pointer", fontSize: "13px" },
  main: { flex: 1, padding: "24px", maxWidth: "1100px", margin: "0 auto", width: "100%" }
};