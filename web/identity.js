/* Byte identity worker for the Annotate tab: a Web Worker port of
 * src/simdref/asm_identity.py. The main thread passes the rows of the
 * search-index-encodings.json shard once; per document, llvm-mc (wasm)
 * assembles the text, x86 bytes go through XED (wasm), and Arm/RISC-V
 * words match the shard's (enc_mask, enc_match) patterns. No mnemonic
 * or form list here: every line ends as one shard key, or with a
 * reason. */

"use strict";

importScripts("lines.js");  // splitAsmLines: the line rule app.js shares

/* The four binaries are release assets of the simd-labs/visualizer tag
 * wasm-v1 (its SHA256SUMS file lists these digests). The deploy copies
 * them into wasm-v1/ beside this file, so the fetch is same-origin:
 * GitHub's release downloads carry no CORS header. The test suite
 * overrides the base through the init message. */
const WASM_BASE = "wasm-v1/";
const WASM_SHA256 = Object.freeze({
  "llvm-mc.js": "f3d3526dac76c04d4514d873e205a1a4af7ae7ebd1b191298ace43fd314dd625",
  "llvm-mc.wasm": "43444c28e5d0da31a6521ca829fecf67bb4ea6c0cdb16b6ee413d119a85dc942",
  "xedform.cjs": "cf8f9238f270474a0b2c714c33c12470183bee8a4ee2e628ed9da25d9ec2d84b",
  "xedform.wasm": "3fea6b95674c29d16ca8e1da2d05888d96d47019dbfb0279df30aca335f3094e",
});

/* Kept in sync with asm_identity._ARCH_CFG. The site has no arm32 and no
 * riscv32 selector, so those two entries stay out (arm32 does no lookup
 * in the reference either). */
const ARCH_CFG = Object.freeze({
  x86: {
    triple: "x86_64-unknown-linux-gnu",
    mattr: "+avx512f,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi,+avx512vbmi2," +
      "+avx512vnni,+avx512bitalg,+avx512vpopcntdq,+avx512ifma,+vaes,+vpclmulqdq," +
      "+avx,+avx2,+fma,+f16c,+bmi,+bmi2,+lzcnt,+movbe",
  },
  aarch64: { triple: "aarch64-unknown-linux-gnu", mattr: "+sve,+sve2,+sve2p1,+sme,+sme2,+sme2p1" },
  riscv64: { triple: "riscv64-unknown-linux-gnu", mattr: "+m,+a,+f,+d,+c,+v,+zba,+zbb,+zbs" },
});

const COMMENT_STARTS = ["#", "//", "/*", "@", ";"];
const ERR_RE = /^<stdin>:(\d+):(\d+): (?:error|warning): (.*)$/;
/* A real llvm-mc diagnostic block ends in a caret line ("^", "^~~~"). */
const CARET_RE = /^[ ~]*\^+[~]*$/;
/* The encoding comment llvm-mc appends ends its echo line. Requiring
 * the end keeps a string echo ('.ascii " # encoding: [0x90]"') from
 * faking bytes. */
const ENC_RE = /encoding: \[([^\]]*)\]\s*$/;
/* The MCInst dump is a comment continuation line. Requiring the line
 * start keeps a string echo from faking the opcode (RV tie-break
 * input). */
