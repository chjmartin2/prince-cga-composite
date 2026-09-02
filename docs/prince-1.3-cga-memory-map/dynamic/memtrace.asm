; MEMTRACE.COM -- low-overhead DOS allocation tracer for Prince 1.3.
;
; Usage inside an expendable copy of the game directory:
;   MEMTRACE.COM improved 14
;
; The wrapper executes PRINCE.EXE, forwarding its own PSP command tail. It
; intercepts INT 21h file-open/close and AH=48h/49h/4Ah memory calls, writes
; fixed 48-byte binary records to MTRACE.BIN, restores INT 21h after Prince
; returns, and exits. It never
; modifies PRINCE.EXE or any DAT archive. The wrapper remains resident as the
; EXEC parent, so the companion report must disclose its measured footprint.

bits 16
org 100h

%define RECORD_SIZE 48

start:
    cld
    push cs
    pop ds

    ; Discover the DOS arena head before shrinking our own EXEC allocation.
    mov ah, 52h
    int 21h
    mov ax, [es:bx-2]
    mov [first_mcb], ax

    ; COM programs initially inherit a top-of-block stack. Move it into our
    ; retained image before AH=4Ah releases the remainder of that block.
    cli
    mov ax, cs
    mov ss, ax
    mov sp, stack_top
    sti

    ; Retain only our PSP, code/data, and stack. This exact paragraph count is
    ; emitted in the binary header for instrumentation-overhead accounting.
    push cs
    pop es
    mov bx, KEEP_PARAS
    mov ah, 4Ah
    int 21h
    jc fatal

    ; Capture the unhooked DOS vector used both for chaining and trace writes.
    mov ax, 3521h
    int 21h
    mov [old21_off], bx
    mov [old21_seg], es

    ; Create/truncate the trace before installing the hook.
    mov dx, trace_name
    xor cx, cx
    mov ah, 3Ch
    int 21h
    jc fatal
    mov [trace_handle], ax

    ; Fill and write the 32-byte header.
    call snapshot_mcb
    mov ax, [snap_total]
    mov [header_base_total], ax
    mov ax, [snap_largest]
    mov [header_base_largest], ax
    mov ax, [snap_count]
    mov [header_base_count], ax
    mov bx, [trace_handle]
    mov cx, header_end-header
    mov dx, header
    mov ah, 40h
    int 21h
    jc close_fatal
    cmp ax, header_end-header
    jne close_fatal

    ; Make every far pointer in the EXEC parameter block explicit.
    mov ax, ds
    mov [exec_cmd_seg], ax
    mov [exec_fcb1_seg], ax
    mov [exec_fcb2_seg], ax

    ; Install our INT 21h hook.
    mov dx, int21_hook
    mov ax, 2521h
    int 21h

    ; Synthetic record F0 marks the immediate pre-EXEC state.
    mov byte [record_op], 0F0h
    xor ax, ax
    mov [record_in_bx], ax
    mov [record_in_es], ax
    mov [record_in_owner], ax
    mov [record_out_ax], ax
    mov [record_out_bx], ax
    mov [record_out_owner], ax
    mov [record_caller_cs], ax
    mov byte [record_cf], 0
    call record_synthetic

    ; Execute the authenticated original PRINCE.EXE and forward our PSP tail.
    push ds
    pop es
    mov bx, exec_block
    mov dx, prince_name
    mov ax, 4B00h
    int 21h
    pushf
    push ax

    ; Synthetic record FF marks the post-EXEC state and carries AX/CF.
    mov byte [record_op], 0FFh
    pop ax
    mov [record_out_ax], ax
    pop ax
    and al, 1
    mov [record_cf], al
    xor ax, ax
    mov [record_in_bx], ax
    mov [record_in_es], ax
    mov [record_in_owner], ax
    mov [record_out_bx], ax
    mov [record_out_owner], ax
    mov [record_caller_cs], ax
    call record_synthetic

    ; Restore INT 21h before any ordinary cleanup calls.
    push ds
    mov ax, [old21_seg]
    mov ds, ax
    mov dx, [cs:old21_off]
    mov ax, 2521h
    int 21h
    pop ds

    mov bx, [trace_handle]
    mov ah, 3Eh
    int 21h
    mov ax, 4C00h
    int 21h

