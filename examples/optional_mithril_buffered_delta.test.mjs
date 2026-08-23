import assert from "node:assert/strict";

import { bufferedDelta } from "./optional_mithril_buffered_delta.js";

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 10));
}

async function coalescesRapidClicks() {
  const sent = [];
  let authoritative = 0;
  const helper = bufferedDelta(null, {
    debounceMs: 0,
    async send({ delta }) {
      sent.push(delta);
      authoritative += delta;
      return { value: authoritative };
    },
  });

  helper.add(1);
  helper.add(2);
  assert.equal(helper.value(), 3);
  await tick();
  assert.deepEqual(sent, [3]);
  assert.equal(helper.value(), 3);
}

async function sendsClicksDuringARequestAsTheNextDelta() {
  const sent = [];
  const resolvers = [];
  const helper = bufferedDelta(null, {
    debounceMs: 0,
    send({ delta }) {
      sent.push(delta);
      return new Promise((resolve) => resolvers.push(resolve));
    },
  });

  helper.add(1);
  await tick();
  helper.add(2);
  assert.deepEqual(sent, [1]);
  assert.equal(helper.value(), 3);

  resolvers.shift()({ value: 1 });
  await tick();
  assert.deepEqual(sent, [1, 2]);

  resolvers.shift()({ value: 3 });
  await tick();
  assert.equal(helper.value(), 3);
}

async function doesNotInventAutomaticRetries() {
  let attempts = 0;
  const expected = new Error("offline");
  const observed = [];
  const helper = bufferedDelta(null, {
    debounceMs: 0,
    async send() {
      attempts += 1;
      throw expected;
    },
    onError(error) {
      observed.push(error);
    },
  });

  helper.add(1);
  await tick();
  await tick();
  assert.equal(attempts, 1);
  assert.equal(helper.value(), 1);
  assert.equal(helper.error(), expected);
  assert.deepEqual(observed, [expected]);
}

await coalescesRapidClicks();
await sendsClicksDuringARequestAsTheNextDelta();
await doesNotInventAutomaticRetries();
