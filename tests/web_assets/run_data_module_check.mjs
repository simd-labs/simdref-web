// Node check for the web modules: web/data.js and web/identity.js import
// with no DOM, the schema check names a mismatch, and the chunk loader
// answers from a fixture chunk (fetch stubbed, no server).
import assert from "node:assert";

const data = await import(new URL("../../web/data.js", import.meta.url));
const identity = await import(new URL("../../web/identity.js", import.meta.url));

// The loader exports app.js binds.
for (const name of ["fetchJson", "chunkPrefix", "loadChunk", "loadIntrinsic",
  "loadEncodingsShard", "measurementsForEntry", "schemaCheck"]) {
  assert.equal(typeof data[name], "function", `data.${name} is a function`);
}
assert.equal(typeof data.SUPPORTED_SCHEMA_VERSION, "number");
assert.equal(typeof identity.buildShard, "function");
assert.equal(typeof identity.identifyDocument, "function");

// Schema check: absent or current stamp passes, a mismatch names the fix.
assert.equal(data.schemaCheck(null), null);
assert.equal(data.schemaCheck({ schema_version: data.SUPPORTED_SCHEMA_VERSION }), null);
const mismatch = data.schemaCheck({ schema_version: data.SUPPORTED_SCHEMA_VERSION + 1 });
assert.ok(mismatch.includes("Rebuild the site data"), mismatch);

// Loader against a fixture chunk: the .gz probe must 404 and fall back to
// the plain .json, and the chunk must come back decoded.
const FIXTURE = {
  "x86:add (r32, r32)": {
    measurements: [
      { uarch: "Golden Cove", latency: 1, tpb: 1, tpp: 1, source_kind: "measured" },
    ],
  },
};
let sawGz = false;
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u.endsWith(".json.gz")) { sawGz = true; return new Response(null, { status: 404 }); }
  if (u.endsWith("detail-chunks/ADD.json")) {
    return new Response(JSON.stringify(FIXTURE), { status: 200 });
  }
  return new Response(null, { status: 404 });
};
assert.equal(data.chunkPrefix("add"), "ADD");
const chunk = await data.loadChunk("ADD");
assert.ok(sawGz, "loader probes the .gz sidecar first");
assert.equal(Object.keys(chunk).length, 1);

// Measurement rows for one entry come back from the same fixture chunk.
const rows = await data.measurementsForEntry({ mnemonic: "add", key: "x86:add (r32, r32)" });
assert.equal(rows.length, 1);
assert.equal(rows[0].latency, 1);
assert.equal(rows[0].uarch, "Golden Cove");

// Line-to-row lookup: the shard builds from encodings-index rows.
const shard = identity.buildShard([
  { arch: "aarch64", enc_bits: 32, enc_mask: 0xffffffff, enc_match: 0x91000000, key: "aarch64:eor (w, w, w)" },
]);
assert.equal(shard.a64.length, 1);
assert.equal(shard.rv.size, 0);

console.log("data module check ok");
