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
 * reads as a directive, an encoding line or a diagnostic, so
 * identity.js declines such a document and the old matcher answers.
 * One line (the splitAsmLines rule) with an odd '"' count marks such a
 * string, and backslash escapes leave their quote out of the count: a
 * '\"' is string text, never a delimiter. Comment parsing is left out
 * on purpose: a '#' or '@' is operand text on the ISA whose scan once
 * read it as a comment (x86 foo@PLT, AArch64 'mov x0, #1') and let a
 * spanning string through.
 * shortcut: a stray quote in a comment or a '"' character constant
 * also declines, and a decline never gives a wrong row */
function asmHasSpanningString(text) {
  for (const line of splitAsmLines(text))
    if (line.replace(/\\./g, "").split('"').length % 2 === 0) return true;
  return false;
}
