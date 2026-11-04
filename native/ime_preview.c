/* Windows message callbacks never call Python or Tcl/Tk.
 * Only unfinished composition is captured. Committed text stays on Tk's
 * normal Windows input path, preserving keyboard order and selection behavior.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <imm.h>

typedef struct {
    HWND hwnd;
    DWORD thread;
    BOOL active;
    WCHAR *text;
    int length;
} Preview;

static void clear_preview(Preview *p) {
    if (p->text) HeapFree(GetProcessHeap(), 0, p->text);
    p->text = NULL;
    p->length = 0;
}

static BOOL capture_preview(Preview *p, HIMC context) {
    LONG bytes = ImmGetCompositionStringW(context, GCS_COMPSTR, NULL, 0);
    if (bytes < 0 || bytes > 65536 || bytes % sizeof(WCHAR)) return FALSE;
    WCHAR *value = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, (SIZE_T)bytes + sizeof(WCHAR));
    if (!value) return FALSE;
    LONG read = bytes ? ImmGetCompositionStringW(context, GCS_COMPSTR, value, (DWORD)bytes) : 0;
    if (read < 0 || read > bytes || read % sizeof(WCHAR)) {
        HeapFree(GetProcessHeap(), 0, value);
        return FALSE;
    }
    clear_preview(p);
    p->text = value;
    p->length = read / sizeof(WCHAR);
    return TRUE;
}

static LRESULT CALLBACK preview_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                      UINT_PTR id, DWORD_PTR data) {
    Preview *p = (Preview *)data;
    if (msg == WM_NCDESTROY) {
        RemoveWindowSubclass(hwnd, preview_proc, id);
        p->hwnd = NULL;
        p->active = FALSE;
        clear_preview(p);
    } else if (p->active) {
        if (msg == WM_IME_SETCONTEXT) {
            lp &= ~((LPARAM)ISC_SHOWUICOMPOSITIONWINDOW);
        } else if (msg == WM_IME_STARTCOMPOSITION) {
            clear_preview(p);
            return 0;
        } else if (msg == WM_IME_ENDCOMPOSITION) {
            clear_preview(p);
        } else if (msg == WM_IME_COMPOSITION) {
            if (lp & GCS_RESULTSTR) clear_preview(p);
            if (lp & GCS_COMPSTR) {
                HIMC context = ImmGetContext(hwnd);
                if (!context) return DefSubclassProc(hwnd, msg, wp, lp);
                BOOL ok = capture_preview(p, context);
                ImmReleaseContext(hwnd, context);
                if (!ok) return DefSubclassProc(hwnd, msg, wp, lp);
            }
            if (!lp) clear_preview(p);
            /* Let Windows/Tk deliver committed characters normally, but never
             * ask the default IME window to paint the unfinished composition. */
            LPARAM result = lp & (GCS_RESULTSTR | GCS_RESULTCLAUSE |
                                   GCS_RESULTREADSTR | GCS_RESULTREADCLAUSE);
            return result ? DefSubclassProc(hwnd, msg, wp, result) : 0;
        }
    }
    return DefSubclassProc(hwnd, msg, wp, lp);
}

__declspec(dllexport) void *WINAPI preview_attach(HWND hwnd) {
    DWORD thread = GetCurrentThreadId();
    if (!hwnd || GetWindowThreadProcessId(hwnd, NULL) != thread) return NULL;
    Preview *p = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(Preview));
    if (!p) return NULL;
    p->hwnd = hwnd;
    p->thread = thread;
    if (!SetWindowSubclass(hwnd, preview_proc, (UINT_PTR)p, (DWORD_PTR)p)) {
        HeapFree(GetProcessHeap(), 0, p);
        return NULL;
    }
    return p;
}

__declspec(dllexport) void WINAPI preview_activate(void *handle, BOOL active) {
    Preview *p = handle;
    if (!p || p->thread != GetCurrentThreadId()) return;
    p->active = active;
    if (!active) clear_preview(p);
}

__declspec(dllexport) int WINAPI preview_read(void *handle, WCHAR *out, int capacity) {
    Preview *p = handle;
    if (!p || p->thread != GetCurrentThreadId()) return 0;
    if (capacity <= p->length) return -(p->length + 1);
    if (p->length) CopyMemory(out, p->text, p->length * sizeof(WCHAR));
    out[p->length] = 0;
    return p->length;
}

__declspec(dllexport) void WINAPI preview_detach(void *handle) {
    Preview *p = handle;
    if (!p || p->thread != GetCurrentThreadId()) return;
    if (p->hwnd && !RemoveWindowSubclass(p->hwnd, preview_proc, (UINT_PTR)p)) return;
    clear_preview(p);
    HeapFree(GetProcessHeap(), 0, p);
}
