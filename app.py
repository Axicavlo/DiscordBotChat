"""A local Discord console with Windows-encrypted token persistence."""
import asyncio
import ctypes
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont

import discord


TOKEN_FILE = Path(__file__).resolve().with_name('.bot-token.dat')


def bind_canvas_pointer(canvas, tag_prefix):
    def motion(event):
        clickable = any(tag.startswith(tag_prefix) for tag in canvas.gettags('current'))
        canvas.configure(cursor='hand2' if clickable else '')
    canvas.bind('<Motion>', motion, add='+')
    canvas.bind('<Leave>', lambda event: canvas.configure(cursor=''), add='+')


def protect_token(data, decrypt=False):
    """Use current-user DPAPI; never store plaintext credentials."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    operation.restype = ctypes.c_int
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def load_token():
    if not TOKEN_FILE.exists():
        return ''
    return protect_token(TOKEN_FILE.read_bytes(), decrypt=True).decode('utf-8')


def save_token(token):
    encrypted = protect_token(token.encode('utf-8'))
    temporary = TOKEN_FILE.with_suffix('.tmp')
    try:
        temporary.write_bytes(encrypted)
        temporary.replace(TOKEN_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def complete_ime(widget):
    """Commit the native composition before Tk reads the Text contents."""
    if os.name != 'nt':
        return
    ime = ctypes.WinDLL('imm32')
    ime.ImmGetContext.argtypes = [ctypes.c_void_p]
    ime.ImmGetContext.restype = ctypes.c_void_p
    ime.ImmNotifyIME.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    ime.ImmNotifyIME.restype = ctypes.c_int
    ime.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    ime.ImmReleaseContext.restype = ctypes.c_int
    # Tk keeps Win32 keyboard focus on the toplevel, not the Text HWND.
    hwnd = widget.winfo_toplevel().winfo_id()
    context = ime.ImmGetContext(hwnd)
    if context:
        try:
            # NI_COMPOSITIONSTR / CPS_COMPLETE (not CPS_CANCEL).
            ime.ImmNotifyIME(context, 0x0015, 0x0001, 0)
        finally:
            ime.ImmReleaseContext(hwnd, context)


class InlineIme:
    """Draw live Windows IME composition using the Text widget's own style."""
    def __init__(self, widget):
        self.widget = widget
        self.active = False
        self.hwnd = widget.winfo_toplevel().winfo_id()
        self.ime = ctypes.WinDLL('imm32')
        self.ime.ImmGetContext.argtypes = [ctypes.c_void_p]
        self.ime.ImmGetContext.restype = ctypes.c_void_p
        self.ime.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.ime.ImmReleaseContext.restype = ctypes.c_int
        self.ime.ImmGetCompositionStringW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                    ctypes.c_void_p, ctypes.c_ulong]
        self.ime.ImmGetCompositionStringW.restype = ctypes.c_long
        self.native = ctypes.WinDLL('comctl32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p,
                                          ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                                          ctypes.c_size_t, ctypes.c_size_t)
        self.callback = callback_type(self.on_message)
        self.subclass_id = id(self)
        self.native.SetWindowSubclass.argtypes = [ctypes.c_void_p, callback_type,
                                                  ctypes.c_size_t, ctypes.c_size_t]
        self.native.SetWindowSubclass.restype = ctypes.c_int
        self.native.RemoveWindowSubclass.argtypes = [ctypes.c_void_p, callback_type, ctypes.c_size_t]
        self.native.RemoveWindowSubclass.restype = ctypes.c_int
        self.native.DefSubclassProc.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                ctypes.c_size_t, ctypes.c_ssize_t]
        self.native.DefSubclassProc.restype = ctypes.c_ssize_t
        if not self.native.SetWindowSubclass(self.hwnd, self.callback, self.subclass_id, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def detach(self):
        self.native.RemoveWindowSubclass(self.hwnd, self.callback, self.subclass_id)

    def read_string(self, context, flag):
        size = self.ime.ImmGetCompositionStringW(context, flag, None, 0)
        if size < 0:
            raise OSError('IME composition could not be read')
        if not size:
            return ''
        buffer = ctypes.create_string_buffer(size)
        read = self.ime.ImmGetCompositionStringW(context, flag, buffer, size)
        if read < 0:
            raise OSError('IME composition could not be read')
        return buffer.raw[:read].decode('utf-16-le')

    def replace(self, value, final=False):
        text = self.widget
        if not self.active:
            if not value:
                return
            if text.tag_ranges('sel'):
                text.mark_set('insert', 'sel.first')
                text.delete('sel.first', 'sel.last')
            text.mark_set('_ime_start', 'insert')
            text.mark_gravity('_ime_start', 'left')
            text.mark_set('_ime_end', 'insert')
            text.mark_gravity('_ime_end', 'right')
            self.active = True
        text.delete('_ime_start', '_ime_end')
        text.insert('_ime_start', value, ())
        text.mark_set('insert', '_ime_end')
        text.see('insert')
        if final:
            text.mark_unset('_ime_start', '_ime_end')
            self.active = False

    def on_message(self, hwnd, message, wparam, lparam, subclass_id, data):
        try:
            if message == 0x0082:  # WM_NCDESTROY: detach before HWND is destroyed.
                self.native.RemoveWindowSubclass(hwnd, self.callback, subclass_id)
            elif message == 0x0281:  # WM_IME_SETCONTEXT: hide native composition UI.
                lparam &= ~0x80000000
            elif message in (0x010D, 0x010E, 0x010F) and not (
                    self.active or self.widget.focus_get() == self.widget):
                return self.native.DefSubclassProc(hwnd, message, wparam, lparam)
            elif message == 0x010D:  # WM_IME_STARTCOMPOSITION
                return 0
            elif message == 0x010E:  # WM_IME_ENDCOMPOSITION (including cancellation)
                self.replace('', final=True)
                return 0
            elif message == 0x010F:  # WM_IME_COMPOSITION
                context = self.ime.ImmGetContext(hwnd)
                if context:
                    try:
                        if lparam & 0x0800:  # GCS_RESULTSTR
                            self.replace(self.read_string(context, 0x0800), final=True)
                        if lparam & 0x0008:  # GCS_COMPSTR
                            self.replace(self.read_string(context, 0x0008))
                        if not lparam:
                            self.replace('', final=True)
                    finally:
                        self.ime.ImmReleaseContext(hwnd, context)
                    return 0  # Do not let Tk insert the result a second time.
        except (OSError, UnicodeError, tk.TclError):
            # Keep native input functional if the input method rejects a request.
            self.replace('', final=True)
        return self.native.DefSubclassProc(hwnd, message, wparam, lparam)


def message_text(message):
    body = message.clean_content
    if message.reference:
        original = message.reference.resolved
        if isinstance(original, discord.Message):
            preview = original.clean_content.replace('\n', ' ')[:80] or '[첨부 메시지]'
            body = f'↳ {original.author.display_name}: {preview}\n{body}'
        else:
            body = f'↳ 원본 메시지 (ID: {message.reference.message_id})\n{body}'
    extras = [a.url for a in message.attachments]
    extras += [e.title or e.description or '[임베드]' for e in message.embeds]
    if extras:
        body += '\n' + '\n'.join(extras)
    return f'{message.created_at.astimezone():%m/%d %H:%M}  {message.author.display_name}\n{body or "[내용 없음]"}\n'


class Bridge(discord.Client):
    def __init__(self, events):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.events = events
        self.worker_loop = None

    async def on_ready(self):
        self.events.put(('ready', None, str(self.user)))
        await self.publish_servers()

    async def on_disconnect(self):
        self.events.put(('status', None, '연결 끊김 · 재연결 대기 중'))

    async def publish_servers(self):
        self.events.put(('servers', None, sorted([(g.id, g.name) for g in self.guilds], key=lambda x: x[1])))

    async def on_guild_join(self, guild):
        await self.publish_servers()

    async def on_guild_remove(self, guild):
        await self.publish_servers()

    async def channels(self, guild_id):
        guild = self.get_guild(guild_id)
        if guild is None or guild.me is None:
            raise RuntimeError('서버 정보를 가져올 수 없습니다. 새로고침하세요.')
        rows = [(c.id, f'{c.category.name + " / " if c.category else ""}#{c.name}')
                for c in guild.text_channels if c.permissions_for(guild.me).view_channel]
        self.events.put(('channels', guild_id, rows))

    async def history(self, channel_id):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise RuntimeError('채널에 접근할 수 없습니다.')
        rows = [m async for m in channel.history(limit=100)]
        self.events.put(('history', channel_id, list(reversed(rows))))

    async def send_text(self, channel_id, text, reply_id=None, notify_reply=False):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise RuntimeError('채널에 접근할 수 없습니다.')
        reference = None
        if reply_id is not None:
            reference = discord.MessageReference(message_id=reply_id, channel_id=channel_id,
                                                 fail_if_not_exists=True)
        await channel.send(text, reference=reference,
                           allowed_mentions=discord.AllowedMentions(
                               users=True, roles=False, everyone=False, replied_user=notify_reply))
        self.events.put(('sent', channel_id, (text, reply_id)))

    async def on_message(self, message):
        if message.guild:
            self.events.put(('message', message.channel.id, message))

    async def on_raw_message_edit(self, payload):
        try:
            channel = self.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                self.events.put(('message', payload.channel_id, msg))
        except discord.HTTPException:
            pass

    async def on_raw_message_delete(self, payload):
        self.events.put(('deleted', payload.channel_id, payload.message_id))

    async def on_raw_bulk_message_delete(self, payload):
        for mid in payload.message_ids:
            self.events.put(('deleted', payload.channel_id, mid))

    def run_worker(self, token):
        async def main():
            self.worker_loop = asyncio.get_running_loop()
            try:
                async with self:
                    await self.start(token)
            except Exception as exc:
                self.events.put(('fatal', None, safe_error(exc)))
        asyncio.run(main())

    def submit(self, method, *args, channel_id=None):
        if not self.worker_loop or not self.is_ready():
            self.events.put(('error', channel_id, '봇 연결이 준비되지 않았습니다.'))
            return
        async def task():
            try:
                await method(*args)
            except Exception as exc:
                self.events.put(('error', channel_id, safe_error(exc)))
        asyncio.run_coroutine_threadsafe(task(), self.worker_loop)


def safe_error(exc):
    if isinstance(exc, discord.LoginFailure):
        return '봇 토큰이 올바르지 않습니다.'
    if isinstance(exc, discord.PrivilegedIntentsRequired):
        return 'Developer Portal에서 Message Content Intent를 켜주세요.'
    if isinstance(exc, discord.Forbidden):
        return '권한이 없습니다. 채널 보기·메시지 기록 보기·메시지 보내기를 확인하세요.'
    if isinstance(exc, discord.HTTPException):
        return f'Discord 요청 실패 (HTTP {exc.status}). 잠시 후 다시 시도하세요.'
    if isinstance(exc, RuntimeError):
        return str(exc)
    return f'연결 또는 처리 실패 ({type(exc).__name__}). 네트워크를 확인하세요.'


class Chat:
    def __init__(self, app, channel_id, title):
        self.app, self.channel_id = app, channel_id
        self.messages = {}
        self.deleted = set()
        self.reply_id = None
        self.mention_window = None
        self.bg = '#e9eef3'
        self.resize_job = None
        self.send_job = None
        self.window = tk.Frame(app.chat_host, bg=self.bg)
        header = tk.Frame(self.window, bg=self.bg)
        header.pack(fill='x', padx=22, pady=(20, 12))
        tk.Label(header, text='#', bg='#d5e1e9', fg='#40596a', font=('맑은 고딕', 18, 'bold'), width=2).pack(side='left')
        tk.Label(header, text='#chat', bg=self.bg, fg='#233747', font=('맑은 고딕', 11, 'bold')).pack(side='left', padx=12)
        self.view = tk.Canvas(self.window, bg=self.bg, highlightthickness=0)
        self.view.pack(fill='both', expand=True, padx=8)
        bind_canvas_pointer(self.view, 'message_')
        self.view.bind('<Configure>', self.schedule_render)
        self.view.bind('<MouseWheel>', lambda event: self.view.yview_scroll(-int(event.delta / 120), 'units'))
        self.status = tk.StringVar(value='최근 대화 불러오는 중…')
        tk.Label(self.window, textvariable=self.status, bg=self.bg, fg='#7c8995', font=('맑은 고딕', 9), anchor='w', wraplength=550).pack(fill='x', padx=22, pady=(4, 6))
        self.composer = tk.Canvas(self.window, bg=self.bg, height=150, highlightthickness=0)
        self.composer.pack(fill='x', padx=12, pady=(0, 12))
        self.input_frame = tk.Frame(self.composer, bg='white')
        self.composer_window = self.composer.create_window(16, 12, window=self.input_frame, anchor='nw')
        self.composer.bind('<Configure>', self.layout_composer)
        self.reply_frame = tk.Frame(self.input_frame, bg='white')
        self.reply_label = tk.Label(self.reply_frame, bg='white', fg='#52717d', anchor='w', justify='left', wraplength=360)
        self.reply_label.pack(side='left', fill='x', expand=True)
        ttk.Button(self.reply_frame, text='취소', command=self.clear_reply, cursor='hand2').pack(side='right')
        self.notify_reply = tk.BooleanVar(value=False)
        tk.Checkbutton(self.reply_frame, text='알림', variable=self.notify_reply, bg='white', activebackground='white', fg='#7c8995', cursor='hand2').pack(side='right')
        self.input = tk.Text(self.input_frame, height=3, wrap='word', font=('맑은 고딕', 11), relief='flat', bd=0, highlightthickness=0, bg='white', fg='#243746', insertbackground='#00a5bc')
        self.input.pack(fill='x', pady=(8, 6))
        self.inline_ime = InlineIme(self.input) if os.name == 'nt' else None
        self.input.bind('<Return>', self.send)
        self.input.bind('<Shift-Return>', self.insert_linebreak)
        self.input.bind('<Alt-Return>', self.insert_linebreak)
        self.input.bind('<KeyRelease>', self.input_key)
        toolbar = tk.Frame(self.input_frame, bg='white')
        toolbar.pack(fill='x')
        tk.Button(toolbar, text='@', command=self.choose_mention, font=('맑은 고딕', 17), bd=0, bg='white', fg='#435560', activebackground='#f0f5f8', cursor='hand2').pack(side='left')
        tk.Label(toolbar, text='Enter 전송 · Shift/Alt+Enter 줄바꿈', bg='white', fg='#a2adb5', font=('맑은 고딕', 9)).pack(side='left', padx=8)
        self.button = tk.Button(toolbar, text='전송', command=self.send, bg='#00a6bd', fg='white', activebackground='#008fa5', activeforeground='white', relief='flat', bd=0, padx=14, pady=6, cursor='hand2')
        self.button.pack(side='right')

    @staticmethod
    def rounded(canvas, x1, y1, x2, y2, color, radius=16, **kwargs):
        # Tk polygons have jagged edges; use prefiltered transparent corner tiles.
        x1, y1, x2, y2 = map(round, (x1, y1, x2, y2))
        r = int(min(radius, (x2-x1)//2, (y2-y1)//2))
        if r < radius:
            return canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='', **kwargs)
        key = ('ffffff' if color == 'white' else color.lstrip('#'), r)
        if not hasattr(canvas, '_round_cache'):
            canvas._round_cache = {}
            canvas._round_serial = 0
        if key not in canvas._round_cache:
            source = tk.PhotoImage(master=canvas, file=str(
                Path(__file__).resolve().parent / 'assets' / f'round-{key[0]}-{r}.png'))
            corners = []
            for sx, sy in ((0, 0), (r, 0), (0, r), (r, r)):
                corner = tk.PhotoImage(master=canvas, width=r, height=r)
                canvas.tk.call(str(corner), 'copy', str(source), '-from', sx, sy, sx+r, sy+r, '-to', 0, 0)
                corners.append(corner)
            canvas._round_cache[key] = corners
        canvas._round_serial += 1
        group = f'_round_{canvas._round_serial}'
        tags = kwargs.pop('tags', ())
        tags = (tags,) if isinstance(tags, str) else tuple(tags)
        tags += (group,)
        canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=color, outline='', tags=tags, **kwargs)
        canvas.create_rectangle(x1, y1+r, x1+r, y2-r, fill=color, outline='', tags=tags, **kwargs)
        canvas.create_rectangle(x2-r, y1+r, x2, y2-r, fill=color, outline='', tags=tags, **kwargs)
        for image, (x, y) in zip(canvas._round_cache[key],
                                  ((x1, y1), (x2-r, y1), (x1, y2-r), (x2-r, y2-r))):
            canvas.create_image(x, y, image=image, anchor='nw', tags=tags)
        return group

    def layout_composer(self, event=None):
        width = max(1, self.composer.winfo_width())
        height = self.input_frame.winfo_reqheight() + 28
        self.composer.configure(height=height)
        self.composer.delete('background')
        self.rounded(self.composer, 0, 0, width, height, 'white', tags='background')
        self.composer.tag_lower('background')
        self.composer.itemconfigure(self.composer_window, width=max(1, width-32))
        self.reply_label.configure(wraplength=max(100, width-180))

    def schedule_render(self, event=None):
        if self.resize_job:
            self.window.after_cancel(self.resize_job)
        self.resize_job = self.window.after(80, self.render)

    def close(self):
        if self.inline_ime:
            if self.inline_ime.active:
                complete_ime(self.input)
            self.inline_ime.detach()
        if self.send_job:
            self.window.after_cancel(self.send_job)
        if self.resize_job:
            self.window.after_cancel(self.resize_job)
        self.app.chats.pop(self.channel_id, None)
        self.window.pack_forget()
        self.window.destroy()
        if self.app.active_chat is self:
            self.app.active_chat = None
            self.app.show_empty()

    def render(self):
        self.resize_job = None
        bottom = self.view.yview()[1] >= .98
        position = self.view.yview()[0]
        self.view.delete('all')
        ordered = sorted(self.messages.values(), key=lambda m: m.id)[-500:]
        self.messages = {m.id: m for m in ordered}
        width = max(380, self.view.winfo_width())
        y, last_date = 12, None
        me = getattr(self.app.bridge, 'user', None)
        for message in ordered:
            local = message.created_at.astimezone()
            if local.date() != last_date:
                self.rounded(self.view, width/2-85, y, width/2+85, y+25, '#d7dfe5', radius=12)
                self.view.create_text(width/2, y+12, text=f'{local:%Y년 %m월 %d일}', fill='#6f7f8c', font=('맑은 고딕', 9))
                y += 45
                last_date = local.date()
            own = me is not None and message.author.id == me.id
            tag = f'message_{message.id}'
            if not own:
                self.view.create_oval(10,y,42,y+32,fill='#c7d6de',outline='',tags=tag)
                self.view.create_text(26,y+16,text=message.author.display_name[:1],fill='#3f5f70',font=('맑은 고딕',11,'bold'),tags=tag)
                self.view.create_text(52,y+3,text=message.author.display_name,anchor='nw',fill='#718493',font=('맑은 고딕',9),tags=tag)
                y += 24
            body = message_text(message).split('\n', 1)[1].rstrip('\n')
            text_id = self.view.create_text(0,0,text=body,anchor='nw',width=max(150,int(width*.64)),font=('맑은 고딕',10),fill='white' if own else '#314b5c',tags=tag)
            box = self.view.bbox(text_id)
            bw, bh = box[2]-box[0]+26, box[3]-box[1]+20
            x = width-bw-20 if own else 52
            bubble = self.rounded(self.view,x,y,x+bw,y+bh,'#00a6bd' if own else 'white',tags=tag)
            self.view.tag_lower(bubble,text_id)
            self.view.coords(text_id,x+13,y+10)
            self.view.create_text(x-8 if own else x+bw+8,y+bh-3,text=f'{local:%H:%M}',anchor='se' if own else 'sw',fill='#8a9aa7',font=('맑은 고딕',8),tags=tag)
            self.view.tag_bind(tag,'<Button-3>',lambda event, mid=message.id: self.message_menu(event,mid))
            y += bh+16
        self.view.configure(scrollregion=(0,0,width,y+12))
        if bottom:
            self.view.yview_moveto(1)
        else:
            self.view.yview_moveto(position)

    def message_menu(self, event, mid):
        if mid not in self.messages:
            return
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(label='답장', command=lambda: self.set_reply(mid))
        menu.add_command(label='작성자 멘션', command=lambda: self.insert_mention(self.messages[mid].author.id))
        menu.add_command(label='내용 복사', command=lambda: self.copy_message(mid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def copy_message(self, mid):
        if mid in self.messages:
            self.window.clipboard_clear()
            self.window.clipboard_append(self.messages[mid].clean_content)

    def set_reply(self, mid):
        if str(self.button['state']) == 'disabled':
            return
        message = self.messages.get(mid)
        if message is None:
            return
        self.reply_id = mid
        preview = message.clean_content.replace('\n', ' ')[:80] or '[첨부 메시지]'
        self.reply_label.configure(text=f'↳ {message.author.display_name}: {preview}')
        self.reply_frame.pack(fill='x', before=self.input)
        self.window.after_idle(self.layout_composer)
        self.input.focus_set()

    def clear_reply(self, force=False):
        if not force and str(self.button['state']) == 'disabled':
            return
        self.reply_id = None
        self.reply_frame.pack_forget()
        self.window.after_idle(self.layout_composer)

    def input_key(self, event):
        if event.char == '@':
            self.choose_mention(remove_at=True)

    def choose_mention(self, remove_at=False):
        if self.mention_window and self.mention_window.winfo_exists():
            self.mention_window.lift()
            return
        # Message authors and mentioned users work without the privileged Members intent.
        users = {}
        for message in self.messages.values():
            for user in [message.author, *message.mentions]:
                users[user.id] = user
        if not users:
            self.status.set('멘션할 사용자가 없습니다. 대화를 불러온 후 다시 시도하세요.')
            return
        self.input.mark_set('mention_insert', 'insert')
        self.input.mark_gravity('mention_insert', 'left')
        popup = self.mention_window = tk.Toplevel(self.window)
        popup.title('멘션 선택 · 불러온 대화의 사용자')
        popup.geometry('380x320')
        search = ttk.Entry(popup)
        search.pack(fill='x', padx=10, pady=10)
        listing = tk.Listbox(popup, exportselection=False)
        listing.pack(fill='both', expand=True, padx=10)
        def hover_user(event):
            box = listing.bbox(listing.nearest(event.y)) if listing.size() else None
            listing.configure(cursor='hand2' if box and box[1] <= event.y < box[1]+box[3] else '')
        listing.bind('<Motion>', hover_user)
        listing.bind('<Leave>', lambda event: listing.configure(cursor=''))
        rows = []

        def refresh(*_):
            query = search.get().casefold()
            rows[:] = sorted((u for u in users.values()
                              if query in f'{u.display_name} {u.name} {u.id}'.casefold()),
                             key=lambda u: (u.display_name.casefold(), u.id))
            listing.delete(0, 'end')
            for user in rows:
                listing.insert('end', f'{user.display_name} (@{user.name}) · {user.id}')
            if rows:
                listing.selection_set(0)

        def select(event=None):
            selection = listing.curselection()
            if not selection:
                return
            index = self.input.index('mention_insert')
            if remove_at and self.input.get(f'{index}-1c', index) == '@':
                self.input.delete(f'{index}-1c', index)
            self.input.mark_set('insert', 'mention_insert')
            self.insert_mention(rows[selection[0]].id)
            popup.destroy()

        search.bind('<KeyRelease>', refresh)
        search.bind('<Return>', select)
        listing.bind('<Double-Button-1>', select)
        listing.bind('<Return>', select)
        ttk.Button(popup, text='선택', command=select, cursor='hand2').pack(pady=10)
        popup.bind('<Escape>', lambda event: popup.destroy())
        refresh()
        search.focus_set()

    def insert_mention(self, user_id):
        self.input.insert('insert', f'<@{user_id}> ')
        self.input.focus_set()

    def insert_linebreak(self, event=None):
        complete_ime(self.input)
        if self.input.tag_ranges('sel'):
            self.input.mark_set('insert', 'sel.first')
            self.input.delete('sel.first', 'sel.last')
        self.input.insert('insert', '\n')
        self.input.see('insert')
        return 'break'

    def send(self, event=None):
        if str(self.button['state']) == 'disabled':
            return 'break'
        self.button.configure(state='disabled')
        complete_ime(self.input)
        self.button.focus_set()
        # Let Windows' IME result messages reach Tk before reading the text.
        self.send_job = self.window.after(30, self.send_completed_text)
        return 'break'

    def send_completed_text(self):
        self.send_job = None
        text = self.input.get('1.0', 'end-1c')
        if not text.strip():
            self.button.configure(state='normal')
            self.input.focus_set()
            return
        if len(text) > 2000:
            self.status.set('메시지는 2,000자까지 보낼 수 있습니다.')
            self.button.configure(state='normal')
            self.input.focus_set()
            return
        self.status.set('전송 중…')
        self.app.bridge.submit(self.app.bridge.send_text, self.channel_id, text,
                               self.reply_id, self.notify_reply.get(), channel_id=self.channel_id)
        return 'break'


class RoundedPanel(tk.Canvas):
    def __init__(self, parent, width=270):
        super().__init__(parent, bg='#e9eef3', highlightthickness=0, width=width)
        self.content = tk.Frame(self, bg='white')
        self.item = self.create_window(8, 8, window=self.content, anchor='nw')
        self.bind('<Configure>', self.layout)

    def layout(self, event=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.delete('panel')
        Chat.rounded(self, 0, 0, w, h, 'white', radius=12, tags='panel')
        self.tag_lower('panel')
        self.itemconfigure(self.item, width=max(1, w-16), height=max(1, h-16))


class App:
    def __init__(self, root):
        self.root = root
        root.option_add('*Button.cursor', 'hand2')
        root.title('채널 메모')
        root.geometry('1100x780')
        root.minsize(900, 600)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.events = queue.Queue()
        self.bridge = None
        self.pending_token = None
        self.chats = {}
        self.servers, self.channels = [], []
        self.active_chat = None
        self.server_id = None
        self.server_name = ''
        self.connected = False
        self.sidebar_visible = True
        root.configure(bg='#e9eef3')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Rooms.Treeview', background='white', fieldbackground='white',
                        foreground='#344f60', rowheight=42, borderwidth=0, font=('맑은 고딕', 10))
        style.map('Rooms.Treeview', background=[('selected', '#def3f6')], foreground=[('selected', '#008fa5')])
        style.configure('Rooms.Treeview.Item', padding=(8, 4))
        style.layout('Rooms.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        style.layout('Rooms.Vertical.TScrollbar', [
            ('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
                ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
        style.configure('Rooms.Vertical.TScrollbar', background='#dce4eb', troughcolor='white',
                        bordercolor='white', lightcolor='#dce4eb', darkcolor='#dce4eb',
                        borderwidth=0, arrowsize=8, width=8, relief='flat')
        self.rail = tk.Frame(root, bg='#f4f7fa', width=68)
        self.rail.pack(side='left', fill='y')
        self.rail.pack_propagate(False)
        self.home_icon = tk.Canvas(self.rail, bg='#f4f7fa', height=58, highlightthickness=0, cursor='hand2', takefocus=True)
        self.home_icon.pack(fill='x', pady=(8, 4))
        self.home_image = tk.PhotoImage(file=str(Path(__file__).resolve().parent / 'assets' / 'home-32.png'))
        self.home_icon.create_image(34, 29, image=self.home_image)
        self.home_icon.bind('<Button-1>', lambda event: self.show_home())
        self.home_icon.bind('<Return>', lambda event: self.show_home())
        tk.Frame(self.rail, bg='#edf1f5', height=1).pack(fill='x', padx=12, pady=4)
        self.server_rail = tk.Canvas(self.rail, bg='#f4f7fa', highlightthickness=0, width=68)
        self.server_rail.pack(fill='both', expand=True)
        bind_canvas_pointer(self.server_rail, 'server:')
        self.server_rail.bind('<MouseWheel>', lambda event: self.server_rail.yview_scroll(-int(event.delta/120), 'units'))
        self.refresh_area = tk.Frame(self.rail, bg='#f4f7fa')
        self.refresh_area.pack(side='bottom', fill='x', before=self.server_rail)
        tk.Frame(self.refresh_area, bg='#dce4eb', height=1).pack(fill='x', padx=12)
        self.refresh_icon = tk.Canvas(self.refresh_area, bg='#f4f7fa', height=54, highlightthickness=0, cursor='hand2', takefocus=True)
        self.refresh_icon.pack(fill='x')
        self.refresh_image = tk.PhotoImage(file=str(Path(__file__).resolve().parent / 'assets' / 'refresh-24.png'))
        self.refresh_icon.create_image(34, 27, image=self.refresh_image)
        self.refresh_icon.bind('<Button-1>', lambda event: self.refresh())
        self.refresh_icon.bind('<Return>', lambda event: self.refresh())
        tk.Frame(root, bg='#dce4eb', width=1).pack(side='left', fill='y')
        self.body = tk.Frame(root, bg='#e9eef3')
        self.body.pack(side='left', fill='both', expand=True)
        self.auth_page = tk.Frame(self.body, bg='#e9eef3')
        auth_card = tk.Canvas(self.auth_page, bg='#e9eef3', highlightthickness=0, width=460)
        auth_card.place(relx=.5, rely=.48, anchor='center')
        card = tk.Frame(auth_card, bg='white', padx=12, pady=6)
        auth_card.create_window(24, 24, window=card, anchor='nw', width=412)
        def size_card(event=None):
            height = card.winfo_reqheight() + 48
            auth_card.configure(height=height)
            auth_card.delete('background')
            Chat.rounded(auth_card, 0, 0, 460, height, 'white', radius=22, tags='background')
            auth_card.tag_lower('background')
        card.bind('<Configure>', size_card)
        tk.Label(card, text='채널 메모', bg='white', fg='#00a6bd', font=('맑은 고딕', 24, 'bold')).pack(anchor='w')
        tk.Label(card, text='봇 계정으로 대화를 시작하세요.', bg='white', fg='#7c8995', font=('맑은 고딕', 11)).pack(anchor='w', pady=(8, 28))
        tk.Label(card, text='봇 토큰', bg='white', fg='#344f60', font=('맑은 고딕', 10, 'bold')).pack(anchor='w')
        self.token = tk.Entry(card, show='*', font=('맑은 고딕', 12), bg='#f4f7f9', relief='flat', highlightthickness=1, highlightbackground='#dce5eb', highlightcolor='#00a6bd')
        token_warning = ''
        try:
            remembered = load_token()
        except (OSError, UnicodeError):
            remembered = ''
            token_warning = '저장된 토큰을 읽지 못했습니다. 토큰을 다시 입력하세요.'
        self.token.insert(0, remembered or os.environ.get('DISCORD_BOT_TOKEN', ''))
        self.token.pack(fill='x', ipady=10, pady=(8, 12))
        tk.Label(card, text='연결에 성공한 토큰은 이 Windows 계정으로 암호화해 기억합니다.', bg='white', fg='#8b9ba6', wraplength=380, justify='left', font=('맑은 고딕', 9)).pack(anchor='w')
        self.connect_button = tk.Button(card, text='연결하기', command=self.connect, bg='#00a6bd', fg='white', activebackground='#008fa5', activeforeground='white', relief='flat', pady=10, font=('맑은 고딕', 11, 'bold'))
        self.connect_button.pack(fill='x', pady=(22, 12))
        self.status = tk.StringVar(value=token_warning or '봇 계정으로 메시지가 전송됩니다.')
        tk.Label(card, textvariable=self.status, bg='white', fg='#718493', wraplength=380, justify='left', font=('맑은 고딕', 9)).pack(fill='x')
        self.resume_button = tk.Button(card, text='대화로 돌아가기', command=self.show_workspace, bg='white', fg='#008fa5', relief='flat', pady=8)
        self.workspace = tk.Frame(self.body, bg='white')
        self.sidebar = tk.Frame(self.workspace, bg='white', width=270)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        self.sidebar.content = self.sidebar
        side_header = tk.Frame(self.sidebar.content, bg='white')
        side_header.pack(fill='x', padx=14, pady=18)
        self.collapse_button = tk.Canvas(side_header, width=30, height=30, bg='white', highlightthickness=0, cursor='hand2', takefocus=True)
        self.collapse_button.pack(side='right')
        self.collapse_button.bind('<Button-1>', lambda event: self.toggle_sidebar())
        self.collapse_button.bind('<Return>', lambda event: self.toggle_sidebar())
        self.expand_button = tk.Canvas(self.workspace, width=34, height=38, bg='white', highlightthickness=0, cursor='hand2', takefocus=True)
        self.expand_button.bind('<Button-1>', lambda event: self.toggle_sidebar())
        self.expand_button.bind('<Return>', lambda event: self.toggle_sidebar())
        self.draw_arrow(self.collapse_button, False)
        self.draw_arrow(self.expand_button, True)
        self.sidebar_title = tk.Label(side_header, text='채널 목록', bg='white', fg='#233747', font=('맑은 고딕', 12, 'bold'), anchor='w', wraplength=155)
        self.sidebar_title.pack(side='left', fill='x', expand=True)
        tk.Frame(self.sidebar.content, bg='#edf1f5', height=1).pack(fill='x')
        listing = tk.Frame(self.sidebar.content, bg='white')
        listing.pack(fill='both', expand=True, padx=8, pady=10)
        self.room_tree = ttk.Treeview(listing, show='tree', selectmode='browse', style='Rooms.Treeview')
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.room_tree.yview, style='Rooms.Vertical.TScrollbar')
        self.room_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.room_tree.pack(side='left', fill='both', expand=True)
        self.room_tree.bind('<<TreeviewSelect>>', self.choose_room)
        self.room_font = tkfont.Font(root=root, font=style.lookup('Rooms.Treeview', 'font'))
        self.hover_room = None
        self.room_tree.tag_configure('hover', background='#f0f8fa')
        self.room_tree.bind('<Motion>', self.hover_channel)
        self.room_tree.bind('<Leave>', lambda event: self.clear_channel_hover())
        self.room_tree.bind('<Button-1>', self.click_channel)
        self.room_tree.bind('<Double-Button-1>', self.click_channel)
        self.connection_footer = tk.Frame(self.sidebar.content, bg='#f2f6f9')
        self.connection_footer.pack(fill='x')
        tk.Frame(self.connection_footer, bg='#dce4eb', height=1).pack(fill='x')
        tk.Label(self.connection_footer, textvariable=self.status, bg='#f2f6f9', fg='#718493', wraplength=230, font=('맑은 고딕', 8), justify='left', anchor='w').pack(fill='x', padx=16, pady=16)
        self.chat_host = tk.Frame(self.workspace, bg='#e9eef3')
        self.chat_host.pack(side='left', fill='both', expand=True, padx=8, pady=8)
        self.empty = tk.Frame(self.chat_host, bg='#e9eef3')
        center = tk.Frame(self.empty, bg='#e9eef3')
        center.place(relx=.5, rely=.46, anchor='center')
        tk.Label(center, text='#', bg='#e9eef3', fg='#b9cbd5', font=('맑은 고딕', 64, 'bold')).pack()
        self.empty_label = tk.Label(center, text='서버를 선택해 주세요.', bg='#e9eef3', fg='#8a9aa7', font=('맑은 고딕', 11))
        self.empty_label.pack(pady=10)
        self.show_empty()
        self.show_home()
        root.after(100, self.poll)

    def connect(self):
        token = self.token.get().strip()
        if not token:
            self.status.set('봇 토큰을 입력하세요.')
            return
        if str(self.connect_button['state']) == 'disabled':
            return
        if self.bridge and self.bridge.worker_loop and self.bridge.worker_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.bridge.close(), self.bridge.worker_loop)
        for chat in list(self.chats.values()):
            chat.close()
        # Isolate events from the previous bot when switching credentials.
        self.events = queue.Queue()
        self.connected = False
        self.server_id = None
        self.servers, self.channels = [], []
        self.room_tree.delete(*self.room_tree.get_children())
        self.server_rail.delete('all')
        self.resume_button.pack_forget()
        self.bridge = Bridge(self.events)
        self.pending_token = token
        self.connect_button.configure(state='disabled')
        self.token.delete(0, 'end')
        self.status.set('연결 중…')
        threading.Thread(target=self.bridge.run_worker, args=(token,), daemon=True).start()

    def refresh(self):
        if self.bridge:
            self.bridge.submit(self.bridge.publish_servers)
            if self.server_id is not None:
                self.bridge.submit(self.bridge.channels, self.server_id)
            if self.active_chat:
                self.bridge.submit(self.bridge.history, self.active_chat.channel_id,
                                   channel_id=self.active_chat.channel_id)

    def hide_chat(self):
        if self.active_chat:
            complete_ime(self.active_chat.input)
            self.active_chat.window.pack_forget()
            self.active_chat = None

    def show_empty(self):
        self.empty.pack(fill='both', expand=True)

    def show_home(self):
        if self.active_chat:
            complete_ime(self.active_chat.input)
        self.workspace.pack_forget()
        self.auth_page.pack(fill='both', expand=True)
        if self.connected:
            self.resume_button.pack(fill='x', pady=(8, 0))
            if not self.token.get():
                try:
                    self.token.insert(0, load_token())
                except (OSError, UnicodeError):
                    pass
        self.token.focus_set()

    def show_workspace(self):
        if not self.connected:
            self.show_home()
            return
        self.auth_page.pack_forget()
        self.workspace.pack(fill='both', expand=True)
        if self.active_chat:
            self.active_chat.input.focus_set()

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.expand_button.pack_forget()
            self.sidebar.pack(side='left', fill='y', before=self.chat_host)
        else:
            self.sidebar.pack_forget()
            self.expand_button.pack(side='left', anchor='n', padx=(6, 0), pady=20, before=self.chat_host)

    @staticmethod
    def draw_arrow(canvas, right):
        canvas.delete('all')
        direction = 'right' if right else 'left'
        canvas.arrow_image = tk.PhotoImage(master=canvas, file=str(
            Path(__file__).resolve().parent / 'assets' / f'arrow-{direction}-20.png'))
        item = canvas.create_image(int(canvas['width'])/2, int(canvas['height'])/2,
                                   image=canvas.arrow_image)
        canvas.bind('<Configure>', lambda event: canvas.coords(item, event.width/2, event.height/2))

    def show_servers(self):
        if not self.connected:
            self.show_home()
            return
        self.hide_chat()
        self.server_id = None
        self.channels = []
        self.sidebar_title.configure(text='채널 목록')
        self.room_tree.delete(*self.room_tree.get_children())
        self.empty_label.configure(text='왼쪽에서 서버를 선택해 주세요.')
        self.show_empty()
        self.render_servers()
        if not self.sidebar_visible:
            self.toggle_sidebar()
        self.show_workspace()

    def render_servers(self):
        self.server_rail.delete('all')
        for index, (sid, name) in enumerate(self.servers):
            y = 10 + index*68
            selected = sid == self.server_id
            tag = f'server:{sid}'
            Chat.rounded(self.server_rail, 10, y, 58, y+48,
                         '#00a6bd' if selected else '#edf3f6', radius=12, tags=tag)
            self.server_rail.create_text(34, y+24, text=name[:3], width=42,
                                         fill='white' if selected else '#52717d', font=('맑은 고딕', 9, 'bold'), tags=tag)
            self.server_rail.tag_bind(tag, '<Button-1>', lambda event, key=sid: self.select_server(key))
            self.server_rail.create_text(34, y+57, text=name[:6], fill='#8a9aa7', font=('맑은 고딕', 7), tags=tag)
        self.server_rail.configure(scrollregion=(0, 0, 68, len(self.servers)*68+16))
        if not self.servers:
            self.empty_label.configure(text='참여 중인 서버가 없습니다. 봇을 서버에 초대해 주세요.')
        elif self.server_id is None:
            self.empty_label.configure(text='왼쪽에서 서버를 선택해 주세요.')

    def channel_text_at(self, x, y):
        tree = self.room_tree
        row = tree.identify_row(y)
        if not row or 'text' not in tree.identify_element(x, y).lower():
            return None
        box = tree.bbox(row)
        # The native text element includes trailing blank space: measure the label.
        left = next((px for px in range(box[0], x+1)
                     if 'text' in tree.identify_element(px, y).lower()), x)
        return row if x < left + self.room_font.measure(tree.item(row, 'text')) else None

    def clear_channel_hover(self):
        if self.hover_room and self.room_tree.exists(self.hover_room):
            tags = tuple(t for t in self.room_tree.item(self.hover_room, 'tags') if t != 'hover')
            self.room_tree.item(self.hover_room, tags=tags)
        self.hover_room = None
        self.room_tree.configure(cursor='')

    def hover_channel(self, event):
        row = self.channel_text_at(event.x, event.y)
        if row != self.hover_room:
            self.clear_channel_hover()
            if row:
                tags = tuple(self.room_tree.item(row, 'tags')) + ('hover',)
                self.room_tree.item(row, tags=tags)
                self.hover_room = row
        indicator = 'indicator' in self.room_tree.identify_element(event.x, event.y).lower()
        self.room_tree.configure(cursor='hand2' if row or indicator else '')

    def click_channel(self, event):
        row = self.channel_text_at(event.x, event.y)
        indicator = 'indicator' in self.room_tree.identify_element(event.x, event.y).lower()
        if not row and not indicator:
            return 'break'

    def choose_room(self, event=None):
        selected = self.room_tree.selection()
        if not selected or not self.bridge:
            return
        kind, value = selected[0].split(':', 1)
        if kind == 's':
            self.select_server(int(value))
        elif kind == 'c':
            self.open_chat(int(value))

    def select_server(self, sid):
        if not self.connected:
            self.show_home()
            return
        if sid == self.server_id:
            if not self.sidebar_visible:
                self.toggle_sidebar()
            self.show_workspace()
            return
        self.hide_chat()
        self.server_id = sid
        self.server_name = next((name for key, name in self.servers if key == sid), '')
        self.sidebar_title.configure(text=self.server_name)
        self.render_servers()
        self.room_tree.delete(*self.room_tree.get_children())
        self.channels = []
        self.empty_label.configure(text='채널 목록을 불러오는 중입니다…')
        self.show_empty()
        if not self.sidebar_visible:
            self.toggle_sidebar()
        self.show_workspace()
        self.bridge.submit(self.bridge.channels, sid)

    def render_channels(self):
        self.room_tree.delete(*self.room_tree.get_children())
        categories = {}
        for cid, name in self.channels:
            category, separator, channel = name.rpartition(' / #')
            parent = ''
            if separator:
                if category not in categories:
                    parent = f'g:{len(categories)}'
                    categories[category] = parent
                    self.room_tree.insert('', 'end', iid=parent, text=category, open=True)
                parent = categories[category]
                label = f'# {channel}'
            else:
                label = '# ' + name.lstrip('#')
            self.room_tree.insert(parent, 'end', iid=f'c:{cid}', text=label)
        if self.active_chat and self.room_tree.exists(f'c:{self.active_chat.channel_id}'):
            self.room_tree.selection_set(f'c:{self.active_chat.channel_id}')
        elif not self.active_chat:
            self.empty_label.configure(text='채팅할 채널을 선택해 주세요.' if self.channels else '접근할 수 있는 텍스트 채널이 없습니다.')

    def open_chat(self, cid):
        if not self.bridge or cid == getattr(self.active_chat, 'channel_id', None):
            return
        name = next((name for key, name in self.channels if key == cid), None)
        if name is None:
            return
        self.hide_chat()
        self.empty.pack_forget()
        if cid not in self.chats:
            self.chats[cid] = Chat(self, cid, f'{self.server_name} · {name}')
            self.bridge.submit(self.bridge.history, cid, channel_id=cid)
        self.active_chat = self.chats[cid]
        self.active_chat.window.pack(fill='both', expand=True)
        self.active_chat.schedule_render()
        self.active_chat.input.focus_set()

    def poll(self):
        try:
            while True:
                kind, key, data = self.events.get_nowait()
                chat = self.chats.get(key)
                if kind in ('ready', 'status', 'fatal'):
                    self.status.set(f'연결됨: {data}' if kind == 'ready' else data)
                    if kind == 'ready' and self.pending_token:
                        try:
                            save_token(self.pending_token)
                        except OSError:
                            self.status.set(f'연결됨: {data} · 토큰 저장 실패 (다음 실행 시 다시 입력)')
                        finally:
                            self.pending_token = None
                    if kind == 'fatal':
                        self.connected = False
                        self.pending_token = None
                        self.connect_button.configure(state='normal')
                        self.resume_button.pack_forget()
                        self.show_home()
                    elif kind == 'ready':
                        first_connection = not self.connected
                        self.connected = True
                        self.connect_button.configure(state='normal', text='이 토큰으로 연결')
                        if first_connection:
                            self.show_servers()
                elif kind == 'servers':
                    self.servers = data
                    if self.server_id is None:
                        self.render_servers()
                    elif self.server_id not in {sid for sid, _ in data}:
                        self.show_servers()
                    else:
                        self.render_servers()
                elif kind == 'channels':
                    if self.server_id == key:
                        self.channels = data
                        self.render_channels()
                elif kind == 'error':
                    if chat:
                        chat.status.set(data)
                        chat.button.configure(state='normal')
                        if chat == self.active_chat and self.workspace.winfo_ismapped():
                            chat.input.focus_set()
                    else:
                        self.status.set(data)
                elif chat:
                    if kind == 'history':
                        for msg in data:
                            if msg.id not in chat.deleted:
                                chat.messages.setdefault(msg.id, msg)
                        chat.status.set('봇 계정으로 전송 · 최근 100개 / 화면 최대 500개')
                        chat.render()
                    elif kind == 'message':
                        if data.id not in chat.deleted:
                            chat.messages[data.id] = data
                        chat.render()
                    elif kind == 'deleted':
                        chat.deleted.add(data)
                        chat.messages.pop(data, None)
                        if chat.reply_id == data:
                            chat.clear_reply(force=True)
                            chat.status.set('답장 대상 메시지가 삭제되었습니다.')
                        chat.render()
                    elif kind == 'sent':
                        text, reply_id = data
                        if chat.input.get('1.0', 'end-1c') == text:
                            chat.input.delete('1.0', 'end')
                        chat.button.configure(state='normal')
                        if chat.reply_id == reply_id:
                            chat.clear_reply()
                        chat.status.set('전송 완료')
                        if chat == self.active_chat and self.workspace.winfo_ismapped():
                            chat.input.focus_set()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        for chat in list(self.chats.values()):
            chat.close()
        if self.bridge and self.bridge.worker_loop and self.bridge.worker_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.bridge.close(), self.bridge.worker_loop)
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
