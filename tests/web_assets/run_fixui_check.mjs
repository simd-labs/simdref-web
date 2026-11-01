/* FIXUI web checks: every perf row keeps a compact source label and the
 * group footer citations stay.
 *
 * Loads web/app.js into a vm sandbox like run_b5_check.mjs.
 * Run via tests/test_fixui_web.py.
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
  renderMeasurements: (ms) => renderMeasurements(ms),
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

/* Every perf row keeps a compact source label; footer citations stay. */
const rows = [
  {uarch: "SKX", source: "uops.info", sourceVersion: "2025-10-30",
   citationUrl: "https://uops.info/table.html", latency: "4", tpLoop: "0.55",
   uops: "2", sourceKind: "measured"},
  {uarch: "neoverse-v1", family: "Arm", source: "llvm-mca", sourceVersion: "24.0.0",
   citationUrl: "https://llvm.org/docs/CommandGuide/llvm-mca.html", latency: "2",
   tpLoop: "0.5", uops: "1", sourceKind: "modeled"},
  {uarch: "ZEN4", source: "amd-swopt", sourceVersion: "1.00",
   citationUrl: "https://docs.amd.com/v/u/en-US/58455_1.00", latency: "3",
   tpLoop: "0.5", uops: "1", sourceKind: "modeled"},
];
const html = T.renderMeasurements(rows);

assert(html.includes(">src<"), `src column header missing, got: ${html}`);
assert(html.includes(">uops.info<"), `per-row uops.info label missing, got: ${html}`);
assert(html.includes(">llvm-mca<"), `per-row llvm-mca label missing, got: ${html}`);
assert(html.includes(">amd-swopt<"), `per-row amd-swopt label missing, got: ${html}`);
/* Footer citations stay (name version url per distinct source). */
assert(html.includes("uops.info 2025-10-30"), `uops.info footer missing, got: ${html}`);
assert(html.includes("llvm-mca 24.0.0"), `llvm-mca footer missing, got: ${html}`);
assert(html.includes("https://llvm.org/docs/CommandGuide/llvm-mca.html"),
       `citation link missing, got: ${html}`);

if (failures.length) {
  console.error("FAIL");
  for (const f of failures) console.error(" - " + f);
  process.exit(1);
}
console.log("PASS: FIXUI web checks hold");
