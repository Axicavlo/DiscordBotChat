"""Display preedit inside the input without Python window-procedure callbacks.

The native shim only captures unfinished text. Tk retains normal ownership of
committed input. All preview widgets are updated from Tk's own event loop.
"""
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
import math

_library = None


def library():
    global _library
    if _library is None:
        native = ctypes.WinDLL(str(Path(__file__).resolve().parent / 'native' / 'ime_preview.dll'))
        native.preview_attach.argtypes = [ctypes.c_void_p]
        native.preview_attach.restype = ctypes.c_void_p
        native.preview_activate.argtypes = [ctypes.c_void_p, ctypes.c_int]
        native.preview_activate.restype = None
        native.preview_read.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        native.preview_read.restype = ctypes.c_int
        native.preview_detach.argtypes = [ctypes.c_void_p]
        native.preview_detach.restype = None
        # Keep the DLL loaded for the entire process, including HWND teardown.
        _library = native
    return _library


class ImePreview:
    def __init__(self, widget):
        self.widget = widget
        self.native = library()
        self.handle = self.native.preview_attach(widget.winfo_toplevel().winfo_id())
        if not self.handle:
            raise OSError('IME preview could not attach to the UI thread')
        self.job = None
        self.enabled = False
        self.surface = tk.Text(widget, font=widget.cget('font'), bg=widget.cget('background'),
                               fg=widget.cget('foreground'), bd=0, highlightthickness=0,
                               padx=0, pady=0, height=1, width=1, wrap='char',
                               spacing1=0, spacing2=0, spacing3=0, state='disabled',
                               takefocus=False, cursor='arrow')
        self.surface.tag_configure('composition', underline=True)
        self.surface.bind('<Button-1>', lambda event: self.keep_focus())
        self.shown_text = None
        self.focus_in_id = widget.bind('<FocusIn>', self.focus_in, add='+')
        self.focus_out_id = widget.bind('<FocusOut>', self.focus_out, add='+')

    def focus_in(self, event=None):
        if not self.handle:
            return
        self.enabled = True
        self.native.preview_activate(self.handle, 1)
        if self.job is None:
            self.job = self.widget.after(15, self.refresh)

    def focus_out(self, event=None):
        self.enabled = False
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.handle:
            self.native.preview_activate(self.handle, 0)
        self.surface.place_forget()

    def keep_focus(self):
        self.widget.focus_set()
        return 'break'

    def value(self):
        buffer = ctypes.create_unicode_buffer(256)
        length = self.native.preview_read(self.handle, buffer, len(buffer))
        if length < 0:
            buffer = ctypes.create_unicode_buffer(-length)
            length = self.native.preview_read(self.handle, buffer, len(buffer))
        return buffer.value if length > 0 else ''

    def refresh(self):
        self.job = None
        if not self.enabled or not self.handle:
            return
        text = self.value()
        index = 'sel.first' if self.widget.tag_ranges('sel') else 'insert'
        box = self.widget.bbox(index)
        if text and box:
            font = tkfont.Font(self.widget, font=self.widget.cget('font'))
            self.surface.configure(font=self.widget.cget('font'),
                                   fg=self.widget.cget('foreground'), bg=self.widget.cget('background'))
            if text != self.shown_text:
                self.surface.configure(state='normal')
                self.surface.delete('1.0', 'end')
                self.surface.insert('1.0', text, ('composition',))
                self.surface.configure(state='disabled')
                self.shown_text = text
            x, y, width, height = box
            line = self.widget.dlineinfo(index)
            # bbox is a character box, not a baseline. Use both Text widgets'
            # actual line baselines to avoid Label/Text vertical differences.
            baseline = line[1] + line[4] if line else y + font.metrics('ascent')
            preview_line = self.surface.dlineinfo('1.0')
            preview_baseline = preview_line[1] + preview_line[4] if preview_line else font.metrics('ascent')
            y = baseline - preview_baseline
            available = max(1, self.widget.winfo_width() - x - int(self.widget.cget('padx')) - 1)
            width = min(available, max(2, max(font.measure(part) for part in text.split('\n')) + 2))
            rows = sum(max(1, math.ceil(font.measure(part) / max(1, width))) for part in text.split('\n'))
            # Text includes its padding in the internal border. bbox coordinates
            # already include it, so place must not add that border a second time.
            self.surface.place(x=x, y=y, width=width, height=font.metrics('linespace') * rows,
                               bordermode='outside')
            self.surface.lift()
        else:
            self.surface.place_forget()
        self.job = self.widget.after(15, self.refresh)

    def close(self):
        self.focus_out()
        self.widget.unbind('<FocusIn>', self.focus_in_id)
        self.widget.unbind('<FocusOut>', self.focus_out_id)
        if self.handle:
            self.native.preview_detach(self.handle)
            self.handle = None
        self.surface.destroy()


def attach_preview(widget):
    try:
        return ImePreview(widget)
    except OSError:
        # Source-only runs can still type using Tk's default IME before the
        # native helper is built. Packaged builds always include the helper.
        return None
