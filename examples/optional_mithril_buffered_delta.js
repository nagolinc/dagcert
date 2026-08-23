// Optional fast-front/slow-back pattern for Mithril applications.
//
// Dagcert can time the immediate redraw and the authoritative request as ordinary
// tasks. The helper deliberately does not choose retry, timeout, queue-limit, or
// rejection policy for the application.

export function bufferedDelta(m, { send, debounceMs, onError = () => {} }) {
  if (typeof send !== "function") {
    throw new TypeError("send must be a function");
  }

  if (!Number.isFinite(debounceMs) || debounceMs < 0) {
    throw new TypeError("choose a nonnegative debounceMs explicitly");
  }

  let confirmed = 0;
  let pending = 0;
  let inFlight = 0;
  let timer = null;
  let sending = false;
  let lastError = null;

  function redraw() {
    m?.redraw?.();
  }

  function value() {
    return confirmed + pending + inFlight;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(flush, debounceMs);
  }

  async function flush() {
    if (sending || pending === 0) {
      return;
    }

    const delta = pending;
    pending = 0;
    inFlight = delta;
    sending = true;
    lastError = null;
    redraw();

    try {
      const response = await send({ delta });
      if (!response || !Number.isFinite(response.value)) {
        throw new TypeError("send must resolve to an object with a finite value");
      }
      confirmed = response.value;
    } catch (error) {
      // Keep the optimistic delta visible, but do not invent automatic retry
      // behavior. The application may call retry() or resolve the error itself.
      pending += delta;
      lastError = error;
      onError(error);
    } finally {
      inFlight = 0;
      sending = false;
      redraw();

      // Clicks received during a successful request form the next buffered delta.
      // After a failure, retry remains an explicit application decision.
      if (pending !== 0 && lastError === null) {
        schedule();
      }
    }
  }

  function add(delta = 1) {
    if (!Number.isFinite(delta)) {
      throw new TypeError("delta must be finite");
    }
    pending += delta;
    lastError = null;
    redraw();
    schedule();
  }

  function retry() {
    if (!sending && pending !== 0) {
      lastError = null;
      schedule();
    }
  }

  return {
    value,
    add,
    flush,
    retry,
    error: () => lastError,
  };
}
