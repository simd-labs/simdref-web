add x0, x1, x2
add w0, w1, w2
sub x0, x1, x2
sub w0, w1, w2
adds x0, x1, x2
adds w0, w1, w2
subs x0, x1, x2
subs w0, w1, w2
and x0, x1, x2
and w0, w1, w2
orr x0, x1, x2
orr w0, w1, w2
eor x0, x1, x2
eor w0, w1, w2
ands x0, x1, x2
ands w0, w1, w2
fadd s0, s1, s2
fadd d0, d1, d2
fsub s0, s1, s2
fsub d0, d1, d2
fmul s0, s1, s2
fmul d0, d1, d2
fdiv s0, s1, s2
fdiv d0, d1, d2
fmax s0, s1, s2
fmax d0, d1, d2
fmin s0, s1, s2
fmin d0, d1, d2
fneg s0, s1
fneg d0, d1
fabs s0, s1
fabs d0, d1
fsqrt s0, s1
fsqrt d0, d1
fmov s0, s1
fmov d0, d1
ldr x0, [x9, #16]
ldr x0, [x9], #16
ldr x0, [x9, #-16]!
ldr w0, [x9, #16]
ldr w0, [x9], #16
ldr w0, [x9, #-16]!
ldr s0, [x9, #16]
ldr s0, [x9], #16
ldr s0, [x9, #-16]!
ldr d0, [x9, #16]
ldr d0, [x9], #16
ldr d0, [x9, #-16]!
ldr q0, [x9, #16]
ldr q0, [x9], #16
ldr q0, [x9, #-16]!
str x0, [x9, #16]
str x0, [x9], #16
str x0, [x9, #-16]!
str w0, [x9, #16]
str w0, [x9], #16
str w0, [x9, #-16]!
str s0, [x9, #16]
str s0, [x9], #16
str s0, [x9, #-16]!
str d0, [x9, #16]
str d0, [x9], #16
str d0, [x9, #-16]!
str q0, [x9, #16]
str q0, [x9], #16
str q0, [x9, #-16]!
mov x0, x1
mov w0, w1
mov w0, #0x10
mov x0, #-1
mov x29, sp
mov sp, x29
mov fp, sp
cmp x29, sp
cmp fp, sp
cmp x0, x1
cmn x0, x1
tst x0, x1
add x0, x1, x2, lsl #2
sub x0, x1, x2, sxtx #2
ld1b {z0.b}, p0/z, [x0]
ld1w {z0.s}, p0/z, [x0]
ldr s1, [x11], #4
ldp x29, x30, [sp], #16
stp x29, x30, [sp, #-16]!
ldr x0, [x1, x2, lsl #3]
fcvt d0, s1
fcvt s0, d1
ret
b .LBB0_2
bl external
ld1b {z0.b, z1.b}, pn8/z, [x0]
ld1b {z0.b-z1.b}, pn8/z, [x0]
ld1h {z0.h, z1.h}, pn8/z, [x0]
ld1h {z0.h-z1.h}, pn8/z, [x0]
ld1w {z0.s, z1.s}, pn8/z, [x0]
ld1w {z0.s-z1.s}, pn8/z, [x0]
ld1d {z0.d, z1.d}, pn8/z, [x0]
ld1d {z0.d-z1.d}, pn8/z, [x0]
st1b {z0.b, z1.b}, pn8, [x0]
st1b {z0.b-z1.b}, pn8, [x0]
st1h {z0.h, z1.h}, pn8, [x0]
st1h {z0.h-z1.h}, pn8, [x0]
st1w {z0.s, z1.s}, pn8, [x0]
st1w {z0.s-z1.s}, pn8, [x0]
st1d {z0.d, z1.d}, pn8, [x0]
st1d {z0.d-z1.d}, pn8, [x0]
