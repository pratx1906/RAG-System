import { useState, useEffect } from "react";
import { api } from "../api/client";

const PROJECTS_CACHE_KEY = "cached_projects";

const ACCENT_GRADIENTS = [
  "linear-gradient(90deg,#4338ca,#7c3aed)",
  "linear-gradient(90deg,#0e7490,#0284c7)",
  "linear-gradient(90deg,#065f46,#059669)",
  "linear-gradient(90deg,#92400e,#d97706)",
  "linear-gradient(90deg,#7f1d1d,#dc2626)",
  "linear-gradient(90deg,#4c1d95,#7c3aed)",
];

function Avatar({ name }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join("");
  const hue = (name.charCodeAt(0) * 37 + (name.charCodeAt(1) || 0) * 13) % 360;
  return (
    <div style={{
      width: "26px", height: "26px", borderRadius: "50%", flexShrink: 0,
      background: `hsl(${hue},55%,35%)`,
      border: "1px solid rgba(255,255,255,0.12)",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: "10px", fontWeight: "700", color: "#f8fafc",
      letterSpacing: "0.02em",
    }}>{initials || "?"}</div>
  );
}

function ProjectCard({ project, index }) {
  const [expanded, setExpanded] = useState(false);
  const accent = ACCENT_GRADIENTS[index % ACCENT_GRADIENTS.length];
  const memberList = project.members || [];
  const docCount = project.document_count ?? null;
  const visibleMembers = expanded ? memberList : memberList.slice(0, 3);
  const hiddenCount = memberList.length - 3;

  return (
    <div style={styles.card}>
      {/* Accent top bar */}
      <div style={{ height: "3px", background: accent, borderRadius: "12px 12px 0 0", margin: "-20px -20px 16px" }} />

      {/* Title row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
        <h3 style={styles.cardTitle}>{project.name}</h3>
        {docCount !== null && (
          <span style={styles.docBadge}>{docCount} doc{docCount !== 1 ? "s" : ""}</span>
        )}
      </div>

      {/* Description */}
      <p style={styles.cardDesc}>{project.description}</p>

      {/* Keywords */}
      {project.keywords?.length > 0 && (
        <div style={styles.keywords}>
          {project.keywords.map((k, i) => (
            <span key={i} style={styles.keyword}>{k}</span>
          ))}
        </div>
      )}

      {/* Divider */}
      <div style={styles.divider} />

      {/* Contributors */}
      {memberList.length > 0 && (
        <div>
          <p style={styles.membersTitle}>Contributors</p>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {visibleMembers.map((m, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Avatar name={m} />
                <span style={styles.member}>{m}</span>
              </div>
            ))}
          </div>
          {!expanded && hiddenCount > 0 && (
            <button style={styles.expandBtn} onClick={() => setExpanded(true)}>
              +{hiddenCount} more
            </button>
          )}
          {expanded && hiddenCount > 0 && (
            <button style={styles.expandBtn} onClick={() => setExpanded(false)}>
              Show less
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Projects() {
  const [projects, setProjects] = useState(() => {
    try {
      const cached = localStorage.getItem(PROJECTS_CACHE_KEY);
      if (cached) return JSON.parse(cached);
    } catch {}
    return [];
  });
  const [loading, setLoading] = useState(true);
  const [reclustering, setReclustering] = useState(false);
  const [error, setError] = useState(null);

  const fetchProjects = async () => {
    try {
      const data = await api.getProjects();
      setProjects(data);
      localStorage.setItem(PROJECTS_CACHE_KEY, JSON.stringify(data));
      setError(null);
    } catch (e) {
      setError(e?.detail || "Failed to load projects. Please check your connection.");
    }
    setLoading(false);
  };

  useEffect(() => { fetchProjects(); }, []);

  const recluster = async () => {
    setReclustering(true);
    try {
      await api.recluster();
      await fetchProjects();
    } catch (e) {
      setError(e?.detail || "Clustering failed. Please try again.");
    }
    setReclustering(false);
  };

  return (
    <div>
      <div style={styles.header}>
        <div>
          <h2 style={styles.heading}>Detected Projects</h2>
          {!loading && !error && (
            <p style={styles.subheading}>
              {projects.length} project{projects.length !== 1 ? "s" : ""} discovered from uploaded documents
            </p>
          )}
        </div>
        <button style={{ ...styles.reclusterBtn, opacity: reclustering ? 0.6 : 1 }} onClick={recluster} disabled={reclustering}>
          {reclustering ? (
            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ display: "inline-block", animation: "spin 1s linear infinite" }}>⟳</span>
              Clustering…
            </span>
          ) : "🔄 Re-cluster"}
        </button>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {error && (
        <div style={styles.errorBox}>⚠ {error}</div>
      )}
      {loading && (
        <p style={{ color: "#94a3b8" }}>Loading projects…</p>
      )}
      {!loading && !error && projects.length === 0 && (
        <div style={styles.emptyState}>
          <div style={{ fontSize: "40px", marginBottom: "12px" }}>🔭</div>
          <p style={{ color: "#94a3b8", margin: 0 }}>No projects detected yet.</p>
          <p style={{ color: "#64748b", fontSize: "13px", marginTop: "6px" }}>
            Upload documents tagged as <em>Personal Schedule</em> or <em>Project Resources</em> and click Re-cluster.
          </p>
        </div>
      )}

      <div style={styles.grid}>
        {projects.map((p, i) => (
          <ProjectCard key={p.id} project={p} index={i} />
        ))}
      </div>
    </div>
  );
}

const styles = {
  header:       { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px" },
  heading:      { color: "#f8fafc", margin: "0 0 4px" },
  subheading:   { color: "#64748b", fontSize: "13px", margin: 0 },
  reclusterBtn: { padding: "10px 20px", background: "#0f172a", border: "1px solid #6366f1", color: "#6366f1", borderRadius: "8px", cursor: "pointer", fontWeight: "600", fontSize: "14px", flexShrink: 0 },
  errorBox:     { background: "#450a0a", border: "1px solid #7f1d1d", color: "#fca5a5", borderRadius: "8px", padding: "12px 16px", fontSize: "14px", marginBottom: "20px" },
  emptyState:   { textAlign: "center", padding: "60px 20px", background: "#1e293b", borderRadius: "12px", border: "1px solid #334155" },
  grid:         { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "20px" },
  card:         { background: "#1e293b", borderRadius: "12px", padding: "20px", border: "1px solid #334155", position: "relative", overflow: "hidden" },
  cardTitle:    { color: "#f8fafc", margin: "0 0 8px", fontSize: "16px", fontWeight: "700", lineHeight: "1.3" },
  docBadge:     { background: "#0f172a", border: "1px solid #334155", color: "#64748b", fontSize: "11px", padding: "2px 8px", borderRadius: "20px", whiteSpace: "nowrap", flexShrink: 0 },
  cardDesc:     { color: "#94a3b8", fontSize: "13px", lineHeight: "1.65", marginBottom: "12px" },
  keywords:     { display: "flex", flexWrap: "wrap", gap: "5px", marginBottom: "14px" },
  keyword:      { background: "#1e1b4b", color: "#a5b4fc", padding: "3px 10px", borderRadius: "20px", fontSize: "11px", border: "1px solid #312e81" },
  divider:      { height: "1px", background: "#334155", margin: "12px 0" },
  membersTitle: { color: "#64748b", fontSize: "11px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.06em", margin: "0 0 8px" },
  member:       { color: "#cbd5e1", fontSize: "13px" },
  expandBtn:    { background: "none", border: "none", color: "#6366f1", fontSize: "12px", cursor: "pointer", marginTop: "6px", padding: "0" },
};
