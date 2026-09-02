; MCBMAP.COM -- read-only DOS conventional-memory arena snapshot.
;
; Build with NASM:
;   nasm -f bin -o MCBMAP.COM mcbmap.asm
;
; The program walks the DOS MCB chain obtained from INT 21h/AH=52h and writes
; plain ASCII to stdout, so DOS redirection can capture a reproducible map.

bits 16
org 100h

start:
    cld
    push cs
    pop ds

    mov ah, 52h
    int 21h
    mov ax, [es:bx-2]
    mov [first_mcb], ax

    ; Release the usual all-remaining-memory COM allocation before observing
    ; the chain. The retained paragraph count is printed with the snapshot.
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
    jc .resize_failed

    mov dx, banner
    call puts
    mov ax, cs
    call hex_word
    mov dx, int12_label
    call puts
    int 12h
    call hex_word
    mov dx, first_label
    call puts
    mov ax, [first_mcb]
    call hex_word
    mov dx, keep_label
    call puts
    mov ax, KEEP_PARAS
    call hex_word
    call newline

    mov dx, columns
    call puts

    mov word [free_total], 0
    mov word [free_largest], 0
    mov word [block_count], 0
    mov ax, [first_mcb]

.next_mcb:
    mov es, ax
    mov dl, [es:0]
    cmp dl, 'M'
    je .valid_mcb
    cmp dl, 'Z'
    jne .bad_chain

.valid_mcb:
    inc word [block_count]
    push ax
    call hex_word
    mov dl, ' '
    call putc
    mov dl, [es:0]
    call putc
    mov dx, owner_label
    call puts
    mov ax, [es:1]
    call hex_word
    mov dx, paras_label
    call puts
    mov ax, [es:3]
    call hex_word
    mov dx, name_label
    call puts
    xor si, si
.name_loop:
    mov dl, [es:8+si]
    cmp dl, 20h
    jae .name_printable
    mov dl, '.'
.name_printable:
    call putc
    inc si
    cmp si, 8
    jb .name_loop
    call newline

    cmp word [es:1], 0
    jne .not_free
    mov ax, [es:3]
    add [free_total], ax
    cmp ax, [free_largest]
    jbe .not_free
    mov [free_largest], ax
.not_free:
    mov dl, [es:0]
    mov bx, [es:3]
    pop ax
    cmp dl, 'Z'
    je .done
    inc bx
    add ax, bx
    jmp .next_mcb

.bad_chain:
    mov dx, bad_chain
    call puts

.done:
    mov dx, totals_label
    call puts
    mov ax, [free_total]
    call hex_word
    mov dx, largest_label
    call puts
    mov ax, [free_largest]
    call hex_word
    mov dx, blocks_label
    call puts
    mov ax, [block_count]
    call hex_word
    call newline

    mov ax, 4C00h
    int 21h

.resize_failed:
    mov ax, 4C01h
    int 21h

; DS:DX -> NUL-terminated string.
puts:
    push ax
    push si
    mov si, dx
.puts_loop:
    lodsb
    test al, al
    jz .puts_done
    mov dl, al
    call putc
    jmp .puts_loop
.puts_done:
    pop si
    pop ax
    ret

; DL -> stdout (redirection-aware).
putc:
    push ax
    push bx
    push cx
    push dx
    push ds
    mov [one_char], dl
    push cs
    pop ds
    mov bx, 1
    mov cx, 1
    mov dx, one_char
    mov ah, 40h
    int 21h
    pop ds
    pop dx
    pop cx
    pop bx
    pop ax
    ret

hex_word:
    push ax
    push bx
    push cx
    push dx
    mov bx, ax
    mov cx, 4
.hex_loop:
    rol bx, 1
    rol bx, 1
    rol bx, 1
    rol bx, 1
    mov dl, bl
    and dl, 0Fh
    add dl, '0'
    cmp dl, '9'
    jbe .hex_emit
    add dl, 7
.hex_emit:
    call putc
    loop .hex_loop
    pop dx
    pop cx
    pop bx
    pop ax
    ret

newline:
    push dx
    mov dl, 13
    call putc
    mov dl, 10
    call putc
    pop dx
    ret

banner         db 'MCBMAP1 PSP=', 0
int12_label    db ' INT12_KB=', 0
first_label    db ' FIRST_MCB=', 0
keep_label     db ' PROBE_PARAS=', 0
columns        db 'SEG  T OWNER PARAS NAME', 13, 10, 0
owner_label    db ' OWNER=', 0
paras_label    db ' PARAS=', 0
name_label     db ' NAME=', 0
totals_label   db 'FREE_TOTAL=', 0
largest_label  db ' FREE_LARGEST=', 0
blocks_label   db ' BLOCKS=', 0
bad_chain      db 'INVALID_MCB_CHAIN', 13, 10, 0
one_char       db 0
first_mcb      dw 0
free_total     dw 0
free_largest   dw 0
block_count    dw 0

    times 256 db 0
stack_top:
program_end:
KEEP_PARAS equ ((program_end - $$ + 100h + 15) / 16)
