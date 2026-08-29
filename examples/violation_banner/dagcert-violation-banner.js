(function () {
  "use strict";

  const script = document.currentScript;
  const endpoint = script?.dataset.endpoint || "/dagcert/runtime-events";
  const statsHref = script?.dataset.statsHref || "/stats";
  const pollMs = Number(script?.dataset.pollMs || 1000);
  const bannerId = "dagcert-violation-banner";
  let dismissedToken = null;
  let visibleToken = null;
  let warned = false;

  function installStyle() {
    if (document.getElementById(`${bannerId}-style`)) return;
    const style = document.createElement("style");
    style.id = `${bannerId}-style`;
    style.textContent = `
      #${bannerId} {
        position: sticky;
        top: 0;
        z-index: 2147483647;
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        min-height: 42px;
        padding: 9px clamp(18px, 4vw, 60px);
        border: 0;
        background: #a92e18;
        color: #fff;
        box-shadow: 0 2px 10px rgba(107, 23, 15, 0.3);
        font: 600 12px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif;
      }
      #${bannerId}[hidden] { display: none; }
      #${bannerId} strong { flex: 0 0 auto; letter-spacing: 0.025em; }
      #${bannerId} .dagcert-violation-detail {
        min-width: 0;
        flex: 1 1 auto;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-weight: 500;
      }
      #${bannerId} a { flex: 0 0 auto; color: #fff; text-decoration: underline; }
      #${bannerId} button {
        flex: 0 0 auto;
        width: 28px;
        height: 28px;
        margin: -3px -8px -3px 0;
        padding: 0;
        border: 1px solid rgba(255, 255, 255, 0.55);
        border-radius: 999px;
        background: transparent;
        color: #fff;
        cursor: pointer;
        font: 700 19px/1 system-ui, sans-serif;
      }
      #${bannerId} button:hover,
      #${bannerId} button:focus-visible { background: rgba(255, 255, 255, 0.18); }
      @media (max-width: 720px) {
        #${bannerId} { align-items: flex-start; flex-wrap: wrap; gap: 5px 10px; }
        #${bannerId} strong { padding-right: 32px; }
        #${bannerId} .dagcert-violation-detail { order: 3; flex-basis: 100%; white-space: normal; }
        #${bannerId} button { position: absolute; top: 9px; right: 18px; }
      }
    `;
    document.head.append(style);
  }

  function installBanner() {
    let banner = document.getElementById(bannerId);
    if (banner) return banner;
    banner = document.createElement("div");
    banner.id = bannerId;
    banner.hidden = true;
    banner.setAttribute("role", "alert");
    banner.setAttribute("aria-live", "assertive");

    const heading = document.createElement("strong");
    heading.textContent = "DAGCERT VIOLATION — GUARANTEES DO NOT HOLD";
    const detail = document.createElement("span");
    detail.className = "dagcert-violation-detail";
    const stats = document.createElement("a");
    const defaultStatsUrl = new URL(statsHref, document.baseURI);
    defaultStatsUrl.hash = "graph";
    stats.className = "dagcert-stats-link";
    stats.href = defaultStatsUrl.href;
    stats.textContent = "View graph in /stats";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", "Dismiss Dagcert violation warning");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", function () {
      dismissedToken = visibleToken;
      banner.hidden = true;
    });
    banner.append(heading, detail, stats, dismiss);
    document.body.prepend(banner);
    return banner;
  }

  function violationOf(payload) {
    if (!payload || typeof payload !== "object") return null;
    if (payload.last_violation && typeof payload.last_violation === "object") {
      return payload.last_violation;
    }
    if (Array.isArray(payload.violations) && payload.violations.length) {
      return payload.violations[payload.violations.length - 1];
    }
    if (Array.isArray(payload.events)) {
      return payload.events.filter(function (event) {
        return event?.violation === true || event?.passed === false;
      }).at(-1) || null;
    }
    return payload.violation === true || payload.passed === false ? payload : null;
  }

  function detailOf(violation) {
    return String(
      violation?.message
      || violation?.detail
      || violation?.error
      || violation?.claim
      || violation?.outcome_type
      || "A runtime certificate premise failed.",
    );
  }

  function tokenOf(violation, occurrence) {
    return JSON.stringify([
      occurrence,
      violation?.id,
      violation?.sequence,
      violation?.recorded_at,
      violation?.at,
      violation?.boundary_id,
      violation?.task_id,
      detailOf(violation),
    ]);
  }

  function taskIdOf(violation) {
    const direct = [
      violation?.task_id,
      violation?.task,
      violation?.node_id,
      violation?.metadata?.task_id,
    ].find(function (value) {
      return typeof value === "string" && value.length > 0;
    });
    if (direct) return direct.replace(/^task:/, "");

    const references = [
      ...(Array.isArray(violation?.primitive_refs) ? violation.primitive_refs : []),
      ...(Array.isArray(violation?.references) ? violation.references : []),
    ];
    const taskReference = references.find(function (value) {
      return typeof value === "string" && value.startsWith("task:");
    });
    return taskReference ? taskReference.slice("task:".length) : null;
  }

  function statsLinkOf(violation) {
    const taskId = taskIdOf(violation);
    const url = new URL(statsHref, document.baseURI);
    if (taskId) url.searchParams.set("task", taskId);
    url.hash = "graph";
    return { taskId, url: url.href };
  }

  function showViolation(violation, occurrence) {
    const banner = installBanner();
    const statsLink = statsLinkOf(violation);
    const stats = banner.querySelector(".dagcert-stats-link");
    visibleToken = tokenOf(violation, occurrence);
    banner.querySelector(".dagcert-violation-detail").textContent = detailOf(violation);
    stats.href = statsLink.url;
    stats.textContent = statsLink.taskId
      ? "View failing task in /stats"
      : "View graph in /stats";
    banner.hidden = dismissedToken === visibleToken;
  }

  function clearViolation() {
    visibleToken = null;
    dismissedToken = null;
    const banner = document.getElementById(bannerId);
    if (banner) banner.hidden = true;
  }

  async function refresh() {
    try {
      const response = await fetch(endpoint, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const payload = await response.json();
      const violation = violationOf(payload);
      if (violation) showViolation(violation, payload.violation_count);
      else clearViolation();
    } catch (error) {
      if (!warned) {
        console.warn(`Dagcert violation banner could not read ${endpoint}:`, error);
        warned = true;
      }
    }
  }

  function start() {
    installStyle();
    installBanner();
    refresh();
    if (Number.isFinite(pollMs) && pollMs > 0) window.setInterval(refresh, pollMs);
  }

  window.DagcertViolationBanner = { refresh, showViolation, clearViolation };
  window.addEventListener("dagcert:violation", function (event) {
    showViolation(event.detail || {});
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
