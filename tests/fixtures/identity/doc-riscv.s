add a0, a1, a2
add t0, t1, t2
add s0, s1, s2
sub a0, a1, a2
sub t0, t1, t2
sub s0, s1, s2
and a0, a1, a2
and t0, t1, t2
and s0, s1, s2
or a0, a1, a2
or t0, t1, t2
or s0, s1, s2
xor a0, a1, a2
xor t0, t1, t2
xor s0, s1, s2
sll a0, a1, a2
sll t0, t1, t2
sll s0, s1, s2
srl a0, a1, a2
srl t0, t1, t2
srl s0, s1, s2
sra a0, a1, a2
sra t0, t1, t2
sra s0, s1, s2
slt a0, a1, a2
slt t0, t1, t2
slt s0, s1, s2
sltu a0, a1, a2
sltu t0, t1, t2
sltu s0, s1, s2
mul a0, a1, a2
mul t0, t1, t2
mul s0, s1, s2
div a0, a1, a2
div t0, t1, t2
div s0, s1, s2
rem a0, a1, a2
rem t0, t1, t2
rem s0, s1, s2
addw a0, a1, a2
addw t0, t1, t2
addw s0, s1, s2
subw a0, a1, a2
subw t0, t1, t2
subw s0, s1, s2
mulw a0, a1, a2
mulw t0, t1, t2
mulw s0, s1, s2
divw a0, a1, a2
divw t0, t1, t2
divw s0, s1, s2
remw a0, a1, a2
remw t0, t1, t2
remw s0, s1, s2
addi sp, sp, -16
sd ra, 8(sp)
ld ra, 8(sp)
addi a0, a0, 1
lw a0, 0(a1)
sw a0, 0(a1)
beq a0, a1, .L2
bne a0, zero, .L3
jal ra, external
jalr zero, 0(ra)
fadd.s fa0, fa1, fa2
vadd.vv v0, v1, v2
vadd.vx v0, v1, a0
vmul.vv v0, v1, v2
