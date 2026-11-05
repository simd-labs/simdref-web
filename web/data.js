/* simdref — web data loader.

 * ES module: the search-index fetch (gzip-aware), the detail-chunk caches
 * and loaders, the schema-version check and the per-entry measurement
 * rows, moved out of app.js so other pages can import them. Every data
 * URL resolves against this module's own directory (import.meta.url), so
 * a page on another origin that imports this module fetches its chunks
 * from this module's origin. Imports in node with no DOM. */

/* Base of the site data: the directory holding this module. */
const BASE = new URL(".", import.meta.url);

// Column-encoding version this build can decode. Bump alongside the matching
// `decodeInstructions`/`decodeIntrinsics` rewrite when core changes the shape.
export const SUPPORTED_SCHEMA_VERSION = 1;


/* Mismatch between the loaded build stamp and this build: the message
 * for the load-error UI, or null when the stamp is absent or current. */
export function schemaCheck(stamp) {
  if (stamp && stamp.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    return `Catalog export is schema v${stamp.schema_version}, this build reads v${SUPPORTED_SCHEMA_VERSION}. Rebuild the site data.`;
  }
  return null;
}

/* ── gzip-aware fetch ─────────────────────────────────────────────────
 * Prefer a pre-compressed *.gz sidecar (so GitHub Pages & bare static
 * hosts don't need Content-Encoding: gzip), fall back to the raw .json.
 */
export async function fetchJson(path) {
  const base = new URL(path.replace(/\.json$/, ""), BASE);
  if (typeof DecompressionStream !== "undefined") {
    try {
      const r = await fetch(`${base}.json.gz`);
      if (r.ok) {
        const ds = r.body.pipeThrough(new DecompressionStream("gzip"));
        return await new Response(ds).json();
      }
    } catch (_) { /* fall through */ }
  }
  const r = await fetch(`${base}.json`);
  return r.ok ? r.json() : null;
}

/* ── Lazy detail loading ──────────────────────────────────────────── */
export function chunkPrefix(mnemonic) {
  const c = (mnemonic || "").trim().toUpperCase();
  return c.length >= 3 ? c.slice(0, 3) : c;
}

/* Keep in sync with simdref.export._intrinsic_chunk_prefix. */
export function intrinsicChunkPrefix(name) {
  let s = String(name || "").replace(/^_+/, "");
  if (s.slice(0, 6).toLowerCase() === "riscv_") s = s.slice(6);
  const m = s.match(/^(?:mm\d*|sv|vq?)_?/i);
  if (m && m[0].length < s.length) s = s.slice(m[0].length);
  s = s.replace(/^_+/, "");
  const clean = (s.match(/[a-z0-9]/gi) || []).join("").toLowerCase();
  if (clean.length < 2) return "misc";
  return clean.slice(0, 3);
}

/* Detail chunk caches: prefix -> Promise<data>. Separate maps for
 * instructions (detail-chunks/) and intrinsics (intrinsic-chunks/) so
 * colliding prefixes (e.g. "ADD") don't shadow each other. */
const chunkCache = new Map();
const intrinsicChunkCache = new Map();

export function loadChunk(prefix) {
  if (chunkCache.has(prefix)) return chunkCache.get(prefix);
  const p = fetchJson(`detail-chunks/${encodeURIComponent(prefix)}.json`)
    .then(data => data || {})
    .catch(() => ({}));
  chunkCache.set(prefix, p);
  return p;
}

function loadIntrinsicChunk(prefix) {
  if (intrinsicChunkCache.has(prefix)) return intrinsicChunkCache.get(prefix);
  const p = fetchJson(`intrinsic-chunks/${encodeURIComponent(prefix)}.json`)
    .then(data => data || {})
    .catch(() => ({}));
  intrinsicChunkCache.set(prefix, p);
  return p;
}

/* Fetch one intrinsic's full details (lazy, per-bucket). Returns the
 * detail entry or null if not found in its bucket (build skew). */
export async function loadIntrinsic(name) {
  const chunk = await loadIntrinsicChunk(intrinsicChunkPrefix(name));
  return chunk[name] || null;
}

/* Warm intrinsic-chunks for the top N visible hits during browser
 * idle time so clicking a result doesn't pay a network round-trip. */
export function prefetchIntrinsicChunks(entries) {
  const schedule = window.requestIdleCallback || ((cb) => setTimeout(cb, 0));
  const prefixes = new Set();
  for (const e of entries) {
    if (!e || e.kind !== "intrinsic") continue;
    prefixes.add(intrinsicChunkPrefix(e.item.name));
    if (prefixes.size >= 4) break;
  }
  for (const prefix of prefixes) {
    if (intrinsicChunkCache.has(prefix)) continue;
    schedule(() => { loadIntrinsicChunk(prefix); });
  }
}

let _encodingsShardPromise = null;
export function loadEncodingsShard() {
  if (!_encodingsShardPromise) {
    _encodingsShardPromise = fetchJson("search-index-encodings.json")
      .then(rows => (Array.isArray(rows) && rows.length ? rows : null))
      .catch(() => null);
  }
  return _encodingsShardPromise;
}

export async function measurementsForEntry(entry) {
  const prefix = chunkPrefix(entry.mnemonic);
  const chunk = await loadChunk(prefix);
  const record = chunk && chunk[entry.key];
  return (record && Array.isArray(record.measurements)) ? record.measurements : [];
}
