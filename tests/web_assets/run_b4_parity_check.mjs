/* B4 web parity: card CPI aggregate matches the list rule, modeled
 * provenance (source name, source_version and citationUrl) renders as a
 * link under the perf table, and the LAT/CPI chips name the list rule
 * ("best over cores") in their tooltip.
 *
 * Loads web/app.js into a vm sandbox like run_b3_sdm_fields_check.mjs.
 * Run via tests/test_b4_parity_web.py.
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
  perfSummary: (ms) => perfSummary(ms),
  renderMeasurements: (ms) => renderMeasurements(ms),
  rowMarkup: (entry, index) => _rowMarkup(entry, index),
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

const CITATION_URL = "https://llvm.org/docs/CommandGuide/llvm-mca.html";

/* Modeled rows whose per-core CPI differs. The list aggregate is the
 * lowest value over cores (perf.best_numeric via the export); the card
 * summary must match it. */
const modeled = [
  {
    uarch: "cortex-a72", latency: "5", tpLoop: "4.00", uops: "1",
    sourceKind: "modeled", source: "llvm-mca", sourceVersion: "22.1.8",
    citationUrl: CITATION_URL,
  },
  {
    uarch: "neoverse-n1", latency: "4", tpLoop: "16.00", uops: "1",
    sourceKind: "modeled", source: "llvm-mca", sourceVersion: "22.1.8",
    citationUrl: CITATION_URL,
  },
];

const summary = T.perfSummary(modeled);
assert(summary.includes("CPI 4"), `card summary must show the list aggregate CPI 4, got: ${summary}`);
assert(!summary.includes("CPI 16"), `card summary shows the median CPI 16 instead of the list value, got: ${summary}`);

/* Provenance renders once per distinct source, with the citation as link. */
const perfHtml = T.renderMeasurements(modeled);
assert(perfHtml.includes("llvm-mca 22.1.8"), `provenance footnote missing from the perf panel, got: ${perfHtml}`);
assert(perfHtml.includes(`<a href="${CITATION_URL}"`), `citation link missing from the perf panel, got: ${perfHtml}`);
assert(perfHtml.split("llvm-mca 22.1.8").length - 1 === 1,
       "provenance footnote must appear once per distinct source, not per core");

/* A record without the fields renders no provenance label. */
const bare = T.renderMeasurements([
  {uarch: "SKL", latency: "4", tpLoop: "1.00", uops: "1", sourceKind: "measured"},
]);
assert(!bare.includes("llvm-mca"), "modeled provenance rendered for a measured record without the field");
assert(!bare.includes("perf-src"), "provenance footnote label rendered for a record without the fields");

/* The LAT and CPI chips name the list rule in their tooltip. */
const row = T.rowMarkup(
  {
    kind: "instruction",
    key: "x86:add",
    title: "ADDPS xmm1, xmm2",
    subtitle: "Add packed values",
    item: {display_architecture: "x86", display_isa: "SSE", isa: ["SSE"], lat: "4", cpi: "0.50"},
  },
  0,
);
assert((row.split('title="best over cores"').length - 1) === 2,
       `LAT and CPI chips must each carry the "best over cores" tooltip, got: ${row}`);
const bareRow = T.rowMarkup(
  {
    kind: "instruction",
    key: "x86:nop",
    title: "NOP",
    subtitle: "",
    item: {display_architecture: "x86", display_isa: "SSE", isa: ["SSE"], lat: "-", cpi: "-"},
  },
  0,
);
assert(!bareRow.includes("result-perf"), "perf chip rendered for a record without the field");

if (failures.length) {
  console.error("[fail] B4 web parity check:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log("[ok] B4 web parity: card CPI matches the list rule, provenance link renders, chip tooltips name the rule");
process.exit(0);
