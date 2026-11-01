/* B1: node-driven check for the web "latency per operand pair" table.
 * Loads web/app.js into a vm sandbox with stub browser globals and
 * asserts on renderMeasurements for the card form:
 *
 *   (a) a measurement row with latencyPairs renders a table holding the
 *       pair segments "10-<=22 (xmm1->xmm0)", "<=8 (mem->xmm0)" and the
 *       same reg marker,
 *   (b) a row without latencyPairs renders no pair table (no empty
 *       pair label),
 *   (c) a row with an empty latencyPairs array renders no pair table.
 *
 * Run via tests/test_b1_latency_pairs_web.py.
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const APP_JS = fs.readFileSync(
  path.resolve(here, "..", "..", "web/app.js"),
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
  renderMeasurements: (m) => renderMeasurements(m),
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

// Fixture row mirrors the simdref _web_measurements export of
// tests/fixtures/b1/latency_pairs.json (SNB entry).
const withPairs = [{
  uarch: "SNB",
  ports: "1*P0",
  latency: "8",
  tpLoop: "10.00",
  tpUnrolled: "10.00",
  tpPorts: "-",
  uops: "2",
  sourceKind: "measured",
  latencyPairs: [
    {start: "xmm1", target: "xmm0", value: "10-<=22"},
    {start: "mem", target: "xmm0", value: "<=8"},
    {start: "xmm0", target: "xmm0", value: "13", sameReg: "10"},
  ],
}];
const noPairs = withPairs.map(r => {
  const {latencyPairs, ...rest} = r;
  return rest;
});

const htmlWith = T.renderMeasurements(withPairs);
assert(htmlWith.includes("latency per operand pair"),
       "pair table label missing from renderMeasurements output");
assert(htmlWith.includes("10-&lt;=22 (xmm1->xmm0)"),
       "range pair segment (with upper-bound mark) missing");
assert(htmlWith.includes("&lt;=8 (mem->xmm0)"),
       "upper-bound memory pair segment missing");
assert(htmlWith.includes("same reg 10"), "same-reg marker missing");

const htmlWithout = T.renderMeasurements(noPairs);
assert(!htmlWithout.includes("latency per operand pair"),
       "pair table rendered for a row without latencyPairs");

const htmlEmpty = T.renderMeasurements(withPairs.map(r => ({...r, latencyPairs: []})));
assert(!htmlEmpty.includes("latency per operand pair"),
       "pair table rendered for an empty latencyPairs array");

if (failures.length) {
  console.error("[fail] latency-pairs check:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log("[ok] latency per operand pair renders in the web detail view");
process.exit(0);
