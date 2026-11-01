/* B2: node-driven check for the web metadata panel and category facet.
 * Loads web/app.js into a vm sandbox with stub browser globals and
 * asserts on the fixture records of simdref
 * tests/fixtures/b2/metadata_records.json:
 *
 *   (a) the intrinsic detail Metadata section shows the category with
 *       the subcategory in front and the RVV policy keys,
 *   (b) the instruction detail Metadata section shows the RVV policy keys,
 *   (c) the operand table lists uops.info flag reads/writes and the
 *       suppressed mark,
 *   (d) records without a field render no label for it,
 *   (e) decodeIntrinsics reads the subcategory column,
 *   (f) the category facet narrows category-carrying rows and lets
 *       category-less rows pass through.
 *
 * Run via tests/test_b2_metadata_web.py.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const APP_JS = fs.readFileSync(
  path.resolve(here, "..", "..", "web", "app.js"),
  "utf8",
);

const noop = () => {};
function makeElement() {
  const el = {
    addEventListener: noop,
    removeEventListener: noop,
    appendChild: noop,
    removeChild: noop,
    insertBefore: noop,
    setAttribute: noop,
    removeAttribute: noop,
    getAttribute: () => null,
    contains: () => false,
    focus: noop,
    blur: noop,
    click: noop,
    scrollIntoView: noop,
    classList: {add: noop, remove: noop, toggle: noop, contains: () => false},
    dataset: {},
    style: new Proxy({}, {
      get(t, p) { return typeof p === "string" && /^[a-z]/.test(p) ? noop : t[p]; },
      set(t, p, v) { t[p] = v; return true; },
    }),
    innerHTML: "",
    textContent: "",
    value: "",
    checked: false,
    children: [],
    childNodes: [],
    firstChild: null,
    parentNode: null,
    isConnected: false,
    getBoundingClientRect: () => ({top: 0, left: 0, width: 0, height: 0}),
  };
  return new Proxy(el, {
    get(t, p) {
      if (p in t) return t[p];
      return typeof p === "string" && /^[a-z]/.test(p) ? noop : undefined;
    },
    set(t, p, v) { t[p] = v; return true; },
  });
}

const windowStub = {
  addEventListener: noop,
  removeEventListener: noop,
  requestIdleCallback: undefined,
  requestAnimationFrame: (cb) => setTimeout(cb, 0),
  cancelAnimationFrame: clearTimeout,
  matchMedia: () => ({matches: false, addEventListener: noop, removeEventListener: noop}),
  scrollTo: noop,
  innerWidth: 1280,
  innerHeight: 800,
  location: {hash: "", search: "", href: "http://localhost/"},
  history: {replaceState: noop, pushState: noop},
  navigator: {clipboard: {writeText: () => Promise.resolve()}, userAgent: "node"},
};

const documentStub = new Proxy(
  {
    getElementById: () => makeElement(),
    querySelector: () => makeElement(),
    querySelectorAll: () => [],
    createElement: () => makeElement(),
    createTextNode: () => ({}),
    createDocumentFragment: () => makeElement(),
    addEventListener: noop,
    removeEventListener: noop,
    body: makeElement(),
    documentElement: makeElement(),
    head: makeElement(),
    activeElement: makeElement(),
  },
  {
    get(t, p) { return p in t ? t[p] : noop; },
    set(t, p, v) { t[p] = v; return true; },
  },
);

const sandbox = {
  console,
  window: windowStub,
  document: documentStub,
  navigator: windowStub.navigator,
  location: windowStub.location,
  matchMedia: windowStub.matchMedia,
  localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
  fetch: () => new Promise(() => {}),
  DecompressionStream: undefined,
  Response: undefined,
  URLSearchParams,
  Map, Set, Promise, JSON, Math, Date, RegExp,
  Array, Object, Number, String, Boolean, Symbol,
  Error, TypeError, RangeError,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Intl,
};
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
sandbox.global = sandbox;

const probe = `
;globalThis.__TEST_API__ = {
  renderIntrinsicDetail: (i, d) => renderIntrinsicDetail(i, d),
  renderInstructionDetail: (i, d) => renderInstructionDetail(i, d),
  renderTable: (h, r) => renderTable(h, r),
  operandHeaders,
  decodeIntrinsics: (s) => decodeIntrinsics(s),
  get searchEntries() { return searchEntries; },
  set searchEntries(v) { searchEntries = v; },
  get bucketsBuilt() { return bucketsBuilt; },
  set bucketsBuilt(v) { bucketsBuilt = v; },
  buildBuckets: () => buildBuckets(),
  rebuildVisibleSet: () => rebuildVisibleSet(),
  get visibleSet() { return visibleSet; },
  set visibleSet(v) { visibleSet = v; },
  get activeCategory() { return activeCategory; },
  set activeCategory(v) { activeCategory = v; },
  get enableAllIsas() { return enableAllIsas; },
  set enableAllIsas(v) { enableAllIsas = v; },
  get byCategory() { return byCategory; },
};
`;

vm.createContext(sandbox);
try {
  vm.runInContext(APP_JS + probe, sandbox, {filename: "app.js"});
} catch (err) {
  console.error("[fatal] app.js failed to evaluate:", err);
  process.exit(2);
}

const T = sandbox.__TEST_API__;
if (!T) {
  console.error("[fatal] __TEST_API__ probe was not installed");
  process.exit(2);
}

const failures = [];
function assert(cond, msg) { if (!cond) failures.push(msg); }

/* ── (a) intrinsic metadata panel: Intel category + RVV policy ─────── */
const x86Item = {
  name: "_mm256_add_ps", subtitle: "Add packed singles.",
  architecture: "x86", isa: ["AVX"], display_isa: "AVX",
  isa_families: ["AVX"], category: "Arithmetic", subcategory: "AVX",
  signature: "__m256 _mm256_add_ps (__m256 a, __m256 b)",
};
const x86Html = T.renderIntrinsicDetail(x86Item, null);
assert(x86Html.includes("AVX / Arithmetic"),
       "category chip with subcategory missing from the intrinsic Metadata section");

