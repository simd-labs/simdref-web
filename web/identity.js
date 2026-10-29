/* Byte identity worker for the Annotate tab: a Web Worker port of
 * src/simdref/asm_identity.py. The main thread passes the rows of the
 * search-index-encodings.json shard once; per document, llvm-mc (wasm)
 * assembles the text, x86 bytes go through XED (wasm), and Arm/RISC-V
 * words match the shard's (enc_mask, enc_match) patterns. No mnemonic
 * or form list here: every line ends as one shard key, or with a
 * reason. */

"use strict";

/* The four binaries are release assets of the simd-labs/visualizer tag
 * wasm-v1 (its SHA256SUMS file lists these digests). The test suite
 * overrides the base through the init message so tests fetch nothing
 * from GitHub. */
const WASM_BASE = "https://github.com/simd-labs/visualizer/releases/download/wasm-v1/";
const WASM_SHA256 = Object.freeze({
  "llvm-mc.js": "f3d3526dac76c04d4514d873e205a1a4af7ae7ebd1b191298ace43fd314dd625",
  "llvm-mc.wasm": "43444c28e5d0da31a6521ca829fecf67bb4ea6c0cdb16b6ee413d119a85dc942",
  "xedform.cjs": "cf8f9238f270474a0b2c714c33c12470183bee8a4ee2e628ed9da25d9ec2d84b",
  "xedform.wasm": "2793750aa3d7ab1ab2e5ee4a04443ac16bff701e6108ca763c66e26042164ba6",
});

/* Kept in sync with asm_identity._ARCH_CFG (arm32 does no lookup there,
 * and the site has no arm32 selector). */
const ARCH_CFG = Object.freeze({
  x86: {
    triple: "x86_64-unknown-linux-gnu",
    mattr: "+avx512f,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi,+avx512vbmi2," +
      "+avx512vnni,+avx512bitalg,+avx512vpopcntdq,+avx512ifma,+vaes,+vpclmulqdq," +
      "+avx,+avx2,+fma,+f16c,+bmi,+bmi2,+lzcnt,+movbe",
  },
  aarch64: { triple: "aarch64-unknown-linux-gnu", mattr: "+sve,+sve2,+sve2p1,+sme,+sme2,+sme2p1" },
  riscv32: { triple: "riscv32-unknown-linux-gnu", mattr: "+m,+a,+f,+d,+c,+v,+zba,+zbb,+zbs" },
  riscv64: { triple: "riscv64-unknown-linux-gnu", mattr: "+m,+a,+f,+d,+c,+v,+zba,+zbb,+zbs" },
});
const X86_SYNTAX_FLAG = Object.freeze({ att: "-x86-asm-syntax=att", intel: "-x86-asm-syntax=intel" });

