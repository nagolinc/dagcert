(function () {
  const colors = {
    duration: "#ff6535",
    interval: "#27777b",
    age: "#765977",
    wait: "#765977",
  };
  let data = window.DAGCERT_SAMPLE;
  const $ = (id) => document.getElementById(id);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>\"]/g,
      (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch],
    );
  const timingOf = (task, caseName) => task.timings?.[caseName] || {};
  function render() {
    renderSummary();
    renderDag();
    renderTimings();
    renderResources();
    renderGuarantees();
  }
  function renderSummary() {
    const c = data.contract,
      a = data.certificate?.analysis || {};
    $("hero-task-count").textContent = c.tasks.length;
    $("header-status").textContent =
      a.passed === false
        ? "certificate not passing"
        : a.conditional
          ? "verified · conditional"
          : "certificate verified";
    document.querySelector(".status-dot").style.background =
      a.passed === false ? "#d64b42" : a.conditional ? "#e6a923" : "#3aaa66";
    const timingCount = c.tasks.reduce(
      (n, t) => n + Object.keys(t.timings || {}).length,
      0,
    );
    const cards = [
      [
        c.workers.length,
        "workers",
        `${c.workers.reduce((n, w) => n + w.concurrency, 0)} concurrent slots`,
      ],
      [
        c.tasks.length,
        "tasks",
        `${c.tasks.filter((t) => (t.depends_on || []).length === 0).length} source task`,
      ],
      [
        c.resources.length,
        "resources",
        `${c.resources.reduce((n, r) => n + (r.initial || 0), 0)} initial work units`,
      ],
      [timingCount, "timings", `${data.evidence.length} observations`],
    ];
    $("summary").innerHTML = cards
      .map(
        ([value, label, detail]) =>
          `<article class="summary-card"><div class="value">${value}</div><div class="label">${label}</div><div class="detail">${detail}</div></article>`,
      )
      .join("");
    $("fingerprint").textContent =
      `source ${String(data.certificate?.source_fingerprint || "unbound").slice(0, 16)}…`;
  }
  function renderDag() {
    const tasks = data.contract.tasks;
    const compact = window.innerWidth <= 700;
    const width = compact ? 380 : 1120;
    const nodeW = compact ? 310 : 250;
    const nodeH = 112;
    const height = compact ? 25 + tasks.length * (nodeH + 35) : 276;
    const level = {};
    const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
    function depth(id, seen = new Set()) {
      if (level[id] != null) return level[id];
      if (seen.has(id)) return 0;
      seen.add(id);
      const deps = byId[id]?.depends_on || [];
      return (level[id] = deps.length
        ? 1 + Math.max(...deps.map((d) => depth(d, seen)))
        : 0);
    }
    tasks.forEach((t) => depth(t.id));
    const max = Math.max(...Object.values(level), 0);
    const groups = Array.from({ length: max + 1 }, () => []);
    tasks.forEach((t) => groups[level[t.id]].push(t));
    const pos = {};
    if (compact) {
      tasks
        .slice()
        .sort((a, b) => level[a.id] - level[b.id] || a.id.localeCompare(b.id))
        .forEach((task, index) => {
          pos[task.id] = { x: 35, y: 18 + index * (nodeH + 35) };
        });
    } else {
      groups.forEach((group, x) =>
        group.forEach((task, y) => {
          pos[task.id] = {
            x: 35 + x * ((width - nodeW - 70) / Math.max(max, 1)),
            y: 25 + y * (nodeH + 20),
          };
        }),
      );
    }
    let svg = `<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path class="dag-arrow" d="M0,0 L8,4 L0,8 Z"/></marker></defs>`;
    tasks.forEach((t) =>
      (t.depends_on || []).forEach((dep) => {
        const a = pos[dep],
          b = pos[t.id];
        const path = compact
          ? `M${a.x + nodeW / 2} ${a.y + nodeH} C${a.x + nodeW / 2} ${a.y + nodeH + 20},${b.x + nodeW / 2} ${b.y - 20},${b.x + nodeW / 2} ${b.y}`
          : `M${a.x + nodeW} ${a.y + nodeH / 2} C${a.x + nodeW + 45} ${a.y + nodeH / 2},${b.x - 45} ${b.y + nodeH / 2},${b.x} ${b.y + nodeH / 2}`;
        svg += `<path class="dag-edge" marker-end="url(#arrow)" d="${path}"/>`;
      }),
    );
    tasks.forEach((t) => {
      const p = pos[t.id],
        effects = Object.entries(t.resources || {})
          .map(
            ([id, e]) =>
              `${e.produce ? "+" : ""}${e.produce || e.consume ? e.produce || -e.consume : "↔"}${id}`,
          )
          .join("  ");
      svg += [
        `<g class="dag-node" transform="translate(${p.x},${p.y})">`,
        `<rect width="${nodeW}" height="${nodeH}" rx="14"/>`,
        `<circle cx="20" cy="21" r="5" fill="${colors[Object.values(t.timings || {})[0]?.metric] || colors.duration}"/>`,
        `<text class="task-name" x="34" y="26">${esc(t.id)}</text>`,
        `<text class="worker-name" x="18" y="52">worker · ${esc(t.worker)}</text>`,
        `<text class="flow-label" x="18" y="78">${esc(effects || "no resource flow")}</text>`,
        `<text class="worker-name" x="18" y="98">${Object.keys(t.timings || {}).length} timing case(s)</text>`,
        "</g>",
      ].join("");
    });
    $("dag").setAttribute("viewBox", `0 0 ${width} ${height}`);
    $("dag").style.height = compact ? `${height}px` : "300px";
    $("dag").innerHTML = svg;
  }
  function renderTimings() {
    const taskMap = Object.fromEntries(
      data.contract.tasks.map((t) => [t.id, t]),
    );
    const series = {};
    data.evidence
      .filter((e) => e.succeeded !== false)
      .forEach((e) => (series[`${e.task_id}/${e.case}`] ??= []).push(e));
    $("histograms").innerHTML = Object.entries(series)
      .map(([key, rows]) => {
        const [taskId, caseName] = key.split("/"),
          timing = timingOf(taskMap[taskId], caseName),
          limit =
            timing.upper_ms || Math.max(...rows.map((r) => r.value_ms)) * 1.3,
          max = Math.max(limit, ...rows.map((r) => r.value_ms)),
          color = colors[timing.metric] || colors.duration;
        const bars = rows
          .map(
            (r) =>
              `<i class="bar" style="height:${Math.max(3, (r.value_ms / max) * 30)}px;background:${color}"></i>`,
          )
          .join("");
        const worst = Math.max(...rows.map((r) => r.value_ms));
        return [
          '<div class="hist-row">',
          `<div class="hist-label"><strong>${esc(taskId)}</strong>`,
          `<span>${esc(caseName)} · ${esc(timing.metric)}</span></div>`,
          `<div class="track">${bars}<i class="limit-marker"></i></div>`,
          `<div class="hist-value"><strong>${fmt(worst)}</strong><span>of ${fmt(limit)}</span></div>`,
          "</div>",
        ].join("");
      })
      .join("");
    const flowSeries = Object.entries(series).filter(([key]) => {
        const [taskId, caseName] = key.split("/");
        return ["interval", "age"].includes(
          timingOf(taskMap[taskId], caseName).metric,
        );
      }),
      w = 420,
      h = 260,
      pad = 28;
    let svg = `<line class="axis" x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}"/><line class="axis" x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}"/>`;
    const thresholdY = h - pad - (1 / 1.2) * (h - 2 * pad);
    svg += `<line class="axis" stroke-dasharray="4 4" x1="${pad}" y1="${thresholdY}" x2="${w - pad}" y2="${thresholdY}"/>`;
    flowSeries.forEach(([key, rows]) => {
      const [taskId, caseName] = key.split("/"),
        timing = timingOf(taskMap[taskId], caseName),
        limit = timing.upper_ms || Math.max(...rows.map((r) => r.value_ms)),
        points = rows
          .map(
            (row, index) => {
              // Interval is inverted so higher means more throughput. Age is
              // direct so higher means more staleness. Both equal 1 at the
              // declared upper bound.
              const normalized =
                timing.metric === "interval"
                  ? limit / row.value_ms
                  : row.value_ms / limit;
              const x =
                pad +
                (index * (w - 2 * pad)) / Math.max(rows.length - 1, 1);
              const y =
                h -
                pad -
                (Math.min(normalized, 1.2) * (h - 2 * pad)) / 1.2;
              return `${x},${y}`;
            },
          )
          .join(" "),
        color = colors[timing.metric] || colors.duration;
      svg += `<polyline class="trend-line" stroke="${color}" points="${points}"/>`;
    });
    if (flowSeries.length === 0) {
      svg += `<text class="worker-name" x="${pad + 12}" y="${h / 2}">Load interval or age observations to show flow health.</text>`;
    }
    $("trend").setAttribute("viewBox", `0 0 ${w} ${h}`);
    $("trend").innerHTML = svg;
  }
  function renderResources() {
    const effects = {};
    data.contract.tasks.forEach((t) =>
      Object.entries(t.resources || {}).forEach(([id, e]) => {
        const x = (effects[id] ??= { producers: [], consumers: [], users: [] });
        if (e.produce) x.producers.push(t.id);
        if (e.consume) x.consumers.push(t.id);
        if (e.acquire) x.users.push(t.id);
      }),
    );
    $("resources").innerHTML = data.contract.resources
      .map((r) => {
        const e = effects[r.id] || { producers: [], consumers: [], users: [] },
          fill = Math.min(100, ((r.initial || 0) / r.capacity) * 100);
        const source = e.producers.length
          ? `produced by ${e.producers.join(", ")}`
          : e.users.length
            ? `acquired by ${e.users.join(", ")}`
            : "no producer";
        const consumers = e.consumers.length ? ` · consumed by ${e.consumers.join(", ")}` : "";
        return [
          '<article class="resource-card">',
          `<div class="resource-head"><strong>${esc(r.id)}</strong>`,
          `<span>${r.initial || 0} / ${r.capacity}</span></div>`,
          `<div class="resource-bar"><i style="width:${fill}%"></i></div>`,
          `<div class="resource-detail">${esc(r.unit)} · ${esc(source)}${esc(consumers)}</div>`,
          "</article>",
        ].join("");
      })
      .join("");
  }
  function renderGuarantees() {
    const a = data.certificate?.analysis || {},
      checkerClaims = (data.certificate?.checks || []).flatMap(
        (check) =>
          (check.facts?.claims || []).map((text) => ({
            ok: check.passed === true,
            text,
          })),
      );
    let rows = [];
    if (a.structural_progress)
      rows.push({
        ok: a.structural_progress.passed,
        text: a.structural_progress.claim,
      });
    checkerClaims.forEach((claim) => rows.push(claim));
    (a.assumptions || []).forEach((text) =>
      rows.push({ assumption: true, text }),
    );
    $("guarantees").innerHTML =
      rows
        .map(
          (r) =>
            [
              `<article class="guarantee ${r.assumption ? "assumption" : ""}">`,
              `<span class="guarantee-icon">${r.assumption ? "!" : r.ok ? "✓" : "×"}</span>`,
              `<div><strong>${r.assumption ? "Assumption" : r.ok ? "Supported" : "Not supported"}</strong>`,
              `<p>${esc(r.text)}</p></div>`,
              "</article>",
            ].join(""),
        )
        .join("") ||
      `<article class="guarantee assumption"><span class="guarantee-icon">!</span><div><strong>No guarantee report</strong><p>Load a certificate artifact.</p></div></article>`;
  }
  function fmt(ms) {
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
  }
  $("artifact-files").addEventListener("change", async (event) => {
    const files = [...event.target.files];
    const next = {
      contract: data.contract,
      evidence: [],
      certificate: null,
    };
    let loadedContract = false;
    for (const file of files) {
      const text = await file.text();
      if (file.name.endsWith(".jsonl")) {
        next.evidence = text
          .trim()
          .split(/\r?\n/)
          .filter(Boolean)
          .map(JSON.parse);
        continue;
      }
      try {
        const parsed = JSON.parse(text);
        if (parsed.schema === "dagcert-contract/v2") {
          next.contract = parsed;
          loadedContract = true;
        } else if (parsed.schema?.startsWith("dagcert-certificate/")) {
          next.certificate = parsed;
          if (!loadedContract && parsed.primitives) {
            next.contract = {
              schema: "dagcert-contract/v2",
              workers: parsed.primitives.workers || [],
              tasks: parsed.primitives.tasks || [],
              resources: parsed.primitives.resources || [],
            };
          }
        }
      } catch (error) {
        alert(`Could not read ${file.name}: ${error.message}`);
      }
    }
    data = next;
    render();
  });
  window.addEventListener("resize", renderDag);
  render();
})();
