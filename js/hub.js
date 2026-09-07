/* BCOBA Digital Hub — client */
const Hub = (() => {
  const TOKEN_KEY = "bcoba_hub_token";
  const CHANNELS = ["facebook", "instagram", "linkedin", "whatsapp", "youtube"];

  const state = {
    user: null,
    categories: [],
    campaigns: [],
    tags: [],
    currentContentId: null,
    calMonth: null,
  };

  function token() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(value) {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (
      options.body != null &&
      !(options.body instanceof FormData) &&
      !headers["Content-Type"]
    ) {
      headers["Content-Type"] = "application/json";
    }
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const res = await fetch(path, { ...options, headers });
    if (res.status === 204) return { ok: true };
    const data = await res.json().catch(() => ({ ok: false, error: "Bad response" }));
    if (res.status === 401 && !path.includes("/auth/login")) {
      setToken("");
      if (!location.pathname.endsWith("index.html") && location.pathname !== "/") {
        location.href = "/index.html";
      }
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `Request failed (${res.status})`);
    }
    return data;
  }

  function qs(sel, root = document) {
    return root.querySelector(sel);
  }
  function qsa(sel, root = document) {
    return [...root.querySelectorAll(sel)];
  }

  function badge(status) {
    return `<span class="badge ${status || ""}">${(status || "").replaceAll("_", " ")}</span>`;
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function channelPills() {
    const labels = { facebook: "f", instagram: "Ig", linkedin: "in", whatsapp: "Wa", youtube: "Yt" };
    return `<div class="channel-pills">${CHANNELS.map(
      (c) => `<span class="ch-pill ${c}" title="${c}">${labels[c] || c.slice(0, 2)}</span>`
    ).join("")}</div>`;
  }

  function postCard(c) {
    return `<article class="post-card">
      <div>
        <h4>${escapeHtml(c.title)}</h4>
        <div class="muted" style="font-size:0.84rem">
          ${escapeHtml(c.category_name || "")}${
            c.campaign_name ? " · " + escapeHtml(c.campaign_name) : ""
          }${c.submitter_name ? " · " + escapeHtml(c.submitter_name) : ""}
        </div>
        <div class="post-meta">
          ${badge(c.status)}
          ${channelPills()}
          <span>${fmtDate(c.updated_at || c.scheduled_at || c.published_at)}</span>
        </div>
      </div>
      <div class="row-actions" style="align-content:start">
        <a class="btn small secondary" href="#editor/${c.id}">Open</a>
      </div>
    </article>`;
  }

  function fmtDate(value) {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleString();
    } catch {
      return value;
    }
  }

  function roleCanEdit(role) {
    return ["admin", "editor", "approver"].includes(role);
  }
  function roleCanApprove(role) {
    return ["admin", "approver"].includes(role);
  }

  async function requireAuth() {
    const data = await api("/api/me");
    state.user = data.user;
    return data.user;
  }

  async function loadLookups() {
    const [cats, camps, tags] = await Promise.all([
      api("/api/categories"),
      api("/api/campaigns"),
      api("/api/tags"),
    ]);
    state.categories = cats.items;
    state.campaigns = camps.items;
    state.tags = tags.items;
  }

  function fillCategorySelect(el, includeBlank = true) {
    if (!el) return;
    el.innerHTML =
      (includeBlank ? `<option value="">Select category</option>` : "") +
      state.categories
        .map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
        .join("");
  }

  function fillCampaignSelect(el, categoryId = "", includeBlank = true) {
    if (!el) return;
    const items = state.campaigns.filter((c) => !categoryId || c.category_id === categoryId);
    el.innerHTML =
      (includeBlank ? `<option value="">No campaign</option>` : "") +
      items
        .map(
          (c) =>
            `<option value="${c.id}">${escapeHtml(c.name)} (${escapeHtml(c.status)})</option>`
        )
        .join("");
  }

  /* ---------- Login ---------- */
  async function initLogin() {
    if (token()) {
      try {
        await requireAuth();
        location.href = "/app.html";
        return;
      } catch {
        setToken("");
      }
    }
    const form = qs("#login-form");
    const err = qs("#login-error");
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      try {
        const fd = new FormData(form);
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            email: fd.get("email"),
            password: fd.get("password"),
          }),
        });
        setToken(data.token);
        location.href = "/app.html";
      } catch (ex) {
        err.textContent = ex.message;
      }
    });
  }

  /* ---------- App shell ---------- */
  async function initApp() {
    try {
      await requireAuth();
      await loadLookups();
    } catch {
      location.href = "/index.html";
      return;
    }

    qs("#user-name").textContent = state.user.name;
    qs("#user-role").textContent = state.user.role.replaceAll("_", " ");

    qsa("[data-nav]").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        location.hash = a.getAttribute("data-nav");
      });
    });

    qs("#logout-btn")?.addEventListener("click", async () => {
      try {
        await api("/api/auth/logout", { method: "POST", body: "{}" });
      } catch {
        /* ignore */
      }
      setToken("");
      location.href = "/index.html";
    });

    window.addEventListener("hashchange", () => route());
    if (!location.hash) location.hash = "#dashboard";
    else route();
  }

  async function route() {
    const hash = (location.hash || "#dashboard").slice(1);
    const [view, id] = hash.split("/");
    qsa("[data-nav]").forEach((a) => {
      a.classList.toggle("active", a.getAttribute("data-nav") === `#${view}`);
    });
    qsa(".view").forEach((v) => v.classList.add("hidden"));
    const el = qs(`#view-${view}`) || qs("#view-dashboard");
    el.classList.remove("hidden");

    const title = qs("#view-title");
    const sub = qs("#view-sub");
    const titles = {
      dashboard: ["Dashboard", "Your publishing command center"],
      submit: ["Compose", "Submit a story for Digital Comms to adapt and approve"],
      queue: ["Publisher queue", "Review, adapt, approve — then schedule across channels"],
      editor: ["Publisher", "Master post + channel packs + tags"],
      calendar: ["Content calendar", "One master calendar for every BCOBA campaign"],
      campaigns: ["Campaigns", "Create initiatives without hard-coding projects"],
      media: ["Media library", "Reuse approved assets by category & campaign"],
      templates: ["Post templates", "Simple branded graphics — no Canva needed for basic posts"],
      diagrams: ["Process diagrams", "Add sections and process points — draw BCOBA workflows yourself"],
      brand: ["Brand guidelines", "BCOBA master brand for all campaigns and channels"],
      engagement: ["Engagement", "Channel admins reply · escalate sensitive items"],
      analytics: ["Analytics", "Live sync when connected · manual fallback"],
      connections: ["Connections", "Save platform credentials for auto-post + analytics"],
    };
    const meta = titles[view] || titles.dashboard;
    title.textContent = meta[0];
    sub.textContent = meta[1];

    if (view === "dashboard") return renderDashboard();
    if (view === "submit") return renderSubmit();
    if (view === "queue") return renderQueue();
    if (view === "editor") return renderEditor(id);
    if (view === "calendar") return renderCalendar();
    if (view === "campaigns") return renderCampaigns();
    if (view === "media") return renderMedia();
    if (view === "templates") return renderTemplates();
    if (view === "diagrams") return renderDiagrams();
    if (view === "brand") return renderBrand();
    if (view === "engagement") return renderEngagement();
    if (view === "analytics") return renderAnalytics();
    if (view === "connections") return renderConnections();
    return renderDashboard();
  }

  async function renderDashboard() {
    const data = (await api("/api/dashboard")).data;
    const root = qs("#view-dashboard");
    const s = data.by_status || {};
    root.innerHTML = `
      <div class="grid stats">
        <div class="stat"><div class="label">Needs review</div><div class="value">${(s.submitted || 0) + (s.changes_requested || 0)}</div></div>
        <div class="stat"><div class="label">In review</div><div class="value">${s.in_review || 0}</div></div>
        <div class="stat"><div class="label">Scheduled / live</div><div class="value">${(s.scheduled || 0) + (s.published || 0)}</div></div>
        <div class="stat"><div class="label">Escalations</div><div class="value">${data.escalations || 0}</div></div>
      </div>
      <div class="grid two" style="margin-top:1rem">
        <div class="panel">
          <div class="panel-head">
            <h3>Publisher stream</h3>
            <a class="btn small secondary" href="#queue">View queue</a>
          </div>
          <div class="post-stream">
            ${
              data.queue.map(postCard).join("") ||
              `<p class="muted">Queue is clear. <a href="#submit">Compose</a> the next post.</p>`
            }
          </div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <h3>Active campaigns</h3>
            <a class="btn small secondary" href="#campaigns">Manage</a>
          </div>
          ${
            data.campaigns
              .map(
                (c) => `<div class="campaign-chip ${escapeHtml(c.status)}">
                  <span class="dot"></span>
                  <div style="flex:1">
                    <strong>${escapeHtml(c.name)}</strong>
                    <div class="muted" style="font-size:0.78rem">${escapeHtml(c.category_name)} · ${escapeHtml(c.status)}</div>
                  </div>
                </div>`
              )
              .join("") || `<p class="muted">No active campaigns</p>`
          }
          <div style="margin-top:1rem">
            <div class="panel-head"><h3>Channels</h3></div>
            ${channelPills()}
            <p class="muted" style="margin:0.55rem 0 0;font-size:0.82rem">
              One master post → adapt for Facebook, Instagram, LinkedIn, WhatsApp, YouTube.
            </p>
          </div>
        </div>
      </div>
    `;
  }

  function renderSubmit() {
    const root = qs("#view-submit");
    root.innerHTML = `
      <div class="composer-shell">
        <div class="composer-bar">
          <span>New post</span>
          ${channelPills()}
        </div>
        <form id="submit-form" class="form-grid">
          <label>Title<input name="title" required placeholder="e.g. Alumni achievement — ..."></label>
          <div class="form-grid two">
            <label>Category<select name="category_id" id="submit-category" required></select></label>
            <label>Campaign (optional)<select name="campaign_id" id="submit-campaign"></select></label>
          </div>
          <label>Story / information<textarea name="body" required placeholder="Facts, quotes, links, caption ideas..."></textarea></label>
          <label>Suggested #tags<input name="extra_tags" placeholder="#AlumniStory #BigMatch #Guardians"></label>
          <label>Notes for Digital Comms<textarea name="notes" placeholder="Urgency, suggested channel, photo credit..."></textarea></label>
          <div class="row-actions">
            <button class="btn secondary" type="submit" data-mode="draft">Save as draft</button>
            <button class="btn" type="submit" data-mode="submitted">Send to Digital Comms</button>
          </div>
          <p class="muted">Drafts stay private in Queue until you submit or publish. Nothing goes to Facebook/IG/etc until you Auto-publish or Schedule.</p>
          <p id="submit-msg" class="muted"></p>
        </form>
      </div>
    `;
    fillCategorySelect(qs("#submit-category"));
    fillCampaignSelect(qs("#submit-campaign"));
    qs("#submit-category").addEventListener("change", (e) => {
      fillCampaignSelect(qs("#submit-campaign"), e.target.value);
    });
    let submitMode = "submitted";
    qsa("#submit-form [data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        submitMode = btn.dataset.mode || "submitted";
      });
    });
    qs("#submit-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = qs("#submit-msg");
      const asDraft = submitMode === "draft";
      msg.textContent = asDraft ? "Saving draft…" : "Submitting…";
      try {
        const data = await api("/api/content", {
          method: "POST",
          body: JSON.stringify({
            title: fd.get("title"),
            category_id: fd.get("category_id"),
            campaign_id: fd.get("campaign_id") || null,
            body: fd.get("body"),
            notes: fd.get("notes"),
            extra_tags: fd.get("extra_tags") || "",
            status: asDraft ? "draft" : "submitted",
          }),
        });
        msg.textContent = asDraft ? "Draft saved. Opening editor…" : "Submitted. Opening editor…";
        location.hash = `#editor/${data.id}`;
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });
  }

  async function renderQueue() {
    const root = qs("#view-queue");
    root.innerHTML = `
      <div class="filters">
        <select id="q-status">
          <option value="">All statuses</option>
          ${["draft","submitted","in_review","changes_requested","approved","scheduled","published","rejected"]
            .map((s) => `<option value="${s}">${s.replaceAll("_"," ")}</option>`).join("")}
        </select>
        <select id="q-category"></select>
        <select id="q-campaign"></select>
        <select id="q-tag">
          <option value="">All #tags</option>
          ${state.tags
            .map((t) => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`)
            .join("")}
        </select>
        <button class="btn secondary" id="q-refresh" type="button">Refresh</button>
      </div>
      <div id="q-table"></div>
    `;
    fillCategorySelect(qs("#q-category"));
    fillCampaignSelect(qs("#q-campaign"));
    const load = async () => {
      const params = new URLSearchParams();
      const st = qs("#q-status").value;
      const cat = qs("#q-category").value;
      const camp = qs("#q-campaign").value;
      const tag = qs("#q-tag").value;
      if (st) params.set("status", st);
      if (cat) params.set("category_id", cat);
      if (camp) params.set("campaign_id", camp);
      if (tag) params.set("tag", tag);
      const data = await api(`/api/content?${params}`);
      qs("#q-table").innerHTML = `
        <div class="post-stream">
          ${
            data.items.map(postCard).join("") ||
            `<div class="panel muted">No content in this filter.</div>`
          }
        </div>`;
    };
    const presetTag = sessionStorage.getItem("hub_queue_tag");
    if (presetTag) {
      qs("#q-tag").value = presetTag;
      sessionStorage.removeItem("hub_queue_tag");
    }
    qs("#q-refresh").onclick = load;
    qs("#q-category").onchange = () => {
      fillCampaignSelect(qs("#q-campaign"), qs("#q-category").value);
      load();
    };
    qs("#q-status").onchange = load;
    qs("#q-campaign").onchange = load;
    qs("#q-tag").onchange = load;
    await load();
  }

  async function renderEditor(id) {
    const root = qs("#view-editor");
    if (!id) {
      root.innerHTML = `<div class="panel muted">Open an item from the queue, or <a href="#submit">submit new content</a>.</div>`;
      return;
    }
    const { item } = await api(`/api/content/${id}`);
    state.currentContentId = id;
    const role = state.user.role;
    const canEdit =
      roleCanEdit(role) ||
      (role === "contributor" &&
        ["draft", "submitted", "changes_requested"].includes(item.status));
    const canApprove = roleCanApprove(role);

    root.innerHTML = `
      <div class="panel">
        <div class="row-actions" style="margin-bottom:0.8rem">
          ${badge(item.status)}
          <span class="muted">Submitted by ${escapeHtml(item.submitter_name || "—")}</span>
        </div>
        <form id="editor-form" class="form-grid">
          <label>Title<input name="title" value="${escapeHtml(item.title)}" ${canEdit ? "" : "readonly"}></label>
          <div class="form-grid two">
            <label>Category<select name="category_id" id="ed-category" ${canEdit ? "" : "disabled"}></select></label>
            <label>Campaign<select name="campaign_id" id="ed-campaign" ${canEdit ? "" : "disabled"}></select></label>
          </div>
          <label>Master content<textarea name="body" ${canEdit ? "" : "readonly"}>${escapeHtml(item.body)}</textarea></label>
          <label>Internal notes<textarea name="notes" ${canEdit ? "" : "readonly"}>${escapeHtml(item.notes)}</textarea></label>
          <label>Schedule at<input type="datetime-local" name="scheduled_at" id="ed-schedule" ${canEdit || canApprove ? "" : "readonly"}></label>
          <div class="tag-box">
            <div class="muted" style="margin-bottom:0.35rem">Locked brand tags (auto)</div>
            <div class="tags" id="ed-auto-tags">
              ${item.tags
                .filter((t) => t.kind !== "custom")
                .map((t) => `<span class="tag">${escapeHtml(t.name)}</span>`)
                .join("") || "—"}
            </div>
            <label style="margin-top:0.75rem">Extra #tags for analysis
              <input name="extra_tags" id="ed-extra-tags" ${canEdit ? "" : "readonly"}
                value="${escapeHtml(
                  item.tags
                    .filter((t) => t.kind === "custom")
                    .map((t) => t.name)
                    .join(" ")
                )}"
                placeholder="#AlumniStory #Guardians #Throwback">
            </label>
            <div class="tag-suggestions" id="ed-tag-suggestions"></div>
            <p class="muted" style="margin:0.35rem 0 0;font-size:0.8rem">
              Separate with spaces. Auto tags always stay. Custom tags are tracked in Analytics.
            </p>
            <div class="row-actions" style="margin-top:0.55rem">
              <button class="btn small secondary" type="button" id="ed-append-tags">Append all tags to channel copies</button>
            </div>
          </div>
          <div>
            <div class="muted" style="margin-bottom:0.45rem">Channel adaptations</div>
            <div class="tabs" id="ch-tabs"></div>
            <div id="ch-panes"></div>
          </div>
          <div class="row-actions" id="ed-actions"></div>
          <p id="ed-msg" class="muted"></p>
        </form>
      </div>
    `;

    fillCategorySelect(qs("#ed-category"), false);
    qs("#ed-category").value = item.category_id;
    fillCampaignSelect(qs("#ed-campaign"), item.category_id);
    qs("#ed-campaign").value = item.campaign_id || "";
    qs("#ed-category").addEventListener("change", (e) => {
      fillCampaignSelect(qs("#ed-campaign"), e.target.value);
    });

    if (item.scheduled_at) {
      const d = new Date(item.scheduled_at);
      if (!Number.isNaN(d.getTime())) {
        const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
          .toISOString()
          .slice(0, 16);
        qs("#ed-schedule").value = local;
      }
    }

    const suggestionRoot = qs("#ed-tag-suggestions");
    const customSuggestions = state.tags
      .filter((t) => t.kind === "custom" || t.kind === "campaign")
      .slice(0, 12);
    suggestionRoot.innerHTML = customSuggestions
      .map(
        (t) =>
          `<button type="button" class="tag suggest" data-tag="${escapeHtml(t.name)}">${escapeHtml(
            t.name
          )}</button>`
      )
      .join("");
    suggestionRoot.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tag]");
      if (!btn || !canEdit) return;
      const input = qs("#ed-extra-tags");
      const current = input.value.trim();
      const tag = btn.dataset.tag;
      if (!current.toLowerCase().includes(tag.toLowerCase())) {
        input.value = `${current} ${tag}`.trim();
      }
    });

    const allTagsText = () => {
      const auto = item.tags.filter((t) => t.kind !== "custom").map((t) => t.name);
      const extra = (qs("#ed-extra-tags").value || "").trim();
      return [...auto, ...extra.split(/\s+/).filter(Boolean)].join(" ");
    };
    qs("#ed-append-tags")?.addEventListener("click", () => {
      const tagsLine = allTagsText();
      if (!tagsLine) return;
      qsa(".ch-pane").forEach((pane) => {
        const ta = qs('[data-field="body"]', pane);
        if (!ta) return;
        if (!ta.value.includes("#BCOBA") && !ta.value.includes(tagsLine.split(" ")[0] || "___")) {
          ta.value = `${ta.value.trim()}\n\n${tagsLine}`.trim();
        } else {
          ta.value = `${ta.value.replace(/\n\n#[\s\S]*$/, "").trim()}\n\n${tagsLine}`;
        }
      });
      qs("#ed-msg").textContent = "Tags appended to channel copies.";
    });

    const tabs = qs("#ch-tabs");
    const panes = qs("#ch-panes");
    item.channels.forEach((ch, idx) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = `tab ${idx === 0 ? "active" : ""}`;
      const labels = {
        facebook: "f Facebook",
        instagram: "Ig Instagram",
        linkedin: "in LinkedIn",
        whatsapp: "Wa WhatsApp",
        youtube: "Yt YouTube",
      };
      tab.textContent = labels[ch.channel] || ch.channel;
      tab.dataset.ch = ch.channel;
      tabs.appendChild(tab);

      let meta = {};
      try {
        meta = ch.meta_json ? JSON.parse(ch.meta_json) : {};
      } catch {
        meta = {};
      }
      const checks = meta.checks || {};

      const pane = document.createElement("div");
      pane.className = `ch-pane ${idx === 0 ? "" : "hidden"}`;
      pane.dataset.ch = ch.channel;

      if (ch.channel === "whatsapp") {
        pane.innerHTML = `
          <div class="wa-box">
            <h4>WhatsApp publish pack</h4>
            <p class="muted" style="margin:0 0 0.6rem">
              WhatsApp has no public auto-schedule like Facebook. Hub prepares the message;
              Channel Admin copies and sends to the approved Community / Broadcast / Group at the scheduled time.
            </p>
            <div class="form-grid">
              <label>WhatsApp message (keep short)
                <textarea data-field="body" ${canEdit ? "" : "readonly"}>${escapeHtml(ch.body)}</textarea>
              </label>
              <div class="form-grid two">
                <label>Send via
                  <select data-field="wa_target" ${canEdit || canApprove ? "" : "disabled"}>
                    ${["community","broadcast","group","status","channel_admin_dm"]
                      .map(
                        (t) =>
                          `<option value="${t}" ${
                            (ch.wa_target || "community") === t ? "selected" : ""
                          }>${t.replaceAll("_", " ")}</option>`
                      )
                      .join("")}
                  </select>
                </label>
                <label>Group / Community / invite link
                  <input data-field="live_url" value="${escapeHtml(ch.live_url)}" placeholder="https://chat.whatsapp.com/..." ${
                    canEdit || canApprove ? "" : "readonly"
                  }>
                </label>
              </div>
              <label>Status
                <select data-field="status" ${canEdit || canApprove ? "" : "disabled"}>
                  ${["draft","ready","published"]
                    .map(
                      (s) =>
                        `<option value="${s}" ${ch.status === s ? "selected" : ""}>${s}</option>`
                    )
                    .join("")}
                </select>
              </label>
              <div class="wa-checklist">
                <label><input type="checkbox" data-check="approved_copy" ${checks.approved_copy ? "checked" : ""}> Copy approved by Digital Comms</label>
                <label><input type="checkbox" data-check="image_ready" ${checks.image_ready ? "checked" : ""}> Image/video ready on phone</label>
                <label><input type="checkbox" data-check="sent" ${checks.sent ? "checked" : ""}> Sent at scheduled time</label>
                <label><input type="checkbox" data-check="metrics_logged" ${checks.metrics_logged ? "checked" : ""}> Views/forwards logged below</label>
              </div>
              <div class="row-actions">
                <button class="btn secondary" type="button" data-copy-wa>Copy WhatsApp message</button>
                <a class="btn secondary" href="${
                  ch.live_url || "https://web.whatsapp.com/"
                }" target="_blank" rel="noopener">Open WhatsApp</a>
              </div>
              <div class="form-grid two">
                <label>Approx. reach / views<input type="number" data-field="reach" value="${ch.reach || 0}"></label>
                <label>Forwards / shares<input type="number" data-field="shares" value="${ch.shares || 0}"></label>
                <label>Replies<input type="number" data-field="comments" value="${ch.comments || 0}"></label>
                <label>Reactions<input type="number" data-field="likes" value="${ch.likes || 0}"></label>
              </div>
            </div>
          </div>`;
      } else {
        pane.innerHTML = `
          <div class="form-grid">
            <label>${ch.channel} copy
              <textarea data-field="body" ${canEdit ? "" : "readonly"}>${escapeHtml(ch.body)}</textarea>
            </label>
            <div class="form-grid two">
              <label>Live URL<input data-field="live_url" value="${escapeHtml(ch.live_url)}" ${canEdit || canApprove ? "" : "readonly"}></label>
              <label>Status
                <select data-field="status" ${canEdit || canApprove ? "" : "disabled"}>
                  ${["draft","ready","published"].map((s) => `<option value="${s}" ${ch.status===s?"selected":""}>${s}</option>`).join("")}
                </select>
              </label>
            </div>
            <div class="form-grid two">
              <label>Reach<input type="number" data-field="reach" value="${ch.reach || 0}"></label>
              <label>Likes<input type="number" data-field="likes" value="${ch.likes || 0}"></label>
              <label>Comments<input type="number" data-field="comments" value="${ch.comments || 0}"></label>
              <label>Shares<input type="number" data-field="shares" value="${ch.shares || 0}"></label>
            </div>
          </div>`;
      }
      panes.appendChild(pane);
    });

    tabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab");
      if (!btn) return;
      qsa(".tab", tabs).forEach((t) => t.classList.toggle("active", t === btn));
      qsa(".ch-pane", panes).forEach((p) =>
        p.classList.toggle("hidden", p.dataset.ch !== btn.dataset.ch)
      );
    });

    panes.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-copy-wa]");
      if (!btn) return;
      const pane = btn.closest(".ch-pane");
      const text = qs('[data-field="body"]', pane)?.value || "";
      try {
        await navigator.clipboard.writeText(text);
        qs("#ed-msg").textContent = "WhatsApp message copied — paste into Community/Broadcast/Group.";
      } catch {
        qs("#ed-msg").textContent = "Copy failed — select the message and copy manually.";
      }
    });

    const actions = qs("#ed-actions");
    if (canEdit) {
      actions.innerHTML += `<button class="btn" type="submit">Save</button>`;
      if (item.status === "draft") {
        actions.innerHTML += `<button class="btn secondary" type="button" data-status="submitted">Submit for review</button>`;
      } else if (["submitted", "changes_requested", "in_review"].includes(item.status)) {
        actions.innerHTML += `<button class="btn secondary" type="button" data-status="draft">Move back to draft</button>`;
      }
      if (roleCanEdit(role)) {
        actions.innerHTML += `<button class="btn secondary" type="button" data-status="in_review">Mark in review</button>`;
        actions.innerHTML += `<button class="btn secondary" type="button" data-status="changes_requested">Request changes</button>`;
      }
    }
    if (canApprove) {
      actions.innerHTML += `<button class="btn secondary" type="button" data-status="approved">Approve</button>`;
      actions.innerHTML += `<button class="btn secondary" type="button" data-status="scheduled">Schedule</button>`;
      actions.innerHTML += `<button class="btn" type="button" data-status="published">Mark published</button>`;
      actions.innerHTML += `<button class="btn" type="button" id="ed-autopublish">Auto-publish now</button>`;
      actions.innerHTML += `<button class="btn danger" type="button" data-status="rejected">Reject</button>`;
    }
    if (roleCanEdit(role) || canApprove) {
      actions.innerHTML += `<button class="btn secondary" type="button" id="ed-sync">Sync analytics</button>`;
    }

    const collectChannels = () =>
      qsa(".ch-pane", panes).map((pane) => {
        const checks = {};
        qsa("[data-check]", pane).forEach((el) => {
          checks[el.dataset.check] = !!el.checked;
        });
        return {
          channel: pane.dataset.ch,
          body: qs('[data-field="body"]', pane)?.value || "",
          live_url: qs('[data-field="live_url"]', pane)?.value || "",
          status: qs('[data-field="status"]', pane)?.value || "draft",
          wa_target: qs('[data-field="wa_target"]', pane)?.value || "",
          meta_json: Object.keys(checks).length ? { checks } : undefined,
          reach: Number(qs('[data-field="reach"]', pane)?.value || 0),
          likes: Number(qs('[data-field="likes"]', pane)?.value || 0),
          comments: Number(qs('[data-field="comments"]', pane)?.value || 0),
          shares: Number(qs('[data-field="shares"]', pane)?.value || 0),
        };
      });

    const save = async () => {
      const fd = new FormData(qs("#editor-form"));
      let scheduled = fd.get("scheduled_at");
      if (scheduled) scheduled = new Date(scheduled).toISOString();
      else scheduled = "";
      await api(`/api/content/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          title: fd.get("title"),
          body: fd.get("body"),
          notes: fd.get("notes"),
          category_id: fd.get("category_id"),
          campaign_id: fd.get("campaign_id") || null,
          scheduled_at: scheduled,
          channels: collectChannels(),
          extra_tags: fd.get("extra_tags") || "",
        }),
      });
      await loadLookups();
    };

    qs("#editor-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = qs("#ed-msg");
      msg.textContent = "Saving…";
      try {
        await save();
        msg.textContent = "Saved.";
        renderEditor(id);
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    actions.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-status]");
      if (!btn) return;
      const msg = qs("#ed-msg");
      msg.textContent = "Updating…";
      try {
        await save();
        const payload = { status: btn.dataset.status };
        const scheduled = qs("#ed-schedule").value;
        if (scheduled) payload.scheduled_at = new Date(scheduled).toISOString();
        await api(`/api/content/${id}/status`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        msg.textContent = "Updated.";
        renderEditor(id);
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    qs("#ed-autopublish")?.addEventListener("click", async () => {
      const msg = qs("#ed-msg");
      msg.textContent = "Auto-publishing to connected channels…";
      try {
        await save();
        const res = await api(`/api/content/${id}/publish`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        const lines = (res.results || []).map(
          (r) =>
            `${r.channel}: ${
              r.ok ? "OK" : r.skipped ? `skipped — ${r.error}` : r.error || "failed"
            }`
        );
        msg.textContent = lines.join(" · ") || "Done.";
        renderEditor(id);
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    qs("#ed-sync")?.addEventListener("click", async () => {
      const msg = qs("#ed-msg");
      msg.textContent = "Syncing live analytics…";
      try {
        const res = await api(`/api/content/${id}/sync-analytics`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        const lines = (res.results || []).map(
          (r) =>
            `${r.channel}: ${
              r.ok
                ? `reach ${r.metrics.reach} / likes ${r.metrics.likes}`
                : r.skipped
                  ? "no post id"
                  : r.error || "failed"
            }`
        );
        msg.textContent = lines.join(" · ") || "Done.";
        renderEditor(id);
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });
  }

  async function renderCalendar() {
    const root = qs("#view-calendar");
    if (!state.calMonth) {
      const now = new Date();
      state.calMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    }
    root.innerHTML = `
      <div class="help-box">
        <strong>Master calendar:</strong> only approved / scheduled / published items appear.
        Set <em>Schedule at</em> in the content editor, then click <em>Schedule</em> or <em>Mark published</em>.
      </div>
      <div class="filters">
        <select id="cal-category"></select>
        <select id="cal-campaign"></select>
        <span class="spacer"></span>
        <button class="btn secondary" id="cal-prev" type="button">←</button>
        <button class="btn secondary" id="cal-today" type="button">Today</button>
        <button class="btn secondary" id="cal-next" type="button">→</button>
      </div>
      <div class="panel">
        <div class="cal-head">
          <h3 id="cal-title"></h3>
          <span class="muted">Click an item to open</span>
        </div>
        <div class="cal-grid" id="cal-grid"></div>
      </div>
    `;
    fillCategorySelect(qs("#cal-category"));
    fillCampaignSelect(qs("#cal-campaign"));

    const dayKey = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    };

    const load = async () => {
      const params = new URLSearchParams();
      if (qs("#cal-category").value) params.set("category_id", qs("#cal-category").value);
      if (qs("#cal-campaign").value) params.set("campaign_id", qs("#cal-campaign").value);
      const data = await api(`/api/calendar?${params}`);
      const byDay = {};
      data.items.forEach((c) => {
        const when = c.scheduled_at || c.published_at;
        if (!when) return;
        const key = dayKey(new Date(when));
        (byDay[key] ||= []).push(c);
      });

      const month = state.calMonth;
      qs("#cal-title").textContent = month.toLocaleString(undefined, {
        month: "long",
        year: "numeric",
      });

      const start = new Date(month.getFullYear(), month.getMonth(), 1);
      const startPad = (start.getDay() + 6) % 7; // Monday-first
      const gridStart = new Date(start);
      gridStart.setDate(start.getDate() - startPad);

      const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        .map((d) => `<div class="cal-dow">${d}</div>`)
        .join("");
      const cells = [];
      const today = dayKey(new Date());
      for (let i = 0; i < 42; i++) {
        const d = new Date(gridStart);
        d.setDate(gridStart.getDate() + i);
        const key = dayKey(d);
        const inMonth = d.getMonth() === month.getMonth();
        const items = byDay[key] || [];
        const shown = items.slice(0, 3);
        const more = items.length - shown.length;
        cells.push(`
          <div class="cal-cell ${inMonth ? "" : "muted-day"} ${key === today ? "today" : ""}">
            <div class="cal-daynum">${d.getDate()}</div>
            ${shown
              .map((c) => {
                const slug = (c.category_name || "").toLowerCase().replace(/\s+/g, "");
                const time = new Date(c.scheduled_at || c.published_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                });
                return `<a class="cal-event ${escapeHtml(slug)}" href="#editor/${c.id}" title="${escapeHtml(
                  c.title
                )}">${escapeHtml(time)} ${escapeHtml(c.title)}</a>`;
              })
              .join("")}
            ${more > 0 ? `<div class="cal-more">+${more} more</div>` : ""}
          </div>`);
      }
      qs("#cal-grid").innerHTML = dows + cells.join("");
    };

    qs("#cal-prev").onclick = () => {
      state.calMonth = new Date(state.calMonth.getFullYear(), state.calMonth.getMonth() - 1, 1);
      load();
    };
    qs("#cal-next").onclick = () => {
      state.calMonth = new Date(state.calMonth.getFullYear(), state.calMonth.getMonth() + 1, 1);
      load();
    };
    qs("#cal-today").onclick = () => {
      const now = new Date();
      state.calMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      load();
    };
    qs("#cal-category").onchange = () => {
      fillCampaignSelect(qs("#cal-campaign"), qs("#cal-category").value);
      load();
    };
    qs("#cal-campaign").onchange = load;
    await load();
  }

  async function renderCampaigns() {
    const root = qs("#view-campaigns");
    const canManage = ["admin", "approver", "editor"].includes(state.user.role);
    root.innerHTML = `
      <div class="help-box">
        <strong>How to add a campaign</strong>
        <ol>
          <li>Sign in as <em>admin</em>, <em>approver</em>, or <em>editor</em></li>
          <li>Open <em>Campaigns</em> in the left menu</li>
          <li>Fill <em>Add campaign</em> on the right → Create campaign</li>
          <li>When submitting content, choose that campaign (optional) under its category</li>
        </ol>
        Example: Category <strong>Membership</strong> → Campaign <strong>Membership Drive 2026</strong> → Hashtag <strong>#MembershipDrive2026</strong>
      </div>
      <div class="grid two">
        <div class="panel">
          <h3>All campaigns</h3>
          <table>
            <thead><tr><th>Campaign</th><th>Category</th><th>Status</th><th>Hashtag</th></tr></thead>
            <tbody>
              ${state.campaigns
                .map(
                  (c) => `<tr>
                    <td><strong>${escapeHtml(c.name)}</strong><div class="muted">${escapeHtml(c.owner || "")}</div></td>
                    <td>${escapeHtml(c.category_name)}</td>
                    <td>${badge(c.status)}</td>
                    <td><span class="tag">${escapeHtml(c.hashtag || "—")}</span></td>
                  </tr>`
                )
                .join("")}
            </tbody>
          </table>
          <h3 style="margin-top:1.4rem">Categories</h3>
          <table>
            <thead><tr><th>Name</th><th>Hashtag</th></tr></thead>
            <tbody>
              ${state.categories
                .map(
                  (c) => `<tr><td>${escapeHtml(c.name)}</td><td><span class="tag">${escapeHtml(c.hashtag)}</span></td></tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
        <div class="panel">
          ${
            canManage
              ? `<h3>Add campaign</h3>
            <form id="camp-form" class="form-grid">
              <label>Campaign name<input name="name" required placeholder="Membership Drive 2026"></label>
              <label>Category<select name="category_id" id="camp-cat" required></select></label>
              <label>Owner / committee<input name="owner" placeholder="Membership Team"></label>
              <div class="form-grid two">
                <label>Status
                  <select name="status">
                    <option value="planned">planned</option>
                    <option value="active" selected>active</option>
                    <option value="ongoing">ongoing</option>
                    <option value="completed">completed</option>
                  </select>
                </label>
                <label>Campaign hashtag<input name="hashtag" placeholder="#MembershipDrive2026"></label>
              </div>
              <div class="form-grid two">
                <label>Start<input type="date" name="start_date"></label>
                <label>End<input type="date" name="end_date"></label>
              </div>
              <label>Landing page<input name="landing_page" placeholder="https://..."></label>
              <label>Description<textarea name="description" placeholder="Objective of this communication initiative"></textarea></label>
              <button class="btn" type="submit">Create campaign</button>
              <p id="camp-msg" class="muted"></p>
            </form>`
              : `<p class="muted">Your role cannot create campaigns. Ask admin/editor/approver.</p>`
          }
        </div>
      </div>
    `;
    if (canManage) {
      fillCategorySelect(qs("#camp-cat"), false);
      qs("#camp-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const msg = qs("#camp-msg");
        msg.textContent = "Creating…";
        try {
          await api("/api/campaigns", {
            method: "POST",
            body: JSON.stringify(Object.fromEntries(fd.entries())),
          });
          await loadLookups();
          msg.textContent = "Campaign created — it now appears in Submit and filters.";
          renderCampaigns();
        } catch (ex) {
          msg.textContent = ex.message;
        }
      });
    }
  }

  async function renderMedia() {
    const root = qs("#view-media");
    root.innerHTML = `
      <div class="panel" style="margin-bottom:1rem">
        <form id="media-form" class="form-grid two">
          <label>File<input type="file" name="file" required accept="image/*,video/*"></label>
          <label>Caption<input name="caption" placeholder="Optional caption"></label>
          <label>Category<select name="category_id" id="media-cat"></select></label>
          <label>Campaign<select name="campaign_id" id="media-camp"></select></label>
          <div class="row-actions"><button class="btn" type="submit">Upload</button></div>
          <p id="media-msg" class="muted"></p>
        </form>
      </div>
      <div class="filters">
        <select id="media-f-cat"></select>
        <select id="media-f-camp"></select>
        <button class="btn secondary" type="button" id="media-refresh">Refresh</button>
      </div>
      <div class="media-grid" id="media-grid"></div>
    `;
    fillCategorySelect(qs("#media-cat"));
    fillCampaignSelect(qs("#media-camp"));
    fillCategorySelect(qs("#media-f-cat"));
    fillCampaignSelect(qs("#media-f-camp"));
    qs("#media-cat").onchange = (e) => fillCampaignSelect(qs("#media-camp"), e.target.value);
    qs("#media-f-cat").onchange = (e) => {
      fillCampaignSelect(qs("#media-f-camp"), e.target.value);
      load();
    };

    const load = async () => {
      const params = new URLSearchParams();
      if (qs("#media-f-cat").value) params.set("category_id", qs("#media-f-cat").value);
      if (qs("#media-f-camp").value) params.set("campaign_id", qs("#media-f-camp").value);
      const data = await api(`/api/media?${params}`);
      qs("#media-grid").innerHTML =
        data.items
          .map((m) => {
            const isImg = (m.mime || "").startsWith("image/");
            return `<div class="media-card">
              ${isImg ? `<img src="${m.path}" alt="">` : `<div class="meta">File</div>`}
              <div class="meta">
                <strong>${escapeHtml(m.original_name)}</strong>
                <div class="muted">${escapeHtml(m.category_name || "—")}${m.campaign_name ? " · " + escapeHtml(m.campaign_name) : ""}</div>
                <div>${escapeHtml(m.caption || "")}</div>
              </div>
            </div>`;
          })
          .join("") || `<p class="muted">No media yet.</p>`;
    };

    qs("#media-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = qs("#media-msg");
      msg.textContent = "Uploading…";
      try {
        await api("/api/media", { method: "POST", body: fd });
        msg.textContent = "Uploaded.";
        e.target.reset();
        fillCategorySelect(qs("#media-cat"));
        fillCampaignSelect(qs("#media-camp"));
        load();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });
    qs("#media-refresh").onclick = load;
    qs("#media-f-camp").onchange = load;
    await load();
  }

  async function renderEngagement() {
    const root = qs("#view-engagement");
    root.innerHTML = `
      <div class="grid two">
        <div class="panel">
          <h3>Log interaction</h3>
          <form id="eng-form" class="form-grid">
            <label>Platform
              <select name="platform" required>
                ${CHANNELS.map((c) => `<option value="${c}">${c}</option>`).join("")}
                <option value="other">other</option>
              </select>
            </label>
            <label>Note / comment summary<textarea name="note" required></textarea></label>
            <label>Link<input name="link" placeholder="https://..."></label>
            <label>Status
              <select name="status">
                <option value="open">open</option>
                <option value="replied">replied</option>
                <option value="escalate">escalate</option>
              </select>
            </label>
            <label>Escalate to (name/role)<input name="escalated_to" placeholder="EC Secretary / Project Lead"></label>
            <button class="btn" type="submit">Save</button>
            <p id="eng-msg" class="muted"></p>
          </form>
        </div>
        <div class="panel">
          <div class="filters">
            <select id="eng-filter">
              <option value="">All</option>
              <option value="open">open</option>
              <option value="replied">replied</option>
              <option value="escalate">escalate</option>
            </select>
            <button class="btn secondary" type="button" id="eng-refresh">Refresh</button>
          </div>
          <div id="eng-list"></div>
        </div>
      </div>
    `;

    const load = async () => {
      const st = qs("#eng-filter").value;
      const data = await api(`/api/engagement${st ? `?status=${st}` : ""}`);
      qs("#eng-list").innerHTML = `
        <table>
          <thead><tr><th>Platform</th><th>Note</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${data.items
              .map(
                (e) => `<tr>
                  <td>${escapeHtml(e.platform)}</td>
                  <td>
                    ${escapeHtml(e.note)}
                    <div class="muted">${escapeHtml(e.created_by_name || "")}${e.escalated_to ? " → " + escapeHtml(e.escalated_to) : ""}</div>
                  </td>
                  <td>${badge(e.status)}</td>
                  <td class="row-actions">
                    <button class="btn small secondary" data-id="${e.id}" data-set="replied">Replied</button>
                    <button class="btn small danger" data-id="${e.id}" data-set="escalate">Escalate</button>
                  </td>
                </tr>`
              )
              .join("") || `<tr><td colspan="4" class="muted">No logs</td></tr>`}
          </tbody>
        </table>`;
      qsa("#eng-list [data-set]").forEach((btn) => {
        btn.onclick = async () => {
          await api(`/api/engagement/${btn.dataset.id}`, {
            method: "PUT",
            body: JSON.stringify({ status: btn.dataset.set }),
          });
          load();
        };
      });
    };

    qs("#eng-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = qs("#eng-msg");
      try {
        await api("/api/engagement", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(fd.entries())),
        });
        msg.textContent = "Logged.";
        e.target.reset();
        load();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });
    qs("#eng-refresh").onclick = load;
    qs("#eng-filter").onchange = load;
    await load();
  }

  async function loadDiagramsList() {
    try {
      return (await api("/api/diagrams")).diagrams || [];
    } catch {
      const res = await fetch("/data/process_diagrams.json");
      const data = await res.json();
      return data.diagrams || [];
    }
  }

  async function renderDiagrams() {
    const root = qs("#view-diagrams");
    const canEdit = ["admin", "editor", "approver"].includes(state.user.role);
    let diagrams = await loadDiagramsList();
    let currentId = sessionStorage.getItem("hub_diagram_id") || diagrams[0]?.id || "";
    if (currentId && !diagrams.find((d) => d.id === currentId)) {
      currentId = diagrams[0]?.id || "";
    }

    const tones = [
      { id: "navy", label: "Navy" },
      { id: "crimson", label: "Crimson" },
      { id: "gold", label: "Gold" },
      { id: "green", label: "Green" },
      { id: "blue", label: "Blue" },
    ];

    const emptyDiagram = () => ({
      id: "",
      title: "New process diagram",
      subtitle: "",
      direction: "vertical",
      sections: [
        {
          id: `s-${Date.now()}`,
          title: "Section 1",
          tone: "navy",
          points: ["Process point 1"],
        },
      ],
    });

    let draft = currentId
      ? JSON.parse(JSON.stringify(diagrams.find((d) => d.id === currentId)))
      : emptyDiagram();

    const render = () => {
      root.innerHTML = `
        <div class="help-box">
          <strong>Draw process diagrams in the Hub</strong>
          Add sections (stages) and process points (steps). Useful for operating models,
          approval flows, campaign journeys. Export PNG for decks / WhatsApp.
        </div>
        <div class="grid two">
          <div class="panel">
            <div class="panel-head">
              <h3>Editor</h3>
              <select id="diag-pick">
                <option value="">＋ New diagram</option>
                ${diagrams
                  .map(
                    (d) =>
                      `<option value="${escapeHtml(d.id)}" ${
                        d.id === draft.id ? "selected" : ""
                      }>${escapeHtml(d.title)}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="form-grid">
              <label>Title<input id="diag-title" value="${escapeHtml(draft.title || "")}" ${
                canEdit ? "" : "readonly"
              }></label>
              <label>Subtitle<input id="diag-sub" value="${escapeHtml(draft.subtitle || "")}" ${
                canEdit ? "" : "readonly"
              }></label>
              <label>Layout
                <select id="diag-dir" ${canEdit ? "" : "disabled"}>
                  <option value="vertical" ${
                    draft.direction !== "horizontal" ? "selected" : ""
                  }>Vertical flow</option>
                  <option value="horizontal" ${
                    draft.direction === "horizontal" ? "selected" : ""
                  }>Horizontal flow</option>
                </select>
              </label>
            </div>
            <div id="diag-sections" style="margin-top:0.9rem"></div>
            ${
              canEdit
                ? `<div class="row-actions" style="margin-top:0.8rem">
              <button class="btn secondary" type="button" id="diag-add-section">＋ Add section</button>
              <button class="btn" type="button" id="diag-save">Save diagram</button>
              ${
                draft.id
                  ? `<button class="btn danger" type="button" id="diag-delete">Delete</button>`
                  : ""
              }
            </div>`
                : `<p class="muted">View only — ask editor/admin to edit.</p>`
            }
            <p id="diag-msg" class="muted"></p>
          </div>
          <div class="panel">
            <div class="panel-head">
              <h3>Preview</h3>
              <button class="btn small secondary" type="button" id="diag-png">Download PNG</button>
            </div>
            <div class="flow-preview ${
              draft.direction === "horizontal" ? "horizontal" : "vertical"
            }" id="diag-preview"></div>
            <canvas id="diag-canvas" class="hidden" width="1400" height="900"></canvas>
          </div>
        </div>
      `;

      const secRoot = qs("#diag-sections");
      secRoot.innerHTML = (draft.sections || [])
        .map(
          (sec, si) => `
        <div class="diag-section" data-si="${si}">
          <div class="diag-section-head">
            <strong>Section ${si + 1}</strong>
            ${
              canEdit
                ? `<div class="row-actions">
              <button class="btn small secondary" type="button" data-up="${si}">↑</button>
              <button class="btn small secondary" type="button" data-down="${si}">↓</button>
              <button class="btn small danger" type="button" data-rm-sec="${si}">Remove</button>
            </div>`
                : ""
            }
          </div>
          <div class="form-grid two">
            <label>Section title
              <input data-sec-title="${si}" value="${escapeHtml(sec.title || "")}" ${
                canEdit ? "" : "readonly"
              }>
            </label>
            <label>Color
              <select data-sec-tone="${si}" ${canEdit ? "" : "disabled"}>
                ${tones
                  .map(
                    (t) =>
                      `<option value="${t.id}" ${
                        sec.tone === t.id ? "selected" : ""
                      }>${t.label}</option>`
                  )
                  .join("")}
              </select>
            </label>
          </div>
          <label style="margin-top:0.55rem">Process points <span class="muted">(one per line)</span>
            <textarea data-sec-points="${si}" rows="4" ${canEdit ? "" : "readonly"}>${escapeHtml(
              (sec.points || []).join("\n")
            )}</textarea>
          </label>
        </div>`
        )
        .join("") || `<p class="muted">No sections yet.</p>`;

      paintPreview();
      bindEditor();
    };

    const readDraftFromForm = () => {
      draft.title = qs("#diag-title")?.value || draft.title;
      draft.subtitle = qs("#diag-sub")?.value || "";
      draft.direction = qs("#diag-dir")?.value || "vertical";
      draft.sections = (draft.sections || []).map((sec, si) => ({
        ...sec,
        title: qs(`[data-sec-title="${si}"]`)?.value || sec.title,
        tone: qs(`[data-sec-tone="${si}"]`)?.value || sec.tone || "navy",
        points: (qs(`[data-sec-points="${si}"]`)?.value || "")
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
      }));
    };

    const paintPreview = () => {
      const preview = qs("#diag-preview");
      if (!preview) return;
      preview.className = `flow-preview ${
        draft.direction === "horizontal" ? "horizontal" : "vertical"
      }`;
      preview.innerHTML = `
        <div class="flow-title">
          <h3>${escapeHtml(draft.title || "Untitled")}</h3>
          ${draft.subtitle ? `<p>${escapeHtml(draft.subtitle)}</p>` : ""}
        </div>
        <div class="flow-track">
          ${(draft.sections || [])
            .map(
              (sec, i) => `
            <article class="flow-card tone-${escapeHtml(sec.tone || "navy")}">
              <div class="flow-step">Step ${i + 1}</div>
              <h4>${escapeHtml(sec.title || "Section")}</h4>
              <ul>${(sec.points || [])
                .map((p) => `<li>${escapeHtml(p)}</li>`)
                .join("")}</ul>
            </article>
            ${
              i < (draft.sections || []).length - 1
                ? `<div class="flow-arrow" aria-hidden="true">${
                    draft.direction === "horizontal" ? "→" : "↓"
                  }</div>`
                : ""
            }`
            )
            .join("")}
        </div>
      `;
    };

    const bindEditor = () => {
      qs("#diag-pick")?.addEventListener("change", (e) => {
        const id = e.target.value;
        if (!id) {
          draft = emptyDiagram();
          sessionStorage.removeItem("hub_diagram_id");
        } else {
          draft = JSON.parse(JSON.stringify(diagrams.find((d) => d.id === id)));
          sessionStorage.setItem("hub_diagram_id", id);
        }
        render();
      });

      ["diag-title", "diag-sub", "diag-dir"].forEach((id) => {
        qs(`#${id}`)?.addEventListener("input", () => {
          readDraftFromForm();
          paintPreview();
        });
        qs(`#${id}`)?.addEventListener("change", () => {
          readDraftFromForm();
          paintPreview();
        });
      });

      qsa("[data-sec-title], [data-sec-tone], [data-sec-points]").forEach((el) => {
        el.addEventListener("input", () => {
          readDraftFromForm();
          paintPreview();
        });
        el.addEventListener("change", () => {
          readDraftFromForm();
          paintPreview();
        });
      });

      qs("#diag-add-section")?.addEventListener("click", () => {
        readDraftFromForm();
        draft.sections.push({
          id: `s-${Date.now()}`,
          title: `Section ${(draft.sections.length || 0) + 1}`,
          tone: "navy",
          points: ["New process point"],
        });
        render();
      });

      qsa("[data-rm-sec]").forEach((btn) => {
        btn.onclick = () => {
          readDraftFromForm();
          const i = Number(btn.dataset.rmSec);
          draft.sections.splice(i, 1);
          render();
        };
      });
      qsa("[data-up]").forEach((btn) => {
        btn.onclick = () => {
          readDraftFromForm();
          const i = Number(btn.dataset.up);
          if (i <= 0) return;
          const tmp = draft.sections[i - 1];
          draft.sections[i - 1] = draft.sections[i];
          draft.sections[i] = tmp;
          render();
        };
      });
      qsa("[data-down]").forEach((btn) => {
        btn.onclick = () => {
          readDraftFromForm();
          const i = Number(btn.dataset.down);
          if (i >= draft.sections.length - 1) return;
          const tmp = draft.sections[i + 1];
          draft.sections[i + 1] = draft.sections[i];
          draft.sections[i] = tmp;
          render();
        };
      });

      qs("#diag-save")?.addEventListener("click", async () => {
        readDraftFromForm();
        const msg = qs("#diag-msg");
        msg.textContent = "Saving…";
        try {
          const payload = {
            title: draft.title,
            subtitle: draft.subtitle,
            direction: draft.direction,
            sections: draft.sections,
          };
          let res;
          if (draft.id) {
            res = await api(`/api/diagrams/${draft.id}`, {
              method: "PUT",
              body: JSON.stringify(payload),
            });
          } else {
            res = await api("/api/diagrams", {
              method: "POST",
              body: JSON.stringify(payload),
            });
          }
          diagrams = res.diagrams || (await loadDiagramsList());
          draft = res.diagram;
          sessionStorage.setItem("hub_diagram_id", draft.id);
          msg.textContent = "Saved.";
          render();
        } catch (ex) {
          msg.textContent = ex.message;
        }
      });

      qs("#diag-delete")?.addEventListener("click", async () => {
        if (!draft.id || !confirm(`Delete “${draft.title}”?`)) return;
        try {
          const res = await api(`/api/diagrams/${draft.id}`, { method: "DELETE" });
          diagrams = res.diagrams || [];
          sessionStorage.removeItem("hub_diagram_id");
          draft = diagrams[0]
            ? JSON.parse(JSON.stringify(diagrams[0]))
            : emptyDiagram();
          render();
        } catch (ex) {
          qs("#diag-msg").textContent = ex.message;
        }
      });

      qs("#diag-png")?.addEventListener("click", () => {
        readDraftFromForm();
        exportDiagramPng(draft);
      });
    };

    const exportDiagramPng = (diag) => {
      const canvas = qs("#diag-canvas");
      const ctx = canvas.getContext("2d");
      const sections = diag.sections || [];
      const horizontal = diag.direction === "horizontal";
      const cardW = horizontal ? 280 : 520;
      const cardH = horizontal ? 320 : 160;
      const gap = 36;
      const pad = 48;
      const width = horizontal
        ? pad * 2 + sections.length * cardW + Math.max(0, sections.length - 1) * gap
        : 720;
      const height = horizontal
        ? 520
        : pad * 2 + 80 + sections.length * (cardH + gap);
      canvas.width = Math.max(720, width);
      canvas.height = Math.max(480, height);

      const tonesMap = {
        navy: "#0A1F38",
        crimson: "#B42336",
        gold: "#D4AF63",
        green: "#067647",
        blue: "#175CD3",
      };

      ctx.fillStyle = "#F2F4F7";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0A1F38";
      ctx.font = "600 34px Newsreader, Georgia, serif";
      ctx.fillText(diag.title || "Process diagram", pad, pad + 10);
      ctx.fillStyle = "#667085";
      ctx.font = "500 16px Manrope, sans-serif";
      if (diag.subtitle) ctx.fillText(diag.subtitle, pad, pad + 38);

      sections.forEach((sec, i) => {
        const x = horizontal ? pad + i * (cardW + gap) : pad;
        const y = horizontal ? pad + 70 : pad + 70 + i * (cardH + gap);
        const accent = tonesMap[sec.tone] || tonesMap.navy;
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = "#E4E7EC";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.rect(x, y, cardW, cardH);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = accent;
        ctx.fillRect(x, y, 8, cardH);
        ctx.fillStyle = accent;
        ctx.font = "700 12px Manrope, sans-serif";
        ctx.fillText(`STEP ${i + 1}`, x + 24, y + 28);
        ctx.fillStyle = "#101828";
        ctx.font = "600 20px Manrope, sans-serif";
        ctx.fillText((sec.title || "Section").slice(0, 40), x + 24, y + 56);
        ctx.fillStyle = "#667085";
        ctx.font = "500 14px Manrope, sans-serif";
        (sec.points || []).slice(0, 5).forEach((p, pi) => {
          const line = `• ${p}`.slice(0, 48);
          ctx.fillText(line, x + 24, y + 88 + pi * 20);
        });
        if (i < sections.length - 1) {
          ctx.fillStyle = "#98A2B3";
          ctx.font = "700 28px Manrope, sans-serif";
          if (horizontal) {
            ctx.fillText("→", x + cardW + 6, y + cardH / 2 + 8);
          } else {
            ctx.fillText("↓", x + cardW / 2 - 8, y + cardH + 28);
          }
        }
      });

      const a = document.createElement("a");
      a.download = `bcoba-diagram-${(diag.title || "process")
        .toLowerCase()
        .replace(/\s+/g, "-")}.png`;
      a.href = canvas.toDataURL("image/png");
      a.click();
    };

    render();
  }

  async function renderBrand() {
    const root = qs("#view-brand");
    let brand;
    try {
      brand = (await api("/api/brand")).brand;
    } catch {
      const res = await fetch("/data/brand_guidelines.json");
      brand = await res.json();
    }
    const swatch = (c) =>
      `<div class="swatch"><span style="background:${c.hex}"></span><div><strong>${escapeHtml(
        c.name
      )}</strong><div class="muted">${escapeHtml(c.hex)}</div></div></div>`;
    root.innerHTML = `
      <div class="help-box">
        <strong>${escapeHtml(brand.title)}</strong> · v${escapeHtml(brand.version)}
        <p style="margin:0.4rem 0 0">${escapeHtml(brand.summary)}</p>
      </div>
      <div class="grid two">
        <div class="panel">
          <h3>Colors</h3>
          <div class="swatch-grid">
            ${(brand.colors.primary || []).map(swatch).join("")}
            ${(brand.colors.secondary || []).map(swatch).join("")}
          </div>
          <h3 style="margin-top:1.2rem">Fonts</h3>
          <p><strong>Display:</strong> ${escapeHtml(brand.fonts.display)}</p>
          <p><strong>Body:</strong> ${escapeHtml(brand.fonts.body)}</p>
          <p class="muted">${escapeHtml(brand.fonts.note)}</p>
        </div>
        <div class="panel">
          <h3>Logo / crest</h3>
          <ul class="guide-list">${brand.logo.rules.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
          <h3>Tone of voice</h3>
          <ul class="guide-list">${brand.tone.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
        </div>
      </div>
      <div class="grid two" style="margin-top:1rem">
        <div class="panel">
          <h3>Photography</h3>
          <ul class="guide-list">${brand.photography.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
          <h3>Hashtags</h3>
          <div class="tags" style="margin-bottom:0.6rem">
            ${(brand.hashtags.master || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}
          </div>
          <ul class="guide-list">${brand.hashtags.rules.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
        </div>
        <div class="panel">
          <h3>Approval</h3>
          <ul class="guide-list">${brand.approval.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
          <h3>Campaign themes</h3>
          <p>${escapeHtml(brand.campaign_themes)}</p>
          <p class="muted" style="margin-top:1rem">Edit file: <code>data/brand_guidelines.json</code></p>
        </div>
      </div>
    `;
  }

  async function loadTemplatesList() {
    try {
      return (await api("/api/templates")).templates || [];
    } catch {
      const res = await fetch("/data/post_templates.json");
      const data = await res.json();
      return data.templates || [];
    }
  }

  async function renderTemplates() {
    const root = qs("#view-templates");
    let TEMPLATES = await loadTemplatesList();
    const canManageTpl = ["admin", "editor", "approver"].includes(state.user.role);
    const SIZES = {
      ig_square: { w: 1080, h: 1080, label: "Instagram / WhatsApp (1:1)" },
      fb_post: { w: 1200, h: 630, label: "Facebook / LinkedIn (1.91:1)" },
      story: { w: 1080, h: 1920, label: "Story / Status (9:16)" },
    };

    const optionHtml = () =>
      TEMPLATES.map(
        (t) =>
          `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}${
            t.builtin ? "" : " ★"
          } — ${escapeHtml(t.hint || "")}</option>`
      ).join("");

    root.innerHTML = `
      <div class="help-box">
        <strong>Custom templates: yes.</strong>
        Add via the form below (admin/editor), or edit <code>data/post_templates.json</code>.
        ★ = custom. Built-in templates cannot be deleted.
      </div>
      <div class="grid two">
        <div class="panel">
          <form id="tpl-form" class="form-grid">
            <label>Template
              <select name="template" id="tpl-type">
                ${optionHtml()}
              </select>
            </label>
            <label>Size
              <select name="size" id="tpl-size">
                ${Object.entries(SIZES)
                  .map(
                    ([k, v]) =>
                      `<option value="${k}">${escapeHtml(v.label)} (${v.w}×${v.h})</option>`
                  )
                  .join("")}
              </select>
            </label>
            <label>Headline<input name="headline" id="tpl-headline" value="Restoring the Pride" maxlength="80"></label>
            <label>Supporting line<textarea name="body" id="tpl-body" maxlength="220">Alumni are rebuilding the Main Hall — brick by brick, generation by generation.</textarea></label>
            <label>Footer / CTA<input name="footer" id="tpl-footer" value="BCOBA · Official" maxlength="60"></label>
            <label>Hashtags<input name="tags" id="tpl-tags" value="#BCOBA #BandaranayakeCollege #RestoringThePride"></label>
            <label>Optional photo<input type="file" id="tpl-photo" accept="image/*"></label>
            <div class="form-grid two">
              <label>Category<select id="tpl-category"></select></label>
              <label>Campaign<select id="tpl-campaign"></select></label>
            </div>
            <div class="row-actions">
              <button class="btn" type="button" id="tpl-download">Download PNG</button>
              <button class="btn secondary" type="button" id="tpl-queue">Send caption to queue</button>
              <button class="btn secondary" type="button" id="tpl-copy">Copy caption</button>
              ${
                canManageTpl
                  ? `<button class="btn secondary" type="button" id="tpl-delete">Delete custom</button>`
                  : ""
              }
            </div>
            <p id="tpl-msg" class="muted"></p>
          </form>
          ${
            canManageTpl
              ? `<div style="margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--line)">
            <h3>Add custom template</h3>
            <form id="tpl-add-form" class="form-grid">
              <label>Name<input name="name" required placeholder="Sports result"></label>
              <label>Short hint<input name="hint" placeholder="Match wins, scores"></label>
              <label>Accent color<input name="accent" type="color" value="#0A1F38"></label>
              <label>Default headline<input name="headline" placeholder="Victory for the Lions"></label>
              <label>Default body<textarea name="body" placeholder="Short supporting line..."></textarea></label>
              <label>Default footer<input name="footer" value="BCOBA · Sports"></label>
              <label>Default #tags<input name="tags" value="#BCOBA #BandaranayakeCollege #BCOBASports"></label>
              <button class="btn" type="submit">Save custom template</button>
              <p id="tpl-add-msg" class="muted"></p>
            </form>
          </div>`
              : `<p class="muted" style="margin-top:1rem">Ask an admin/editor to add custom templates.</p>`
          }
        </div>
        <div class="panel">
          <div class="panel-head">
            <h3>Preview</h3>
            <span class="muted" id="tpl-dim"></span>
          </div>
          <div class="tpl-preview-wrap">
            <canvas id="tpl-canvas" width="1080" height="1080"></canvas>
          </div>
        </div>
      </div>
    `;

    fillCategorySelect(qs("#tpl-category"));
    fillCampaignSelect(qs("#tpl-campaign"));
    qs("#tpl-category").onchange = (e) =>
      fillCampaignSelect(qs("#tpl-campaign"), e.target.value);

    let photoImg = null;
    const canvas = qs("#tpl-canvas");
    const ctx = canvas.getContext("2d");

    function applyDefaults(tpl) {
      const d = tpl?.defaults || {};
      if (d.headline) qs("#tpl-headline").value = d.headline;
      if (d.body) qs("#tpl-body").value = d.body;
      if (d.footer) qs("#tpl-footer").value = d.footer;
      if (d.tags) qs("#tpl-tags").value = d.tags;
    }
    applyDefaults(TEMPLATES[0]);

    function wrapText(context, text, x, y, maxWidth, lineHeight, maxLines) {
      const words = (text || "").split(/\s+/);
      let line = "";
      let lines = 0;
      for (let n = 0; n < words.length; n++) {
        const test = line ? `${line} ${words[n]}` : words[n];
        if (context.measureText(test).width > maxWidth && line) {
          context.fillText(line, x, y);
          line = words[n];
          y += lineHeight;
          lines += 1;
          if (lines >= maxLines - 1) {
            let rest = words.slice(n).join(" ");
            while (context.measureText(rest + "…").width > maxWidth && rest.length > 3) {
              rest = rest.slice(0, -1);
            }
            context.fillText(rest + (rest !== words.slice(n).join(" ") ? "…" : ""), x, y);
            return;
          }
        } else {
          line = test;
        }
      }
      if (line) context.fillText(line, x, y);
    }

    function draw() {
      const tpl = TEMPLATES.find((t) => t.id === qs("#tpl-type").value) || TEMPLATES[0];
      const size = SIZES[qs("#tpl-size").value] || SIZES.ig_square;
      canvas.width = size.w;
      canvas.height = size.h;
      qs("#tpl-dim").textContent = `${size.w}×${size.h}`;

      const w = size.w;
      const h = size.h;
      const pad = Math.round(w * 0.07);

      // Background
      const g = ctx.createLinearGradient(0, 0, w, h);
      g.addColorStop(0, "#0A1F38");
      g.addColorStop(0.55, "#122C4D");
      g.addColorStop(1, tpl.accent);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);

      // Optional photo panel
      if (photoImg) {
        const ph = Math.round(h * (size.h > size.w * 1.2 ? 0.42 : 0.38));
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, w, ph);
        ctx.clip();
        const scale = Math.max(w / photoImg.width, ph / photoImg.height);
        const pw = photoImg.width * scale;
        const pH = photoImg.height * scale;
        ctx.drawImage(photoImg, (w - pw) / 2, (ph - pH) / 2, pw, pH);
        ctx.restore();
        ctx.fillStyle = "rgba(10,31,56,0.35)";
        ctx.fillRect(0, 0, w, ph);
      }

      // Brand chip
      const chip = Math.round(w * 0.16);
      ctx.fillStyle = "#D4AF63";
      ctx.fillRect(pad, pad, chip, chip);
      ctx.fillStyle = "#1A1205";
      ctx.font = `800 ${Math.round(w * 0.055)}px Manrope, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("BC", pad + chip / 2, pad + chip / 2);

      ctx.textAlign = "left";
      ctx.fillStyle = "#D4AF63";
      ctx.font = `700 ${Math.round(w * 0.028)}px Manrope, sans-serif`;
      ctx.fillText("BCOBA DIGITAL", pad, pad + Math.round(w * 0.22));

      const headline = qs("#tpl-headline").value || "";
      const body = qs("#tpl-body").value || "";
      const footer = qs("#tpl-footer").value || "";
      const tags = qs("#tpl-tags").value || "";

      const textTop = photoImg ? Math.round(h * 0.48) : Math.round(h * 0.38);
      ctx.fillStyle = "#FFFFFF";
      ctx.font = `600 ${Math.round(w * 0.075)}px Newsreader, Georgia, serif`;
      wrapText(ctx, headline, pad, textTop, w - pad * 2, Math.round(w * 0.085), 3);

      ctx.fillStyle = "rgba(248,250,252,0.88)";
      ctx.font = `500 ${Math.round(w * 0.034)}px Manrope, sans-serif`;
      wrapText(
        ctx,
        body,
        pad,
        textTop + Math.round(w * 0.22),
        w - pad * 2,
        Math.round(w * 0.045),
        5
      );

      // Bottom bar
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.fillRect(0, h - Math.round(h * 0.14), w, Math.round(h * 0.14));
      ctx.fillStyle = "#D4AF63";
      ctx.fillRect(0, h - Math.round(h * 0.14), w, 6);
      ctx.fillStyle = "#FFFFFF";
      ctx.font = `700 ${Math.round(w * 0.028)}px Manrope, sans-serif`;
      ctx.fillText(footer, pad, h - Math.round(h * 0.07));
      ctx.fillStyle = "rgba(248,250,252,0.75)";
      ctx.font = `600 ${Math.round(w * 0.022)}px Manrope, sans-serif`;
      ctx.fillText(tags, pad, h - Math.round(h * 0.035));
    }

    const redraw = () => draw();
    qs("#tpl-type").addEventListener("change", () => {
      const tpl = TEMPLATES.find((t) => t.id === qs("#tpl-type").value);
      applyDefaults(tpl);
      redraw();
    });
    ["tpl-size", "tpl-headline", "tpl-body", "tpl-footer", "tpl-tags"].forEach((id) => {
      qs(`#${id}`).addEventListener("input", redraw);
      qs(`#${id}`).addEventListener("change", redraw);
    });

    qs("#tpl-add-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = qs("#tpl-add-msg");
      msg.textContent = "Saving…";
      try {
        const res = await api("/api/templates", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(fd.entries())),
        });
        TEMPLATES = res.templates;
        qs("#tpl-type").innerHTML = optionHtml();
        qs("#tpl-type").value = res.item.id;
        applyDefaults(res.item);
        redraw();
        msg.textContent = `Added: ${res.item.name}`;
        e.target.reset();
        qs('#tpl-add-form [name="accent"]').value = "#0A1F38";
        qs('#tpl-add-form [name="footer"]').value = "BCOBA · Official";
        qs('#tpl-add-form [name="tags"]').value = "#BCOBA #BandaranayakeCollege";
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    qs("#tpl-delete")?.addEventListener("click", async () => {
      const tid = qs("#tpl-type").value;
      const tpl = TEMPLATES.find((t) => t.id === tid);
      if (!tpl || tpl.builtin) {
        qs("#tpl-msg").textContent = "Built-in templates cannot be deleted.";
        return;
      }
      if (!confirm(`Delete custom template “${tpl.name}”?`)) return;
      try {
        const res = await api(`/api/templates/${tid}`, { method: "DELETE" });
        TEMPLATES = res.templates;
        qs("#tpl-type").innerHTML = optionHtml();
        applyDefaults(TEMPLATES[0]);
        redraw();
        qs("#tpl-msg").textContent = "Custom template deleted.";
      } catch (ex) {
        qs("#tpl-msg").textContent = ex.message;
      }
    });
    qs("#tpl-photo").addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) {
        photoImg = null;
        redraw();
        return;
      }
      const img = new Image();
      img.onload = () => {
        photoImg = img;
        redraw();
      };
      img.src = URL.createObjectURL(file);
    });

    qs("#tpl-download").onclick = () => {
      draw();
      const a = document.createElement("a");
      a.download = `bcoba-${qs("#tpl-type").value}-${Date.now()}.png`;
      a.href = canvas.toDataURL("image/png");
      a.click();
      qs("#tpl-msg").textContent = "PNG downloaded — upload it in Media or attach when publishing.";
    };

    qs("#tpl-copy").onclick = async () => {
      const caption = [
        qs("#tpl-headline").value,
        "",
        qs("#tpl-body").value,
        "",
        qs("#tpl-tags").value,
      ].join("\n");
      try {
        await navigator.clipboard.writeText(caption);
        qs("#tpl-msg").textContent = "Caption copied.";
      } catch {
        qs("#tpl-msg").textContent = "Copy failed — select text manually.";
      }
    };

    qs("#tpl-queue").onclick = async () => {
      const msg = qs("#tpl-msg");
      msg.textContent = "Creating queue item…";
      try {
        const data = await api("/api/content", {
          method: "POST",
          body: JSON.stringify({
            title: qs("#tpl-headline").value,
            body: `${qs("#tpl-body").value}\n\n${qs("#tpl-tags").value}`,
            notes: `Created from template: ${qs("#tpl-type").value}. Download PNG from Post templates and attach in Media.`,
            category_id: qs("#tpl-category").value,
            campaign_id: qs("#tpl-campaign").value || null,
            extra_tags: qs("#tpl-tags").value,
          }),
        });
        msg.textContent = "Sent to queue.";
        location.hash = `#editor/${data.id}`;
      } catch (ex) {
        msg.textContent = ex.message;
      }
    };

    draw();
  }

  async function renderConnections() {
    const root = qs("#view-connections");
    const canManage = ["admin", "editor", "approver", "channel_admin"].includes(
      state.user.role
    );
    const data = await api("/api/connections");
    const items = data.items || [];
    const fbSaved = items.find((c) => c.platform === "facebook" && c.active);
    root.innerHTML = `
      <div class="help-box">
        <strong>Semi-manual Facebook post</strong>
        Facebook does not allow username/password for posting. You paste a
        <em>Page Access Token</em> once, type the message, click <em>Post to Facebook</em>.
        Optional: tick “Save credentials” so next time you only type the message.
      </div>

      <div class="panel" style="margin-bottom:1rem">
        <h3>Quick post to Facebook</h3>
        <form id="quick-fb-form" class="form-grid">
          <div class="form-grid two">
            <label>Page ID
              <input name="account_id" ${fbSaved?.account_id ? "" : "required"} placeholder="e.g. 1234567890" value="${escapeHtml(
                fbSaved?.account_id || ""
              )}">
            </label>
            <label>Label (if saving)
              <input name="label" value="${escapeHtml(fbSaved?.label || "BCOBA Facebook")}" >
            </label>
          </div>
          <label>Access Token ${
            fbSaved?.has_token
              ? '<span class="muted">(saved token will be used if you leave this blank)</span>'
              : '<span class="muted">(user token OR Gamata Page token from me/accounts)</span>'
          }
            <textarea name="access_token" rows="3" ${fbSaved?.has_token ? "" : "required"} placeholder="${
              fbSaved?.has_token
                ? "Leave blank to use saved token, or paste a new one"
                : "Paste token from Graph API Explorer (user token is OK — Hub will resolve Page token)"
            }"></textarea>
          </label>
          <label>Message
            <textarea name="message" required rows="4" placeholder="BCOBA Hub test post — please ignore">BCOBA Hub test — please ignore</textarea>
          </label>
          <label>Optional link<input name="link" placeholder="https://..."></label>
          <label class="muted" style="display:flex;align-items:center;gap:0.5rem">
            <input type="checkbox" name="save_connection" value="1" style="width:auto" ${
              fbSaved ? "" : "checked"
            }>
            Save credentials for next time (encrypted)
          </label>
          <div class="row-actions">
            <button class="btn" type="submit">Post to Facebook now</button>
          </div>
          <p id="quick-fb-msg" class="muted" style="white-space:pre-wrap"></p>
          <p id="quick-fb-link"></p>
        </form>
        <div class="help-box" style="margin-top:0.9rem">
          <strong>Get token in 2 minutes</strong>
          <ol>
            <li>Open <a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noopener">Graph API Explorer</a></li>
            <li>Permissions: <code>pages_manage_posts</code>, <code>pages_show_list</code></li>
            <li>Generate token → run <code>me/accounts</code></li>
            <li>Copy Page <code>id</code> + Page <code>access_token</code> into the form above</li>
          </ol>
        </div>
      </div>

      <div class="grid two">
        <div class="panel">
          <h3>Saved connections</h3>
          <table>
            <thead><tr><th>Platform</th><th>Label / Account ID</th><th>Auto</th><th></th></tr></thead>
            <tbody>
              ${
                items
                  .map(
                    (c) => `<tr>
                      <td><strong>${escapeHtml(c.platform)}</strong>
                        <div class="muted">${c.active ? "active" : "off"} · hint ${escapeHtml(
                          c.token_hint || "—"
                        )}</div>
                      </td>
                      <td>${escapeHtml(c.label)}<div class="muted">${escapeHtml(
                        c.account_id || "—"
                      )}</div></td>
                      <td>${c.auto_publish ? "Yes" : "No"}</td>
                      <td class="row-actions">
                        ${
                          ["admin", "editor", "approver"].includes(state.user.role)
                            ? `<button class="btn small danger" data-del="${c.id}">Remove</button>`
                            : ""
                        }
                      </td>
                    </tr>`
                  )
                  .join("") ||
                `<tr><td colspan="4" class="muted">No saved connections yet.</td></tr>`
              }
            </tbody>
          </table>
          <div class="row-actions" style="margin-top:0.8rem">
            <button class="btn secondary" type="button" id="run-scheduled">Run due scheduled posts now</button>
          </div>
          <p id="conn-job-msg" class="muted"></p>
        </div>
        <div class="panel">
          ${
            ["admin", "editor", "approver"].includes(state.user.role)
              ? `<h3>Add other platforms</h3>
            <form id="conn-form" class="form-grid">
              <label>Platform
                <select name="platform" required>
                  <option value="facebook">Facebook Page</option>
                  <option value="instagram">Instagram Business</option>
                  <option value="linkedin">LinkedIn</option>
                  <option value="youtube">YouTube (credentials only for now)</option>
                  <option value="whatsapp">WhatsApp (manual pack — no API auto-post)</option>
                </select>
              </label>
              <label>Label<input name="label" placeholder="BCOBA Official Page"></label>
              <label>Account / Page / IG User / URN ID
                <input name="account_id" required placeholder="Facebook Page ID or IG user id or LinkedIn URN">
              </label>
              <label>Access token
                <textarea name="access_token" required placeholder="Paste Page Access Token / LinkedIn token"></textarea>
              </label>
              <label>Refresh token (optional)<input name="refresh_token"></label>
              <label><span class="muted">Auto-publish enabled</span>
                <select name="auto_publish">
                  <option value="1" selected>Yes</option>
                  <option value="0">No (analytics only)</option>
                </select>
              </label>
              <button class="btn" type="submit">Save encrypted credentials</button>
              <p id="conn-msg" class="muted"></p>
            </form>`
              : `<p class="muted">Use Quick post above, or ask admin to save other platform credentials.</p>`
          }
        </div>
      </div>
    `;

    qs("#quick-fb-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!canManage) {
        qs("#quick-fb-msg").textContent = "Your role cannot publish.";
        qs("#quick-fb-msg").style.color = "#b42336";
        return;
      }
      const fd = new FormData(e.target);
      const pageId = String(fd.get("account_id") || "").trim();
      const token = String(fd.get("access_token") || "").trim();
      const msg = qs("#quick-fb-msg");
      const linkEl = qs("#quick-fb-link");
      msg.style.color = "";
      if (!pageId || (!token && !fbSaved?.has_token)) {
        msg.style.color = "#b42336";
        msg.textContent =
          "Fill Page ID and Page Access Token from Graph API Explorer → me/accounts.";
        return;
      }
      if (token && !token.startsWith("EAA") && !token.startsWith("YA")) {
        msg.style.color = "#b42336";
        msg.textContent =
          "Token looks wrong. Paste the Page access_token from me/accounts (usually starts with EAA…).";
        return;
      }
      msg.textContent = "Posting to Facebook…";
      linkEl.innerHTML = "";
      try {
        const res = await api("/api/quick-post", {
          method: "POST",
          body: JSON.stringify({
            platform: "facebook",
            account_id: pageId,
            access_token: token,
            message: fd.get("message"),
            link: fd.get("link"),
            label: fd.get("label"),
            save_connection: fd.get("save_connection") === "1",
          }),
        });
        msg.style.color = "#0f766e";
        msg.textContent = res.saved_connection
          ? "Posted. Credentials saved for next time."
          : "Posted.";
        if (res.live_url) {
          linkEl.innerHTML = `<a href="${escapeHtml(
            res.live_url
          )}" target="_blank" rel="noopener">Open Facebook post</a>`;
        } else if (res.platform_post_id) {
          linkEl.textContent = `Post ID: ${res.platform_post_id}`;
        }
        if (res.saved_connection) renderConnections();
      } catch (ex) {
        msg.style.color = "#b42336";
        msg.textContent = ex.message || "Post failed";
      }
    });

    qs("#run-scheduled")?.addEventListener("click", async () => {
      const msg = qs("#conn-job-msg");
      msg.textContent = "Running…";
      try {
        const res = await api("/api/jobs/run-scheduled", {
          method: "POST",
          body: JSON.stringify({}),
        });
        msg.textContent = `Processed ${(res.ran || []).length} due item(s).`;
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });

    qsa("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm("Remove this connection?")) return;
        await api(`/api/connections/${btn.dataset.del}`, { method: "DELETE" });
        renderConnections();
      };
    });

    qs("#conn-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = qs("#conn-msg");
      msg.textContent = "Saving…";
      try {
        await api("/api/connections", {
          method: "POST",
          body: JSON.stringify({
            platform: fd.get("platform"),
            label: fd.get("label"),
            account_id: fd.get("account_id"),
            access_token: fd.get("access_token"),
            refresh_token: fd.get("refresh_token"),
            auto_publish: fd.get("auto_publish") === "1",
          }),
        });
        msg.textContent = "Saved.";
        renderConnections();
      } catch (ex) {
        msg.textContent = ex.message;
      }
    });
  }

  async function renderAnalytics() {
    const root = qs("#view-analytics");
    const data = (await api("/api/analytics")).data;
    const ops = data.ops || {};
    const tags = data.tags || [];
    const maxEng = Math.max(1, ...tags.map((t) => Number(t.engagement) || 0));

    const renderTagTable = () => {
      const kind = qs("#tag-kind-filter")?.value || "";
      const sort = qs("#tag-sort")?.value || "engagement";
      let rows = [...tags];
      if (kind) rows = rows.filter((t) => t.kind === kind);
      rows.sort((a, b) => (Number(b[sort]) || 0) - (Number(a[sort]) || 0));
      qs("#tag-table-body").innerHTML =
        rows
          .map((t) => {
            const eng = Number(t.engagement) || 0;
            const pct = Math.round((eng / maxEng) * 100);
            return `<tr>
              <td>
                <span class="tag">${escapeHtml(t.name)}</span>
                <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
              </td>
              <td class="muted">${escapeHtml(t.kind)}</td>
              <td>${t.uses}</td>
              <td>${t.published_count || 0}</td>
              <td>${t.reach || 0}</td>
              <td><strong>${eng}</strong></td>
              <td><a class="btn small secondary" href="#queue" data-filter-tag="${escapeHtml(
                t.name
              )}">View</a></td>
            </tr>`;
          })
          .join("") || `<tr><td colspan="7" class="muted">No hashtag data yet</td></tr>`;
    };

    root.innerHTML = `
      <div class="help-box">
        <strong>${data.is_sample ? "Sample metrics may still be present." : "Hub analytics"}</strong>
        ${escapeHtml(data.source_note || "")}
        Connected: ${
          Object.keys(data.connections || {}).length
            ? Object.entries(data.connections)
                .map(([k, v]) => `${k}×${v}`)
                .join(", ")
            : "none — add under Connections"
        }
        · API-synced channel packs: ${data.api_synced_channels || 0}
        · <a href="#connections">Manage connections</a>
      </div>
      <div class="grid stats">
        <div class="stat"><div class="label">Submitted</div><div class="value">${ops.submitted || 0}</div></div>
        <div class="stat"><div class="label">Approved</div><div class="value">${ops.approved || 0}</div></div>
        <div class="stat"><div class="label">Published</div><div class="value">${ops.published || 0}</div></div>
        <div class="stat"><div class="label">Active #tags</div><div class="value">${tags.filter((t) => t.uses > 0).length}</div></div>
      </div>

      <div class="panel" style="margin-top:1rem">
        <div class="panel-head">
          <h3>#Hashtag performance</h3>
          <div class="row-actions">
            <button class="btn small secondary" type="button" id="load-sample">Load sample data</button>
            <select id="tag-kind-filter">
              <option value="">All kinds</option>
              <option value="master">master</option>
              <option value="category">category</option>
              <option value="campaign">campaign</option>
              <option value="custom">custom</option>
            </select>
            <select id="tag-sort">
              <option value="engagement">Sort: engagement</option>
              <option value="reach">Sort: reach</option>
              <option value="uses">Sort: uses</option>
              <option value="published_count">Sort: published</option>
            </select>
          </div>
        </div>
        <p class="muted" style="margin:0 0 0.8rem;font-size:0.84rem">
          Shows which tags actually drive reach & engagement (from metrics logged on published channel packs).
        </p>
        <div class="tag-top">
          ${(data.top_tags || [])
            .slice(0, 6)
            .map(
              (t) => `<div class="tag-top-card">
                <span class="tag">${escapeHtml(t.name)}</span>
                <div class="value">${t.engagement || 0}</div>
                <div class="muted">engagement · ${t.reach || 0} reach · ${t.uses} uses</div>
              </div>`
            )
            .join("") || `<p class="muted">Publish posts and log metrics to rank hashtags.</p>`}
        </div>
        <table style="margin-top:1rem">
          <thead>
            <tr>
              <th>Hashtag</th><th>Kind</th><th>Uses</th><th>Published</th><th>Reach</th><th>Engagement</th><th></th>
            </tr>
          </thead>
          <tbody id="tag-table-body"></tbody>
        </table>
      </div>

      <div class="grid two" style="margin-top:1rem">
        <div class="panel">
          <h3>By category</h3>
          <table>
            <thead><tr><th>Category</th><th>Content</th><th>Reach</th><th>Engagement</th></tr></thead>
            <tbody>
              ${data.by_category
                .map(
                  (r) => `<tr>
                    <td>${escapeHtml(r.name)}</td>
                    <td>${r.content_count}</td>
                    <td>${r.reach}</td>
                    <td>${Number(r.likes) + Number(r.comments) + Number(r.shares)}</td>
                  </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
        <div class="panel">
          <h3>By campaign</h3>
          <table>
            <thead><tr><th>Campaign</th><th>Category</th><th>Reach</th><th>Engagement</th></tr></thead>
            <tbody>
              ${data.by_campaign
                .map(
                  (r) => `<tr>
                    <td>${escapeHtml(r.name)}</td>
                    <td>${escapeHtml(r.category_name)}</td>
                    <td>${r.reach}</td>
                    <td>${Number(r.likes) + Number(r.comments) + Number(r.shares)}</td>
                  </tr>`
                )
                .join("") || `<tr><td colspan="4" class="muted">No campaign content yet</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
      <div class="panel" style="margin-top:1rem">
        <h3>By platform</h3>
        <table>
          <thead><tr><th>Platform</th><th>Reach</th><th>Likes</th><th>Comments</th><th>Shares</th></tr></thead>
          <tbody>
            ${data.by_platform
              .map(
                (r) => `<tr>
                  <td>${escapeHtml(r.platform)}</td>
                  <td>${r.reach}</td><td>${r.likes}</td><td>${r.comments}</td><td>${r.shares}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
    renderTagTable();
    qs("#tag-kind-filter").onchange = renderTagTable;
    qs("#tag-sort").onchange = renderTagTable;
    qs("#load-sample")?.addEventListener("click", async () => {
      try {
        const res = await api("/api/seed", {
          method: "POST",
          body: JSON.stringify({ force: true }),
        });
        alert(
          `Sample data ready: ${res.counts?.content || "?"} posts, ${
            res.counts?.tags || "?"
          } tags. Reloading analytics…`
        );
        renderAnalytics();
      } catch (ex) {
        // Fallback if server not restarted yet — seed via note
        alert(
          `${ex.message}\n\nIf seed API is unavailable, restart server then run:\npython3 scripts/seed_sample.py --force`
        );
      }
    });
    root.addEventListener("click", (e) => {
      const a = e.target.closest("[data-filter-tag]");
      if (!a) return;
      e.preventDefault();
      sessionStorage.setItem("hub_queue_tag", a.dataset.filterTag);
      location.hash = "#queue";
    });
  }

  return { initLogin, initApp };
})();
