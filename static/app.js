(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  $("#yr").textContent = new Date().getFullYear();

  // ---------------- helpers ----------------
  let toastTimer;
  function toast(msg, isErr = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.className = "toast"), 3800);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    let data = {};
    try { data = await res.json(); } catch (_) { /* not json */ }
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  const fmtTime = (s) => {
    if (!s && s !== 0) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0");
  };
  const fmtSize = (b) => {
    if (!b) return "";
    const u = ["B", "KB", "MB", "GB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(i ? 1 : 0) + " " + u[i];
  };
  const setLoading = (btn, on) => { btn.classList.toggle("loading", on); btn.disabled = on; };

  function fillSelect(sel, items, selected) {
    sel.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(selected) ? " selected" : ""}>${esc(l)}</option>`).join("");
  }

  // ---------------- tabs ----------------
  $$(".tab").forEach((b) => b.addEventListener("click", () => {
    $$(".tab").forEach((x) => { x.classList.toggle("active", x === b); x.setAttribute("aria-selected", x === b); });
    $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + b.dataset.tab));
  }));

  // ---------------- format options ----------------
  const VIDEO_FORMATS = [["mp4", "MP4"], ["webm", "WEBM"], ["mkv", "MKV"]];
  const AUDIO_FORMATS = [["mp3", "MP3"], ["m4a", "M4A"], ["opus", "OPUS"], ["wav", "WAV"], ["flac", "FLAC"]];
  const BITRATES = [["320", "320 kbps (best)"], ["256", "256 kbps"], ["192", "192 kbps"], ["128", "128 kbps"]];
  const ALL_HEIGHTS = [2160, 1440, 1080, 720, 480, 360];
  const heightLabel = (h) => ({ 2160: "4K (2160p)", 1440: "2K (1440p)" }[h] || h + "p");

  function setFormatOptions(mode, fmtSel, qSel, heights) {
    if (mode === "audio") {
      fillSelect(fmtSel, AUDIO_FORMATS, "mp3");
      fillSelect(qSel, BITRATES, "320");
    } else {
      fillSelect(fmtSel, VIDEO_FORMATS, "mp4");
      const hs = (heights && heights.length ? heights : ALL_HEIGHTS).filter((h) => h >= 144);
      const uniq = [...new Set(hs)];
      const best = uniq.find((h) => h <= 1080) || uniq[uniq.length - 1];
      fillSelect(qSel, uniq.map((h) => [h, heightLabel(h)]), best);
    }
    const lossless = () => ["wav", "flac"].includes(fmtSel.value);
    qSel.disabled = mode === "audio" && lossless();
    fmtSel.onchange = () => { qSel.disabled = mode === "audio" && lossless(); };
  }

  // ---------------- job queue (shared) ----------------
  const queues = {
    dl: { list: $("#dlQueue"), wrap: $("#dlQueueWrap"), zip: $("#dlZip"), ids: [] },
    cv: { list: $("#cvQueue"), wrap: $("#cvQueueWrap"), zip: $("#cvZip"), ids: [] },
  };
  const jobs = new Map(); // id -> {q, el, status}

  function addJob(qName, job) {
    const q = queues[qName];
    q.wrap.classList.remove("hidden");
    const li = document.createElement("li");
    li.className = "job queued";
    li.innerHTML = `<div class="jt"></div><div class="jm"></div><div class="ja"></div><div class="bar"><i></i></div>`;
    q.list.prepend(li);
    q.ids.push(job.id);
    jobs.set(job.id, { q: qName, el: li, status: "queued" });
    renderJob(job);
    poll();
  }

  function renderJob(j) {
    const rec = jobs.get(j.id);
    if (!rec) return;
    const li = rec.el;
    rec.status = j.status;
    li.className = "job " + j.status;
    $(".jt", li).textContent = j.status === "done" && j.filename ? j.filename : j.label;
    $(".jm", li).textContent = j.status === "done" ? ["Ready", fmtSize(j.size)].filter(Boolean).join(" · ") : j.message;
    const bar = $(".bar i", li);
    bar.style.width = (j.status === "error" ? 100 : j.progress) + "%";
    bar.classList.toggle("indet", j.status === "running" && !j.progress);
    const act = $(".ja", li);
    if (j.status === "done" && !act.firstChild) {
      act.innerHTML = `<a class="btn small primary save" href="/api/file/${encodeURIComponent(j.id)}" download>Save</a>`;
    }
    updateZip(rec.q);
  }

  function updateZip(qName) {
    const q = queues[qName];
    const done = q.ids.filter((id) => jobs.get(id)?.status === "done");
    q.zip.disabled = done.length < 2;
    q.zip.onclick = () => { window.location.href = "/api/zip?ids=" + done.join(","); };
  }

  let pollTimer = null;
  function poll() {
    if (pollTimer) return;
    const tick = async () => {
      const active = [...jobs.entries()].filter(([, r]) => r.status === "queued" || r.status === "running").map(([id]) => id);
      if (!active.length) { pollTimer = null; return; }
      try {
        const data = await api("/api/jobs?ids=" + active.join(","));
        const seen = new Set();
        for (const j of data.jobs) {
          seen.add(j.id);
          const before = jobs.get(j.id)?.status;
          renderJob(j);
          if (before !== "done" && j.status === "done") toast("Ready: " + (j.filename || j.label));
          if (before !== "error" && j.status === "error") toast(j.message, true);
        }
        for (const id of active) if (!seen.has(id)) {
          renderJob({ id, status: "error", progress: 100, message: "Expired on the server", label: jobs.get(id).el.querySelector(".jt").textContent });
        }
      } catch (_) { /* network blip: keep polling */ }
      pollTimer = setTimeout(tick, 900);
    };
    pollTimer = setTimeout(tick, 400);
  }

  // ---------------- DOWNLOAD ----------------
  const urlInput = $("#urlInput");
  const preview = $("#preview");
  const playlist = $("#playlist");
  let current = null;   // single video info
  let mode = "video";

  $("#pasteBtn").addEventListener("click", async () => {
    try {
      const t = await navigator.clipboard.readText();
      if (t) { urlInput.value = t.trim(); $("#urlForm").requestSubmit(); }
    } catch (_) { toast("Clipboard blocked — long-press to paste.", true); urlInput.focus(); }
  });

  // allow ?url=… deep links (e.g. share targets)
  const qp = new URLSearchParams(location.search);
  const shared = qp.get("url") || qp.get("text");
  if (shared && /https?:\/\//.test(shared)) urlInput.value = shared.match(/https?:\/\/\S+/)[0];

  $("#urlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;
    const btn = $("#fetchBtn");
    setLoading(btn, true);
    preview.classList.add("hidden");
    playlist.classList.add("hidden");
    try {
      const info = await api("/api/info", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
      });
      info.type === "playlist" ? showPlaylist(info) : showVideo(info);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setLoading(btn, false);
    }
  });

  function showVideo(info) {
    current = info;
    $("#pvThumb").src = info.thumbnail || "";
    $("#pvTitle").textContent = info.title || "Untitled";
    $("#pvMeta").textContent = [info.uploader, fmtTime(info.duration)].filter(Boolean).join(" · ");
    setMode(mode);
    preview.classList.remove("hidden");
  }

  function setMode(m) {
    mode = m;
    $$("#modeSeg .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
    $("#dlQualityLabel").textContent = m === "audio" ? "Audio quality" : "Resolution";
    setFormatOptions(m, $("#dlFormat"), $("#dlQuality"), current?.heights);
  }
  $$("#modeSeg .seg-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

  async function startDownload(payload) {
    const job = await api("/api/download", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    addJob("dl", job);
  }

  $("#dlBtn").addEventListener("click", async () => {
    if (!current) return;
    const btn = $("#dlBtn");
    setLoading(btn, true);
    try {
      await startDownload({
        url: current.url, title: current.title, mode,
        format: $("#dlFormat").value, quality: $("#dlQuality").value,
      });
      toast("Added to downloads");
      $("#dlQueueWrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) { toast(err.message, true); }
    finally { setLoading(btn, false); }
  });

  // Playlist
  let plEntries = [];
  function showPlaylist(info) {
    plEntries = info.entries || [];
    $("#plTitle").textContent = info.title || "Playlist";
    $("#plMeta").textContent = `${info.count} items` + (info.uploader ? " · " + info.uploader : "");
    $("#plList").innerHTML = plEntries.map((e, i) => `
      <li data-i="${i}">
        <input type="checkbox" checked aria-label="Select">
        ${e.thumbnail ? `<img src="${esc(e.thumbnail)}" alt="" loading="lazy">` : ""}
        <span class="t">${esc(e.title)}</span>
        <span class="muted small">${esc(fmtTime(e.duration))}</span>
      </li>`).join("");
    $("#plAll").checked = true;
    setPlMode();
    playlist.classList.remove("hidden");
  }
  $("#plList").addEventListener("click", (e) => {
    const li = e.target.closest("li");
    if (!li || e.target.tagName === "INPUT") return;
    const cb = $("input", li); cb.checked = !cb.checked;
  });
  $("#plAll").addEventListener("change", (e) => $$("#plList input").forEach((c) => (c.checked = e.target.checked)));
  const setPlMode = () => setFormatOptions($("#plMode").value, $("#plFormat"), $("#plQuality"), null);
  $("#plMode").addEventListener("change", setPlMode);

  $("#plBtn").addEventListener("click", async () => {
    const picked = $$("#plList li").filter((li) => $("input", li).checked).map((li) => plEntries[+li.dataset.i]);
    if (!picked.length) return toast("Select at least one item.", true);
    const btn = $("#plBtn");
    setLoading(btn, true);
    const base = { mode: $("#plMode").value, format: $("#plFormat").value, quality: $("#plQuality").value };
    let ok = 0;
    for (const e of picked) {
      try { await startDownload({ ...base, url: e.url, title: e.title }); ok++; }
      catch (err) { toast(err.message, true); }
    }
    setLoading(btn, false);
    if (ok) { toast(`Added ${ok} item${ok > 1 ? "s" : ""}`); $("#dlQueueWrap").scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  });

  // ---------------- CONVERT ----------------
  const drop = $("#drop");
  const fileInput = $("#fileInput");
  const fileList = $("#fileList");
  let files = [];
  let maxMB = 1024;
  api("/api/health").then((h) => {
    if (h.max_upload_mb) { maxMB = h.max_upload_mb; $("#dropHint").textContent = `Video or audio, many at once · up to ${maxMB} MB per upload`; }
  }).catch(() => {});

  function addFiles(list) {
    for (const f of list) {
      if (!/^(video|audio)\//.test(f.type) && !/\.(mkv|flac|opus|m4a|webm|avi|mov|wmv|3gp|ts|mp3|wav|ogg|aac|mp4|m4v|flv|wma|amr|aiff?)$/i.test(f.name)) {
        toast(`Skipped ${f.name} (not audio/video)`, true);
        continue;
      }
      if (!files.some((x) => x.name === f.name && x.size === f.size)) files.push(f);
    }
    renderFiles();
  }

  function renderFiles() {
    fileList.classList.toggle("hidden", !files.length);
    fileList.innerHTML = files.map((f, i) => `
      <li><span class="ftype">${esc((f.name.split(".").pop() || "?").slice(0, 5))}</span>
      <span class="n">${esc(f.name)}</span><span class="muted small">${fmtSize(f.size)}</span>
      <button class="x" data-i="${i}" aria-label="Remove">×</button></li>`).join("");
    $("#cvBtn").disabled = !files.length;
    $("#cvBtn").textContent = files.length > 1 ? `Convert ${files.length} files` : "Convert";
  }

  fileList.addEventListener("click", (e) => {
    const b = e.target.closest(".x");
    if (b) { files.splice(+b.dataset.i, 1); renderFiles(); }
  });
  fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  const VIDEO_T = ["mp4", "webm", "mkv", "mov", "avi", "gif"];
  const LOSSLESS = ["wav", "flac"];
  function syncCvOptions() {
    const t = $("#cvTarget").value;
    $("#cvHeightWrap").classList.toggle("hidden", !VIDEO_T.includes(t));
    $("#cvBitrateWrap").classList.toggle("hidden", t === "gif" || LOSSLESS.includes(t));
  }
  $("#cvTarget").addEventListener("change", syncCvOptions);
  syncCvOptions();

  // Upload in batches that fit the server's limit, so 20 big files don't fail together
  function batches(list) {
    const limit = maxMB * 1024 * 1024 * 0.95;
    const maxFiles = 20;
    const out = []; let cur = []; let size = 0;
    for (const f of list) {
      if (f.size > limit) { toast(`${f.name} is larger than ${maxMB} MB`, true); continue; }
      if (cur.length && (size + f.size > limit || cur.length >= maxFiles)) { out.push(cur); cur = []; size = 0; }
      cur.push(f); size += f.size;
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function upload(group, fields, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      group.forEach((f) => fd.append("files", f, f.name));
      Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/convert");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let data = {}; try { data = JSON.parse(xhr.responseText); } catch (_) {}
        xhr.status < 300 ? resolve(data) : reject(new Error(data.error || `Upload failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error("Upload failed — check your connection."));
      xhr.send(fd);
    });
  }

  $("#cvBtn").addEventListener("click", async () => {
    if (!files.length) return;
    const btn = $("#cvBtn");
    const fields = { target: $("#cvTarget").value, height: $("#cvHeight").value, bitrate: $("#cvBitrate").value };
    const groups = batches(files);
    btn.disabled = true;
    const label = btn.textContent;
    let added = 0;
    for (let g = 0; g < groups.length; g++) {
      try {
        const res = await upload(groups[g], fields, (p) => {
          btn.textContent = `Uploading ${groups.length > 1 ? `${g + 1}/${groups.length} ` : ""}${Math.round(p * 100)}%`;
        });
        (res.jobs || []).forEach((j) => { addJob("cv", j); added++; });
      } catch (err) { toast(err.message, true); }
    }
    btn.textContent = label;
    if (added) {
      files = []; renderFiles();
      toast(`Converting ${added} file${added > 1 ? "s" : ""}…`);
      $("#cvQueueWrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      btn.disabled = false;
    }
  });
})();
