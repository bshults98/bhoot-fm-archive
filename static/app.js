(() => {
  "use strict";

  // ─── DOM ─────────────────────────────────────────────────────────────
  const $q = document.getElementById("q");
  const $form = document.getElementById("search-form");
  const $status = document.getElementById("status");
  const $results = document.getElementById("results");
  const $transcript = document.getElementById("transcript");
  const $tTitle = document.getElementById("t-title");
  const $tMeta = document.getElementById("t-meta");
  const $tSegs = document.getElementById("t-segments");
  const $back = document.getElementById("back-to-results");
  const $player = document.getElementById("player-bar");
  const $audio = document.getElementById("audio");
  const $nowTitle = document.getElementById("now-title");
  const $nowMeta = document.getElementById("now-meta");
  const $dial = document.getElementById("dial");
  const $randomBtn      = document.getElementById("random-btn");
  const $prevBtn        = document.getElementById("prev-btn");
  const $nextBtn        = document.getElementById("next-btn");
  const $expandBtn      = document.getElementById("expand-btn");
  const $collapseBtn    = document.getElementById("collapse-btn");
  const $expandedPlayer = document.getElementById("expanded-player");
  const $expEpTitle     = document.getElementById("exp-ep-title");
  const $expEpMeta      = document.getElementById("exp-ep-meta");
  const $rotatingTagline = document.getElementById("rotating-tagline");
  const $canonical = document.getElementById("canonical");
  const $eye = document.querySelector(".brand .logo");
  const $playBtn = document.getElementById("play-btn");
  const $scrubber = document.getElementById("scrubber");
  const $scrubFill = document.getElementById("scrubber-fill");
  const $scrubBuffer = document.getElementById("scrubber-buffer");
  const $scrubThumb = document.getElementById("scrubber-thumb");
  const $timeCur = document.getElementById("time-cur");
  const $timeDur = document.getElementById("time-dur");
  const $dripLayer = document.getElementById("drip-layer");
  // Home view refs
  const $home = document.getElementById("home");
  const $heroResume = document.getElementById("hero-resume");
  const $heroTitle = document.getElementById("hero-title");
  const $heroMeta = document.getElementById("hero-meta");
  const $heroProgressFill = document.getElementById("hero-progress-fill");
  const $heroResumeBtn = document.getElementById("hero-resume-btn");
  const $heroResumeTime = document.getElementById("hero-resume-time");
  const $heroRestartBtn = document.getElementById("hero-restart-btn");
  const $heroDismissBtn = document.getElementById("hero-dismiss-btn");
  const $railTonight = document.getElementById("rail-tonight");
  const $railTonightCards = document.getElementById("rail-tonight-cards");
  const $railRecent = document.getElementById("rail-recent");
  const $railRecentCards = document.getElementById("rail-recent-cards");
  const $railRecentClear = document.getElementById("rail-recent-clear");
  const $yearPills = document.getElementById("year-pills");
  const $monthPills = document.getElementById("month-pills");
  const $browseGrid = document.getElementById("browse-grid");
  const $browseSub = document.getElementById("browse-sub");
  const $railMostPlayed = document.getElementById("rail-mostplayed");
  const $railMostPlayedCards = document.getElementById("rail-mostplayed-cards");
  const $resetHistoryBtn = document.getElementById("reset-history-btn");
  const $firstRun = document.getElementById("first-run");
  const $firstRunDismiss = document.getElementById("first-run-dismiss");
  const $filterPills = document.querySelectorAll(".filter-pill");
  const $sortSelect = document.getElementById("sort-select");
  const $expSleepStatus = document.getElementById("exp-sleep-status");
  const $expSleepPills = document.querySelectorAll(".exp-ctrl-pill[data-sleep]");
  const $expRatePills = document.querySelectorAll(".exp-ctrl-pill[data-rate]");

  // Clean up any leftover flag from the Webamp experiment.
  try { localStorage.removeItem("bfa_webamp"); } catch {}

  // ─── State ───────────────────────────────────────────────────────────
  const state = {
    view: "episodes",
    query: "",
    currentEpisode: null,
    currentSegments: [],
    allEpisodes: null,
    browseFilter: "all",
    browseSort: "newest",
  };
  Object.assign(state, loadBrowsePrefs());

  // Browse filter + sort (persisted on this device).
  const BROWSE_PREFS_KEY = "bfa_browse_prefs_v1";
  function loadBrowsePrefs() {
    try {
      const p = JSON.parse(localStorage.getItem(BROWSE_PREFS_KEY)) || {};
      return { filter: p.filter || "all", sort: p.sort || "newest" };
    } catch { return { filter: "all", sort: "newest" }; }
  }
  function saveBrowsePrefs() {
    try { localStorage.setItem(BROWSE_PREFS_KEY, JSON.stringify({ filter: state.browseFilter, sort: state.browseSort })); } catch {}
  }

  const SITE_NAME = "Bhoot FM Archive";
  const BASE_DESC = "Search and listen to Bengali horror radio episodes from Bhoot FM. Find ghost stories by keyword, jump to the exact moment.";

  // Rotating taglines — subtle and mood-setting, bilingual.
  const TAGLINES = [
    "search and listen where you dare",
    "রাতের গল্প · stories of the night",
    "broadcasts from beyond",
    "ভূত এফএম · since 2007",
    "tune in if you can sleep after",
    "stories the night remembers",
    "প্রতিটি কণ্ঠে একটি গল্প",
    "the dial still turns",
  ];

  // ─── Helpers ─────────────────────────────────────────────────────────
  // Fly free-tier machines auto-stop after idle, so the *first* request can
  // wait several seconds while the box boots. Same story for any cold-start
  // backend (HF Spaces etc.). Retry transient failures with backoff so a sleepy
  // server doesn't look like a broken one to the user.
  const API_RETRY_DELAYS_MS = [600, 1800, 4500];
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  async function api(path, params, opts = {}) {
    const url = new URL(path, location.origin);
    if (params)
      for (const [k, v] of Object.entries(params))
        if (v != null && v !== "") url.searchParams.set(k, v);
    const { retries = API_RETRY_DELAYS_MS.length, onRetry } = opts;
    let lastErr;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const r = await fetch(url);
        if (r.ok) return await r.json();
        // 429 = real rate limit, surface immediately; client should slow down.
        // 4xx other than 429 = our request is wrong, no point retrying.
        if (r.status === 429 || (r.status >= 400 && r.status < 500)) {
          const err = new Error(`request failed`);
          err.status = r.status;
          throw err;
        }
        lastErr = new Error(`request failed (${r.status})`);
        lastErr.status = r.status;
      } catch (e) {
        // Network errors / aborts retry; explicit 4xx throws don't.
        if (e.status && e.status < 500) throw e;
        lastErr = e;
      }
      if (attempt >= retries) break;
      const delay = API_RETRY_DELAYS_MS[Math.min(attempt, API_RETRY_DELAYS_MS.length - 1)];
      if (onRetry) onRetry(attempt + 1, retries + 1);
      await sleep(delay);
    }
    throw lastErr || new Error("request failed");
  }

  const fmtTs = sec => {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
             : `${m}:${String(s).padStart(2, "0")}`;
  };
  const fmtDate = iso => {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${parseInt(d, 10)} ${months[parseInt(m, 10) - 1]} ${y}`;
  };
  const debounce = (fn, ms) => {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  };
  const setStatus = (txt, cls = "") => {
    $status.className = "status " + cls;
    $status.textContent = txt;
  };
  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ─── Listening history (localStorage, no accounts) ──────────────────
  // Map of { [epId]: { pos, dur, pct, updated } }.
  // pct >= 0.90 → completed. 0.02 < pct < 0.90 → in_progress. Else: not started.
  const HIST_KEY = "bfa_history_v1";
  const HIST_MAX_ENTRIES = 250;
  function historyLoad() {
    try { return JSON.parse(localStorage.getItem(HIST_KEY)) || {}; }
    catch { return {}; }
  }
  function historySave(h) {
    try {
      const keys = Object.keys(h);
      if (keys.length > HIST_MAX_ENTRIES) {
        // Drop the oldest by `updated` to stay under the cap.
        keys.sort((a, b) => (h[a].updated || 0) - (h[b].updated || 0));
        for (let i = 0; i < keys.length - HIST_MAX_ENTRIES; i++) delete h[keys[i]];
      }
      localStorage.setItem(HIST_KEY, JSON.stringify(h));
    } catch {}
  }
  // An episode counts as touched once it's been played for >= 15 seconds.
  // Anything shorter is treated as "didn't really listen" and stays unstarted.
  const HIST_MIN_POS_SEC = 15;
  function historyStatus(epId) {
    if (!epId) return null;
    const rec = historyLoad()[epId];
    if (!rec) return null;
    const pct = rec.pct || 0;
    const pos = rec.pos || 0;
    let status = null;
    if (pct >= 0.90) status = "completed";
    else if (pos >= HIST_MIN_POS_SEC) status = "in_progress";
    return status ? { status, ...rec } : null;
  }
  function historyUpdate(epId, pos, dur) {
    if (!epId || !dur || !isFinite(dur) || dur <= 0) return;
    const h = historyLoad();
    const prev = h[epId] || {};
    // Once completed, don't overwrite back to in-progress just because the
    // user started replaying the episode — keep the ✓ on the card.
    const completed = prev.pct >= 0.90;
    const pct = Math.max(0, Math.min(1, pos / dur));
    h[epId] = {
      pos: Math.floor(pos),
      dur: Math.floor(dur),
      pct: completed ? Math.max(prev.pct, pct) : pct,
      updated: Date.now(),
    };
    historySave(h);
  }
  function historyMarkPlayed(epId, dur) {
    if (!epId) return;
    const h = historyLoad();
    const d = dur || (h[epId] && h[epId].dur) || 0;
    h[epId] = { pos: d, dur: d, pct: 1, updated: Date.now() };
    historySave(h);
  }
  function historyRemove(epId) {
    if (!epId) return;
    const h = historyLoad();
    delete h[epId];
    historySave(h);
  }
  function historyClear() {
    try {
      localStorage.removeItem(HIST_KEY);
      // Also clear the per-episode "already pinged the server" flags so
      // a true reset means the user can contribute play counts again.
      const toDel = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith("bfa_pinged_")) toDel.push(k);
      }
      for (const k of toDel) localStorage.removeItem(k);
    } catch {}
  }
  function historyRecent(n = 5) {
    const h = historyLoad();
    return Object.entries(h)
      .map(([id, r]) => ({ id, ...r }))
      .sort((a, b) => (b.updated || 0) - (a.updated || 0))
      .slice(0, n);
  }
  function historyInProgress() {
    const h = historyLoad();
    return Object.entries(h)
      .map(([id, r]) => ({ id, ...r }))
      .filter(r => (r.pos || 0) >= HIST_MIN_POS_SEC && (r.pct || 0) < 0.90)
      .sort((a, b) => (b.updated || 0) - (a.updated || 0));
  }

  // Card HTML used by home rails, browse grid, etc. Cards show status.
  function cardHtml(ep, idx = 0) {
    const st = historyStatus(ep.id);
    const cls = st?.status === "completed" ? " ep-completed"
              : st?.status === "in_progress" ? " ep-in-progress" : "";
    const pct = st?.pct ?? 0;
    const badge = st?.status === "completed"
      ? `<span class="card-badge done">✓ played</span>`
      : st?.status === "in_progress"
        ? `<span class="card-badge in-prog">${Math.round(pct * 100)}%</span>`
        : "";
    const progress = st?.status === "in_progress"
      ? `<div class="card-progress"><div class="card-progress-fill" style="width:${(pct * 100).toFixed(1)}%"></div></div>`
      : "";
    return `
      <div class="card episode-card card-appear${cls}" data-ep-id="${ep.id}" style="animation-delay:${Math.min(idx, 20) * 18}ms">
        <div class="card-main">
          <div class="card-title">${escapeHtml(ep.title)}</div>
          <div class="card-date">${fmtDate(ep.air_date)}${ep.duration_sec ? " · " + fmtTs(ep.duration_sec) : ""}</div>
        </div>
        ${badge}
        ${progress}
      </div>`;
  }

  // ─── SEO: dynamic title + canonical + description ───────────────────
  function setMeta({ title, description }) {
    document.title = title || SITE_NAME;
    const d = document.querySelector('meta[name="description"]');
    if (d && description) d.setAttribute("content", description);
    const og = document.querySelector('meta[property="og:title"]');
    if (og) og.setAttribute("content", title || SITE_NAME);
    const ogd = document.querySelector('meta[property="og:description"]');
    if (ogd && description) ogd.setAttribute("content", description);
    if ($canonical) $canonical.setAttribute("href", location.origin + location.pathname + location.hash);
  }

  // ─── Routing ─────────────────────────────────────────────────────────
  function readHash() {
    const h = location.hash.replace(/^#\/?/, "");
    if (!h) return { type: "home" };
    const parts = h.split("/");
    if (parts[0] === "q" && parts[1])
      return { type: "query", q: decodeURIComponent(parts.slice(1).join("/")) };
    if (parts[0] === "ep" && parts[1])
      return { type: "ep", id: parts[1], at: parts[2] ? parseFloat(parts[2]) : null };
    if (parts[0] === "y" && /^\d{4}$/.test(parts[1] || ""))
      return { type: "home", year: parts[1], month: /^\d{2}$/.test(parts[2] || "") ? parts[2] : null };
    return { type: "home" };
  }

  // ─── Audio ───────────────────────────────────────────────────────────
  let currentTimeSec = 0;

  function playEpisodeAt(episode, startSec) {
    // Before swapping to a different episode, save the OUTGOING one's last
    // known position so we don't lose the last few seconds of progress that
    // happened between the most recent 10s-interval tick and the switch.
    const prevId = $audio.dataset.episodeId;
    if (prevId && prevId !== episode.id) {
      const prevDur = $audio.duration;
      const prevPos = $audio.currentTime;
      if (prevDur && isFinite(prevDur) && prevDur > 0) {
        historyUpdate(prevId, prevPos, prevDur);
      }
    }

    const meta = `${fmtDate(episode.air_date)}${episode.duration_sec ? " • " + fmtTs(episode.duration_sec) : ""}`;
    $nowTitle.textContent = episode.title;
    $nowMeta.textContent  = meta;
    $expEpTitle.textContent = episode.title;
    $expEpMeta.textContent  = episode.duration_sec ? fmtTs(episode.duration_sec) + " remaining" : "";
    const wasLoaded = $audio.dataset.episodeId === episode.id;
    $player.classList.remove("hidden");
    updateSkipButtons();
    if (!wasLoaded) {
      $audio.src = episode.mp3_url;
      $audio.dataset.episodeId = episode.id;
      $audio.addEventListener(
        "loadedmetadata",
        () => { try { $audio.currentTime = startSec; $audio.play(); } catch {} },
        { once: true }
      );
      $audio.load();
    } else {
      $audio.currentTime = startSec;
      $audio.play().catch(() => {});
    }
    updateMediaSession(episode);
  }

  // ── Media Session API: lock-screen / dynamic-island / hardware-key UI ─
  // Exposes the current episode's title + artwork to the OS media controls so
  // listeners can play/pause/seek without opening the tab. Silently noops if
  // the browser doesn't implement it (older Safari, some embedded views).
  function updateMediaSession(episode) {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: episode.title || "Bhoot FM",
        artist: "RJ Russell · Bhoot FM",
        album: `Radio Foorti 88.0 FM · ${fmtDate(episode.air_date)}`,
        artwork: [
          { src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
          { src: "/og-image.png",         sizes: "1200x630", type: "image/png" },
          { src: "/favicon.svg",          sizes: "any",      type: "image/svg+xml" },
        ],
      });
    } catch {}
    if (!navigator.mediaSession._bfaWired) {
      const setHandler = (action, fn) => {
        try { navigator.mediaSession.setActionHandler(action, fn); } catch {}
      };
      setHandler("play",            () => { $audio.play().catch(() => {}); });
      setHandler("pause",           () => { $audio.pause(); });
      setHandler("seekbackward",    e => { $audio.currentTime = Math.max(0, $audio.currentTime - (e?.seekOffset || 15)); });
      setHandler("seekforward",     e => { $audio.currentTime = Math.min($audio.duration || 0, $audio.currentTime + (e?.seekOffset || 30)); });
      setHandler("seekto",          e => {
        if (e?.fastSeek && "fastSeek" in $audio) { $audio.fastSeek(e.seekTime); return; }
        if (e?.seekTime != null) $audio.currentTime = e.seekTime;
      });
      setHandler("previoustrack",   () => { if (!$prevBtn.disabled) $prevBtn.click(); });
      setHandler("nexttrack",       () => { if (!$nextBtn.disabled) $nextBtn.click(); });
      navigator.mediaSession._bfaWired = true;
    }
  }

  // Keep the OS scrubber and play-state in sync with the actual audio element.
  function updateMediaSessionState() {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.playbackState = $audio.paused ? "paused" : "playing";
      if ("setPositionState" in navigator.mediaSession && $audio.duration && isFinite($audio.duration)) {
        navigator.mediaSession.setPositionState({
          duration: $audio.duration,
          playbackRate: $audio.playbackRate || 1,
          position: Math.min($audio.currentTime || 0, $audio.duration),
        });
      }
    } catch {}
  }
  // ─── Audio-reactive visualizer ───────────────────────────────────────
  let audioCtx = null;
  let analyser = null;
  let timeData = null;  // waveform (time-domain)
  let freqData = null;  // spectrum (frequency-domain)
  const pulse = { bass: 0, mid: 0, level: 0, playing: false };

  function ensureAudioGraph() {
    if (analyser) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = new Ctx();
      const src = audioCtx.createMediaElementSource($audio);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.82;
      src.connect(analyser);
      analyser.connect(audioCtx.destination);
      timeData = new Uint8Array(analyser.fftSize);           // 1024 samples
      freqData = new Uint8Array(analyser.frequencyBinCount); //  512 bins
    } catch (e) {
      console.warn("Web Audio unavailable:", e);
    }
  }

  // DPR-aware canvas setup (crisp on retina).
  (function setupDPR() {
    const dpr = window.devicePixelRatio || 1;
    $dial.width  = 72 * dpr;
    $dial.height = 72 * dpr;
    $dial.getContext("2d").scale(dpr, dpr);
  })();

  // ── Compact dial: polar oscilloscope ─────────────────────────────────
  // The audio waveform is mapped radially around a circle. In idle/paused
  // state a gentle sine keeps it alive. The shape is organic and ghostly.
  function drawDial() {
    const ctx = $dial.getContext("2d");
    const S = 72, cx = 36, cy = 36;
    ctx.clearRect(0, 0, S, S);

    const isPlaying = !$audio.paused && !!$audio.src;
    const t = performance.now() / 1000;

    // Gather samples.
    if (analyser && isPlaying && timeData) {
      analyser.getByteTimeDomainData(timeData);
      analyser.getByteFrequencyData(freqData);
    }

    // Update shared pulse from frequency data (used by easter-egg effects).
    if (analyser && isPlaying && freqData) {
      let bSum = 0, mSum = 0, lSum = 0;
      for (let i = 0; i < 8; i++)  bSum += freqData[i];
      for (let i = 8; i < 24; i++) mSum += freqData[i];
      for (let i = 0; i < freqData.length; i++) lSum += freqData[i];
      const b = bSum / 8 / 255, m = mSum / 16 / 255, l = lSum / freqData.length / 255;
      pulse.bass  = pulse.bass  * 0.7 + b * 0.3;
      pulse.mid   = pulse.mid   * 0.7 + m * 0.3;
      pulse.level = pulse.level * 0.7 + l * 0.3;
      pulse.playing = true;
    } else {
      const rate = isPlaying ? 2.2 : 1.1;
      const b = 0.12 + 0.07 * Math.sin(t * rate);
      pulse.bass  = pulse.bass  * 0.9 + b * 0.1;
      pulse.level = pulse.bass;
      pulse.playing = false;
    }

    // Background glow — breathes with bass.
    const glowR = 20 + pulse.bass * 12;
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
    glow.addColorStop(0, `rgba(180, 18, 18, ${0.28 + pulse.bass * 0.25})`);
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, S, S);

    // Polar waveform — 128 points sampled evenly from timeData.
    const N = 128;
    const baseR = 18, ampR = 10;
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const ang = (i / N) * Math.PI * 2 - Math.PI / 2;
      let v;
      if (analyser && isPlaying && timeData) {
        const idx = Math.floor((i % N) / N * timeData.length);
        v = (timeData[idx] - 128) / 128; // –1 … +1
      } else {
        // Idle: two overlapping sine waves for a Lissajous-like breathe.
        v = 0.22 * Math.sin(t * (isPlaying ? 2.4 : 1.1) + i * 0.18)
          + 0.08 * Math.sin(t * 0.7 + i * 0.42);
      }
      const r = baseR + v * ampR;
      const x = cx + Math.cos(ang) * r, y = cy + Math.sin(ang) * r;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = `rgba(255, 52, 52, ${isPlaying ? 0.9 : 0.45})`;
    ctx.lineWidth = 1.4;
    ctx.shadowColor = "rgba(255, 30, 30, 0.7)";
    ctx.shadowBlur  = isPlaying ? 5 : 2;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // Centre dot.
    ctx.fillStyle = `rgba(255, 65, 65, ${isPlaying ? 0.95 : 0.5})`;
    ctx.beginPath();
    ctx.arc(cx, cy, 2.2, 0, Math.PI * 2);
    ctx.fill();

    setTimeout(drawDial, 50);
  }
  drawDial();

  // ══════════════════════════════════════════════════════════════════
  // ── "Ghost Signal" — fullscreen visualizer ────────────────────────
  // ══════════════════════════════════════════════════════════════════
  //
  // The key technique: instead of clearRect each frame we overdraw a
  // semi-transparent dark fill. Old frames fade rather than vanish —
  // producing motion-blur trails that make the visuals feel alive.
  //
  // Layers (back → front every frame):
  //   1. Fade   — semi-opaque dark rect (persistence / motion blur)
  //   2. Blobs  — slow-moving radial gradients give depth + warmth
  //   3. Spectrum ring — 256 freq bars rotating slowly; trails = spirals
  //   4. Waveform mandala — polar waveform × 2 mirror symmetry; multi-pass
  //      fake glow (no shadowBlur, which is expensive on large canvases)
  //   5. Eye    — central iris/pupil that breathes with bass
  //   6. Particles — emitted on high-energy transients, drift outward

  // ── Expanded player toggle ────────────────────────────────────────────
  let isExpanded = false;

  function openExpanded() {
    isExpanded = true;
    $expandedPlayer.classList.add("open");
    $expandedPlayer.setAttribute("aria-hidden", "false");
    $expandBtn.classList.add("active");
    // Small delay so the CSS slide-up completes before we read dimensions.
    setTimeout(() => {
      setupBigViz();
      if (bigVizRaf) cancelAnimationFrame(bigVizRaf);
      drawBigViz();
    }, 60);
  }
  function closeExpanded() {
    isExpanded = false;
    $expandedPlayer.classList.remove("open");
    $expandedPlayer.setAttribute("aria-hidden", "true");
    $expandBtn.classList.remove("active");
    if (bigVizRaf) { cancelAnimationFrame(bigVizRaf); bigVizRaf = null; }
    // Clear particle state so next open starts fresh.
    bvParticles.length = 0;
  }

  $expandBtn  .addEventListener("click", () => isExpanded ? closeExpanded() : openExpanded());
  $collapseBtn.addEventListener("click", closeExpanded);
  // Close on backdrop click (click on the ghost area, not the canvas/info).
  $expandedPlayer.addEventListener("click", e => {
    if (e.target === $expandedPlayer) closeExpanded();
  });

  $audio.addEventListener("play", () => {
    if (audioCtx?.state === "suspended") audioCtx.resume();
    ensureAudioGraph();
  });

  // Click the compact dial to toggle play/pause.
  $dial.addEventListener("click", () => {
    if (!$audio.src) return;
    $audio.paused ? $audio.play().catch(() => {}) : $audio.pause();
  });

  // ─── Views ───────────────────────────────────────────────────────────
  // Show/hide the three top-level sections. Only one is visible at a time.
  function showSection(name) {
    $home.classList.toggle("hidden", name !== "home");
    $results.classList.toggle("hidden", name !== "results");
    $transcript.classList.toggle("hidden", name !== "transcript");
  }

  // Year/month index built once from /api/episodes.
  function buildYearIndex(eps) {
    const idx = {};
    for (const ep of eps) {
      const m = /^(\d{4})-(\d{2})/.exec(ep.air_date || "");
      if (!m) continue;
      const y = m[1], mo = m[2];
      if (!idx[y]) idx[y] = { _total: 0 };
      if (!idx[y][mo]) idx[y][mo] = [];
      idx[y][mo].push(ep);
      idx[y]._total++;
    }
    return idx;
  }

  // Deterministic-per-day random pick. Same episode for everyone visiting today.
  function tonightsPick(eps) {
    if (!eps.length) return null;
    const indexed = eps.filter(e => e.transcript_status === "done");
    const pool = indexed.length ? indexed : eps;
    const d = new Date();
    const seed = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
    let h = 5381;
    for (let i = 0; i < seed.length; i++) h = ((h * 33) ^ seed.charCodeAt(i)) >>> 0;
    return pool[h % pool.length];
  }

  const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  async function ensureAllEpisodes(onRetry) {
    if (state.allEpisodes) return state.allEpisodes;
    const data = await api("/api/episodes", null, { onRetry });
    state.allEpisodes = data.episodes;
    state.yearIndex = buildYearIndex(data.episodes);
    return state.allEpisodes;
  }

  async function renderHome(routeYear, routeMonth) {
    state.view = "home";
    showSection("home");
    setMeta({ title: SITE_NAME, description: BASE_DESC });
    setStatus("Listening for whispers…", "loading");

    let eps;
    try {
      eps = await ensureAllEpisodes((n, total) => {
        setStatus(`The archive is waking up… (attempt ${n}/${total})`, "loading");
      });
    } catch {
      setStatus("");
      $browseGrid.innerHTML = `
        <div class="empty">
          <h2>Could not reach the archive</h2>
          <div>The server may be cold-starting or briefly unreachable. Try again in a moment.</div>
          <button type="button" class="retry-btn" id="home-retry-btn">↻ Retry</button>
        </div>`;
      const btn = document.getElementById("home-retry-btn");
      if (btn) btn.addEventListener("click", () => {
        state.allEpisodes = null;
        renderHome(routeYear, routeMonth);
      });
      return;
    }
    if (!eps.length) {
      setStatus("");
      $browseGrid.innerHTML =
        `<div class="empty"><h2>Nothing here yet</h2><div>The archive is empty.</div></div>`;
      return;
    }

    setStatus(`${eps.length} broadcasts unearthed`);

    // ── First-run welcome (only for visitors with no listening history) ─
    renderFirstRun();

    // ── Continue listening hero ──────────────────────────────────────
    renderHero(eps);

    // ── Tonight's pick + recently played + most played ───────────────
    renderTonight(eps);
    renderRecent(eps);
    renderMostPlayed(eps);

    // ── Browse: years + months + grid ────────────────────────────────
    const years = Object.keys(state.yearIndex).sort();
    const defaultYear = years[years.length - 1];
    const activeYear = state.yearIndex[routeYear] ? routeYear : defaultYear;
    const yearData = state.yearIndex[activeYear];
    const monthsInYear = Object.keys(yearData).filter(k => k !== "_total").sort();
    const activeMonth = (routeMonth && yearData[routeMonth]) ? routeMonth : null;

    $yearPills.innerHTML = years.map(y => `
      <button type="button" class="year-pill${y === activeYear ? " active" : ""}" data-year="${y}" role="tab" aria-selected="${y === activeYear}">
        ${y}<span class="pill-count">${state.yearIndex[y]._total}</span>
      </button>
    `).join("");
    $yearPills.querySelectorAll(".year-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        location.hash = `#/y/${btn.dataset.year}`;
      });
    });

    if (monthsInYear.length > 1) {
      $monthPills.classList.remove("hidden");
      $monthPills.innerHTML = `
        <button type="button" class="month-pill${!activeMonth ? " active" : ""}" data-month="" role="tab" aria-selected="${!activeMonth}">All</button>
        ${monthsInYear.map(mo => `
          <button type="button" class="month-pill${mo === activeMonth ? " active" : ""}" data-month="${mo}" role="tab" aria-selected="${mo === activeMonth}">
            ${MONTH_NAMES[parseInt(mo, 10) - 1]}<span class="pill-count">${yearData[mo].length}</span>
          </button>
        `).join("")}
      `;
      $monthPills.querySelectorAll(".month-pill").forEach(btn => {
        btn.addEventListener("click", () => {
          const m = btn.dataset.month;
          location.hash = m ? `#/y/${activeYear}/${m}` : `#/y/${activeYear}`;
        });
      });
    } else {
      $monthPills.classList.add("hidden");
      $monthPills.innerHTML = "";
    }

    // Episodes to show in the browse grid (before filter/sort).
    let baseEps;
    if (activeMonth) {
      baseEps = yearData[activeMonth].slice();
    } else {
      baseEps = monthsInYear.flatMap(mo => yearData[mo]);
    }

    // Reflect persisted filter/sort in the controls.
    syncBrowseControls();
    renderBrowseGrid(baseEps, activeYear, activeMonth);

    // Year/month-aware SEO meta.
    const yearLabel = activeMonth
      ? `${MONTH_NAMES[parseInt(activeMonth, 10) - 1]} ${activeYear}`
      : activeYear;
    if (routeYear) {
      setMeta({
        title: `Bhoot FM episodes from ${yearLabel} — ${SITE_NAME}`,
        description: `Browse and listen to every Bhoot FM episode aired in ${yearLabel}. ${BASE_DESC}`,
      });
    }
  }

  // Render only the grid — used both on initial home render and when the
  // user changes the filter/sort controls (without nuking everything else).
  function renderBrowseGrid(baseEps, activeYear, activeMonth) {
    const filtered = applyBrowseFilterSort(baseEps);
    const total = baseEps.length;
    const showCount = filtered.length;
    const yearLabel = activeMonth
      ? `${MONTH_NAMES[parseInt(activeMonth, 10) - 1]} ${activeYear}`
      : activeYear;
    const filterSuffix = state.browseFilter === "all"
      ? ""
      : ` · ${showCount} of ${total} match "${filterLabel(state.browseFilter)}"`;
    $browseSub.textContent = state.browseFilter === "all"
      ? `${yearLabel} · ${total} episode${total === 1 ? "" : "s"}`
      : `${yearLabel}${filterSuffix}`;
    if (!filtered.length) {
      $browseGrid.innerHTML = `<div class="empty-filter">No episodes match this filter in ${yearLabel}.</div>`;
      return;
    }
    $browseGrid.innerHTML = filtered.map((ep, i) => cardHtml(ep, i)).join("");
    wireEpisodeCards($browseGrid);
    // Stash for re-renders triggered by control changes.
    state._browseBaseEps = baseEps;
    state._browseYear = activeYear;
    state._browseMonth = activeMonth;
  }

  function filterLabel(f) {
    return f === "unplayed" ? "Unplayed"
         : f === "in_progress" ? "In progress"
         : f === "completed" ? "Played" : "All";
  }

  function applyBrowseFilterSort(eps) {
    let out = eps.slice();
    if (state.browseFilter !== "all") {
      out = out.filter(ep => {
        const st = historyStatus(ep.id);
        if (state.browseFilter === "unplayed") return !st;
        if (state.browseFilter === "in_progress") return st?.status === "in_progress";
        if (state.browseFilter === "completed") return st?.status === "completed";
        return true;
      });
    }
    const cmpDateDesc = (a, b) => (b.air_date || "").localeCompare(a.air_date || "");
    const cmpDateAsc  = (a, b) => (a.air_date || "").localeCompare(b.air_date || "");
    const cmpDurDesc  = (a, b) => (b.duration_sec || 0) - (a.duration_sec || 0);
    const cmpDurAsc   = (a, b) => (a.duration_sec || 0) - (b.duration_sec || 0);
    if (state.browseSort === "oldest")        out.sort(cmpDateAsc);
    else if (state.browseSort === "longest")  out.sort(cmpDurDesc);
    else if (state.browseSort === "shortest") out.sort(cmpDurAsc);
    else if (state.browseSort === "random") {
      // Fisher–Yates.
      for (let i = out.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [out[i], out[j]] = [out[j], out[i]];
      }
    }
    else                                       out.sort(cmpDateDesc);
    return out;
  }

  function syncBrowseControls() {
    $filterPills.forEach(p => {
      const on = p.dataset.filter === state.browseFilter;
      p.classList.toggle("active", on);
      p.setAttribute("aria-checked", on ? "true" : "false");
    });
    if ($sortSelect) $sortSelect.value = state.browseSort;
  }

  $filterPills.forEach(p => {
    p.addEventListener("click", () => {
      state.browseFilter = p.dataset.filter;
      saveBrowsePrefs();
      syncBrowseControls();
      if (state._browseBaseEps) {
        renderBrowseGrid(state._browseBaseEps, state._browseYear, state._browseMonth);
      }
    });
  });
  if ($sortSelect) {
    $sortSelect.addEventListener("change", () => {
      state.browseSort = $sortSelect.value;
      saveBrowsePrefs();
      if (state._browseBaseEps) {
        renderBrowseGrid(state._browseBaseEps, state._browseYear, state._browseMonth);
      }
    });
  }

  // ── First-run welcome panel ───────────────────────────────────────────
  const FIRST_RUN_DISMISSED_KEY = "bfa_first_run_dismissed_v1";
  function renderFirstRun() {
    if (!$firstRun) return;
    let dismissed = false;
    try { dismissed = !!localStorage.getItem(FIRST_RUN_DISMISSED_KEY); } catch {}
    const hasHistory = Object.keys(historyLoad()).length > 0;
    if (dismissed || hasHistory) { $firstRun.classList.add("hidden"); return; }
    $firstRun.classList.remove("hidden");
    // Wire example chips inside the panel (idempotent — clones avoid dupes).
    $firstRun.querySelectorAll(".how-eg").forEach(btn => {
      const clone = btn.cloneNode(true);
      btn.replaceWith(clone);
      clone.addEventListener("click", () => {
        const q = clone.dataset.q || clone.textContent.trim();
        $q.value = q;
        location.hash = `#/q/${encodeURIComponent(q)}`;
      });
    });
  }
  if ($firstRunDismiss) {
    $firstRunDismiss.addEventListener("click", () => {
      try { localStorage.setItem(FIRST_RUN_DISMISSED_KEY, "1"); } catch {}
      $firstRun.classList.add("hidden");
    });
  }

  // ── Hero: continue listening ──────────────────────────────────────────
  function renderHero(eps) {
    const $resumeBody = document.getElementById("hero-resume-body");
    const $emptyBody = document.getElementById("hero-empty-body");
    const $label = document.getElementById("hero-label");
    const inProg = historyInProgress();
    const epById = new Map(eps.map(e => [e.id, e]));
    const top = inProg.find(r => epById.has(r.id));

    if (!top) {
      // No in-progress episode. Only show an empty-state hero if the user has
      // *some* history (otherwise the first-run welcome covers this slot).
      const hasAnyHistory = Object.keys(historyLoad()).length > 0;
      if (!hasAnyHistory) {
        $heroResume.classList.add("hidden");
        return;
      }
      $heroResume.classList.remove("hidden");
      $heroResume.classList.add("hero-empty");
      if ($label) $label.textContent = "▶ Continue listening";
      if ($resumeBody) $resumeBody.classList.add("hidden");
      if ($emptyBody) $emptyBody.classList.remove("hidden");
      delete $heroResume.dataset.epId;
      return;
    }

    const ep = epById.get(top.id);
    $heroResume.classList.remove("hidden");
    $heroResume.classList.remove("hero-empty");
    if ($label) $label.textContent = "▶ Continue listening";
    if ($resumeBody) $resumeBody.classList.remove("hidden");
    if ($emptyBody) $emptyBody.classList.add("hidden");
    $heroResume.dataset.epId = ep.id;
    $heroResume.dataset.pos = String(top.pos || 0);
    $heroResume.dataset.dur = String(top.dur || ep.duration_sec || 0);
    $heroTitle.textContent = ep.title;
    $heroMeta.textContent = `${fmtDate(ep.air_date)} · ${fmtTs(top.pos || 0)} / ${fmtTs(top.dur || ep.duration_sec || 0)}`;
    $heroProgressFill.style.width = `${(top.pct * 100).toFixed(1)}%`;
    $heroResumeTime.textContent = `from ${fmtTs(top.pos || 0)}`;
  }

  // ── Tonight's pick (deterministic per day) ────────────────────────────
  function renderTonight(eps) {
    const pick = tonightsPick(eps);
    if (!pick) { $railTonight.classList.add("hidden"); return; }
    $railTonight.classList.remove("hidden");
    state._tonightPick = pick;
    $railTonightCards.innerHTML = cardHtml(pick, 0);
    wireEpisodeCards($railTonightCards);
    wireTonightActions(eps);
  }

  function wireTonightActions(eps) {
    const $play = document.getElementById("tonight-play-btn");
    const $reroll = document.getElementById("tonight-reroll-btn");
    if ($play && !$play.dataset.wired) {
      $play.dataset.wired = "1";
      $play.addEventListener("click", () => {
        const pick = state._tonightPick;
        if (pick) location.hash = `#/ep/${pick.id}`;
      });
    }
    if ($reroll && !$reroll.dataset.wired) {
      $reroll.dataset.wired = "1";
      $reroll.addEventListener("click", () => {
        const indexed = eps.filter(e => e.transcript_status === "done");
        const pool = indexed.length ? indexed : eps;
        if (!pool.length) return;
        let next;
        do { next = pool[Math.floor(Math.random() * pool.length)]; }
        while (pool.length > 1 && next.id === state._tonightPick?.id);
        state._tonightPick = next;
        $railTonightCards.innerHTML = cardHtml(next, 0);
        wireEpisodeCards($railTonightCards);
      });
    }
  }

  // ── Recently played rail ──────────────────────────────────────────────
  function renderRecent(eps) {
    const recent = historyRecent(8);
    if (!recent.length) { $railRecent.classList.add("hidden"); return; }
    const epById = new Map(eps.map(e => [e.id, e]));
    const items = recent
      .map(r => epById.get(r.id))
      .filter(Boolean)
      .slice(0, 6);
    if (!items.length) { $railRecent.classList.add("hidden"); return; }
    $railRecent.classList.remove("hidden");
    $railRecentCards.innerHTML = items.map((ep, i) => cardHtml(ep, i)).join("");
    wireEpisodeCards($railRecentCards);
  }

  // ── Most played rail (server-side, global across all visitors) ──────
  async function renderMostPlayed(_eps) {
    try {
      const data = await api("/api/popular", { limit: 3 });
      const items = data.episodes || [];
      if (!items.length) { $railMostPlayed.classList.add("hidden"); return; }
      $railMostPlayed.classList.remove("hidden");
      $railMostPlayedCards.innerHTML = items.map((ep, i) => cardHtml(ep, i)).join("");
      wireEpisodeCards($railMostPlayedCards);
    } catch {
      $railMostPlayed.classList.add("hidden");
    }
  }

  // Ping /api/play once per (episode, device) after >=15 seconds played.
  // localStorage flag prevents double-counting on this device.
  const PINGED_KEY_PREFIX = "bfa_pinged_";
  function maybePingPlay(epId, pos) {
    if (!epId || pos < HIST_MIN_POS_SEC) return;
    const key = PINGED_KEY_PREFIX + epId;
    try { if (localStorage.getItem(key)) return; localStorage.setItem(key, "1"); }
    catch { return; }
    fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_id: epId }),
    }).then(r => {
      if (!r.ok) { try { localStorage.removeItem(key); } catch {} }
    }).catch(() => { try { localStorage.removeItem(key); } catch {} });
  }

  // Play an episode in place — used by every homepage card click. Resumes
  // at saved position when there is one, otherwise starts from 0. The URL
  // does NOT change, so the user stays on whatever browse view they were
  // looking at. The segments page is still reachable by clicking the
  // now-playing title in the player bar.
  async function playEpisodeInline(epId, opts = {}) {
    let ep = state.allEpisodes?.find(e => e.id === epId);
    if (!ep) {
      try { const d = await api(`/api/episode/${epId}`); ep = d.episode; }
      catch { setStatus("Could not load that broadcast.", "error"); return; }
    }
    let startSec = opts.start;
    if (startSec == null) {
      const st = historyStatus(epId);
      startSec = (st && st.status === "in_progress") ? (st.pos || 0) : 0;
    }
    playEpisodeAt(ep, startSec);
  }

  // Common click/context-menu wiring for any container holding episode cards.
  function wireEpisodeCards(container) {
    container.querySelectorAll(".episode-card").forEach(card => {
      card.addEventListener("click", () => {
        playEpisodeInline(card.dataset.epId);
      });
      // Right-click (desktop) and long-press (touch) → context menu.
      card.addEventListener("contextmenu", e => {
        e.preventDefault();
        openCardMenu(e.clientX, e.clientY, card.dataset.epId);
      });
      let pressTimer = null;
      card.addEventListener("touchstart", e => {
        const t = e.touches[0];
        pressTimer = setTimeout(() => {
          openCardMenu(t.clientX, t.clientY, card.dataset.epId);
        }, 520);
      }, { passive: true });
      const cancelPress = () => { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } };
      card.addEventListener("touchend", cancelPress);
      card.addEventListener("touchmove", cancelPress);
      card.addEventListener("touchcancel", cancelPress);
    });
  }

  async function renderSearch(q) {
    state.view = "results";
    state.query = q;
    $q.value = q;
    showSection("results");
    setMeta({
      title: `"${q}" — ${SITE_NAME}`,
      description: `Search results for "${q}" in the Bhoot FM Archive.`,
    });
    setStatus("Searching the static…", "loading");

    // Banglish → Bangla fallback. If the user typed in Latin (e.g. "hospital",
    // "ambulance"), transliterate to Bangla and search the converted query.
    // Transcripts are pure Bangla, so the original Latin form would otherwise
    // hit zero — this is the difference between "no results" and useful hits.
    const tr = (typeof banglishToBangla === "function")
      ? banglishToBangla(q)
      : { bangla: q, original: q, transformed: false };
    const effectiveQ = tr.transformed ? tr.bangla : q;
    try {
      const data = await api("/api/search", { q: effectiveQ, limit: 200 });
      if (data.total === 0) {
        const hasBangla = /[ঀ-৿]/.test(q);
        const hint = hasBangla
          ? ""
          : `<div class="empty-hint">
               Transcripts are in <strong>Bangla</strong>. ${tr.transformed
                 ? `We searched for <strong lang="bn">${escapeHtml(tr.bangla)}</strong> and still found nothing — try a different Bangla word.`
                 : `Try a Bangla word —`}
               <button type="button" class="how-eg" data-q="অ্যাম্বুলেন্স">অ্যাম্বুলেন্স</button>
               <button type="button" class="how-eg" data-q="হাসপাতাল">হাসপাতাল</button>
               <button type="button" class="how-eg" data-q="বাড়ি">বাড়ি</button>
             </div>`;
        $results.innerHTML =
          `<div class="empty"><h2>Silence</h2>
           <div>No echoes of "${escapeHtml(q)}" in the archive.</div>
           ${hint}</div>`;
        setStatus(`0 echoes for "${q}"`);
        // Re-wire newly inserted example chips.
        $results.querySelectorAll(".how-eg").forEach(btn => {
          btn.addEventListener("click", () => {
            const eq = btn.dataset.q || btn.textContent.trim();
            $q.value = eq;
            location.hash = `#/q/${encodeURIComponent(eq)}`;
          });
        });
        return;
      }
      const byEpisode = new Map();
      for (const hit of data.results) {
        if (!byEpisode.has(hit.episode_id)) {
          byEpisode.set(hit.episode_id, {
            episode_id: hit.episode_id,
            episode_title: hit.episode_title,
            episode_date: hit.episode_date,
            mp3_url: hit.mp3_url,
            hits: [],
          });
        }
        byEpisode.get(hit.episode_id).hits.push({ start_sec: hit.start_sec });
      }
      setStatus(
        `${data.total} echo${data.total > 1 ? "es" : ""} across ${byEpisode.size} broadcast${byEpisode.size > 1 ? "s" : ""}`
      );
      const translitNotice = tr.transformed
        ? `<div class="translit-notice">
             Showing results for <strong lang="bn">${escapeHtml(tr.bangla)}</strong>
             <span class="translit-from">— transliterated from <em>${escapeHtml(tr.original)}</em></span>
           </div>`
        : "";
      $results.innerHTML = translitNotice + [...byEpisode.values()].map((ep, i) => `
        <div class="card card-appear" data-ep-id="${ep.episode_id}" style="animation-delay: ${Math.min(i, 20) * 22}ms">
          <div class="card-head">
            <div>
              <div class="card-title">${escapeHtml(ep.episode_title)}</div>
              <div class="card-date">${fmtDate(ep.episode_date)}</div>
            </div>
            <div class="card-count">${ep.hits.length} ${ep.hits.length === 1 ? "trace" : "traces"}</div>
          </div>
          <div class="markers">
            ${ep.hits.map(h => `
              <div class="marker-group">
                <button class="marker" data-ep-id="${ep.episode_id}" data-at="${h.start_sec}" aria-label="Play at ${fmtTs(h.start_sec)}">
                  ${fmtTs(h.start_sec)}
                </button>
                <button class="marker-share" data-share-ep="${ep.episode_id}" data-share-at="${h.start_sec}" title="Copy link to this moment" aria-label="Copy link to ${fmtTs(h.start_sec)}">🔗</button>
              </div>
            `).join("")}
          </div>
        </div>
      `).join("");
      $results.querySelectorAll(".marker").forEach(btn => {
        btn.addEventListener("click", async () => {
          const epId = btn.dataset.epId;
          const at = parseFloat(btn.dataset.at);
          const data = await api(`/api/episode/${epId}`);
          playEpisodeAt(data.episode, at);
        });
      });
      $results.querySelectorAll(".marker-share").forEach(btn => {
        btn.addEventListener("click", e => {
          e.stopPropagation();
          shareTimestampLink(btn.dataset.shareEp, parseFloat(btn.dataset.shareAt), btn);
        });
      });
    } catch (e) {
      setStatus("Search failed.", "error");
    }
  }

  async function renderTranscript(episodeId, at) {
    state.view = "transcript";
    showSection("transcript");
    setStatus("Opening the broadcast…", "loading");
    try {
      const data = await api(`/api/episode/${episodeId}`);
      state.currentEpisode = data.episode;
      state.currentSegments = data.segments;
      $tTitle.textContent = data.episode.title;
      $tMeta.textContent =
        `${fmtDate(data.episode.air_date)}${data.episode.duration_sec ? " · " + fmtTs(data.episode.duration_sec) : ""}${data.segments.length ? " · " + data.segments.length + " markers" : ""}`;
      setMeta({
        title: `${data.episode.title} — ${SITE_NAME}`,
        description: `${data.episode.title}. Listen to this Bhoot FM episode at any moment.`,
      });
      $tSegs.innerHTML = data.segments.map((s, i) => `
        <div class="marker-group">
          <button class="marker" data-seg-idx="${i}" data-start="${s.start_sec}" aria-label="Play at ${fmtTs(s.start_sec)}">
            ${fmtTs(s.start_sec)}
          </button>
          <button class="marker-share" data-share-at="${s.start_sec}" title="Copy link to this moment" aria-label="Copy link to ${fmtTs(s.start_sec)}">🔗</button>
        </div>
      `).join("");
      setStatus("");
      $tSegs.querySelectorAll(".marker").forEach(row => {
        row.addEventListener("click", () => {
          playEpisodeAt(data.episode, parseFloat(row.dataset.start));
        });
      });
      $tSegs.querySelectorAll(".marker-share").forEach(btn => {
        btn.addEventListener("click", e => {
          e.stopPropagation();
          const at = parseFloat(btn.dataset.shareAt);
          shareTimestampLink(data.episode.id, at, btn);
        });
      });
      // Decide where to start playback:
      //   1. Explicit ?at=… from the URL wins.
      //   2. Otherwise, if there's a saved in-progress position, resume there.
      //   3. Otherwise, start from 0.
      let startAt = (at != null && !isNaN(at)) ? at : null;
      if (startAt == null) {
        const st = historyStatus(data.episode.id);
        if (st && st.status === "in_progress") startAt = st.pos || 0;
      }
      if (startAt == null) startAt = 0;
      playEpisodeAt(data.episode, startAt);
      if (startAt > 0) {
        const idx = data.segments.findIndex(s => s.start_sec >= startAt - 1);
        const target = $tSegs.querySelector(`.marker[data-seg-idx="${Math.max(0, idx)}"]`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (e) {
      setStatus("Could not open broadcast.", "error");
    }
  }

  // Highlight the currently-playing marker. Works for both native and Webamp.
  let lastHighlight = -1;
  function updateMarkerHighlight() {
    if (state.view !== "transcript") return;
    const t = currentTimeSec;
    const idx = state.currentSegments.findIndex(
      (s, i) =>
        t >= s.start_sec &&
        (i === state.currentSegments.length - 1 ||
          t < state.currentSegments[i + 1].start_sec)
    );
    if (idx !== lastHighlight) {
      const prev = $tSegs.querySelector(".marker.active");
      if (prev) prev.classList.remove("active");
      if (idx >= 0) {
        const el = $tSegs.querySelector(`.marker[data-seg-idx="${idx}"]`);
        if (el) el.classList.add("active");
      }
      lastHighlight = idx;
    }
  }
  $audio.addEventListener("timeupdate", () => {
    currentTimeSec = $audio.currentTime;
    updateMarkerHighlight();
  });

  // ─── Prev / Next episode ─────────────────────────────────────────────
  function updateSkipButtons() {
    const eps = state.allEpisodes;
    const epId = $audio.dataset.episodeId;
    if (!eps || !epId) {
      $prevBtn.disabled = true;
      $nextBtn.disabled = true;
      return;
    }
    const idx = eps.findIndex(e => e.id === epId);
    // Episodes are sorted newest-first, so:
    //   prev (⏮) = lower index  = newer episode
    //   next (⏭) = higher index = older episode
    $prevBtn.disabled = idx <= 0;
    $nextBtn.disabled = idx < 0 || idx >= eps.length - 1;
  }

  async function skipEpisode(dir) {
    // Ensure we have the full list.
    if (!state.allEpisodes) {
      try {
        const d = await api("/api/episodes");
        state.allEpisodes = d.episodes;
      } catch { return; }
    }
    const eps = state.allEpisodes;
    const epId = $audio.dataset.episodeId;
    if (!epId) return;
    const idx = eps.findIndex(e => e.id === epId);
    if (idx === -1) return;
    const target = eps[idx + dir];
    if (!target) return;
    // Fetch full episode data, start playing immediately, then navigate.
    try {
      const data = await api(`/api/episode/${target.id}`);
      playEpisodeAt(data.episode, 0);
      location.hash = `#/ep/${target.id}`;
    } catch { return; }
  }

  $prevBtn.addEventListener("click", () => skipEpisode(-1));
  $nextBtn.addEventListener("click", () => skipEpisode(+1));

  // Auto-advance to next episode when one finishes — unless sleep timer
  // asked us to stop at the end of the episode.
  $audio.addEventListener("ended", () => {
    if (sleepStopAtEnd) {
      sleepStopAtEnd = false;
      sleepClear();
      whisperToast("☾ sleep · stopped at end of episode");
      return;
    }
    skipEpisode(+1);
  });

  // ─── Share a timestamp ───────────────────────────────────────────────
  async function shareTimestampLink(epId, atSec, btn) {
    const at = Math.max(0, Math.floor(atSec));
    const url = `${location.origin}/#/ep/${epId}/${at}`;
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
        ok = true;
      } else {
        // Fallback for http://localhost dev or older browsers.
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;";
        document.body.appendChild(ta);
        ta.select();
        ok = document.execCommand("copy");
        ta.remove();
      }
    } catch {
      ok = false;
    }
    if (btn) {
      btn.classList.add(ok ? "copied" : "copy-failed");
      setTimeout(() => btn.classList.remove("copied", "copy-failed"), 1400);
    }
    whisperToast(ok ? "link copied · " + fmtTs(at) : "could not copy — long-press to copy manually");
  }

  // ─── Random episode ──────────────────────────────────────────────────
  async function randomEpisode() {
    let eps = state.allEpisodes;
    if (!eps) {
      try {
        const d = await api("/api/episodes");
        eps = d.episodes;
      } catch { return; }
    }
    if (!eps || !eps.length) return;
    // Prefer indexed ones if any are present, else any.
    const indexed = eps.filter(e => e.transcript_status === "done");
    const pool = indexed.length ? indexed : eps;
    const pick = pool[Math.floor(Math.random() * pool.length)];
    playEpisodeInline(pick.id);
  }

  // ─── Rotating tagline (very subtle) ──────────────────────────────────
  let taglineIdx = 0;
  function rotateTagline() {
    if (document.hidden) return;
    taglineIdx = (taglineIdx + 1) % TAGLINES.length;
    $rotatingTagline.style.opacity = "0";
    setTimeout(() => {
      $rotatingTagline.textContent = TAGLINES[taglineIdx];
      $rotatingTagline.style.opacity = "0.8";
    }, 500);
  }
  $rotatingTagline.style.transition = "opacity 0.5s ease";

  // ─── Spotify-style player controls ───────────────────────────────────
  function setPlayingUI(playing) {
    $playBtn.classList.toggle("playing", playing);
    $playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  }
  function updateScrubber() {
    const d = $audio.duration || 0;
    const c = $audio.currentTime || 0;
    const pct = d > 0 ? (c / d) * 100 : 0;
    $scrubFill.style.width = pct + "%";
    $scrubThumb.style.left = pct + "%";
    $scrubber.setAttribute("aria-valuenow", Math.round(pct));
    $timeCur.textContent = fmtTs(c);
    $timeDur.textContent = d > 0 ? fmtTs(d) : "0:00";
    // Live countdown in the expanded player.
    if (isExpanded && d > 0) {
      const remaining = Math.max(0, d - c);
      $expEpMeta.textContent = fmtTs(Math.ceil(remaining)) + " remaining";
    }
  }
  function updateBuffer() {
    try {
      const b = $audio.buffered;
      if (b && b.length && $audio.duration) {
        const end = b.end(b.length - 1);
        $scrubBuffer.style.width = ((end / $audio.duration) * 100) + "%";
      }
    } catch {}
  }
  // Clicking the now-playing title/meta navigates to that episode's page.
  document.querySelector(".now").addEventListener("click", () => {
    const epId = $audio.dataset.episodeId;
    if (epId) location.hash = `#/ep/${epId}`;
  });

  $playBtn.addEventListener("click", () => {
    if (!$audio.src) return;
    if ($audio.paused) $audio.play().catch(() => {});
    else $audio.pause();
  });
  $audio.addEventListener("play", () => { setPlayingUI(true); updateMediaSessionState(); });
  $audio.addEventListener("pause", () => { setPlayingUI(false); updateMediaSessionState(); });
  $audio.addEventListener("ended", () => { setPlayingUI(false); updateMediaSessionState(); });
  $audio.addEventListener("loadedmetadata", () => { updateScrubber(); updateMediaSessionState(); });
  $audio.addEventListener("durationchange", () => { updateScrubber(); updateMediaSessionState(); });
  $audio.addEventListener("ratechange", updateMediaSessionState);
  $audio.addEventListener("progress", updateBuffer);
  // Scrubber updates 4×/sec — plenty for the visual, far cheaper than
  // RAF (60fps) for what's just a width change. setInterval is paused
  // automatically by the browser on background tabs.
  let scrubInterval = null;
  $audio.addEventListener("play", () => {
    if (!scrubInterval) scrubInterval = setInterval(updateScrubber, 250);
  });
  $audio.addEventListener("pause", () => {
    if (scrubInterval) { clearInterval(scrubInterval); scrubInterval = null; }
    updateScrubber();
  });

  // Scrubber: click + drag to seek (pointer events handle mouse + touch).
  let scrubDragging = false;
  function seekFromEvent(e) {
    const rect = $scrubber.getBoundingClientRect();
    const x = (e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? 0) - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    if ($audio.duration) $audio.currentTime = pct * $audio.duration;
    updateScrubber();
  }
  $scrubber.addEventListener("pointerdown", e => {
    if (!$audio.src || !$audio.duration) return;
    scrubDragging = true;
    $scrubber.classList.add("dragging");
    $scrubber.setPointerCapture(e.pointerId);
    seekFromEvent(e);
  });
  $scrubber.addEventListener("pointermove", e => {
    if (scrubDragging) seekFromEvent(e);
  });
  function endScrub(e) {
    if (!scrubDragging) return;
    scrubDragging = false;
    $scrubber.classList.remove("dragging");
    try { $scrubber.releasePointerCapture(e.pointerId); } catch {}
  }
  $scrubber.addEventListener("pointerup", endScrub);
  $scrubber.addEventListener("pointercancel", endScrub);
  // Keyboard scrubbing (←/→ = 5s, Shift+ = 30s).
  $scrubber.addEventListener("keydown", e => {
    if (!$audio.duration) return;
    const step = e.shiftKey ? 30 : 5;
    if (e.key === "ArrowRight") { $audio.currentTime = Math.min($audio.duration, $audio.currentTime + step); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { $audio.currentTime = Math.max(0, $audio.currentTime - step); e.preventDefault(); }
    else if (e.key === "Home") { $audio.currentTime = 0; e.preventDefault(); }
    else if (e.key === "End") { $audio.currentTime = $audio.duration; e.preventDefault(); }
  });

  // ─── Sleep timer ─────────────────────────────────────────────────────
  // "Off" | "end" | minutes-as-number. "end" stops at end of current episode
  // by disabling auto-advance for one ended event.
  let sleepMode = "off";
  let sleepDeadline = 0;        // ms timestamp when fixed-minute timer fires
  let sleepTickInterval = null;
  let sleepStopAtEnd = false;   // honoured by the "ended" handler below

  function sleepRender() {
    $expSleepPills.forEach(p => {
      const v = p.dataset.sleep;
      const on = (sleepMode === "off" && v === "0")
              || (sleepMode === "end" && v === "end")
              || (typeof sleepMode === "number" && String(sleepMode) === v);
      p.classList.toggle("active", on);
      p.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (!$expSleepStatus) return;
    if (sleepMode === "off") $expSleepStatus.textContent = "";
    else if (sleepMode === "end") $expSleepStatus.textContent = "⏸ will stop at end of episode";
    else if (typeof sleepMode === "number") {
      const remainingMs = Math.max(0, sleepDeadline - Date.now());
      const m = Math.floor(remainingMs / 60000);
      const s = Math.floor((remainingMs % 60000) / 1000);
      $expSleepStatus.textContent = `☾ sleeping in ${m}:${String(s).padStart(2, "0")}`;
    }
  }

  function sleepClear() {
    sleepMode = "off";
    sleepStopAtEnd = false;
    sleepDeadline = 0;
    if (sleepTickInterval) { clearInterval(sleepTickInterval); sleepTickInterval = null; }
    sleepRender();
  }

  function sleepSet(value) {
    if (value === "0" || value === 0) { sleepClear(); return; }
    if (value === "end") {
      sleepMode = "end";
      sleepStopAtEnd = true;
      if (sleepTickInterval) { clearInterval(sleepTickInterval); sleepTickInterval = null; }
      sleepRender();
      whisperToast("sleep · stop at end of episode");
      return;
    }
    const mins = parseInt(value, 10);
    if (!mins || mins <= 0) { sleepClear(); return; }
    sleepMode = mins;
    sleepStopAtEnd = false;
    sleepDeadline = Date.now() + mins * 60_000;
    if (sleepTickInterval) clearInterval(sleepTickInterval);
    sleepTickInterval = setInterval(() => {
      const remaining = sleepDeadline - Date.now();
      if (remaining <= 0) {
        try { $audio.pause(); } catch {}
        whisperToast("☾ sleep timer · paused");
        sleepClear();
        return;
      }
      sleepRender();
    }, 1000);
    sleepRender();
    whisperToast(`sleep timer · ${mins} min`);
  }

  $expSleepPills.forEach(p => {
    p.addEventListener("click", () => sleepSet(p.dataset.sleep));
  });

  // ─── Playback speed ──────────────────────────────────────────────────
  const RATE_KEY = "bfa_playback_rate_v1";
  function applyRate(r) {
    const rate = parseFloat(r) || 1;
    try { $audio.playbackRate = rate; } catch {}
    try { localStorage.setItem(RATE_KEY, String(rate)); } catch {}
    $expRatePills.forEach(p => {
      const on = parseFloat(p.dataset.rate) === rate;
      p.classList.toggle("active", on);
      p.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  // Restore saved rate.
  try {
    const saved = parseFloat(localStorage.getItem(RATE_KEY));
    if (saved && saved > 0) applyRate(saved);
  } catch {}
  $expRatePills.forEach(p => {
    p.addEventListener("click", () => applyRate(p.dataset.rate));
  });
  // Re-apply rate when a new source is loaded (browsers reset on load).
  $audio.addEventListener("loadedmetadata", () => {
    try {
      const saved = parseFloat(localStorage.getItem(RATE_KEY)) || 1;
      $audio.playbackRate = saved;
    } catch {}
  });

  // ─── Easter eggs ─────────────────────────────────────────────────────
  // Tiny system for blood drips from anywhere on screen.
  function bleedAt(x, y, opts = {}) {
    if (!$dripLayer) return;
    const n = opts.count ?? (3 + Math.floor(Math.random() * 4));
    for (let i = 0; i < n; i++) {
      const drop = document.createElement("div");
      drop.className = "blood-drop";
      const jitterX = (Math.random() - 0.5) * 30;
      const fall    = 60 + Math.random() * (opts.fall ?? 200);
      const delay   = Math.random() * 200;
      const width   = 1.5 + Math.random() * 2.5;
      drop.style.cssText =
        `left:${x + jitterX}px;top:${y}px;` +
        `--fall:${fall}px;--w:${width}px;` +
        `animation-delay:${delay}ms;` +
        `animation-duration:${800 + Math.random() * 700}ms;`;
      $dripLayer.appendChild(drop);
      setTimeout(() => drop.remove(), 2200);
    }
  }
  // Subtle screen-edge bleed (vignette flicker).
  function screenBleed(duration = 1400) {
    document.body.classList.add("bleeding");
    setTimeout(() => document.body.classList.remove("bleeding"), duration);
  }

  // Clicking the eye → home. Clicking it 13 times within 8s also unlocks
  // a brief blood shower (rare easter egg).
  let eyeClicks = 0, eyeClickTimer = null;
  $eye.addEventListener("click", () => {
    eyeClicks++;
    clearTimeout(eyeClickTimer);
    eyeClickTimer = setTimeout(() => { eyeClicks = 0; }, 8000);
    if (eyeClicks >= 13) {
      eyeClicks = 0;
      for (let i = 0; i < 14; i++) {
        bleedAt(Math.random() * window.innerWidth, -5, { count: 1, fall: 400 });
      }
      screenBleed(2200);
      whisperToast("you saw");
      return; // skip the home-navigation on the unlock click
    }
    location.hash = "";
  });

  // Egg 2: typing one of the spooky keywords in the search bar triggers
  // a brief screen bleed.
  const HORROR_WORDS = ["ভূত", "প্রেত", "রাত", "ghost", "spirit", "demon", "bhoot"];
  let lastHorrorTrigger = 0;
  $q.addEventListener("input", () => {
    const v = $q.value.toLowerCase();
    const hit = HORROR_WORDS.some(w => v.includes(w.toLowerCase()));
    if (hit && Date.now() - lastHorrorTrigger > 6000) {
      lastHorrorTrigger = Date.now();
      screenBleed(900);
    }
  });

  // Egg 3: the witching hour. Between 3:00 – 3:33 AM local time the page
  // is *very slightly* dimmer and gets a one-time toast on first load.
  const now = new Date();
  if (now.getHours() === 3 && now.getMinutes() <= 33) {
    document.body.classList.add("witching-hour");
    setTimeout(() => whisperToast("…3 am. it’s listening too."), 1500);
  }

  // Egg 4: while an episode is playing, every minute there's a 1-in-40
  // chance a faint shadow figure drifts across the bottom of the page.
  setInterval(() => {
    if ($audio.paused) return;
    if (Math.random() > 1 / 40) return;
    spawnShadow();
  }, 60_000);

  function spawnShadow() {
    const fig = document.createElement("div");
    fig.className = "shadow-figure";
    fig.style.setProperty("--y", (window.innerHeight - 80 - Math.random() * 40) + "px");
    fig.style.setProperty("--from", (-80) + "px");
    fig.style.setProperty("--to", (window.innerWidth + 80) + "px");
    fig.style.setProperty("--dur", (8 + Math.random() * 6) + "s");
    if (Math.random() < 0.5) fig.classList.add("reversed");
    $dripLayer.appendChild(fig);
    setTimeout(() => fig.remove(), 16000);
  }

  // Lightweight whisper toast (no inline scripts — CSS animated).
  function whisperToast(msg) {
    const t = document.createElement("div");
    t.className = "whisper-toast";
    t.textContent = msg;
    $dripLayer.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  // ─── Wiring ─────────────────────────────────────────────────────────
  const debouncedSearch = debounce(q => {
    if (!q.trim()) { location.hash = ""; return; }
    location.hash = `#/q/${encodeURIComponent(q.trim())}`;
  }, 250);

  $form.addEventListener("submit", e => { e.preventDefault(); debouncedSearch($q.value); });
  $q.addEventListener("input", () => debouncedSearch($q.value));
  $back.addEventListener("click", () => history.back());

  // Example-search chips in the how-to hint ("try ভূত / রাত / বাড়ি").
  document.querySelectorAll(".how-eg").forEach(btn => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.q || btn.textContent.trim();
      $q.value = q;
      location.hash = `#/q/${encodeURIComponent(q)}`;
    });
  });
  $randomBtn.addEventListener("click", randomEpisode);
  window.addEventListener("hashchange", route);

  // Keyboard shortcuts
  document.addEventListener("keydown", e => {
    const target = e.target;
    const inField = target.tagName === "INPUT" || target.tagName === "TEXTAREA";
    if (e.key === "/" && !inField) { e.preventDefault(); $q.focus(); }
    else if (e.key.toLowerCase() === "r" && !inField) { randomEpisode(); }
    else if (e.key === "Escape") {
      if (isExpanded) { closeExpanded(); }
      else if (inField) target.blur();
      else if (state.view !== "episodes") history.back();
    }
    else if (e.key === " " && !inField && $audio.src) {
      e.preventDefault();
      $audio.paused ? $audio.play() : $audio.pause();
    }
  });

  // (eye click → home is wired in the easter-egg section.)

  // Track the type of the last route so we only reset scroll when the
  // view kind actually changes. Within the same view (e.g. refining a
  // search), we leave the scroll position alone.
  let lastRouteType = null;
  let lastRouteId = null;
  function route() {
    const r = readHash();
    const viewKindChanged = r.type !== lastRouteType;
    const episodeChanged  = r.type === "ep" && r.id !== lastRouteId;
    if (viewKindChanged || episodeChanged) scrollToTop();
    lastRouteType = r.type;
    lastRouteId   = r.type === "ep" ? r.id : null;
    if (r.type === "query") return renderSearch(r.q);
    if (r.type === "ep")    return renderTranscript(r.id, r.at);
    return renderHome(r.year, r.month);
  }
  function scrollToTop() {
    try { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); }
    catch { window.scrollTo(0, 0); }
  }

  // Don't let the browser restore old scroll positions when navigating
  // between hash routes — we manage scrolling deliberately in route().
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  // ─── Position saving (listening history) ────────────────────────────
  function saveCurrentPosition() {
    const epId = $audio.dataset.episodeId;
    if (!epId) return;
    const dur = $audio.duration;
    const pos = $audio.currentTime;
    if (!dur || !isFinite(dur) || dur <= 0) return;
    historyUpdate(epId, pos, dur);
    maybePingPlay(epId, pos);
  }
  let posSaveInterval = null;
  $audio.addEventListener("play", () => {
    if (!posSaveInterval) posSaveInterval = setInterval(saveCurrentPosition, 5000);
  });
  $audio.addEventListener("pause", () => {
    if (posSaveInterval) { clearInterval(posSaveInterval); posSaveInterval = null; }
    saveCurrentPosition();
  });
  $audio.addEventListener("ended", () => {
    const epId = $audio.dataset.episodeId;
    const dur = $audio.duration;
    if (epId && dur) historyMarkPlayed(epId, dur);
  });
  window.addEventListener("pagehide", saveCurrentPosition);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) saveCurrentPosition();
  });

  // ─── Hero (continue listening) actions ───────────────────────────────
  $heroResumeBtn.addEventListener("click", () => {
    const epId = $heroResume.dataset.epId;
    const pos = parseFloat($heroResume.dataset.pos) || 0;
    if (!epId) return;
    playEpisodeInline(epId, { start: Math.floor(pos) });
  });
  $heroRestartBtn.addEventListener("click", () => {
    const epId = $heroResume.dataset.epId;
    if (!epId) return;
    historyRemove(epId);
    playEpisodeInline(epId, { start: 0 });
    renderHome(readHash().year, readHash().month);
  });
  $heroDismissBtn.addEventListener("click", () => {
    const epId = $heroResume.dataset.epId;
    const dur = parseFloat($heroResume.dataset.dur) || 0;
    if (!epId) return;
    historyMarkPlayed(epId, dur);
    if (state.view === "home") renderHome(readHash().year, readHash().month);
  });

  // ─── Reset listening history + recent rail clear ─────────────────────
  if ($resetHistoryBtn) {
    $resetHistoryBtn.addEventListener("click", () => {
      if (!confirm("Clear all listening history on this device?")) return;
      historyClear();
      whisperToast("listening history cleared");
      if (state.view === "home") renderHome(readHash().year, readHash().month);
    });
  }
  if ($railRecentClear) {
    $railRecentClear.addEventListener("click", () => {
      if (!confirm("Clear recently-played list?")) return;
      historyClear();
      whisperToast("history cleared");
      renderHome(readHash().year, readHash().month);
    });
  }

  // ─── Card context menu (mark played / remove from history) ───────────
  let $cardMenu = null;
  function closeCardMenu() {
    if ($cardMenu) { $cardMenu.remove(); $cardMenu = null; }
    document.removeEventListener("click", closeCardMenu, true);
    document.removeEventListener("keydown", onCardMenuKey, true);
  }
  function onCardMenuKey(e) { if (e.key === "Escape") closeCardMenu(); }
  function openCardMenu(x, y, epId) {
    if (!epId) return;
    closeCardMenu();
    const st = historyStatus(epId);
    const ep = state.allEpisodes?.find(e => e.id === epId);
    const dur = ep?.duration_sec || 0;
    const menu = document.createElement("div");
    menu.className = "card-menu";
    const items = [];
    if (!st || st.status !== "completed") {
      items.push({ label: "✓ Mark as played", action: () => { historyMarkPlayed(epId, dur); } });
    }
    if (st && st.status === "in_progress") {
      items.push({ label: "▶ Resume listening", action: () => playEpisodeInline(epId, { start: Math.floor(st.pos || 0) }) });
    }
    items.push({ label: "↺ Play from start", action: () => { historyRemove(epId); playEpisodeInline(epId, { start: 0 }); } });
    items.push({ label: "📜 View segments", action: () => { location.hash = `#/ep/${epId}`; } });
    if (st) {
      items.push({ sep: true });
      items.push({ label: "✕ Remove from history", danger: true, action: () => { historyRemove(epId); } });
    }
    menu.innerHTML = items.map(it =>
      it.sep ? `<div class="card-menu-sep"></div>`
             : `<button type="button" class="card-menu-item${it.danger ? " danger" : ""}">${it.label}</button>`
    ).join("");
    document.body.appendChild(menu);
    // Position; clamp to viewport.
    const r = menu.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const px = Math.min(x, vw - r.width - 8);
    const py = Math.min(y, vh - r.height - 8);
    menu.style.left = px + "px";
    menu.style.top  = py + "px";
    $cardMenu = menu;
    // Wire each item.
    const btnEls = menu.querySelectorAll(".card-menu-item");
    let bi = 0;
    items.forEach(it => {
      if (it.sep) return;
      const btn = btnEls[bi++];
      btn.addEventListener("click", e => {
        e.stopPropagation();
        try { it.action(); } finally {
          closeCardMenu();
          if (state.view === "home") renderHome(readHash().year, readHash().month);
        }
      });
    });
    // Close on outside click / Esc.
    setTimeout(() => {
      document.addEventListener("click", closeCardMenu, true);
      document.addEventListener("keydown", onCardMenuKey, true);
    }, 0);
  }

  // Boot
  route();
  setInterval(rotateTagline, 9000);
})();
