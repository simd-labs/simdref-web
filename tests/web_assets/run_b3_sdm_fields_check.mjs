/* B3: node-driven check for the SDM table sections in the web detail view.
 * Loads web/app.js into a vm sandbox with stub browser globals and
 * asserts that renderInstructionDetail shows the Opcode & Modes and
 * Operand Encoding description sections, and the exception class
 * reference text, for a fixture record that holds them. A record
 * without the fields renders no label for them.
 *
 * Run via tests/test_b3_sdm_fields_web.py.
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
  renderInstructionDetail: (i, d) => renderInstructionDetail(i, d),
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

/* Fixture record: ADDPS with the B3 table sections and the exception
 * class reference, as parsed by simdref.pdfparse.intel.form_table_sections
 * from the vendored SDM page. */
const item = {
  key: "x86:addps xmm1, xmm2/m128", mnemonic: "ADDPS",
  form: "ADDPS xmm1, xmm2/m128",
  summary: "Add packed single precision floating-point values",
  architecture: "x86", display_architecture: "x86", isa: ["SSE"],
  display_isa: "SSE", isa_families: ["SSE"],
};
const detail = {
  summary: item.summary,
  metadata: {},
  description: {
    "Opcode & Modes":
      "NP 0F 58 /r (A): 64-bit V, compat/legacy V; CPUID SSE\n" +
      "EVEX.128.0F.W0 58 /r (C): 64-bit V, compat/legacy V; CPUID (AVX512VL AND AVX512F) OR AVX10.1",
    "Operand Encoding":
      "A: ModRM:reg (r, w); ModRM:r/m (r)\n" +
      "C: ModRM:reg (w); EVEX.vvvv (r); ModRM:r/m (r); tuple: Full",
    "Exceptions": "Exceptions Type 14; see Table 2-31.",
  },
};
const html = T.renderInstructionDetail(item, detail);
assert(html.includes("Opcode &amp; Modes"), "Opcode & Modes label missing from the web instruction detail");
assert(html.includes("CPUID SSE"), "CPUID flag column text missing from the web instruction detail");
assert(html.includes("(AVX512VL AND AVX512F) OR AVX10.1"),
       "AND/OR CPUID expression missing from the web instruction detail");
assert(html.includes("Operand Encoding"), "Operand Encoding label missing from the web instruction detail");
assert(html.includes("tuple: Full"), "EVEX tuple type missing from the web instruction detail");
assert(html.includes("Exceptions Type 14; see Table 2-31."),
       "exception class reference missing from the web instruction detail");

/* A record without the fields renders no label. */
const bare = T.renderInstructionDetail(item, {summary: item.summary, metadata: {}});
assert(!bare.includes("Opcode &amp; Modes"), "Opcode & Modes label rendered for a record without the field");
assert(!bare.includes("Operand Encoding"), "Operand Encoding label rendered for a record without the field");

if (failures.length) {
  console.error("[fail] B3 SDM fields check:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log("[ok] B3 SDM modes, CPUID, operand encoding and exception references render in the web detail view");
process.exit(0);
