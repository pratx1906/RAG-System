import { useState, useEffect, useRef } from "react";
import { api } from "../api/client";

const POLL_MS = 120_000; // 2 minutes

// ── Colour helpers ────────────────────────────────────────────────────────────

const PERSON_PALETTES = [
  ["#6366f1","#4338ca"], ["#ec4899","#be185d"], ["#14b8a6","#0f766e"],
  ["#f97316","#c2410c"], ["#a855f7","#7e22ce"], ["#22c55e","#15803d"],
  ["#0ea5e9","#0369a1"], ["#eab308","#a16207"],
];

function personPalette(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff;
  return PERSON_PALETTES[h % PERSON_PALETTES.length];
}

const STATUS_THEMES = {
  active:    { label: "Active",      dot: "#22c55e", bg: "rgba(34,197,94,.12)",  border: "rgba(34,197,94,.3)",  text: "#4ade80" },
  progress:  { label: "In Progress", dot: "#60a5fa", bg: "rgba(96,165,250,.12)", border: "rgba(96,165,250,.3)", text: "#93c5fd" },
  hold:      { label: "On Hold",     dot: "#fbbf24", bg: "rgba(251,191,36,.12)", border: "rgba(251,191,36,.3)", text: "#fcd34d" },
  done:      { label: "Completed",   dot: "#34d399", bg: "rgba(52,211,153,.12)", border: "rgba(52,211,153,.3)", text: "#6ee7b7" },
  cancelled: { label: "Cancelled",   dot: "#f87171", bg: "rgba(248,113,113,.12)",border: "rgba(248,113,113,.3)",text: "#fca5a5" },
  planning:  { label: "Planning",    dot: "#a78bfa", bg: "rgba(167,139,250,.12)",border: "rgba(167,139,250,.3)",text: "#c4b5fd" },
  unknown:   { label: "Unknown",     dot: "#94a3b8", bg: "rgba(148,163,184,.08)",border: "rgba(148,163,184,.2)",text: "#94a3b8" },
};

function resolveStatus(status = "") {
  const s = status.toLowerCase();
  if (/complet|done|finish/.test(s))             return STATUS_THEMES.done;
  if (/progress|ongoing|started/.test(s))        return STATUS_THEMES.progress;
  if (/\bactive\b/.test(s))                      return STATUS_THEMES.active;
  if (/hold|pause|block|wait/.test(s))           return STATUS_THEMES.hold;
  if (/cancel|stop|terminat/.test(s))            return STATUS_THEMES.cancelled;
  if (/plan|not start|backlog/.test(s))          return STATUS_THEMES.planning;
  return STATUS_THEMES.unknown;
}

