// Injected before app.js in every verify.py arm. Marks the moment Phase-2
// intrinsic ingest finishes, so verify.py knows when the search index is
// complete and safe to fingerprint.
window.__readyAllAt = null;
document.addEventListener("DOMContentLoaded", () => {
  if (typeof _ingestIntrinsics !== "function") return;
  const orig = _ingestIntrinsics;
  _ingestIntrinsics = function (...a) {
    const p = orig.apply(this, a);
    Promise.resolve(p).then(() => {
      if (window.__readyAllAt === null) window.__readyAllAt = performance.now();
    });
    return p;
  };
});