close_fatal:
    mov bx, [trace_handle]
    mov ah, 3Eh
    int 21h
fatal:
    mov ax, 4C01h
    int 21h

; ---------------------------------------------------------------------------
; INT 21h hook. Other calls chain without modification.
; ---------------------------------------------------------------------------
int21_hook:
    cmp ah, 3Dh
    je .trace
    cmp ah, 3Eh
    je .trace
    cmp ah, 48h
    je .trace
    cmp ah, 49h
    je .trace
    cmp ah, 4Ah
    je .trace
    jmp far [cs:old21_off]

.trace:
    ; Capture inputs and the call-site segment before touching the stack.
    mov [cs:record_op], ah
    mov [cs:record_in_bx], bx
    mov [cs:record_in_es], es
    mov word [cs:record_in_owner], 0FFFFh
    mov word [cs:record_out_owner], 0FFFFh
    push ax
    push bp
    mov bp, sp
    mov ax, [ss:bp+6]              ; original interrupt-frame CS
    mov [cs:record_caller_cs], ax
    pop bp
    pop ax

    ; Preserve the opened pathname for direct evidence of DAT selection.
    push ax
    push cx
    push si
    push di
    push es
    push cs
    pop es
    mov di, record_name
    xor ax, ax
    mov cx, 8
    rep stosw
    cmp byte [cs:record_op], 3Dh
    jne .name_done
    mov si, dx
    mov di, record_name
    mov cx, 15
.name_copy:
    lodsb
    stosb
    test al, al
    jz .name_done
    loop .name_copy
    mov byte [es:di], 0
.name_done:
    pop es
    pop di
    pop si
    pop cx
    pop ax

    ; For free/resize, capture the target block's owner before DOS mutates it.
    cmp ah, 49h
    je .input_owner
    cmp ah, 4Ah
    jne .pre_snapshot
.input_owner:
    push ax
    push es
    mov ax, es
    dec ax
    mov es, ax
    mov al, [es:0]
    cmp al, 'M'
    je .owner_valid
    cmp al, 'Z'
    jne .owner_done
.owner_valid:
    mov ax, [es:1]
    mov [cs:record_in_owner], ax
.owner_done:
    pop es
    pop ax

.pre_snapshot:
    ; Save the call exactly while a read-only MCB walk computes pre-state.
    pushf
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    push cs
    pop ds
    call snapshot_mcb
    mov ax, [snap_total]
    mov [record_pre_total], ax
    mov ax, [snap_largest]
    mov [record_pre_largest], ax
    mov ax, [snap_count]
    mov [record_pre_count], al
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    popf

    ; Invoke the original DOS handler. Its IRET returns AX/BX/CF results here.
    ; DOS callers conventionally enter with CF clear; some DOS implementations
    ; leave it untouched on success and only set it on failure.
    clc
    pushf
    call far [cs:old21_off]

    mov [cs:record_out_ax], ax
    mov [cs:record_out_bx], bx
    pushf
    pop word [cs:result_flags]

    ; Preserve every observable output while collecting post-state and writing.
    pushf
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    push ds
    push es
    push cs
    pop ds

    mov ax, [result_flags]
    and al, 1
    mov [record_cf], al

    call snapshot_mcb
    mov ax, [snap_total]
    mov [record_post_total], ax
    mov ax, [snap_largest]
    mov [record_post_largest], ax
    mov ax, [snap_count]
    mov [record_post_count], al

    ; A successful AH=48h returns the allocated block segment in AX.
    cmp byte [record_op], 48h
    jne .write_record
    cmp byte [record_cf], 0
    jne .write_record
    mov ax, [record_out_ax]
    dec ax
    mov es, ax
    mov al, [es:0]
    cmp al, 'M'
    je .allocated_owner_valid
    cmp al, 'Z'
    jne .write_record
.allocated_owner_valid:
    mov ax, [es:1]
    mov [record_out_owner], ax

.write_record:
    call stamp_and_write_record
    pop es
    pop ds
    pop bp
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    popf
    retf 2

; Generate a pre=post snapshot for F0/FF marker records.
record_synthetic:
    call snapshot_mcb
    mov ax, [snap_total]
    mov [record_pre_total], ax
    mov [record_post_total], ax
    mov ax, [snap_largest]
    mov [record_pre_largest], ax
    mov [record_post_largest], ax
    mov ax, [snap_count]
    mov [record_pre_count], al
    mov [record_post_count], al
    call stamp_and_write_record
    ret

