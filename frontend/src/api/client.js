// When VITE_API_URL="" (Docker/nginx proxy), BASE is "" so all fetches use relative paths.
// When unset (local dev), falls back to localhost:8000.
const BASE = import.meta.env.VITE_API_URL !== undefined
  ? import.meta.env.VITE_API_URL
  : "http://localhost:8000";

function getToken() {
  return localStorage.getItem("token");
}

function authHeaders() {
  return {
    Authorization: `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
}

export const api = {
  login: async (email, name) => {
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, name }),
    });
    if (!res.ok) throw await res.json();
    return res.json();
  },

  uploadFile: async (file, docCategory = "project_resources") => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_category", docCategory);
    const res = await fetch(`${BASE}/upload/`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: form,
    });
    if (!res.ok) throw await res.json();
    return res.json();
  },

  query: async (question) => {
    const res = await fetch(`${BASE}/query/`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ question }),
    });
    if (!res.ok) throw await res.json();
    return res.json();
  },

  getProjects: async () => {
    const res = await fetch(`${BASE}/projects/`, { headers: authHeaders() });
    if (!res.ok) throw await res.json();
    return res.json();
  },

  recluster: async () => {
    const res = await fetch(`${BASE}/projects/recluster`, {
      method: "POST",
      headers: authHeaders(),
    });
    if (!res.ok) throw await res.json();
    return res.json();
  },

  myUploads: async () => {
    const res = await fetch(`${BASE}/projects/my-uploads`, { headers: authHeaders() });
    if (!res.ok) throw await res.json();
    return res.json();
  },
};