const rvvItem = {
  name: "__riscv_vadd_vv_i32m1_tu", subtitle: "vector add",
  architecture: "riscv", isa: ["V"], display_isa: "V",
  isa_families: ["RISC-V"],
};
const rvvDetail = {
  signature: "vint32m1_t __riscv_vadd_vv_i32m1_tu(...)",
  description: "Vector integer add intrinsic.",
  metadata: {
    masking: "unmasked",
    policy: "undisturbed",
    tail_policy: "undisturbed",
    mask_policy: "agnostic",
  },
};
const rvvHtml = T.renderIntrinsicDetail(rvvItem, rvvDetail);
assert(rvvHtml.includes("Tail Policy"), "tail_policy label missing from the intrinsic Metadata section");
assert(rvvHtml.includes("undisturbed"), "tail_policy value missing from the intrinsic Metadata section");
assert(rvvHtml.includes("Mask Policy"), "mask_policy label missing from the intrinsic Metadata section");
assert(rvvHtml.includes("agnostic"), "mask_policy value missing from the intrinsic Metadata section");

/* ── (d) a record without the fields renders no label ─────────────── */
const bareHtml = T.renderIntrinsicDetail(
  rvvItem,
  {signature: "sig", description: "d", metadata: {}},
);
assert(!bareHtml.includes("Tail Policy"), "tail_policy label rendered for a record without the field");
assert(!bareHtml.includes("Masking"), "masking label rendered for a record without the field");
assert(!x86Html.includes("Tail Policy"), "tail_policy label rendered on an x86 record without the field");

