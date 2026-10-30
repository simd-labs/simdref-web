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

/* A quoted string that spans a line break breaks byte identity: its
 * text lands on its own lines in llvm-mc's listing or stderr, where it
 * reads as a directive, an encoding line or a diagnostic. identity.js
 * declines such documents; only strings outside comments count: '#'
 * and '//' run to the next line break, '/'+'*' opens and '*'+'/'
 * closes a block comment, and '@'
 * starts a comment only when atComment holds (AArch64; on x86 '@' is
 * operand text like foo@GOTPCREL). An escaped char never closes the
 * string, and a break inside the string counts, escape or not.
 * shortcut: a comment ending earlier than GAS would end it only risks
 * a decline, and a decline never gives a wrong row */
function asmHasSpanningString(text, atComment) {
  let state = "code";  // code | string | line comment | block comment
  let escaped = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (state === "string") {
      if (/\n|\r|[\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/.test(ch)) return true;
      if (escaped) { escaped = false; continue; }
      if (ch === "\\") { escaped = true; continue; }
      if (ch === '"') state = "code";
      continue;
    }
    if (state === "line") {
      if (/\n|\r/.test(ch)) state = "code";
      continue;
    }
    if (state === "block") {
      if (ch === "*" && text[i + 1] === "/") { state = "code"; i++; }
      continue;
    }
    if (ch === '"') { state = "string"; continue; }
    if (ch === "#" || (atComment && ch === "@")) { state = "line"; continue; }
    if (ch === "/" && text[i + 1] === "/") { state = "line"; i++; continue; }
    if (ch === "/" && text[i + 1] === "*") { state = "block"; i++; }
  }
  return false;
}
