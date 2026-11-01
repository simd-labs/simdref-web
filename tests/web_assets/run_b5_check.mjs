/* B5 web checks: perf group labels name the core's real vendor/family
 * (never a fixed Intel label), and the ISA filter honors an entry whose
 * only Arm sub-ISA is SME.
 *
 * Loads web/app.js into a vm sandbox like run_b4_parity_check.mjs.
 * Run via tests/test_b5_web.py.
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
  uarchFamily: (row) => uarchFamily(row),
  renderMeasurements: (ms) => renderMeasurements(ms),
  setIsaConfig: (order, defaults, isas) => {
    FAMILY_SUB_ORDER = order;
    DEFAULT_SUBS = defaults;
    availableIsas = isas;
    enableAllIsas = false;
    enabledIsas = new Set(isas);
  },
  initSubs: () => initEnabledSubIsas(),
  setSubs: (fam, subs) => enabledSubIsas.set(fam, new Set(subs)),
  visible: (item) => isaVisible(item),
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

/* Perf group labels: the export family wins, x86 keeps its labels, and
 * an unknown core never takes an Intel label. */
assert(T.uarchFamily({uarch: "neoverse-v1", family: "Arm"}) === "Arm",
       "aarch64 row with export family must group under Arm");
assert(T.uarchFamily({uarch: "sifive-x280", family: "RISC-V"}) === "RISC-V",
       "riscv row with export family must group under RISC-V");
assert(T.uarchFamily({uarch: "SKL"}) === "Intel Client", "SKL groups under Intel Client");
assert(T.uarchFamily({uarch: "SKX"}) === "Intel Server", "SKX groups under Intel Server");
assert(T.uarchFamily({uarch: "ZEN3"}) === "AMD", "ZEN3 groups under AMD");
assert(!/^Intel/.test(T.uarchFamily({uarch: "neoverse-v1"})),
       "an Arm core without an export label must not read Intel");
assert(!/^Intel/.test(T.uarchFamily({uarch: "x60"})),
       "an unknown core must not read Intel");

/* The rendered group headers show the export family for Arm rows. */
const armHtml = T.renderMeasurements([
  {uarch: "neoverse-v1", family: "Arm", latency: "2", tpLoop: "1.00", uops: "1", sourceKind: "modeled"},
  {uarch: "neoverse-n2", family: "Arm", latency: "2", tpLoop: "1.00", uops: "1", sourceKind: "modeled"},
]);
assert(armHtml.includes(">Arm (2)<"), `Arm group header missing, got: ${armHtml}`);
assert(!armHtml.includes("Intel"), `Arm rows must not render an Intel label, got: ${armHtml}`);

/* SME sub-ISA filter: an entry tagged SME stays visible while the SME
 * sub-ISA is enabled and hides when it is off. */
T.setIsaConfig(
  {Arm: ["NEON", "SVE", "SVE2", "SME"]},
  {Arm: new Set(["NEON", "SVE", "SVE2", "SME"])},
  ["Arm"],
);
T.initSubs();
const smeEntry = {isa_families: ["Arm"], isa_subs: ["SME"]};
assert(T.visible(smeEntry), "SME entry must be visible with default Arm subs");
T.setSubs("Arm", ["NEON", "SVE", "SVE2"]);
assert(!T.visible(smeEntry), "SME entry must hide when the SME sub is off");

if (failures.length) {
  console.error("FAIL");
  for (const f of failures) console.error(" - " + f);
  process.exit(1);
}
console.log("PASS: B5 web checks hold");
