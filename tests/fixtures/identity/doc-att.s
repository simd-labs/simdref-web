	addq %rax, %rbx
	addl %eax, %ecx
	addw %ax, %dx
	addb %al, %cl
	subq %rax, %rbx
	subl %eax, %ecx
	subw %ax, %dx
	subb %al, %cl
	andq %rax, %rbx
	andl %eax, %ecx
	andw %ax, %dx
	andb %al, %cl
	orq %rax, %rbx
	orl %eax, %ecx
	orw %ax, %dx
	orb %al, %cl
	xorq %rax, %rbx
	xorl %eax, %ecx
	xorw %ax, %dx
	xorb %al, %cl
	cmpq %rax, %rbx
	cmpl %eax, %ecx
	cmpw %ax, %dx
	cmpb %al, %cl
	testq %rax, %rbx
	testl %eax, %ecx
	testw %ax, %dx
	testb %al, %cl
	movq %rax, %rbx
	movl %eax, %ecx
	movw %ax, %dx
	movb %al, %cl
	movq 8(%rsp), %rax
	movq %rax, 16(%rsp)
	movl counter(%rip), %eax
	movl %eax, counter(%rip)
	movzbl (%rax), %edx
	movzwl 2(%rdi), %eax
	movslq %eax, %rdx
	movsbq %al, %rax
	movswq (%rdi), %rax
	movsbl (%rax), %edx
	leaq 16(%rdi,%rsi,4), %rax
	pushq %rbp
	popq %rbp
	imulq %rsi, %rax
	shlq $2, %rax
	sarq $3, %rax
	addq $8, %rsp
	subq $32, %rsp
	cmpl $0, %eax
	movsd 8(%rsp), %xmm0
	movss (%rax), %xmm0
	addsd %xmm1, %xmm0
	mulsd %xmm2, %xmm0
	vaddps %ymm2, %ymm1, %ymm0
	vmulps (%rax), %ymm1, %ymm0
	vpxor %xmm0, %xmm0, %xmm0
	vxorps %ymm0, %ymm0, %ymm0
	cltq
	cqto
	cltd
	cwtl
	cbtw
	ret
	leave
	nop
	vzeroupper
