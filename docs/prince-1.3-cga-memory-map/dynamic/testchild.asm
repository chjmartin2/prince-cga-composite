; Deterministic COM-format test payload for validating MEMTRACE.COM. During the
; test only, build it with the filename PRINCE.EXE; DOS distinguishes COM-style
; flat binaries by content when no MZ header is present.

bits 16
org 100h

start:
    cli
    mov ax, cs
    mov ss, ax
    mov sp, stack_top
    sti
    push cs
    pop es
    mov bx, KEEP_PARAS
    mov ah, 4Ah
    int 21h

    mov bx, 20h
    mov ah, 48h
    int 21h
    mov [block1], ax

    mov bx, 10h
    mov ah, 48h
    int 21h
    mov [block2], ax

    mov ax, [block1]
    mov es, ax
    mov ah, 49h
    int 21h

    mov ax, [block2]
    mov es, ax
    mov bx, 08h
    mov ah, 4Ah
    int 21h

    mov ah, 49h
    int 21h
    mov ax, 4C00h
    int 21h

block1 dw 0
block2 dw 0
times 128 db 0
stack_top:
program_end:
KEEP_PARAS equ ((program_end - $$ + 100h + 15) / 16)
