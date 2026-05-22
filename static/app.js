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

  // Clean up any leftover flag from the Webamp experiment.
  try { localStorage.removeItem("bfa_webamp"); } catch {}

  // ─── State ───────────────────────────────────────────────────────────
  const state = {
    view: "episodes",
    query: "",
    currentEpisode: null,
    currentSegments: [],
    allEpisodes: null,
  };

  const SITE_NAME = "Bhoot FM Archive";
  const BASE_DESC = "Search and listen to Bengali horror radio episodes from Bhoot FM. Find ghost stories by keyword, jump to the exact moment.";

  // Rotating taglines — subtle and mood-setting, bilingual.
  const TAGLINES = [
    "listen where you dare",
    "রাতের গল্প · stories of the night",
    "broadcasts from beyond",
    "ভূত এফএম · since 2007",
    "tune in if you can sleep after",
    "stories the night remembers",
    "প্রতিটি কণ্ঠে একটি গল্প",
    "the dial still turns",
  ];

  // ─── Helpers ─────────────────────────────────────────────────────────
  const api = (path, params) => {
    const url = new URL(path, location.origin);
    if (params)
      for (const [k, v] of Object.entries(params))
        if (v != null && v !== "") url.searchParams.set(k, v);
    return fetch(url).then(r => {
      if (!r.ok) throw new Error(`request failed`);
      return r.json();
    });
  };

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
    return { type: "home" };
  }

  // ─── Audio ───────────────────────────────────────────────────────────
  let currentTimeSec = 0;

  function playEpisodeAt(episode, startSec) {
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
  async function renderEpisodes() {
    state.view = "episodes";
    $transcript.classList.add("hidden");
    $results.classList.remove("hidden");
    setMeta({
      title: SITE_NAME,
      description: BASE_DESC,
    });
    setStatus("Listening for whispers…", "loading");
    try {
      const data = await api("/api/episodes");
      state.allEpisodes = data.episodes;
      if (!data.episodes.length) {
        $results.innerHTML =
          `<div class="empty"><h2>Nothing here yet</h2>
           <div>Try a different filter to summon the full archive.</div></div>`;
        setStatus("");
        return;
      }
      setStatus(
        `${data.episodes.length} broadcast${data.episodes.length > 1 ? "s" : ""} unearthed`
      );
      $results.innerHTML = data.episodes.map((ep, i) => `
        <div class="card episode-card card-appear" data-ep-id="${ep.id}" style="animation-delay: ${Math.min(i, 20) * 18}ms">
          <div>
            <div class="card-title">${escapeHtml(ep.title)}</div>
            <div class="card-date">${fmtDate(ep.air_date)}${ep.duration_sec ? " · " + fmtTs(ep.duration_sec) : ""}</div>
          </div>
          <div class="ep-segs">${ep.segment_count} markers</div>
        </div>
      `).join("");
      $results.querySelectorAll(".episode-card").forEach(el => {
        el.addEventListener("click", () => {
          location.hash = `#/ep/${el.dataset.epId}`;
        });
      });
    } catch (e) {
      setStatus("Could not reach the archive.", "error");
    }
  }

  async function renderSearch(q) {
    state.view = "results";
    state.query = q;
    $q.value = q;
    $transcript.classList.add("hidden");
    $results.classList.remove("hidden");
    setMeta({
      title: `"${q}" — ${SITE_NAME}`,
      description: `Search results for "${q}" in the Bhoot FM Archive.`,
    });
    setStatus("Searching the static…", "loading");
    try {
      const data = await api("/api/search", { q, limit: 200 });
      if (data.total === 0) {
        // If the query is all Latin (no Bengali codepoints), the user
        // probably typed in English — gently steer them to Bangla, since
        // the transcripts are all in Bangla.
        const hasBangla = /[ঀ-৿]/.test(q);
        const hint = hasBangla
          ? ""
          : `<div class="empty-hint">
               Transcripts are in <strong>Bangla</strong>. Try a Bangla word —
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
      $results.innerHTML = [...byEpisode.values()].map((ep, i) => `
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
              <button class="marker" data-ep-id="${ep.episode_id}" data-at="${h.start_sec}" aria-label="Play at ${fmtTs(h.start_sec)}">
                ${fmtTs(h.start_sec)}
              </button>
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
    } catch (e) {
      setStatus("Search failed.", "error");
    }
  }

  async function renderTranscript(episodeId, at) {
    state.view = "transcript";
    $results.classList.add("hidden");
    $transcript.classList.remove("hidden");
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
      if (at != null && !isNaN(at)) {
        playEpisodeAt(data.episode, at);
        const idx = data.segments.findIndex(s => s.start_sec >= at - 1);
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

  // Auto-advance to next episode when one finishes.
  $audio.addEventListener("ended", () => skipEpisode(+1));

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
    location.hash = `#/ep/${pick.id}`;
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
  $audio.addEventListener("play", () => setPlayingUI(true));
  $audio.addEventListener("pause", () => setPlayingUI(false));
  $audio.addEventListener("ended", () => setPlayingUI(false));
  $audio.addEventListener("loadedmetadata", updateScrubber);
  $audio.addEventListener("durationchange", updateScrubber);
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
    return renderEpisodes();
  }
  function scrollToTop() {
    try { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); }
    catch { window.scrollTo(0, 0); }
  }

  // Don't let the browser restore old scroll positions when navigating
  // between hash routes — we manage scrolling deliberately in route().
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  // Boot
  route();
  setInterval(rotateTagline, 9000);
})();
