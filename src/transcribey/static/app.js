(() => {
  const $ = (s) => document.querySelector(s),
    COLORS = [
      "#2563eb",
      "#c026d3",
      "#059669",
      "#d97706",
      "#dc2626",
      "#0891b2",
      "#7c3aed",
      "#65a30d",
    ];
  const PAD_B = 0.4,
    PAD_A = 0.3;
  let S = { speakers: [], lines: [], env: {} },
    polling = null,
    cur = null,
    watch = null,
    checking = false,
    busy = false,
    chkNote = "";
  const picks = new Map();
  const nameEl = (sp, cls = "nm") =>
    el("span", { class: cls, title: sp ? sp.name : "" }, sp ? sp.name : "?");
  const spk = (id) => S.speakers.find((s) => s.id === id),
    col = (id) =>
      COLORS[
        Math.max(
          0,
          S.speakers.findIndex((s) => s.id === id),
        ) % COLORS.length
      ];
  const fmt = (t) => {
    if (!Number.isFinite(Number(t))) return "—";
    t = Math.max(0, Math.floor(t));
    const h = Math.floor(t / 3600),
      m = Math.floor((t % 3600) / 60),
      s = t % 60;
    return `${h ? `${h}:${String(m).padStart(2, "0")}` : String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };
  const code = (t) => el("code", {}, t),
    codes = (names) => names.flatMap((n, i) => (i ? [", ", code(n)] : [code(n)]));
  function ask(msg, { ok = "Continue", cancel = "Cancel" } = {}) {
    const dlg = $("#dlg");
    $("#dlgMsg").replaceChildren(...[msg].flat());
    $("#dlgOk").textContent = ok;
    $("#dlgNo").textContent = cancel;
    $("#dlgNo").classList.toggle("hide", !cancel);
    dlg.returnValue = "";
    return new Promise((done) => {
      dlg.addEventListener("close", () => done(dlg.returnValue === "ok"), { once: true });
      dlg.showModal();
    });
  }
  const tell = (msg) => ask(msg, { ok: "OK", cancel: "" });
  async function api(path, body) {
    const r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({ error: "Bad reply" }));
    if (!r.ok || j.error) throw new Error(j.error || r.statusText);
    return j;
  }
  function el(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null) e.append(c);
    return e;
  }

  function renderEnv() {
    const e = S.env,
      b = $("#envBox");
    b.textContent = "";
    $("#gpuHint").textContent = "";
    if (!e.engine)
      b.append(
        el(
          "div",
          { class: "box bad" },
          el("b", {}, "The transcription engine is not installed. "),
          "Open a terminal, run ",
          el("code", {}, "pip install faster-whisper"),
          ", then start this program again.",
        ),
      );
    else if (e.cuda > 0) $("#gpuHint").textContent = "NVIDIA graphics card found. Much faster.";
    else
      b.append(
        el(
          "div",
          { class: "box warn" },
          "No NVIDIA graphics card was found, so the processor does the work. That is much slower: try a short recording first and choose the Balanced quality.",
          el(
            "details",
            {},
            el("summary", {}, "I have an NVIDIA card. Why was it not found?"),
            el(
              "p",
              { class: "small" },
              "Update your NVIDIA driver, then run: ",
              el("code", {}, 'pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"'),
              " and start this program again. It needs a card that supports CUDA 12 (most GeForce cards from the last several years do).",
            ),
          ),
        ),
      );
    const sel = $("#model");
    if (!sel.options.length) {
      for (const m of e.models || []) sel.append(el("option", { value: m.name }, m.label));
      sel.value =
        (e.models || []).find((m) => m.default === (e.cuda > 0 ? "gpu" : "cpu"))?.name || "";
      updateModelHint();
    }
  }
  function updateModelHint() {
    const v = $("#model").value,
      gpu = S.env.cuda > 0,
      m = (S.env.models || []).find((x) => x.name === v) || {},
      h = [];
    if (!gpu && m.slow) h.push("This quality is very slow without a graphics card. ");
    if (m.thai) {
      h.push("Thai only, so set Language to Thai. ");
      const cmd = code(`python -m transcribey.convert_model ${v}`);
      if (m.state === "missing") h.push("Not installed yet: run ", cmd, ", then reload this page.");
      if (m.state === "incomplete")
        h.push("Incomplete: run ", cmd, " again, then reload this page.");
    }
    $("#modelHint").replaceChildren(...h);
  }
  $("#model").onchange = updateModelHint;

  $("#pick").onclick = () => $("#file").click();
  $("#file").onchange = (e) => {
    upload([...e.target.files]);
    e.target.value = "";
  };
  const dragFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  document.addEventListener("dragover", (e) => {
    if (!dragFiles(e)) return;
    e.preventDefault();
    $("#drop").classList.add("over");
  });
  document.addEventListener("dragleave", (e) => {
    if (!e.relatedTarget) $("#drop").classList.remove("over");
  });
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    $("#drop").classList.remove("over");
    if (e.dataTransfer.files.length) upload([...e.dataTransfer.files]);
  });
  function upload(files) {
    return files
      .reduce(
        (p, f) =>
          p.then(
            () =>
              new Promise((res) => {
                const x = new XMLHttpRequest();
                x.open("POST", `/api/upload?name=${encodeURIComponent(f.name)}`);
                x.upload.onprogress = (e) => {
                  $("#upMsg").classList.remove("err");
                  $("#upMsg").replaceChildren(
                    "Adding ",
                    code(f.name),
                    `… ${Math.round(e.loaded / 1048576)} of ${Math.round(e.total / 1048576)} MB`,
                  );
                };
                x.onload = () => {
                  let j = {};
                  try {
                    j = JSON.parse(x.responseText);
                  } catch (_) {}
                  $("#upMsg").classList.toggle("err", !!j.error);
                  if (j.error) $("#upMsg").textContent = j.error;
                  else $("#upMsg").replaceChildren("Added ", ...codes(j.added || []));
                  res();
                };
                x.onerror = () => {
                  $("#upMsg").classList.add("err");
                  $("#upMsg").replaceChildren("Could not send ", code(f.name));
                  res();
                };
                x.send(f);
              }),
          ),
        Promise.resolve(),
      )
      .then(async () => {
        await refresh();
        for (const s of S.speakers) picks.set(s.id, true);
        renderPeople();
      });
  }
  function runText(r) {
    const name = (c) => ({ th: "Thai", en: "English" })[c] || c,
      lang = r.language === "auto" ? `auto (${name(r.detected) || "?"})` : name(r.language);
    return [
      r.model.split(/[\\/]/).pop(),
      lang,
      new Date(r.at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
    ].join(" · ");
  }
  function renderPeople() {
    const box = $("#people");
    box.textContent = "";
    if (!S.speakers.length) {
      box.append(el("p", { class: "muted small" }, "No recordings yet."));
      return;
    }
    box.append(el("b", {}, "People in this recording"));
    for (const sp of S.speakers) {
      const n = S.lines.filter((l) => l.spk === sp.id).length,
        nm = el("input", { type: "text", value: sp.name, "aria-label": "Speaker name" });
      const pk = el("input", { type: "checkbox" });
      pk.checked = picks.has(sp.id) ? picks.get(sp.id) : n === 0;
      pk.dataset.pick = sp.id;
      pk.onchange = () => picks.set(sp.id, pk.checked);
      nm.onchange = async () => {
        await api("/api/speaker", { id: sp.id, name: nm.value });
        refresh();
      };
      box.append(
        el(
          "div",
          { class: "person" },
          el("span", { class: "dot", style: `background:${col(sp.id)}` }),
          nm,
          el("span", { class: "small muted" }, sp.duration ? fmt(sp.duration) : "length unknown"),
          el("span", { class: `pill${n ? " ok" : ""}` }, n ? `${n} lines` : "no transcript yet"),
          n && sp.run
            ? el(
                "span",
                { class: "small muted", title: "Settings of the run that produced these lines" },
                runText(sp.run),
              )
            : null,
          el("label", { class: "small" }, pk, " transcribe"),
          el(
            "button",
            {
              class: "danger",
              onclick: async () => {
                if (await ask(["Remove ", code(sp.name), " and their lines?"], { ok: "Remove" })) {
                  await api("/api/speaker/remove", { id: sp.id });
                  refresh();
                }
              },
            },
            "Remove",
          ),
        ),
      );
    }
  }

  const runOpts = () => ({
    model: $("#custom").value.trim() || $("#model").value,
    language: $("#lang").value,
    device: $("#device").value,
    prompt: $("#prompt").value,
  });
  const unchecked = () =>
    S.speakers.filter((s) => !s.speech && S.lines.some((l) => l.spk === s.id));
  function renderCheck() {
    const todo = unchecked();
    $("#chkBox").classList.toggle("hide", !todo.length && !checking && !chkNote);
    if (!checking) {
      $("#chk").textContent = "Check for missed speech";
      $("#chk").disabled = false;
      if (chkNote || !todo.length) $("#chkMsg").textContent = chkNote;
      else
        $("#chkMsg").replaceChildren(
          "Not checked yet for ",
          ...codes(todo.map((s) => s.name)),
          ". Takes seconds and changes no line.",
        );
    }
  }
  $("#chk").onclick = async () => {
    if (checking) {
      api("/api/cancel", {});
      $("#chk").disabled = true;
      return;
    }
    chkNote = "";
    $("#jobEnd").textContent = "";
    try {
      await api("/api/transcribe", {
        ...runOpts(),
        speakers: unchecked().map((s) => s.id),
        check: true,
      });
      poll();
    } catch (e) {
      chkNote = e.message;
      renderCheck();
    }
  };
  $("#go").onclick = async () => {
    const ids = [...document.querySelectorAll("[data-pick]")]
      .filter((c) => c.checked)
      .map((c) => c.dataset.pick);
    if (!ids.length) {
      $("#goHint").textContent = S.speakers.length
        ? "Tick at least one person first."
        : "Add a recording first (step 1).";
      return;
    }
    await refresh();
    const redo = S.speakers.filter((s) => ids.includes(s.id) && s.touched).map((s) => s.name);
    if (
      redo.length &&
      !(await ask(
        [
          "Transcribing ",
          ...codes(redo),
          " again replaces their lines, including your fixes and reviewed ticks. Continue?",
        ],
        { ok: "Transcribe again" },
      ))
    )
      return;
    $("#goHint").textContent = "";
    $("#jobEnd").textContent = "";
    try {
      await api("/api/transcribe", { ...runOpts(), speakers: ids });
      poll();
    } catch (e) {
      $("#jobEnd").append(el("div", { class: "box bad" }, e.message));
    }
  };
  async function again(spk_id, start, end) {
    if (busy) return;
    await refresh();
    const sp = spk(spk_id),
      mid = (l) => (l.start + l.end) / 2,
      edited = S.lines.filter(
        (l) => l.spk === spk_id && l.edited && mid(l) >= start && mid(l) <= end,
      ).length;
    if (
      edited &&
      !(await ask(
        [
          `${fmt(start)} – ${fmt(end)} of `,
          code(sp.name),
          ` holds ${edited} line${edited > 1 ? "s" : ""} you edited. Transcribing this part again replaces ${edited > 1 ? "them" : "it"}. Continue?`,
        ],
        { ok: "Transcribe again" },
      ))
    )
      return;
    $("#jobEnd").textContent = "";
    try {
      await api("/api/transcribe", { ...runOpts(), speakers: [spk_id], start, end });
      poll();
    } catch (e) {
      $("#jobEnd").append(el("div", { class: "box bad" }, e.message));
    }
  }
  function againBtn(spk_id, start, end) {
    const b = el(
      "button",
      { class: "again", onclick: () => again(spk_id, start, end) },
      "transcribe this part again",
    );
    b.disabled = busy;
    return b;
  }
  $("#stop").onclick = () => {
    api("/api/cancel", {});
    $("#stop").disabled = true;
    $("#stop").textContent = "Stopping…";
  };
  function drawLane(cv, spans, dur, color, head) {
    const dpr = window.devicePixelRatio || 1,
      w = cv.clientWidth,
      h = cv.clientHeight;
    cv.width = w * dpr;
    cv.height = h * dpr;
    if (!dur) return;
    const g = cv.getContext("2d");
    g.scale(dpr, dpr);
    g.fillStyle = color;
    for (const [a, b] of spans) g.fillRect((a / dur) * w, 0, Math.max(1.5, ((b - a) / dur) * w), h);
    if (head && spans.length) {
      g.fillStyle = getComputedStyle(document.body).color;
      g.fillRect(Math.min(w - 3, (spans[spans.length - 1][1] / dur) * w), 0, 3, h);
    }
  }
  function renderLanes(j) {
    const box = $("#lanes");
    box.textContent = "";
    if (j.check) return;
    (j.ids || []).forEach((id, i) => {
      const sp = spk(id),
        spans = j.spans?.[id] || [],
        now = i === j.index,
        cv = el("canvas", { class: "lane", "aria-hidden": "true" });
      box.append(
        el(
          "div",
          { class: `lanerow ${now ? "now" : i < j.index ? "done" : "wait"}` },
          nameEl(sp, "small nm"),
          cv,
          el(
            "span",
            { class: "small muted" },
            i > j.index ? "waiting" : `${spans.length} lines${now ? " so far" : ""}`,
          ),
        ),
      );
      drawLane(cv, spans, sp?.duration || spans.at(-1)?.[1] || 0, col(id), now);
    });
  }
  function renderSteps() {
    const people = S.speakers.length,
      lines = S.lines.length,
      transcribed = people > 0 && S.speakers.every((sp) => S.lines.some((l) => l.spk === sp.id)),
      reviewed = lines > 0 && S.lines.every((l) => l.ok),
      step = {
        s1: people ? "done" : "current",
        s2: !people ? "todo" : transcribed && !busy ? "done" : "current",
        s3: !lines ? "todo" : busy ? "open" : reviewed ? "done" : "current",
        s4: lines ? "current" : "todo",
      };
    for (const [id, v] of Object.entries(step)) $(`#${id}`).dataset.step = v;
  }
  function poll() {
    clearInterval(polling);
    tick();
    polling = setInterval(tick, 1000);
  }
  async function tick() {
    const j = await api("/api/status").catch(() => null);
    if (!j?.phase) return;
    const running = !!j.running;
    checking = running && !!j.check;
    busy = running;
    for (const b of document.querySelectorAll(".again")) b.disabled = running;
    renderSteps();
    renderCheck();
    if (running && !j.check) $("#chk").disabled = true;
    $("#job").classList.toggle("hide", false);
    $("#go").classList.toggle("hide", running);
    $("#stop").classList.toggle("hide", !running);
    $("#stop").disabled = !running;
    if (running && $("#stop").textContent === "Stopping…" && !j.cancel)
      $("#stop").textContent = "Stop";
    if (running) {
      if (j.phase === "loading") $("#jobWho").textContent = "Getting the model ready…";
      else $("#jobWho").replaceChildren(`Person ${j.index + 1} of ${j.count}: `, code(j.who));
      const frac = j.check
        ? j.index / j.count
        : j.dur > 0
          ? Math.min(1, (j.index + j.pos / j.dur) / j.count)
          : 0;
      $("#jobBar").style.width = `${j.phase === "loading" ? 3 : frac * 100}%`;
      let t = j.message || "";
      if (j.check) {
        $("#chk").textContent = "Stop";
        $("#chkMsg").textContent = `Person ${j.index + 1} of ${j.count}: ${j.message}`;
      } else if (j.phase === "working") {
        t =
          `Heard ${fmt(j.pos)}` +
          (j.dur ? ` of ${fmt(j.dur)}` : "") +
          ` · ${fmt(j.elapsed)} elapsed · using the ${j.device === "cuda" ? "graphics card" : "processor"}`;
        if (j.pos > 20 && j.dur && j.elapsed > 10) {
          const left = (j.dur - j.pos) * (j.elapsed / Math.max(1, (j.audio_done || 0) + j.pos));
          t += ` · about ${fmt(left)} left for this person`;
        }
      }
      $("#jobText").textContent = t;
      $("#jobNote").textContent = j.note || "";
      renderLanes(j);
      $("#live").textContent = "";
      for (const r of j.recent || []) $("#live").append(el("div", {}, r));
    } else {
      clearInterval(polling);
      polling = null;
      chkNote = j.check ? j.error || j.note || "" : "";
      $("#review").open = false;
      $("#job").classList.add("hide");
      const end = $("#jobEnd");
      end.textContent = "";
      if (j.phase === "error") {
        end.append(
          el(
            "div",
            { class: "box bad" },
            el("b", {}, "Whisper stopped with an error. "),
            j.error,
            el(
              "p",
              { class: "small" },
              'Nothing you did is lost. Try the Balanced quality, or choose "Processor only", then start again.',
            ),
            el(
              "details",
              {},
              el("summary", {}, "Technical details"),
              el(
                "pre",
                {},
                `${j.error}\n${j.trace || ""}\nengine python ${S.env.py} cuda=${S.env.cuda}`,
              ),
            ),
          ),
        );
      } else if (j.phase === "cancelled")
        end.append(
          el(
            "div",
            { class: "box warn" },
            "Stopped. People who finished were saved; the person in progress kept their previous lines.",
          ),
        );
      else if (j.phase === "done" && j.check)
        end.append(
          el(
            "div",
            { class: `box ${j.note ? "warn" : "ok"}` },
            el("b", {}, j.note ? "Not fully checked. " : "Done. "),
            j.note
              ? j.note
              : `Checked in ${fmt(j.seconds)}. Missed speech rows now show in Transcript lines in step 3.`,
          ),
        );
      else if (j.phase === "done" && j.stretch)
        end.append(
          el(
            "div",
            { class: "box ok" },
            el("b", {}, "Done. "),
            `That part was transcribed again in ${fmt(j.seconds)}. Open Transcript lines in step 3.`,
          ),
        );
      else if (j.phase === "done")
        end.append(
          el(
            "div",
            { class: "box ok" },
            el("b", {}, "Done. "),
            `Finished in ${fmt(j.seconds)}. Open Transcript lines in step 3. Start with "unsure", then "TH/EN", where the model slips most.`,
          ),
        );
      if (j.phase === "done") $("#newTag").hidden = false;
      picks.clear();
      await refresh();
    }
  }

  const pend = new Map();
  let saveT = null;
  function queue(id, patch) {
    pend.set(id, Object.assign(pend.get(id) || { id }, patch));
    $("#saveState").textContent = "Saving…";
    $("#saveState").dataset.state = "saving";
    clearTimeout(saveT);
    saveT = setTimeout(flush, 600);
  }
  async function flush() {
    const u = [...pend.values()];
    pend.clear();
    if (!u.length) return;
    try {
      await api("/api/lines", { updates: u });
      $("#saveState").textContent = "Saved";
      $("#saveState").dataset.state = "saved";
    } catch (e) {
      $("#saveState").textContent = `Not saved: ${e.message}`;
      $("#saveState").dataset.state = "error";
    }
  }
  function visible() {
    const f = $("#filter").value;
    return S.lines.filter(
      (l) =>
        f === "all" ||
        (f === "todo" && !l.ok) ||
        (f === "check" && !l.ok && l.unsure) ||
        (f === "mixed" && l.mixed),
    );
  }
  const rows = () =>
    S.speakers.flatMap((s) =>
      (s.missed || []).map((m) => ({
        row: true,
        id: `m${s.id}-${m.start}`,
        spk: s.id,
        start: m.start,
        end: m.end,
      })),
    );
  function shown() {
    const ls = visible();
    return $("#filter").value === "mixed"
      ? ls
      : [...ls, ...rows()].sort((a, b) => a.start - b.start);
  }
  function nextCheck(id) {
    const v = shown(),
      nx = v.slice(v.findIndex((x) => x.id === id) + 1).find((x) => x.row || (x.unsure && !x.ok));
    if (!nx) return;
    const e = document.querySelector(`[data-id="${nx.id}"]`);
    e?.querySelector(nx.row ? ".play" : "textarea")?.focus();
    e?.scrollIntoView({ block: "center", behavior: "smooth" });
    playRange(nx);
  }
  function gone(r) {
    const s = spk(r.spk);
    s.missed = s.missed.filter((m) => m.start !== r.start || m.end !== r.end);
  }
  function missedRow(r) {
    const sp = spk(r.spk),
      play = el("button", { class: "play", onclick: () => playRange(r) }, "▶");
    play.addEventListener("keydown", (e) => {
      if (e.altKey && e.key === "ArrowDown") {
        e.preventDefault();
        nextCheck(r.id);
      }
    });
    return el(
      "div",
      { class: "line missed", "data-id": r.id },
      el(
        "div",
        { class: "meta" },
        el("div", {}, play),
        el(
          "div",
          { class: "who" },
          el("span", { class: "dot", style: `background:${col(r.spk)}` }),
          nameEl(sp),
        ),
        el("div", { class: "t" }, `${fmt(r.start)} – ${fmt(r.end)}`),
      ),
      el(
        "div",
        {},
        el("b", {}, "Missed speech"),
        ` · ${(r.end - r.start).toFixed(1)} s of voice with no line`,
        el(
          "div",
          { class: "acts" },
          el(
            "button",
            {
              onclick: async () => {
                const l = await api("/api/line/add", { spk: r.spk, start: r.start, end: r.end });
                gone(r);
                S.lines.push(l.line);
                S.lines.sort((a, b) => a.start - b.start);
                renderLines();
                document.querySelector(`[data-id="${l.line.id}"] textarea`)?.focus();
              },
            },
            "+ add line here",
          ),
          againBtn(r.spk, r.start, r.end),
          el(
            "button",
            {
              onclick: async () => {
                await api("/api/missed/dismiss", { spk: r.spk, start: r.start, end: r.end });
                gone(r);
                renderLines();
              },
            },
            "dismiss",
          ),
        ),
      ),
    );
  }
  function counts() {
    const n = S.lines.length,
      d = S.lines.filter((l) => l.ok).length;
    const c = S.lines.filter((l) => !l.ok && l.unsure).length + rows().length;
    const box = $("#counts"),
      sum = $("#sumCheck");
    box.textContent = "";
    if (n) {
      const bar = el("i");
      bar.style.width = `${(d / n) * 100}%`;
      box.append(
        el("span", { class: "meter" }, bar),
        el("b", {}, String(d)),
        ` of ${n} reviewed`,
        c ? el("span", { class: "unsure-n" }, `${c} unsure`) : null,
      );
    }
    sum.textContent = c ? `${c} unsure` : n && d === n ? "All reviewed" : "";
    sum.dataset.k = c ? "check" : "done";
  }
  function autosize(t) {
    t.style.height = "auto";
    t.style.height = `${Math.max(40, t.scrollHeight + 2)}px`;
  }
  function renderLines() {
    const list = $("#list");
    list.textContent = "";
    for (const id of ["#s3", "#s4"]) $(id).classList.toggle("hide", !S.lines.length);
    counts();
    for (const l of shown()) {
      if (l.row) {
        list.append(missedRow(l));
        continue;
      }
      const sp = spk(l.spk),
        ta = el("textarea", { lang: "th", spellcheck: "false" });
      ta.value = l.text;
      let mir = null,
        at = 0;
      if (l.unsure_words?.length) {
        mir = el("div", { class: "mirror", "aria-hidden": "true" });
        for (const [a, b] of l.unsure_words) {
          mir.append(l.text.slice(at, a), el("u", {}, l.text.slice(a, b)));
          at = b;
        }
        mir.append(l.text.slice(at));
      }
      const ck = el("input", { type: "checkbox" });
      ck.checked = l.ok;
      const row = el("div", {
        class: `line${l.ok ? " done" : ""}`,
        "data-id": l.id,
        style: `--spk:${col(l.spk)}`,
      });
      const tags = el("div", { class: "tags" });
      if (l.mixed) tags.append(el("span", { class: "tag" }, "TH/EN"));
      let why = null;
      if (l.unsure) {
        const w = l.unsure_words.map(([a, b]) => l.text.slice(a, b)),
          n = w.length > 3 ? ` +${w.length - 3}` : "";
        why = el(
          "span",
          { class: "why" },
          l.reasons
            .map((r) => (r === "unsure word" ? `unsure word: ${w.slice(0, 3).join(", ")}${n}` : r))
            .join(" · "),
        );
        tags.append(el("span", { class: "tag low" }, "unsure"), why);
      }
      row.append(
        el(
          "div",
          { class: "meta" },
          el("div", {}, el("button", { class: "play", onclick: () => playLine(l.id) }, "▶")),
          el(
            "div",
            { class: "who" },
            el("span", { class: "dot", style: `background:${col(l.spk)}` }),
            nameEl(sp),
          ),
          el("div", { class: "t" }, `${fmt(l.start)} – ${fmt(l.end)}`),
          tags,
        ),
        el(
          "div",
          {},
          el("div", { class: "hl" }, ta, mir),
          el(
            "div",
            { class: "acts" },
            el("label", {}, ck, " reviewed"),
            el(
              "button",
              {
                onclick: async () => {
                  const r = await api("/api/line/add", { after: l.id });
                  S.lines.push(r.line);
                  S.lines.sort((a, b) => a.start - b.start);
                  renderLines();
                  document.querySelector(`[data-id="${r.line.id}"] textarea`)?.focus();
                },
              },
              "+ line below",
            ),
            el(
              "button",
              {
                class: "danger",
                onclick: async () => {
                  if (!l.text || (await ask("Delete this line?", { ok: "Delete" }))) {
                    await api("/api/line/delete", { id: l.id });
                    S.lines = S.lines.filter((x) => x.id !== l.id);
                    renderLines();
                  }
                },
              },
              "delete",
            ),
            (l.reasons || []).includes("missed speech") ? againBtn(l.spk, l.start, l.end) : null,
            l.edited ? el("span", { class: "tag" }, "edited") : null,
          ),
        ),
      );
      ta.addEventListener("input", () => {
        mir?.remove();
        why?.remove();
        tags.querySelector(".low")?.remove();
        l.unsure_words = [];
        l.reasons = [];
        l.unsure = false;
        l.text = ta.value;
        autosize(ta);
        queue(l.id, { text: ta.value });
      });
      ck.onchange = () => {
        l.ok = ck.checked;
        row.classList.toggle("done", l.ok);
        queue(l.id, { ok: l.ok });
        counts();
      };
      ta.addEventListener("keydown", (e) => {
        if (e.altKey && e.key === "Enter") {
          e.preventDefault();
          l.ok = true;
          ck.checked = true;
          row.classList.add("done");
          queue(l.id, { ok: true });
          counts();
          const v = visible(),
            i = v.findIndex((x) => x.id === l.id),
            nx = v[i + 1];
          if (nx) {
            document.querySelector(`[data-id="${nx.id}"] textarea`)?.focus();
            playLine(nx.id);
          }
        } else if (e.altKey && e.key === "ArrowDown") {
          e.preventDefault();
          nextCheck(l.id);
        }
      });
      list.append(row);
    }
    const tas = [...list.querySelectorAll("textarea")]; // batch: one layout, not one per line
    for (const t of tas) t.style.height = "auto";
    const hs = tas.map((t) => t.scrollHeight);
    tas.forEach((t, i) => {
      t.style.height = `${Math.max(40, hs[i] + 2)}px`;
    });
    if (cur) mark(cur.id);
  }
  $("#filter").onchange = refresh;
  window.addEventListener("beforeunload", (e) => {
    if (pend.size > 0) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  $("#replaceAll").onclick = async () => {
    const f = $("#find").value;
    if (!f) return;
    const mc = $("#matchCase").checked,
      re = new RegExp(f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), mc ? "g" : "gi");
    const ch = [];
    for (const l of S.lines) {
      const t = l.text.replace(re, () => $("#repl").value);
      if (t !== l.text) {
        ch.push({ id: l.id, text: t });
        l.text = t;
      }
    }
    if (ch.length) await api("/api/lines", { updates: ch });
    $("#replMsg").textContent = ch.length
      ? `Changed ${ch.length} line${ch.length > 1 ? "s" : ""}`
      : "Nothing found";
    renderLines();
  };

  const player = $("#player");
  function mark(id) {
    for (const e of document.querySelectorAll(".line.playing")) e.classList.remove("playing");
    document.querySelector(`[data-id="${id}"]`)?.classList.add("playing");
  }
  function playLine(id) {
    const l = S.lines.find((x) => x.id === id);
    if (l) playRange(l);
  }
  function renderBar() {
    const r = cur,
      bar = $("#playbar");
    bar.classList.toggle("hide", !r);
    if (!r) return;
    const sp = spk(r.spk),
      v = shown(),
      i = v.findIndex((x) => x.id === r.id);
    $("#pbWho").textContent = sp ? sp.name : "?";
    $("#pbWho").title = sp ? sp.name : "";
    $("#pbDot").style.background = col(r.spk);
    $("#pbTime").textContent = `${fmt(r.start)} – ${fmt(r.end)}`;
    $("#pbText").textContent = r.row ? "Missed speech" : r.text;
    $("#pbPrev").disabled = i <= 0;
    $("#pbNext").disabled = i < 0 || i >= v.length - 1;
    bar.dataset.state = player.paused ? "paused" : "playing";
  }
  function step(d) {
    const v = shown(),
      nx = v[v.findIndex((x) => x.id === cur?.id) + d];
    if (!nx) return;
    playRange(nx);
    document
      .querySelector(`[data-id="${nx.id}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  function playRange(r) {
    cur = r;
    mark(r.id);
    renderBar();
    $("#pbBar").style.width = "0";
    const url = `/audio/${r.spk}`,
      go = () => {
        player.currentTime = Math.max(0, r.start - PAD_B);
        player.playbackRate = +$("#rate").value;
        player.play().catch((e) => {
          if (e.name === "AbortError") return;
          halt();
          tell(
            `The browser could not play this audio: ${e.message}\nTry converting the file to WAV or MP3.`,
          );
        });
        clearInterval(watch);
        watch = setInterval(check, 40);
      };
    if (!player.src.endsWith(url)) {
      player.src = url;
      player.addEventListener("loadedmetadata", go, { once: true });
      player.load();
    } else go();
  }
  function check() {
    const r = cur;
    if (!r || player.paused) {
      if (!r) clearInterval(watch);
      return;
    }
    const from = Math.max(0, r.start - PAD_B),
      frac = (player.currentTime - from) / (r.end + PAD_A - from);
    $("#pbBar").style.width = `${Math.min(1, Math.max(0, frac)) * 100}%`;
    if (player.currentTime >= r.end + PAD_A) {
      if ($("#loop").checked) {
        player.currentTime = Math.max(0, r.start - PAD_B);
        return;
      }
      const v = visible(),
        i = v.findIndex((x) => x.id === r.id);
      if ($("#auto").checked && !r.row && v[i + 1]) {
        playLine(v[i + 1].id);
        document
          .querySelector(`[data-id="${v[i + 1].id}"]`)
          ?.scrollIntoView({ block: "center", behavior: "smooth" });
      } else halt();
    }
  }
  function halt() {
    player.pause();
    clearInterval(watch);
    for (const e of document.querySelectorAll(".line.playing")) e.classList.remove("playing");
    cur = null;
    renderBar();
  }
  $("#review").ontoggle = () => {
    if ($("#review").open) $("#newTag").hidden = true;
  };
  $("#pbStop").onclick = halt;
  $("#pbPrev").onclick = () => step(-1);
  $("#pbNext").onclick = () => step(1);
  $("#pbPlay").onclick = () => (player.paused ? player.play() : player.pause());
  player.addEventListener("play", renderBar);
  player.addEventListener("pause", renderBar);
  $("#rate").onchange = () => {
    player.playbackRate = +$("#rate").value;
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") halt();
  });

  $("#reset").onclick = async () => {
    if (
      await ask(
        "Delete all audio copies and transcripts in this program and start over? Your original files are not touched.",
        { ok: "Start over" },
      )
    ) {
      try {
        await api("/api/reset", {});
        $("#jobEnd").textContent = "";
        refresh();
      } catch (e) {
        tell(e.message);
      }
    }
  };
  async function refresh() {
    await flush();
    S = await api("/api/state");
    for (const sp of S.speakers)
      if (S.lines.some((l) => l.spk === sp.id) && !picks.has(sp.id)) picks.set(sp.id, false); // already has a transcript: do not redo by default
    picks.forEach((_, k) => {
      if (!S.speakers.some((s) => s.id === k)) picks.delete(k);
    });
    renderEnv();
    renderPeople();
    renderCheck();
    renderLines();
    renderSteps();
  }
  for (let i = 0; i < 40; i++)
    $("#wave").append(
      el("i", {
        style: `--h:${20 + 80 * Math.abs(Math.sin(i * 0.9) * Math.cos(i * 0.31))}%;--i:${i}`,
      }),
    );
  refresh()
    .finally(() => document.body.classList.add("ready"))
    .then(() =>
      api("/api/status").then((j) => {
        if (j?.running) poll();
      }),
    );
})();
