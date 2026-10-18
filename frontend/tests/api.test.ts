import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api, ApiError, isTransientError, post } from "../src/api.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

for (const path of ["/jobs", "/jobs/parent/revisions"]) {
  test(`ambiguous ${path} submission retries with the same ID`, async () => {
    const requests: RequestInit[] = [];
    globalThis.fetch = async (_url, options) => {
      requests.push(options!);
      if (requests.length === 1) throw new TypeError("Failed to fetch");
      return Response.json({id:"same-job"}, {status:201});
    };
    assert.deepEqual(await post(path, {topic:"Test"}), {id:"same-job"});
    assert.equal(requests.length, 2);
    const first = new Headers(requests[0].headers).get("Idempotency-Key");
    assert.ok(first);
    assert.equal(first, new Headers(requests[1].headers).get("Idempotency-Key"));
    assert.equal(requests[0].body, requests[1].body);
  });
}

test("validation and non-idempotent commands are not retried", async () => {
  let count = 0;
  globalThis.fetch = async () => { count++; return Response.json({detail:"Invalid input"}, {status:400}); };
  await assert.rejects(post("/jobs", {}), /Invalid input/);
  assert.equal(count, 1);
  globalThis.fetch = async () => { count++; throw new TypeError("Failed to fetch"); };
  await assert.rejects(post("/jobs/123/cancel"), TypeError);
  assert.equal(count, 2);
});

test("server outages remain transient even with a non-JSON body", async () => {
  globalThis.fetch = async () => new Response("Unavailable", {status:503});
  await assert.rejects(api("/jobs"), error => isTransientError(error));
  assert.equal(isTransientError(new ApiError("Missing job", 404)), false);
});

test("retries are bounded when the server stays unavailable", async () => {
  let count = 0;
  globalThis.fetch = async () => { count++; return new Response("Unavailable", {status:503}); };
  await assert.rejects(post("/jobs"), ApiError);
  assert.equal(count, 2);
});