/* ── (b) instruction metadata panel: RVV policy ───────────────────── */
const instrItem = {
  key: "riscv:vadd.vv vd, vs2, vs1, vm", mnemonic: "vadd.vv",
  form: "vadd.vv vd, vs2, vs1, vm", summary: "Vector integer add.",
  architecture: "riscv", display_architecture: "riscv", isa: ["V"],
  display_isa: "V", isa_families: ["RISC-V"],
};
const instrDetail = {
  summary: "Vector integer add.",
  metadata: {extension: "V", masking: "unmasked", policy: "agnostic", tail_policy: "agnostic", mask_policy: "agnostic"},
};
const instrHtml = T.renderInstructionDetail(instrItem, instrDetail);
assert(instrHtml.includes("Tail Policy"), "tail_policy label missing from the instruction Metadata section");
assert(instrHtml.includes("agnostic"), "tail_policy value missing from the instruction Metadata section");
const instrBare = T.renderInstructionDetail(instrItem, {summary: "s", metadata: {}});
assert(!instrBare.includes("Tail Policy"), "tail_policy label rendered for an instruction without the field");

/* ── (c) operand table: flag reads/writes + suppressed ────────────── */
const operands = [
  {idx: "1", r: "1", w: "1", type: "reg", width: "64", xtype: "int", name: "REG0"},
  {idx: "2", r: "1", type: "reg", width: "64", xtype: "int", name: "REG1"},
  {idx: "3", r: "1", type: "flags", name: "REG2", flag_CF: "r/w", suppressed: "1"},
];
const opsHtml = T.renderTable(T.operandHeaders, operands);
assert(opsHtml.includes("CF r/w"), "flag_CF value missing from the operand table");
assert(opsHtml.includes("suppressed"), "suppressed mark missing from the operand table");

/* ── (e) columnar decode: subcategory column ───────────────────────── */
const decoded = T.decodeIntrinsics({
  n: 1,
  cols: {
    name: ["_mm256_add_ps"],
    isa: [0], arch: [0], perf: [0], desc: [0], ins: [0],
    prim: [-1], arm: [-1], cat: [0], sub: [0],
  },
  isa: [[["AVX"], "AVX", ["AVX"], []]],
  arch: [["x86", "x86"]],
  perf: [["-", "-"]],
  desc: ["Add packed singles."],
  ins: ["VADDPS"],
  prim: [], arm: [],
  cat: ["Arithmetic"],
  sub: ["AVX"],
  fields: {},
  summaries: {},
});
assert(decoded[0].category === "Arithmetic", "decodeIntrinsics lost the category column");
assert(decoded[0].subcategory === "AVX", "decodeIntrinsics lost the subcategory column");

/* ── (f) category facet ────────────────────────────────────────────── */
function intrEntry(name, category) {
  const item = {name, isa_families: ["AVX"], isa_subs: []};
  if (category) item.category = category;
  return {kind: "intrinsic", key: name, title: name, subtitle: "", item, fields: []};
}
function plainInstrEntry(key) {
  return {
    kind: "instruction", key, title: key, subtitle: "",
    item: {key, isa_families: ["AVX"], isa_subs: []}, fields: [],
  };
}
T.searchEntries = [
  intrEntry("_mm256_add_ps", "Arithmetic"),
  intrEntry("_mm256_lzcnt_epi32", "Bit Manipulation"),
  plainInstrEntry("x86:vaddps (ymm, ymm, ymm)"),
];
T.bucketsBuilt = false;
T.buildBuckets();
T.enableAllIsas = true;
assert((T.byCategory.get("Arithmetic") || []).length === 1,
       "byCategory bucket missing the Arithmetic intrinsic");

T.activeCategory = "Arithmetic";
T.visibleSet = null;
T.rebuildVisibleSet();
const visible = T.visibleSet;
assert(visible.has(0), "category facet dropped the matching intrinsic");
assert(!visible.has(1), "category facet kept an intrinsic of another category");
assert(visible.has(2), "category facet dropped a record without a category (pass-through)");

T.activeCategory = null;
T.visibleSet = null;
T.rebuildVisibleSet();
assert(T.visibleSet.size === 3, "category facet still filters after reset to all");

if (failures.length) {
  console.error("[fail] B2 metadata check:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log("[ok] B2 metadata panel + category facet render in the web detail view");
process.exit(0);