const COMMENT_STARTS = ["#", "//", "/*", "@", ";"];
const ERR_RE = /^<stdin>:(\d+):(\d+): (?:error|warning): (.*)$/;
const ENC_RE = /encoding: \[([^\]]*)\]/;
const INST_RE = /<MCInst #\d+ (\S+)/;
const CONT_RE = /^\s+(#|\/\/|@|;)/;
const LABEL_RE = /^[\w.$]+:/;
const BYTE_RE = /^0x([0-9a-fA-F]{2})(?:'A')?$/;
const BITS_RE = /^0b([01Aa]{8})$/;

/* uops.info eosz attribute values per effective operand size. */
const EOSZ_ATTR = Object.freeze({ 16: "1", 32: "2", 64: "3" });
/* The four x86 registers uops.info tags as high-byte (its high8 attr). */
const HIGH8_REGS = new Set(["AH", "BH", "CH", "DH"]);

// --------------------------------------------------------------------
// shard side: pattern lists and iform pools
// --------------------------------------------------------------------

let shard = null;

function push(map, key, value) {
  let bucket = map.get(key);
  if (!bucket) map.set(key, (bucket = []));
  bucket.push(value);
}

function buildShard(rows) {
  const index = { a64: [], rv: new Map(), iform: new Map() };
  for (const row of rows) {
    const bits = row.enc_bits || 0;
    const mask = (row.enc_mask || 0) >>> 0;
    const match = (row.enc_match || 0) >>> 0;
    if (row.arch === "aarch64" && bits === 32) {
      index.a64.push({ mask, match, key: row.key });
    } else if (row.arch === "riscv") {
      const extras = Array.isArray(row.enc_extra) && row.enc_extra.length
        ? row.enc_extra
        : [["", bits, mask, match]];
      for (const e of extras) {
        push(index.rv, String(e[0] || ""), {
          bits: e[1] || 0,
          mask: (e[2] || 0) >>> 0,
          match: (e[3] || 0) >>> 0,
          key: row.key,
        });
      }
    } else if (row.arch === "x86" && row.iform) {
      push(index.iform, row.iform, { key: row.key, attrs: row.split_attrs || {} });
    }
  }
  return index;
}

/* RV32E/RV64E keys serve their whole base family; a bare key is
 * base-agnostic (flat encoding block). asm_identity.rv_patterns_for. */
function rvPatternsFor(base) {
  const out = [];
  for (const [key, entries] of shard.rv) {
    if (!key || key.slice(0, 4) === base.slice(0, 4)) out.push(...entries);
  }
  return out;
}

/* Drop a candidate strictly covered by another candidate's pattern
 * (asm_identity._refine_subset). */
function refineSubset(hits) {
  return hits.filter(
    (b) =>
      !hits.some(
        (a) =>
          a.mask !== b.mask &&
          ((b.mask & a.mask) >>> 0) === b.mask &&
          (((b.match ^ a.match) & b.mask) >>> 0) === 0
      )
  );
}
// The Python predicate is (match_b & mask_b) == (match_a & mask_b);
// ((a.match ^ b.match) & mask_b) === 0 is the same test in one step.

// --------------------------------------------------------------------
// line classification and llvm-mc echo parsing
// --------------------------------------------------------------------

function classifyLine(text) {
  let stripped = text.trim();
  if (!stripped) return "blank";
  if (COMMENT_STARTS.some((c) => stripped.startsWith(c))) return "comment";
  const label = LABEL_RE.exec(stripped);
  if (label) {
    stripped = stripped.slice(label[0].length).trim();
    if (!stripped) return "label";
  }
  if (stripped.startsWith(".")) return "directive";
  return null;
}

function parseEchoBlocks(stdout) {
  const blocks = [];
  for (const line of stdout.split("\n")) {
    /* Continuation lines carry the encoding/MCInst info of the block
     * above them; only a fresh echo line opens a new block. */
    if (!CONT_RE.test(line) || !blocks.length) blocks.push({ opcode: null, bytes: null });
    const block = blocks[blocks.length - 1];
    if (block.opcode === null) {
      const m = INST_RE.exec(line);
      if (m) block.opcode = m[1];
    }
    if (block.bytes === null) {
      const m = ENC_RE.exec(line);
      if (m) block.bytes = m[1].trim();
    }
  }
  return blocks;
}

/* llvm-mc prints fixup-covered bits as 'A' (whole byte, nibble, or
 * bit); zero-fill them. The ISA patterns never fix those bits (they are
 * operand fields), so the zeroed bits cannot break a (mask, match)
 * test. */
function bytesToWords(hexbytes) {
  if (!hexbytes) return new Uint8Array(0);
  const out = [];
  for (let token of hexbytes.split(",")) {
    token = token.trim();
    if (token === "A" || token === "'A'") { out.push(0); continue; }
    const m = BYTE_RE.exec(token) || BITS_RE.exec(token);
    if (!m) {
      // shortcut: unknown llvm-mc byte forms zero-fill the whole byte,
      // upgrade the shapes if llvm-mc prints new fixup forms
      out.push(0);
      continue;
    }
    out.push(token.startsWith("0b") ? parseInt(m[1].replace(/[Aa]/g, "0"), 2) : parseInt(m[1], 16));
  }
  return Uint8Array.from(out);
}

// --------------------------------------------------------------------
// tools: fetch signed binaries once, one fresh instance per run
// --------------------------------------------------------------------

async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* Hash the payload before any of it runs. */
async function fetchVerified(base, name, asText) {
  const response = await fetch(base + name);
  if (!response.ok) throw new Error(`${name}: fetch failed (${response.status})`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const got = await sha256Hex(bytes);
  if (got !== WASM_SHA256[name]) {
    throw new Error(
      `${name}: sha256 mismatch (got ${got.slice(0, 12)}…, wanted ${WASM_SHA256[name].slice(0, 12)}…)`
    );
  }
  return asText ? new TextDecoder().decode(bytes) : bytes;
}

/* Byte-at-a-time stdout sink (the Emscripten print hook double-fires
 * under this build, so the Module["stdout"] device gets used). */
function byteSink(lines) {
  let current = "";
  return {
    sink(code) {
      if (code === 10 || code === null) {
        lines.push(current);
        current = "";
      } else {
        current += String.fromCharCode(code);
      }
    },
    flush() {
      if (current) { lines.push(current); current = ""; }
    },
  };
}

let mcState = null; // { factory, compiled }
async function ensureMc(tools) {
  if (mcState) return mcState;
  const [code, wasm] = await Promise.all([
    fetchVerified(tools.base, "llvm-mc.js", true),
    fetchVerified(tools.base, "llvm-mc.wasm", false),
  ]);
  const compiled = await WebAssembly.compile(wasm);
  // The glue is an ES module factory; the text is hash-checked above.
  // data: import() works in module workers.
  const b64 = btoa(unescape(encodeURIComponent(code)));
  mcState = { factory: (await import(`data:text/javascript;base64,${b64}`)).default, compiled };
  return mcState;
}

/* One fresh Module instance per run: re-running callMain on one
 * instance accumulates llvm-mc's cl:: positional inputs across runs.
 * The document rides stdin (no input file), so error lines name
 * <stdin> exactly like the native pipeline. */
async function runMc(tools, args, text) {
  const { factory, compiled } = await ensureMc(tools);
  const outLines = [];
  const errLines = [];
  const out = byteSink(outLines);
  const err = byteSink(errLines);
  let pos = 0;
  let readyResolve, readyReject;
  const ready = new Promise((res, rej) => { readyResolve = res; readyReject = rej; });
  const promise = factory({
    noInitialRun: true,
    onRuntimeInitialized: () => readyResolve(),
    onAbort: (what) => readyReject(new Error(`llvm-mc aborted: ${what}`)),
    stdin() { return pos < text.length ? text.charCodeAt(pos++) : null; },
    stdout: out.sink,
    stderr: err.sink,
    print: () => {},
    printErr: () => {},
    instantiateWasm(imports, receive) {
      WebAssembly.instantiate(compiled, imports).then(receive);
    },
  });
  const module = await promise;
  await ready;
  /* callMain unshifts thisProgram into the array; hand over a copy so
   * the caller's args survive the next pass unchanged. */
  const exit = module.callMain([...args]);
  out.flush();
  err.flush();
  return { exit, stdout: outLines.join("\n"), stderr: errLines.join("\n") };
}

let xedTools = null; // { code, compiled }
async function ensureXed(tools) {
  if (xedTools) return xedTools;
  const [code, wasm] = await Promise.all([
    fetchVerified(tools.base, "xedform.cjs", true),
    fetchVerified(tools.base, "xedform.wasm", false),
  ]);
  xedTools = { code, compiled: await WebAssembly.compile(wasm) };
  return xedTools;
}

/* The xedform glue is a classic script that builds one Module global.
 * One fresh Function scope per run keeps that global per-run clean; the
 * Module parameter preset wins its `var Module = typeof Module ==
 * "undefined" ? {} : Module` guard. */
function runXed(tools, hexes) {
  return ensureXed(tools).then(({ code, compiled }) => new Promise((resolve, reject) => {
    const input = hexes.join("\n") + "\n";
    let pos = 0;
    const outLines = [];
    const out = byteSink(outLines);
    const preset = {
      print: () => {},
      printErr: () => {},
      stdout: out.sink,
      stdin() { return pos < input.length ? input.charCodeAt(pos++) : null; },
      instantiateWasm(imports, receive) {
        WebAssembly.instantiate(compiled, imports).then(receive);
      },
      postRun: [() => { out.flush(); resolve(outLines); }],
      onAbort: (what) => reject(new Error(`xedform aborted: ${what}`)),
    };
    try {
      new Function("Module", `${code}\n;return Module;`)(preset);
    } catch (e) {
      reject(e);
    }
  }));
}

/* asm_identity._xed_facts parse. */
function parseXedFacts(lines, count) {
  if (lines.length !== count) {
    throw new Error(`xedform returned ${lines.length} lines for ${count} inputs`);
  }
  return lines.map((line) => {
    const parts = line.split(/\s+/).filter(Boolean);
    if (!parts.length) return { error: "EMPTY_OUTPUT" };
    if (parts[0] === "DECODE_ERROR") return { error: parts[1] || "DECODE_ERROR" };
    const kv = {};
    for (const part of parts.slice(3)) {
      const eq = part.indexOf("=");
      if (eq > 0) kv[part.slice(0, eq)] = part.slice(eq + 1);
    }
    return {
      iclass: parts[1],
      iform: parts[2],
      eosz: parseInt(kv.eosz, 10),
      regs: (kv.regs || "").split(","),
      imm: parseInt(kv.imm, 10),
      base: kv.base,
      idx: kv.idx,
      scale: parseInt(kv.scale, 10),
      displen: parseInt(kv.displen, 10),
      zero: parseInt(kv.zero || "0", 10),
    };
  });
}

// --------------------------------------------------------------------
// x86: the uops.info attribute splits (asm_identity._x86_pick)
// --------------------------------------------------------------------

function agenShape(value) {
  let base = "", idx = "", disp = 0;
  for (const part of value.split("_")) {
    if (part === "B" || part === "R") base = part;
    else if (part === "I" || part === "IS") idx = part;
    else if (part === "D8" || part === "D32") disp = parseInt(part.slice(1), 10);
    else throw new Error(`unknown agen token ${part} in ${value}`);
  }
  return { base, idx, disp };
}

function agenFacts(d) {
  return {
    base: d.base === "RIP" ? "R" : d.base !== "INVALID" ? "B" : "",
    idx: d.idx === "INVALID" ? "" : d.scale !== 1 ? "IS" : "I",
    disp: d.displen * 8,
  };
}

function x86Pick(pool, d) {
  let cur = pool.slice();
  const filt = (stageOk, pred) => {
    if (cur.length <= 1 || !stageOk) return;
    const picked = cur.filter((row) => pred(row.attrs));
    if (picked.length > 0 && picked.length < cur.length) cur = picked;
  };
  filt(
    cur.some((row) => "eosz" in row.attrs),
    (a) => !("eosz" in a) || a.eosz === EOSZ_ATTR[d.eosz]
  );
  const wantAgen = agenFacts(d);
  filt(
    cur.some((row) => "agen" in row.attrs),
    (a) => {
      if (!("agen" in a)) return true;
      const shape = agenShape(a.agen);
      return shape.base === wantAgen.base && shape.idx === wantAgen.idx && shape.disp === wantAgen.disp;
    }
  );
  const wantHigh8 = new Set(d.regs.flatMap((reg, i) => (HIGH8_REGS.has(reg) ? [`REG${i}`] : [])));
  filt(
    cur.some((row) => "high8" in row.attrs),
    (a) => {
      const got = new Set((a.high8 || "").split(",").filter(Boolean));
      if (got.size !== wantHigh8.size) return false;
      for (const x of wantHigh8) if (!got.has(x)) return false;
      return true;
    }
  );
  const immZero = d.imm === 0 ? "1" : "0";
  filt(
    cur.some((row) => "immzero" in row.attrs),
    (a) => ("immzero" in a ? a.immzero : immZero) === immZero
  );
  const masked = d.regs.some((reg) => reg.startsWith("K") && reg !== "K0") ? "1" : "0";
  filt(
    cur.some((row) => "mask" in row.attrs),
    (a) => ("mask" in a ? a.mask : masked) === masked
  );
  const zeroing = d.zero ? "1" : "0";
  filt(
    cur.some((row) => "zeroing" in row.attrs),
    (a) => ("zeroing" in a ? a.zeroing : zeroing) === zeroing
  );
  return cur;
}
// The Python default is "1" if imm_zero else "0", i.e. the state
// itself; a missing attr then always matches.

// --------------------------------------------------------------------
// document pipeline (asm_identity._probe_lines and friends)
// --------------------------------------------------------------------

function mcArgs(arch, syntax) {
  const cfg = ARCH_CFG[arch];
  const args = [`--triple=${cfg.triple}`, "-show-encoding", "-show-inst"];
  if (cfg.mattr) args.push(`-mattr=${cfg.mattr}`);
  if (arch === "x86") args.push(X86_SYNTAX_FLAG[syntax]);
  return args;
}

async function probeLines(tools, lines, arch, syntax) {
  const args = mcArgs(arch, syntax);
  const work = lines.slice();
  const errors = new Map();
  let stdout = "";
  let lastErrs = new Map();
  /* Blank failing lines and re-run, at most three passes. */
  for (let pass = 0; pass < 3; pass++) {
    const run = await runMc(tools, args, work.join("\n"));
    stdout = run.stdout;
    lastErrs = new Map();
    for (const line of run.stderr.split("\n")) {
      const m = ERR_RE.exec(line);
      if (m && !lastErrs.has(Number(m[1]))) lastErrs.set(Number(m[1]), m[3]);
    }
    if (!lastErrs.size) break;
    for (const [lineNo, text] of lastErrs) {
      if (!errors.has(lineNo)) errors.set(lineNo, text);
      work[lineNo - 1] = "";
    }
  }

  const results = lines.map((text, i) => {
    const kind = classifyLine(text);
    if (errors.has(i + 1)) return { n: i + 1, text, status: "REJECTED", error: errors.get(i + 1) };
    if (kind !== null) return { n: i + 1, text, status: "NOT-AN-INSTRUCTION", kind };
    return { n: i + 1, text, status: "PENDING" };
  });

  /* Lockstep: source lines map one-to-one to echo blocks, except
   * comments (dropped) and lines that failed in the final pass. */
  const echoed = lines
    .map((text, i) => ({ n: i + 1, text }))
    .filter(({ n, text }) => classifyLine(text) !== "comment" && !lastErrs.has(n));
  const blocks = parseEchoBlocks(stdout);
  const pending = results.filter((r) => r.status === "PENDING");
  if (blocks.length === echoed.length) {
    echoed.forEach(({ n }, i) => {
      const result = results[n - 1];
      if (result.status !== "PENDING") return;
      const { opcode, bytes } = blocks[i];
      if (opcode !== null) {
        result.status = "OK";
        result.bytes = bytes;
        result.opcode = opcode;
      } else {
        result.status = "NOT-AN-INSTRUCTION";
        result.kind = "echo-no-inst";
      }
    });
  } else {
    for (const result of pending) {
      result.status = "REJECTED";
      result.error = `line mapping unverified (echo ${blocks.length} vs source ${echoed.length})`;
    }
  }
  return results;
}

/* asm_identity._rv_tiebreak: name the row by llvm-mc's own MCInst
 * opcode; an unnamed tie keeps the coverage refinement and can end
 * ambiguous. */
function rvTiebreak(rows, opcode) {
  const named = String(opcode || "").toLowerCase().replace(/_/g, ".");
  /* The shard keys a row as "riscv:<mnemonic>"; the MCInst opcode names
   * the bare mnemonic. */
  const picked = rows.filter((row) => row.key.toLowerCase().replace(/^riscv:/, "") === named);
  if (picked.length) return picked;
  return refineSubset(rows.map((row) => ({ mask: row.mask, match: row.match, key: row.key })));
}

function identifyWords(probed, results, arch) {
  const docBase = arch === "riscv32" ? "RV32" : "RV64";
  for (const [entry, result] of zip(probed, results)) {
    if (entry.status !== "OK") continue;
    const raw = bytesToWords(entry.bytes);
    let rows;
    if (arch === "aarch64") {
      if (raw.length !== 4) { result.reason = "no catalog row (not one 32-bit word)"; continue; }
      const word = new DataView(raw.buffer, raw.byteOffset, 4).getUint32(0, true);
      const hits = refineSubset(shard.a64.filter((p) => ((word & p.mask) >>> 0) === p.match));
      rows = hits;
    } else {
      if (raw.length !== 2 && raw.length !== 4) {
        result.reason = "no catalog row (not a 16/32-bit word)";
        continue;
      }
      const dv = new DataView(raw.buffer, raw.byteOffset, raw.length);
      const word = raw.length === 2 ? dv.getUint16(0, true) : dv.getUint32(0, true);
      rows = rvPatternsFor(docBase).filter(
        (p) => p.bits === raw.length * 8 && ((word & p.mask) >>> 0) === p.match
      );
      if (rows.length > 1) rows = rvTiebreak(rows, entry.opcode);
    }
    const keys = [...new Set(rows.map((r) => r.key))];
    if (keys.length === 1) {
      result.status = "row";
      result.key = keys[0];
    } else if (!keys.length) {
      result.reason = "no catalog row";
    } else {
      result.reason = `ambiguous: ${keys.length} rows match the encoding`;
      result.candidates = keys.slice();
    }
  }
}
// keys are deduped for the row verdict: Python rows carry db_key
// one-to-one, and the shard keys one entry per row, so this matches.

async function identifyX86(tools, probed, results) {
  const pending = [...zip(probed, results)].filter(([entry]) => entry.status === "OK");
  if (!pending.length) return;
  const hexes = pending.map(([entry]) =>
    [...bytesToWords(entry.bytes)].map((b) => b.toString(16).padStart(2, "0")).join("")
  );
  const facts = parseXedFacts(await runXed(tools, hexes), hexes.length);
  for (const [[entry, result], fact] of zip(pending, facts)) {
    if ("error" in fact) { result.reason = `no catalog row (XED ${fact.error})`; continue; }
    const pool = shard.iform.get(fact.iform) || [];
    if (!pool.length) { result.reason = `no catalog row (iform ${fact.iform} absent)`; continue; }
    let rows;
    try {
      rows = pool.length > 1 ? x86Pick(pool, fact) : pool;
    } catch (e) {
      result.reason = `no catalog row (${e.message})`;
      continue;
    }
    if (rows.length === 1) {
      result.status = "row";
      result.key = rows[0].key;
    } else if (!rows.length) {
      result.reason = `no catalog row (splits emptied iform ${fact.iform})`;
    } else {
      result.reason = `ambiguous: ${rows.length} rows share iform ${fact.iform}`;
      result.candidates = rows.map((r) => r.key);
    }
  }
}

function* zip(a, b) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) yield [a[i], b[i]];
}