const INST_RE = /^\s*# <MCInst #\d+ (\S+)/;
const CONT_RE = /^\s+(#|\/\/|@|;)/;
const LABEL_RE = /^[\w.$]+:/;
const BYTE_RE = /^0x([0-9a-fA-F]{2})(?:'A')?$/;
const BITS_RE = /^0b([01Aa]{8})$/;
/* One x86 mode flag; the output re-emits it when the assembler executes
 * it. Only the bare echo counts: a label (".code16:") and a symbol
 * assignment print (".code16 = 1", from '.set .code16, 1') echo
 * user-chosen names at the line start in the same stream, and user text
 * must never set the mode. */
const MODE_DIR_RE = /^\.(code16gcc|code16|code32|code64)$/;
const MODE_BITS = Object.freeze({ code16: "16", code16gcc: "16", code32: "32", code64: "64" });

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
  /* Each block also carries the mode llvm-mc assembled it in: the output
   * stream re-emits every active `.code` flag in execution order (a flag
   * in an `.if 0` body, a macro body or a comment does not emit), so the
   * mode comes from what the assembler did, never from the source text.
   * The x86_64 triple starts at 64. (asm_identity._parse_echo_blocks) */
  let mode = "64";
  for (const line of stdout.split("\n")) {
    /* Continuation lines carry the encoding/MCInst info of the block
     * above them; only a fresh echo line opens a new block. The echo
     * text marks the block: the line-marker labels echo back here. */
    const cont = CONT_RE.test(line);
    if (!cont) {
      const m = MODE_DIR_RE.exec(line.trim());
      if (m) mode = MODE_BITS[m[1]];
    }
    if (!cont || !blocks.length) {
      blocks.push({ echo: cont ? "" : line.trimEnd(), opcode: null, bytes: null, mode });
    }
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

/* asm_identity._covered_mask, kept per byte: bit mask of fixup-covered
 * bits in each byte. A binary token names its known bits and a plain
 * hex byte names all 8; every other shape names none. */
function coveredBits(hexbytes) {
  if (!hexbytes) return [];
  return hexbytes.split(",").map((token) => {
    token = token.trim();
    const bits = BITS_RE.exec(token);
    if (bits) {
      let covered = 0;
      for (let pos = 0; pos < 8; pos++) {
        if (bits[1][pos] === "A" || bits[1][pos] === "a") covered |= 1 << (7 - pos);
      }
      return covered;
    }
    if (BYTE_RE.exec(token) && !token.endsWith("'A'")) return 0;
    return 0xff;
  });
}

/* The covered bits of one <=4-byte word as an unsigned mask. */
function coveredWord(bits) {
  let mask = 0;
  for (let i = 0; i < bits.length; i++) mask = (mask | (bits[i] << (8 * i))) >>> 0;
  return mask;
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
 * instance accumulates llvm-mc's cl:: positional inputs across runs,
 * and a fresh module carries a fresh in-memory filesystem. The
 * document rides stdin (no input file), so error lines name
 * <stdin> exactly like the native pipeline.
 *
 * .print text goes to stdout, where the mode-flag and line-marker
 * text also lands, so captured stdout is poisonable and never
 * parsed: the assembly output goes through -o to a file in the
 * module's own filesystem, and only that output is parsed.
 *
 * The output cannot be a plain file: on any assembly error llvm-mc's
 * ToolOutputFile cleanup deletes it and the lines that did assemble
 * lose their bytes (the old stdout path kept them). A character
 * device survives: the cleanup unlinks the node, but the written
 * bytes already landed in the JS chunk list. */
const MC_OUT = "/simdref-mc.out";

async function runMc(tools, args, text) {
  const { factory, compiled } = await ensureMc(tools);
  const errLines = [];
  const err = byteSink(errLines);
  const outChunks = [];
  let pos = 0;
  let readyResolve, readyReject;
  const ready = new Promise((res, rej) => { readyResolve = res; readyReject = rej; });
  const promise = factory({
    noInitialRun: true,
    onRuntimeInitialized: () => readyResolve(),
    onAbort: (what) => readyReject(new Error(`llvm-mc aborted: ${what}`)),
    stdin() { return pos < text.length ? text.charCodeAt(pos++) : null; },
    stdout: () => {},
    stderr: err.sink,
    print: () => {},
    printErr: () => {},
    instantiateWasm(imports, receive) {
      WebAssembly.instantiate(compiled, imports).then(receive);
    },
  });
  const module = await promise;
  await ready;
  module.FS.createDevice("/", "simdref-mc.out", null, (code) => outChunks.push(code));
  /* callMain unshifts thisProgram into the array; hand over a copy so
   * the caller's args survive the next pass unchanged. */
  const exit = module.callMain([...args, "-o", MC_OUT]);
  err.flush();
  return {
    exit,
    text: new TextDecoder().decode(Uint8Array.from(outChunks)),
    stderr: errLines.join("\n"),
  };
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

function x86Pick(pool, d, immUnknown) {
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
  /* A fixup placeholder covers the immediate (audit A1): the immzero
   * split cannot narrow on it. */
  const immZero = d.imm === 0 ? "1" : "0";
  filt(
    !immUnknown && cur.some((row) => "immzero" in row.attrs),
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

function mcArgs(arch) {
  const cfg = ARCH_CFG[arch];
  const args = [`--triple=${cfg.triple}`, "-show-encoding", "-show-inst"];
  if (cfg.mattr) args.push(`-mattr=${cfg.mattr}`);
  if (arch === "x86") args.push("-x86-asm-syntax=att");
  return args;
}

/* llvm-mc's lexer names a string that the line end cuts off. Anchored
 * to the diagnostic start: the lone line's stderr echoes the line's
 * own text, and that echo must never pose as the diagnostic. */
const UNTERM_STR_RE = /^<stdin>:\d+:\d+: error: unterminated string constant/m;

/* Verdicts of the lone-line scan, per (arch, line text), for the
 * worker's life: re-annotating one document reruns nothing. */
const spanScanCache = new Map();

/* A quoted string that spans a line break lands its text on its own
 * lines in llvm-mc's listing or stderr, where it reads as a directive,
 * an encoding line or a diagnostic (review F1: the fake .code64
 * flipped the mode; review F2: the fake error declined the movq row).
 * No textual scan sees it reliably: quotes in a comment (a block
 * comment holding one quote) or a '"' character constant balance any
 * quote count while the string still spans. So the assembler itself
 * decides: each source line that holds a '"' assembles alone, and an
 * unterminated string constant on that lone line means the string
 * continues past the line break. The whole document then declines and
 * the old matcher answers.
 * Only that diagnostic declines: any other lone-line error (an .ascii
 * whose argument the scan cut, a symbol line with a quote) keeps the
 * document, because no string crosses the line break there. A lone
 * line never suffers from error hiding of a multi-line scan, which is
 * why the lines assemble one by one instead of .include'd in one run. */
async function stringSpansLines(tools, lines, arch) {
  const args = mcArgs(arch);
  for (const line of lines) {
    if (!line.includes('"')) continue;
    const key = arch + "\0" + line;
    let spans = spanScanCache.get(key);
    if (spans === undefined) {
      const run = await runMc(tools, args, line + "\n");
      spans = UNTERM_STR_RE.test(run.stderr);
      spanScanCache.set(key, spans);
    }
    if (spans) return true;
  }
  return false;
}

async function probeLines(tools, lines, arch) {
  const args = mcArgs(arch);
  /* The map comes from llvm-mc's own output, never from counting: a
   * unique label (the line marker) stands before every source line and
   * echoes back among the output blocks, so the blocks after marker i
   * and before the next forward marker belong to source line i. One
   * line can yield several blocks (';' statements, label + instruction,
   * macro expansion) or none (comment, macro body, '.endm'). Only a
   * line with exactly one encoding block and its marker echoed exactly
   * once has proven bytes. (asm_identity._probe_lines) */
  const nonce = [...crypto.getRandomValues(new Uint8Array(4))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const markers = lines.map((_, i) => `.L__simdref_lm_${nonce}_${i + 1}:`);
  const work = [];
  for (let i = 0; i < lines.length; i++) work.push(markers[i], lines[i]);
  /* The trailing newline keeps trailing blank source lines in the
   * input (a bare join swallows them and the whole map fails). */
  const run = await runMc(tools, args, work.join("\n") + "\n");

  /* Error lines number the marked document: 2i-1 is the marker of
   * source line i, 2i is the source line itself. Only the exact llvm-mc
   * diagnostic shape counts: the diagnostic, the echo of the line it
   * names, then the caret line. A source line or string text can print
   * a diagnostic-shaped line of its own (review F2 without the span)
   * and that must never decline another line. (asm_identity) */
  const errors = new Map();
  const stderrLines = run.stderr.split("\n");
  for (let i = 0; i + 2 < stderrLines.length; i++) {
    const m = ERR_RE.exec(stderrLines[i]);
    if (!m) continue;
    const claimed = Number(m[1]);
    if (!(claimed > 0 && claimed <= work.length)) continue;
    if (stderrLines[i + 1].trimEnd() !== work[claimed - 1].trimEnd()) continue;
    if (!CARET_RE.test(stderrLines[i + 2])) continue;
    if (!errors.has(claimed)) errors.set(claimed, m[3]);
  }
  const blocks = parseEchoBlocks(run.text);

  const indexOf = new Map(markers.map((marker, i) => [marker, i + 1]));
  const seen = new Map();
  const buckets = new Map();
  let current = 0;
  for (const block of blocks) {
    const marker = indexOf.get(block.echo.trim());
    if (marker === undefined) {
      if (!buckets.has(current)) buckets.set(current, []);
      buckets.get(current).push(block);
      continue;
    }
    seen.set(marker, (seen.get(marker) || 0) + 1);
    /* Only a forward marker moves the attribution: a marker echoed
     * again comes from a macro or .rept body expansion, and those
     * blocks belong to the line that triggered the expansion. */
    if (marker > current) current = marker;
  }

  return lines.map((text, i) => {
    const n = i + 1;
    const kind = classifyLine(text);
    if (errors.has(2 * n)) return { n, text, status: "REJECTED", error: errors.get(2 * n) };
    const bucket = buckets.get(n) || [];
    const enc = bucket.filter((block) => block.bytes !== null);
    const proven = (seen.get(n) || 0) === 1 && !errors.has(2 * n - 1);
    if (kind === "blank" || kind === "label" || kind === "directive") {
      /* These kinds are certain from the text; a leaked block from a
       * line with a swallowed marker never becomes this line's row. */
      return { n, text, status: "NOT-AN-INSTRUCTION", kind };
    }
    if (enc.length === 1 && proven) {
      return { n, text, status: "OK", bytes: enc[0].bytes, opcode: enc[0].opcode, mode: enc[0].mode };
    }
    if (!enc.length && kind !== null) return { n, text, status: "NOT-AN-INSTRUCTION", kind };
    if (!enc.length && bucket.length === 1) {
      return { n, text, status: "NOT-AN-INSTRUCTION", kind: "echo-no-inst" };
    }
    const reason = !proven
      ? `line mapping unverified (marker echoes ${seen.get(n) || 0})`
      : enc.length > 1
        ? `line mapping unverified (${enc.length} instruction blocks on one line)`
        : "line mapping unverified (no instruction echo for the line)";
    return { n, text, status: "REJECTED", error: reason };
  });
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
    const covered = coveredWord(coveredBits(entry.bytes));
    let rows, checks;
    if (arch === "aarch64") {
      if (raw.length !== 4) { result.reason = "no catalog row (not one 32-bit word)"; continue; }
      const word = new DataView(raw.buffer, raw.byteOffset, 4).getUint32(0, true);
      /* A fixup placeholder covers pattern bits (audit A4): match the
       * known bits only, never the zero fill. */
      checks = shard.a64.filter((p) => ((word ^ p.match) & p.mask & ~covered) === 0);
      rows = refineSubset(checks);
    } else {
      if (raw.length !== 2 && raw.length !== 4) {
        result.reason = "no catalog row (not a 16/32-bit word)";
        continue;
      }
      const dv = new DataView(raw.buffer, raw.byteOffset, raw.length);
      const word = raw.length === 2 ? dv.getUint16(0, true) : dv.getUint32(0, true);
      checks = rvPatternsFor(docBase).filter(
        (p) => p.bits === raw.length * 8 && ((word ^ p.match) & p.mask & ~covered) === 0
      );
      rows = checks.length > 1 ? rvTiebreak(checks, entry.opcode) : checks;
    }
    if (covered) {
      /* The row is decided without the placeholder only when one row
       * survives on the known bits and one of its matching patterns
       * reads no covered bit: then the pattern holds for every value
       * of the placeholder and the row is not a guess. (audit A4) */
      const keys = [...new Set(rows.map((r) => r.key))];
      const decided =
        keys.length === 1 && checks.some((c) => (c.mask & covered) === 0 && c.key === keys[0]);
      if (decided) {
        result.status = "row";
        result.key = keys[0];
      } else if (!keys.length) {
        result.reason = "no catalog row";
      } else if (keys.length > 1) {
        result.reason = `no catalog row (fixup placeholder decides between ${keys.length} rows)`;
      } else {
        result.reason = "no catalog row (fixup placeholder covers a pattern field)";
      }
      continue;
    }
    const keys = [...new Set(rows.map((r) => r.key))];
    if (keys.length === 1) {
      result.status = "row";
      result.key = keys[0];
    } else if (!keys.length) {
      result.reason = "no catalog row";
    } else {
      result.reason = `ambiguous: ${keys.length} rows match the encoding`;
    }
  }
}
// keys are deduped for the row verdict: Python rows carry db_key
// one-to-one, and the shard keys one entry per row, so this matches.
// With covered = 0 the match test is (word & mask) === match again, so
// the covered-aware filter needs no separate fast path.

async function identifyX86(tools, probed, results) {
  const pending = [];
  for (const [entry, result] of zip(probed, results)) {
    if (entry.status !== "OK") continue;
    const mode = entry.mode;
    /* The decoder runs in 64-bit mode (audit B1); a line another mode
     * encodes decodes to the wrong facts, so it reports no row. */
    if (mode !== "64") {
      result.reason = `no catalog row (assembled in ${mode}-bit mode)`;
      continue;
    }
    pending.push([entry, result]);
  }
  if (!pending.length) return;
  const hexes = pending.map(([entry]) =>
    [...bytesToWords(entry.bytes)].map((b) => b.toString(16).padStart(2, "0")).join("")
  );
  const facts = parseXedFacts(await runXed(tools, hexes), hexes.length);
  for (const [[entry, result], fact] of zip(pending, facts)) {
    if ("error" in fact) { result.reason = `no catalog row (XED ${fact.error})`; continue; }
    const pool = shard.iform.get(fact.iform) || [];
    if (!pool.length) { result.reason = `no catalog row (iform ${fact.iform} absent)`; continue; }
    /* A fixup placeholder covers the immediate value (audit A1): the
     * pick must not read it, and a row carrying an immzero claim about
     * it would be a guess either way. */
    const covered = coveredBits(entry.bytes).some((byte) => byte !== 0);
    let rows;
    try {
      rows = pool.length > 1 ? x86Pick(pool, fact, covered) : pool;
    } catch (e) {
      result.reason = `no catalog row (${e.message})`;
      continue;
    }
    if (covered) {
      const guessed = rows.filter((row) => "immzero" in row.attrs);
      if (rows.length === 1 && !guessed.length) {
        result.status = "row";
        result.key = rows[0].key;
      } else if (rows.length > 1) {
        result.reason = `no catalog row (fixup placeholder decides between ${rows.length} rows)`;
      } else {
        result.reason = "no catalog row (fixup placeholder covers an encoded field)";
      }
      continue;
    }
    if (rows.length === 1) {
      result.status = "row";
      result.key = rows[0].key;
    } else if (!rows.length) {
      result.reason = `no catalog row (splits emptied iform ${fact.iform})`;
    } else {
      result.reason = `ambiguous: ${rows.length} rows share iform ${fact.iform}`;
    }
  }
}

function* zip(a, b) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) yield [a[i], b[i]];
}

async function identifyDocument(tools, text, arch) {
  /* splitAsmLines (lines.js) numbers the lines exactly as app.js
   * splits the document for rendering, so the rows join on the same
   * line index. */
  const lines = splitAsmLines(text);
  /* A quoted string that spans a line break breaks byte identity (see
   * stringSpansLines): the whole document gets no byte identity and
   * the old name matcher answers. */
  if (await stringSpansLines(tools, lines, arch)) return null;
  const probed = await probeLines(tools, lines, arch);
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
      const results = await identifyDocument(tools, msg.text, msg.arch);
      /* null: the worker declined the document (a quoted string spans
       * lines); app.js falls back to the old name matcher. */
      self.postMessage({ type: "result", seq: msg.seq, results });
    } catch (e) {
      self.postMessage({ type: "run-failed", seq: msg.seq, error: String(e && e.message || e) });
    }
  }
};