; Stamp BIOS ticks and sequence, then write one fixed record through the saved
; original DOS vector (bypassing this hook and avoiding recursion).
stamp_and_write_record:
    push es
    mov ax, 40h
    mov es, ax
    mov ax, [es:6Ch]
    mov [record_ticks], ax
    mov ax, [es:6Eh]
    mov [record_ticks+2], ax
    pop es
    mov ax, [sequence]
    mov [record_sequence], ax
    inc word [sequence]

    mov bx, [trace_handle]
    mov cx, RECORD_SIZE
    mov dx, record
    mov ah, 40h
    pushf
    call far [old21_off]
    ret

; Read-only MCB-chain summary. DS must equal CS. Results are stored in snap_*.
snapshot_mcb:
    mov word [snap_total], 0
    mov word [snap_largest], 0
    mov word [snap_count], 0
    mov word [snap_valid], 1
    mov ax, [first_mcb]
.snap_next:
    mov es, ax
    mov dl, [es:0]
    cmp dl, 'M'
    je .snap_valid_block
    cmp dl, 'Z'
    jne .snap_invalid
.snap_valid_block:
    inc word [snap_count]
    cmp word [es:1], 0
    jne .snap_not_free
    mov bx, [es:3]
    add [snap_total], bx
    cmp bx, [snap_largest]
    jbe .snap_not_free
    mov [snap_largest], bx
.snap_not_free:
    cmp dl, 'Z'
    je .snap_done
    mov bx, [es:3]
    inc bx
    add ax, bx
    jmp .snap_next
.snap_invalid:
    mov word [snap_valid], 0
.snap_done:
    ret

; 32-byte file header.
header:
    db 'P13MTRC1'
    dw 2                              ; format version
    dw RECORD_SIZE
    dw KEEP_PARAS
    dw 0                              ; reserved
    dw first_mcb-header               ; field-layout sanity marker
    dw 0                              ; reserved
header_base_total:   dw 0
header_base_largest: dw 0
header_base_count:   dw 0
    dw 0
    dw 0
    dw 0
header_end:

; 48-byte trace record (little endian).
record:
record_ticks:        dd 0             ; +00 BIOS timer ticks
record_op:           db 0             ; +04 F0/Ff marker or DOS AH
record_cf:           db 0             ; +05 DOS carry result
record_in_bx:        dw 0             ; +06 requested/new paragraphs
record_in_es:        dw 0             ; +08 target segment for free/resize
record_in_owner:     dw 0             ; +10 target owner before operation
record_out_ax:       dw 0             ; +12 DOS AX result/segment
record_out_bx:       dw 0             ; +14 DOS BX result/largest on failure
record_pre_total:    dw 0             ; +16 free paragraphs before
record_pre_largest:  dw 0             ; +18 largest free block before
record_post_total:   dw 0             ; +20 free paragraphs after
record_post_largest: dw 0             ; +22 largest free block after
record_pre_count:    db 0             ; +24 MCB count before
record_post_count:   db 0             ; +25 MCB count after
record_out_owner:    dw 0             ; +26 allocated-block owner
record_caller_cs:    dw 0             ; +28 caller CS from interrupt frame
record_sequence:     dw 0             ; +30 monotonic record number
record_name:         times 16 db 0    ; +32 opened ASCIIZ path for AH=3Dh

old21_off       dw 0
old21_seg       dw 0
first_mcb       dw 0
trace_handle    dw 0
result_flags    dw 0
sequence        dw 0
snap_total      dw 0
snap_largest    dw 0
snap_count      dw 0
snap_valid      dw 0

prince_name     db 'PRINCE.EXE', 0
trace_name      db 'MTRACE.BIN', 0

exec_block:
    dw 0                              ; inherit parent environment
    dw 80h
exec_cmd_seg:   dw 0
    dw 5Ch
exec_fcb1_seg:  dw 0
    dw 6Ch
exec_fcb2_seg:  dw 0

    ; Private stack; EXEC and nested DOS calls need more than the tiny code path.
    times 512 db 0
stack_top:

program_end:
KEEP_PARAS equ ((program_end - $$ + 100h + 15) / 16)