// ── Shimmer skeleton ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <>
      <style>{`
        @keyframes sk-shimmer {
          0%   { background-position: -800px 0; }
          100% { background-position:  800px 0; }
        }
        .sk {
          background: linear-gradient(90deg,#0f172a 25%,#1e293b 50%,#0f172a 75%);
          background-size: 800px 100%;
          animation: sk-shimmer 1.6s infinite linear;
          border-radius: 8px;
        }
      `}</style>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(340px,1fr))", gap:20 }}>
        {[1,2,3,4].map(i => (
          <div key={i} style={{
            background:"#0b1120", border:"1px solid #1e293b",
            borderRadius:18, padding:28, display:"flex", flexDirection:"column", gap:16,
          }}>
            <div className="sk" style={{ height:10, width:60, borderRadius:20 }} />
            <div className="sk" style={{ height:26, width:"65%" }} />
            <div style={{ display:"flex", gap:8, marginTop:4 }}>
              {[1,2,3].map(j=>(
                <div key={j} className="sk" style={{ height:36, width:70+j*18, borderRadius:30 }} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

// ── Person chip ───────────────────────────────────────────────────────────────

function PersonChip({ name }) {
  const [light, dark] = personPalette(name);
  const initials = name.split(" ").filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join("");
  return (
    <div style={{
      display:"flex", alignItems:"center", gap:9,
      background:`${light}18`, border:`1px solid ${light}40`,
      borderRadius:30, padding:"5px 14px 5px 6px",
      transition:"transform .15s",
    }}
      onMouseEnter={e=>e.currentTarget.style.transform="scale(1.04)"}
      onMouseLeave={e=>e.currentTarget.style.transform="scale(1)"}
    >
      <div style={{
        width:32, height:32, borderRadius:"50%",
        background:`linear-gradient(135deg,${light},${dark})`,
        display:"flex", alignItems:"center", justifyContent:"center",
        fontSize:12, fontWeight:900, color:"#fff",
        flexShrink:0, letterSpacing:".03em",
        boxShadow:`0 0 8px ${light}50`,
      }}>
        {initials || "?"}
      </div>
      <span style={{ color:"#e2e8f0", fontSize:14, fontWeight:600, whiteSpace:"nowrap" }}>
        {name}
      </span>
    </div>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const t = resolveStatus(status);
  return (
    <div style={{
      display:"inline-flex", alignItems:"center", gap:7,
      background:t.bg, border:`1px solid ${t.border}`,
      borderRadius:30, padding:"5px 14px",
    }}>
      <span style={{
        width:7, height:7, borderRadius:"50%",
        background:t.dot, display:"inline-block",
        boxShadow:`0 0 6px ${t.dot}`,
      }} />
      <span style={{ color:t.text, fontSize:12, fontWeight:700, letterSpacing:".04em" }}>
        {status}
      </span>
    </div>
  );
}

// ── Project card ──────────────────────────────────────────────────────────────

function ProjectCard({ project, index }) {
  const t = resolveStatus(project.status);
  // Subtle gradient tint from status color
  const cardBg = `linear-gradient(135deg, #0b1120 60%, ${t.dot}0a 100%)`;

  return (
    <div style={{
      position:"relative", overflow:"hidden",
      background:cardBg,
      border:`1px solid ${t.border}`,
      borderRadius:18,
      padding:"26px 26px 22px",
      display:"flex", flexDirection:"column", gap:0,
      boxShadow:`0 4px 24px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.04)`,
    }}>
      {/* Top glow strip */}
      <div style={{
        position:"absolute", top:0, left:0, right:0, height:2,
        background:`linear-gradient(90deg, transparent, ${t.dot}80, transparent)`,
      }} />

      {/* Index number — decorative */}
      <span style={{
        position:"absolute", top:18, right:22,
        color:"rgba(255,255,255,.04)", fontSize:64, fontWeight:900,
        lineHeight:1, userSelect:"none", pointerEvents:"none",
        fontVariantNumeric:"tabular-nums",
      }}>
        {String(index + 1).padStart(2, "0")}
      </span>

      {/* Status badge */}
      <div style={{ marginBottom:14 }}>
        <StatusBadge status={project.status} />
      </div>

      {/* Project name */}
      <h2 style={{
        color:"#f1f5f9", margin:"0 0 22px",
        fontSize:22, fontWeight:800, lineHeight:1.3,
        letterSpacing:"-.02em",
        maxWidth:"85%",
      }}>
        {project.project_name}
      </h2>

      {/* People */}
      {project.people?.length > 0 && (
        <div>
          <p style={{
            color:"#475569", fontSize:10, fontWeight:700,
            textTransform:"uppercase", letterSpacing:".1em",
            margin:"0 0 10px",
          }}>
            People · {project.people.length}
          </p>
          <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
            {project.people.map((name, i) => (
              <PersonChip key={i} name={name} />
            ))}
          </div>
        </div>
      )}

      {/* Source files — subtle footer */}
      {project.sources?.length > 0 && (
        <div style={{ marginTop:20, paddingTop:14, borderTop:"1px solid rgba(255,255,255,.05)" }}>
          <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
            {project.sources.map((src, i) => (
              <span key={i} style={{
                background:"rgba(255,255,255,.04)", border:"1px solid rgba(255,255,255,.07)",
                color:"#475569", borderRadius:6, padding:"3px 10px", fontSize:11,
              }}>
                {src}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Countdown ring ────────────────────────────────────────────────────────────

function CountdownRing({ msUntilNext }) {
  const pct = 1 - msUntilNext / POLL_MS;
  const r = 10, circ = 2 * Math.PI * r;
  const dash = circ * pct;
  return (
    <svg width={26} height={26} style={{ transform:"rotate(-90deg)" }}>
      <circle cx={13} cy={13} r={r} fill="none" stroke="#1e293b" strokeWidth={2} />
      <circle cx={13} cy={13} r={r} fill="none" stroke="#6366f1" strokeWidth={2}
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        style={{ transition:"stroke-dasharray .8s linear" }}
      />
    </svg>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Projects() {
  const [projects, setProjects]       = useState([]);
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [msUntilNext, setMsUntilNext] = useState(POLL_MS);
  const [error, setError]             = useState(null);
  const nextFetchAt = useRef(null);

  const fetchProjects = async (silent = false) => {
    if (silent) setRefreshing(true);
    else        setLoading(true);
    try {
      const data = await api.getProjects();
      setProjects(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e?.detail || "Failed to load projects.");
    } finally {
      setLoading(false);
      setRefreshing(false);
      nextFetchAt.current = Date.now() + POLL_MS;
      setMsUntilNext(POLL_MS);
    }
  };

  // Countdown ticker
  useEffect(() => {
    const tick = setInterval(() => {
      if (nextFetchAt.current) {
        setMsUntilNext(Math.max(0, nextFetchAt.current - Date.now()));
      }
    }, 800);
    return () => clearInterval(tick);
  }, []);

  // Polling
  useEffect(() => {
    fetchProjects(false);
    nextFetchAt.current = Date.now() + POLL_MS;
    const poll = setInterval(() => fetchProjects(true), POLL_MS);
    return () => clearInterval(poll);
  }, []);

  const secsLeft = Math.ceil(msUntilNext / 1000);
  const fmtTime  = d => d
    ? d.toLocaleTimeString([], { hour:"2-digit", minute:"2-digit", second:"2-digit" })
    : "—";

  return (
    <div style={{ maxWidth:1000, margin:"0 auto" }}>
      <style>{`
        @keyframes fadeUp {
          from { opacity:0; transform:translateY(12px); }
          to   { opacity:1; transform:translateY(0); }
        }
      `}</style>

      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:30, gap:16 }}>
        <div style={{ animation:"fadeUp .4s ease both" }}>
          <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:6 }}>
            <div style={{
              width:8, height:8, borderRadius:"50%",
              background: error ? "#f87171" : refreshing ? "#fbbf24" : "#22c55e",
              boxShadow:`0 0 8px ${error ? "#f87171" : refreshing ? "#fbbf24" : "#22c55e"}`,
            }} />
            <span style={{ color:"#475569", fontSize:12, fontWeight:600, textTransform:"uppercase", letterSpacing:".08em" }}>
              {loading ? "Loading" : error ? "Error" : refreshing ? "Refreshing" : "Live"}
            </span>
          </div>
          <h1 style={{
            color:"#f8fafc", margin:"0 0 6px",
            fontSize:32, fontWeight:900, letterSpacing:"-.03em",
            background:"linear-gradient(90deg,#f8fafc,#94a3b8)",
            WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent",
          }}>
            Project Board
          </h1>
          <p style={{ color:"#334155", fontSize:13, margin:0 }}>
            Personal schedule · auto-updates every 2 minutes
          </p>
        </div>

        {/* Countdown widget */}
        {!loading && !error && (
          <div style={{
            display:"flex", alignItems:"center", gap:12, flexShrink:0,
            background:"#0b1120", border:"1px solid #1e293b",
            borderRadius:14, padding:"10px 16px",
            animation:"fadeUp .4s .1s ease both",
          }}>
            <CountdownRing msUntilNext={msUntilNext} />
            <div style={{ lineHeight:1.3 }}>
              <p style={{ color:"#94a3b8", fontSize:13, margin:0, fontWeight:600 }}>
                Next refresh
              </p>
              <p style={{ color:"#475569", fontSize:11, margin:0 }}>
                {secsLeft}s · last {fmtTime(lastUpdated)}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Stat strip */}
      {!loading && !error && projects.length > 0 && (
        <div style={{
          display:"flex", gap:16, marginBottom:28, flexWrap:"wrap",
          animation:"fadeUp .4s .15s ease both",
        }}>
          {[
            { label:"Projects", value: projects.length },
            { label:"People",   value: [...new Set(projects.flatMap(p=>p.people))].length },
            { label:"Sources",  value: [...new Set(projects.flatMap(p=>p.sources))].length },
          ].map(stat => (
            <div key={stat.label} style={{
              background:"#0b1120", border:"1px solid #1e293b",
              borderRadius:12, padding:"12px 20px", flex:"1 0 100px",
            }}>
              <p style={{ color:"#334155", fontSize:11, fontWeight:700, textTransform:"uppercase", letterSpacing:".08em", margin:"0 0 4px" }}>
                {stat.label}
              </p>
              <p style={{ color:"#f1f5f9", fontSize:28, fontWeight:900, margin:0, lineHeight:1 }}>
                {stat.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{
          background:"#450a0a", border:"1px solid #7f1d1d", color:"#fca5a5",
          borderRadius:10, padding:"14px 18px", fontSize:14, marginBottom:24,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* Skeleton */}
      {loading && <Skeleton />}

      {/* Empty */}
      {!loading && !error && projects.length === 0 && (
        <div style={{
          textAlign:"center", padding:"70px 20px",
          background:"#0b1120", borderRadius:18, border:"1px solid #1e293b",
          animation:"fadeUp .4s ease both",
        }}>
          <div style={{ fontSize:52, marginBottom:16 }}>📂</div>
          <p style={{ color:"#64748b", fontSize:17, margin:"0 0 8px", fontWeight:600 }}>No projects found</p>
          <p style={{ color:"#334155", fontSize:13, margin:0 }}>
            Upload documents tagged as <em>Personal Schedule</em> to see them here.
          </p>
        </div>
      )}

      {/* Grid */}
      {!loading && projects.length > 0 && (
        <div style={{
          display:"grid",
          gridTemplateColumns:"repeat(auto-fill,minmax(340px,1fr))",
          gap:20,
        }}>
          {projects.map((p, i) => (
            <div key={p.id} style={{ animation:`fadeUp .35s ${i * 0.06}s ease both` }}>
              <ProjectCard project={p} index={i} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