async function identifyDocument(tools, text, arch, syntax) {
  /* Python splitlines() semantics: the line terminator is implicit, so
   * a document ending in "\n" has no phantom last line. */
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  const probed = await probeLines(tools, lines, arch, syntax);
  const results = probed.map((entry) => ({
    n: entry.n,
    text: entry.text,
    status: entry.status === "NOT-AN-INSTRUCTION" ? "not-an-instruction" : "no-row",
    reason:
      entry.status === "NOT-AN-INSTRUCTION"
        ? entry.kind || ""
        : entry.status === "REJECTED"
          ? entry.error || "rejected by llvm-mc"
          : "",
    key: null,
    candidates: [],
  }));
  if (arch === "x86") await identifyX86(tools, probed, results);
  else identifyWords(probed, results, arch);
  return results;
}

// --------------------------------------------------------------------
// message protocol
// --------------------------------------------------------------------

let tools = null;

self.onmessage = async (event) => {
  const msg = event.data;
  if (msg.type === "init") {
    try {
      shard = buildShard(msg.rows);
      tools = { base: msg.base || WASM_BASE };
      /* Fetch and hash all four binaries up front: a sha256 failure
       * reports once at init instead of racing the first annotate. */
      await ensureMc(tools);
      await ensureXed(tools);
      self.postMessage({ type: "ready" });
    } catch (e) {
      self.postMessage({ type: "init-failed", error: String(e && e.message || e) });
    }
    return;
  }
  if (msg.type === "identify") {
    try {
      const results = await identifyDocument(tools, msg.text, msg.arch, msg.syntax || "att");
      self.postMessage({ type: "result", seq: msg.seq, results });
    } catch (e) {
      self.postMessage({ type: "run-failed", seq: msg.seq, error: String(e && e.message || e) });
    }
  }
};
