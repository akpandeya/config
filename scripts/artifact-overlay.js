/* Artifact feedback overlay (issue #10).
 * Injected into artifact HTML — by artifact-server.py at serve time, or embedded
 * by generators (agent-explainer.py) for file:// viewing. CSP-safe: no eval, no
 * inline handlers, no images, no external network calls. Comments POST to the
 * localhost feedback server when reachable and always mirror to localStorage so
 * comments survive server downtime and file:// viewing. */
(() => {
  "use strict";
  if (window.__artifactFeedback) return;

  const MARK = "agent-overlay:v1";
  const STORE_PREFIX = "artifact-feedback:";
  const API_FALLBACK = "http://127.0.0.1:8787";
  const MAX_TEXT = 2000;
  const ANCHORS = "p, li, h1, h2, h3, h4, h5, h6, pre, figure, figcaption, table, blockquote, dt, dd, summary";
  const artifact = location.pathname;
  const apiBase = /^https?:$/.test(location.protocol) ? location.origin : API_FALLBACK;

  let comments = [];          // merged view: server comments + unsynced local ones
  let serverIds = new Set();  // ids known to the server
  let commentMode = false;
  let panel = null;
  let toggle = null;
  let dismissPrompt = null;   // closes the currently open comment prompt, if any

  const storeKey = () => STORE_PREFIX + location.pathname;
  const loadLocal = () => {
    try { return JSON.parse(localStorage.getItem(storeKey()) || "[]"); }
    catch { return []; }
  };
  const saveLocal = (list) => {
    try {
      if (list.length) localStorage.setItem(storeKey(), JSON.stringify(list));
      else localStorage.removeItem(storeKey());
    } catch { /* storage may be unavailable; comments stay in memory */ }
  };

  /* ---------- anchoring ---------- */

  const anchorOf = (target) => {
    let el = target && target.closest ? target.closest(ANCHORS) : null;
    if (!el) el = target && target.closest ? target.closest("section, main, body") : document.body;
    if (!el || el === document.body) el = document.querySelector("main") || document.body;
    return el;
  };

  const selectorOf = (el) => {
    const parts = [];
    let node = el;
    while (node && node !== document.body && parts.length < 6) {
      const tag = node.tagName.toLowerCase();
      if (tag === "main" || tag === "body") { parts.unshift(tag); break; }
      const parent = node.parentElement;
      if (!parent) { parts.unshift(tag); break; }
      const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      const index = same.indexOf(node) + 1;
      parts.unshift(same.length > 1 ? `${tag}:nth-of-type(${index})` : tag);
      node = parent;
    }
    return parts.join(" > ") || "body";
  };

  /* ---------- server sync ---------- */

  const api = async (path, options) => {
    const response = await fetch(apiBase + path, options);
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  };

  const syncNew = async (fresh) => {
    if (!fresh.length) return;
    try {
      const result = await api("/api/comments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact, comments: fresh }),
      });
      const stored = (result && result.comments) || [];
      comments = comments.filter((c) => !fresh.includes(c)).concat(stored);
      serverIds = new Set([...serverIds, ...stored.map((c) => c.id)]);
      saveLocal(comments.filter((c) => !serverIds.has(c.id)));
    } catch {
      saveLocal(comments.filter((c) => !serverIds.has(c.id))); // keep for later retry
    }
    renderPanel();
  };

  const removeComment = async (id) => {
    comments = comments.filter((c) => c.id !== id);
    if (serverIds.has(id)) {
      try {
        await api(`/api/comments?artifact=${encodeURIComponent(artifact)}&id=${encodeURIComponent(id)}`,
          { method: "DELETE" });
      } catch { /* server may be down; it stays removed locally */ }
    }
    saveLocal(comments.filter((c) => !serverIds.has(c.id)));
    renderPanel();
  };

  /* ---------- UI ---------- */

  const css = `
#af-toggle{position:fixed;right:14px;bottom:14px;z-index:9998;border:1px solid #8b93a8;border-radius:999px;
  padding:6px 14px;font:600 13px system-ui,sans-serif;background:#ffffff;color:#1b2340;cursor:pointer;
  box-shadow:0 2px 10px rgba(0,0,0,.18)}
#af-toggle .af-badge{display:inline-block;min-width:1.2em;margin-left:6px;padding:0 5px;border-radius:999px;
  background:#4f46e5;color:#fff;text-align:center;font-size:11px}
#af-panel{position:fixed;top:0;right:0;bottom:0;width:min(340px,92vw);z-index:9999;overflow:auto;
  background:#ffffff;color:#1b2340;border-left:1px solid #d9deea;box-shadow:-4px 0 18px rgba(0,0,0,.12);
  font:14px/1.5 system-ui,sans-serif;padding:14px;display:none}
#af-panel.open{display:block}
#af-panel h2{font-size:15px;margin:0 0 4px}
#af-panel .af-sub{color:#5a6478;font-size:12px;margin-bottom:10px}
#af-comment{border:1px solid #d9deea;border-radius:8px;padding:10px;margin:10px 0}
#af-comment .af-quote{color:#5a6478;font-size:12px;font-style:italic;margin-bottom:6px;
  overflow-wrap:anywhere;max-height:4.5em;overflow:hidden}
#af-comment .af-text{overflow-wrap:anywhere;white-space:pre-wrap}
#af-comment .af-status{font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  border:1px solid #cbd5e1;border-radius:999px;padding:1px 8px;margin-right:6px;color:#475569}
#af-comment[data-status=resolved] .af-status{color:#15803d;border-color:#86efac;background:#ecfdf5}
#af-comment[data-status=local] .af-status{color:#b45309;border-color:#fcd34d;background:#fffbeb}
#af-comment .af-del{float:right;border:none;background:none;color:#b91c1c;cursor:pointer;font-size:12px}
#af-prompt{position:fixed;z-index:10000;background:#ffffff;border:1px solid #8b93a8;border-radius:10px;
  box-shadow:0 6px 24px rgba(0,0,0,.25);padding:10px;width:min(320px,90vw);font:14px system-ui,sans-serif}
#af-prompt textarea{width:100%;box-sizing:border-box;min-height:64px;font:inherit;resize:vertical}
#af-prompt .af-row{display:flex;gap:8px;justify-content:flex-end;margin-top:8px}
#af-prompt button{border:1px solid #9aa4bb;border-radius:6px;padding:4px 12px;cursor:pointer;
  background:#fff;color:#1b2340}
#af-prompt .af-save{background:#4f46e5;border-color:#4f46e5;color:#fff}
#af-anchor-hover{outline:2px solid #4f46e5 !important;outline-offset:2px}
#af-picked{outline:3px solid #f59e0b !important;outline-offset:2px}
`;

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const statusOf = (c) => (serverIds.has(c.id) ? c.status || "open" : "local");

  const renderPanel = () => {
    if (!panel) return;
    panel.replaceChildren();
    const head = el("h2", null, "Comments");
    const close = el("button", "af-del", "Close");
    close.addEventListener("click", () => panel.classList.remove("open"));
    head.appendChild(close);
    const sub = el("div", "af-sub");
    sub.append(`${comments.length} comment${comments.length === 1 ? "" : "s"}`);
    const copy = el("button", "af-del", "Copy JSON");
    copy.style.cssText = "float:right;color:#1b2340;border:1px solid #9aa4bb;border-radius:6px;padding:2px 10px;cursor:pointer;background:#fff";
    copy.addEventListener("click", () => {
      const text = JSON.stringify({ artifact, comments }, null, 2);
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
      else fallbackCopy(text);
    });
    sub.appendChild(copy);
    panel.append(head, sub);
    if (!comments.length) panel.appendChild(el("p", "af-sub", "No comments yet. Enable commenting and click any paragraph."));
    for (const c of comments) {
      const card = el("div", "af-comment");
      card.dataset.status = statusOf(c);
      const del = el("button", "af-del", "Delete");
      del.addEventListener("click", () => removeComment(c.id));
      card.appendChild(del);
      card.appendChild(el("span", "af-status", statusOf(c)));
      if (c.quote) card.appendChild(el("div", "af-quote", "“" + c.quote + "”"));
      card.appendChild(el("div", "af-text", c.text));
      card.addEventListener("mouseenter", () => highlight(c, true));
      card.addEventListener("mouseleave", () => highlight(c, false));
      panel.appendChild(card);
    }
    const open = comments.filter((c) => statusOf(c) === "open").length;
    const badge = toggle && toggle.querySelector(".af-badge");
    if (badge) badge.textContent = String(open);
    badgeCount = open;
  };

  let badgeCount = 0;

  const fallbackCopy = (text) => {
    const area = el("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch { /* best effort */ }
    area.remove();
  };

  const highlight = (comment, on) => {
    let target = null;
    if (comment.selector) {
      try { target = document.querySelector(comment.selector); }
      catch { return; /* stored selector may be stale or malformed */ }
    }
    if (target) target.classList.toggle("af-anchor-hover", on);
  };

  const buildPrompt = (anchor) => {
    if (dismissPrompt) dismissPrompt();
    anchor.classList.add("af-picked");
    const box = el("div");
    box.id = "af-prompt";
    const rect = anchor.getBoundingClientRect();
    box.style.top = Math.min(window.innerHeight - 180, rect.bottom + window.scrollY + 6) + "px";
    box.style.left = Math.max(8, Math.min(window.innerWidth - 340, rect.left + window.scrollX)) + "px";
    const area = el("textarea");
    area.placeholder = "What should change here?";
    const row = el("div", "af-row");
    const cancel = el("button", null, "Cancel");
    const save = el("button", "af-save", "Save comment");
    row.append(cancel, save);
    box.append(area, row);
    document.body.appendChild(box);
    area.focus();
    const finish = () => {
      dismissPrompt = null;
      anchor.classList.remove("af-picked");
      box.remove();
    };
    dismissPrompt = finish;
    cancel.addEventListener("click", finish);
    const commit = () => {
      const text = area.value.trim().slice(0, MAX_TEXT);
      if (!text) { finish(); return; }
      finish();
      const fresh = [{
        id: "local-" + Date.now(),
        selector: selectorOf(anchor),
        quote: (anchor.textContent || "").trim().replace(/\s+/g, " ").slice(0, 300),
        text,
        created_at: new Date().toISOString(),
        status: "open",
      }];
      comments.push(fresh[0]);
      renderPanel();
      syncNew(fresh);
    };
    save.addEventListener("click", commit);
    area.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) commit();
      if (event.key === "Escape") finish();
    });
  };

  const setMode = (on) => {
    commentMode = on;
    document.documentElement.classList.toggle("af-commenting", on);
    toggle.textContent = on ? "Done commenting" : "Comment";
    const badge = el("span", "af-badge", String(badgeCount));
    toggle.appendChild(badge);
    if (on) panel.classList.add("open");
  };

  const boot = async () => {
    const style = el("style");
    style.textContent = css;
    document.head.appendChild(style);

    toggle = el("button");
    toggle.id = "af-toggle";
    setMode(false);
    toggle.addEventListener("click", () => setMode(!commentMode));
    document.body.appendChild(toggle);

    panel = el("div");
    panel.id = "af-panel";
    document.body.appendChild(panel);

    document.addEventListener("click", (event) => {
      if (!commentMode) return;
      if (panel.contains(event.target) || event.target === toggle || toggle.contains(event.target)) return;
      if (event.target.closest && event.target.closest("#af-prompt")) return; // let Save/Cancel/type work
      event.preventDefault();
      event.stopPropagation();
      buildPrompt(anchorOf(event.target));
    }, true);

    document.addEventListener("mouseover", (event) => {
      if (!commentMode) return;
      document.querySelectorAll(".af-anchor-hover").forEach((n) => n.classList.remove("af-anchor-hover"));
      anchorOf(event.target).classList.add("af-anchor-hover");
    });

    // Load existing comments from the server; fall back to local-only ones.
    let serverComments = [];
    try {
      const data = await api(`/api/feedback?artifact=${encodeURIComponent(artifact)}`);
      serverComments = (data && data.comments) || [];
    } catch { /* file:// or server down: local comments only */ }
    const local = loadLocal();
    comments = serverComments.concat(local.filter((c) => !serverComments.some((s) => s.id === c.id)));
    serverIds = new Set(serverComments.map((c) => c.id));
    renderPanel();
    // Comments written while the server was down get retried now that it answered.
    syncNew(comments.filter((c) => !serverIds.has(c.id)));
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.__artifactFeedback = { version: 1, mark: MARK };
})();
