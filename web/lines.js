/* Python str.splitlines() semantics for the Annotate document. app.js
 * renders rows by these line numbers and the identity worker reports
 * rows by them, so both must split the document with this one rule:
 * \r\n, \r and the other line terminators end a line and never ride
 * on it, and a document ending in a terminator has no phantom last
 * line. */
function splitAsmLines(text) {
  const lines = text.split(/\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}
