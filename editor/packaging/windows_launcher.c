/*
 * Portable Windows launcher for Prince DAT Explorer.
 *
 * This file deliberately uses only Win32 calls and is linked without a C
 * runtime. The executable lives beside app/ and runtime/ in the standalone
 * ZIP and resolves every dependency relative to itself. The original command
 * line tail is passed through unchanged so quoted drag-and-drop paths survive.
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define PATH_BUFFER_CHARS 32768
#define WINDOWS_COMMAND_LINE_LIMIT 32767

typedef struct LaunchState {
    wchar_t base[PATH_BUFFER_CHARS];
    wchar_t python[PATH_BUFFER_CHARS];
    wchar_t script[PATH_BUFFER_CHARS];
    wchar_t runtime[PATH_BUFFER_CHARS];
    wchar_t tcl_library[PATH_BUFFER_CHARS];
    wchar_t tk_library[PATH_BUFFER_CHARS];
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
} LaunchState;

static size_t wide_length(const wchar_t *text) {
    size_t length = 0;
    while (text[length] != L'\0') {
        ++length;
    }
    return length;
}

static BOOL append_text(wchar_t *destination, size_t capacity,
                        size_t *position, const wchar_t *source) {
    size_t cursor = *position;
    while (*source != L'\0') {
        if (cursor + 1 >= capacity) {
            SetLastError(ERROR_INSUFFICIENT_BUFFER);
            return FALSE;
        }
        destination[cursor++] = *source++;
    }
    destination[cursor] = L'\0';
    *position = cursor;
    return TRUE;
}

static BOOL join_path(wchar_t *destination, size_t capacity,
                      const wchar_t *base, const wchar_t *suffix) {
    size_t position = 0;
    destination[0] = L'\0';
    return append_text(destination, capacity, &position, base) &&
           append_text(destination, capacity, &position, L"\\") &&
           append_text(destination, capacity, &position, suffix);
}

static void show_last_error(const wchar_t *summary) {
    DWORD code = GetLastError();
    HANDLE heap = GetProcessHeap();
    wchar_t *system_message = HeapAlloc(heap, HEAP_ZERO_MEMORY,
                                        1024 * sizeof(wchar_t));
    wchar_t *message = HeapAlloc(heap, HEAP_ZERO_MEMORY,
                                 1536 * sizeof(wchar_t));
    size_t position = 0;

    if (system_message == NULL || message == NULL) {
        MessageBoxW(NULL, summary, L"Prince DAT Explorer", MB_OK | MB_ICONERROR);
    } else {
        FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM |
                           FORMAT_MESSAGE_IGNORE_INSERTS,
                       NULL, code, 0, system_message, 1024, NULL);
        append_text(message, 1536, &position, summary);
        if (system_message[0] != L'\0') {
            append_text(message, 1536, &position, L"\r\n\r\n");
            append_text(message, 1536, &position, system_message);
        }
        MessageBoxW(NULL, message, L"Prince DAT Explorer", MB_OK | MB_ICONERROR);
    }
    if (system_message != NULL) {
        HeapFree(heap, 0, system_message);
    }
    if (message != NULL) {
        HeapFree(heap, 0, message);
    }
    SetLastError(code);
}

static const wchar_t *command_line_tail(void) {
    const wchar_t *cursor = GetCommandLineW();

    if (*cursor == L'"') {
        ++cursor;
        while (*cursor != L'\0' && *cursor != L'"') {
            ++cursor;
        }
        if (*cursor == L'"') {
            ++cursor;
        }
    } else {
        while (*cursor != L'\0' && *cursor != L' ' && *cursor != L'\t') {
            ++cursor;
        }
    }
    while (*cursor == L' ' || *cursor == L'\t') {
        ++cursor;
    }
    return cursor;
}

void WINAPI launcher_entry(void) {
    HANDLE heap = GetProcessHeap();
    LaunchState *state = HeapAlloc(heap, HEAP_ZERO_MEMORY, sizeof(LaunchState));
    const wchar_t *tail;
    wchar_t *child_command;
    size_t command_capacity;
    size_t position = 0;
    DWORD module_length;
    DWORD child_exit_code = 1;

    if (state == NULL) {
        MessageBoxW(NULL,
                    L"Windows could not allocate memory for the standalone launcher.",
                    L"Prince DAT Explorer", MB_OK | MB_ICONERROR);
        ExitProcess(1);
    }

    module_length = GetModuleFileNameW(NULL, state->base, PATH_BUFFER_CHARS);
    if (module_length == 0 || module_length >= PATH_BUFFER_CHARS) {
        show_last_error(L"Could not locate the standalone application folder.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }
    while (module_length > 0 && state->base[module_length - 1] != L'\\' &&
           state->base[module_length - 1] != L'/') {
        --module_length;
    }
    if (module_length == 0) {
        SetLastError(ERROR_BAD_PATHNAME);
        show_last_error(L"Could not locate the standalone application folder.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }
    state->base[module_length - 1] = L'\0';

    if (!join_path(state->python, PATH_BUFFER_CHARS, state->base,
                   L"runtime\\pythonw.exe") ||
        !join_path(state->script, PATH_BUFFER_CHARS, state->base,
                   L"app\\PrinceDATViewer.pyw") ||
        !join_path(state->runtime, PATH_BUFFER_CHARS, state->base, L"runtime") ||
        !join_path(state->tcl_library, PATH_BUFFER_CHARS, state->base,
                   L"runtime\\tcl\\tcl8.6") ||
        !join_path(state->tk_library, PATH_BUFFER_CHARS, state->base,
                   L"runtime\\tcl\\tk8.6")) {
        show_last_error(L"The extracted path is too long for the standalone launcher.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }

    if (GetFileAttributesW(state->python) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(state->script) == INVALID_FILE_ATTRIBUTES) {
        SetLastError(ERROR_FILE_NOT_FOUND);
        show_last_error(L"The standalone runtime is incomplete. Extract the entire ZIP before launching it.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }

    if (!SetEnvironmentVariableW(L"PYTHONHOME", state->runtime) ||
        !SetEnvironmentVariableW(L"TCL_LIBRARY", state->tcl_library) ||
        !SetEnvironmentVariableW(L"TK_LIBRARY", state->tk_library)) {
        show_last_error(L"Could not configure the private standalone runtime.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }

    tail = command_line_tail();
    command_capacity = wide_length(state->python) + wide_length(state->script) +
                       wide_length(tail) + 24;
    if (command_capacity > WINDOWS_COMMAND_LINE_LIMIT) {
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        show_last_error(L"The application or DAT path is too long for Windows to launch.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }
    child_command = HeapAlloc(heap, HEAP_ZERO_MEMORY,
                              command_capacity * sizeof(wchar_t));
    if (child_command == NULL) {
        SetLastError(ERROR_NOT_ENOUGH_MEMORY);
        show_last_error(L"Could not start the bundled runtime.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }

    append_text(child_command, command_capacity, &position, L"\"");
    append_text(child_command, command_capacity, &position, state->python);
    append_text(child_command, command_capacity, &position, L"\" -B -X utf8 \"");
    append_text(child_command, command_capacity, &position, state->script);
    append_text(child_command, command_capacity, &position, L"\"");
    if (*tail != L'\0') {
        append_text(child_command, command_capacity, &position, L" ");
        append_text(child_command, command_capacity, &position, tail);
    }

    state->startup.cb = sizeof(STARTUPINFOW);
    if (!CreateProcessW(state->python, child_command, NULL, NULL, FALSE, 0,
                        NULL, state->base, &state->startup, &state->process)) {
        HeapFree(heap, 0, child_command);
        show_last_error(L"Could not start the bundled Prince DAT Explorer runtime.");
        HeapFree(heap, 0, state);
        ExitProcess(1);
    }

    HeapFree(heap, 0, child_command);
    CloseHandle(state->process.hThread);
    WaitForSingleObject(state->process.hProcess, INFINITE);
    GetExitCodeProcess(state->process.hProcess, &child_exit_code);
    CloseHandle(state->process.hProcess);
    HeapFree(heap, 0, state);

    if (child_exit_code != 0) {
        MessageBoxW(NULL,
                    L"The editor stopped unexpectedly. Re-extract the complete ZIP and try again.",
                    L"Prince DAT Explorer", MB_OK | MB_ICONERROR);
    }
    ExitProcess(child_exit_code);
}
