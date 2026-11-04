"""Android adapter. Discord operations stay in chatbot_core."""
import asyncio
import json
import os
import queue
import threading

import certifi

# Set before importing aiohttp so certificate verification remains enabled.
os.environ['SSL_CERT_FILE'] = certifi.where()

from chatbot_core import Bridge, message_text, VERSION


class MobileClient:
    def __init__(self):
        self.bridge = None
        self.thread = None
        self.events = queue.Queue()
        self.state = dict(version=VERSION, connected=False, busy=False,
                          status='봇 토큰을 입력하세요.', servers=[], channels=[],
                          server_id='', channel_id='', messages=[], sent=0)
        self.messages = {}
        self.deleted = set()

    def disconnect(self):
        if self.thread and self.thread.is_alive():
            loop = self.bridge.worker_loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(self.bridge.close(), loop).result(timeout=8)
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                raise RuntimeError('이전 연결 종료 중입니다. 잠시 후 다시 시도하세요.')
        self.bridge = None
        self.thread = None
        self.state.update(connected=False, busy=False, status='연결 종료')

    def connect(self, token):
        token = token.strip()
        if not token:
            raise ValueError('봇 토큰을 입력하세요.')
        self.disconnect()
        self.events = queue.Queue()
        self.messages.clear()
        self.deleted.clear()
        self.state.update(connected=False, busy=True, status='연결 중…',
                          servers=[], channels=[], server_id='', channel_id='', messages=[])
        self.bridge = Bridge(self.events)
        self.thread = threading.Thread(target=self.bridge.run_worker, args=(token,), daemon=True)
        self.thread.start()

    def command(self, action, value='', text='', reply_id=''):
        if action == 'connect':
            self.connect(value)
            return
        if action == 'disconnect':
            self.disconnect()
            return
        if not self.bridge:
            return
        if action == 'server':
            self.state.update(server_id=str(value), channel_id='', channels=[], messages=[])
            self.messages.clear()
            self.deleted.clear()
            self.bridge.submit(self.bridge.channels, int(value))
        elif action == 'channel':
            self.state.update(channel_id=str(value), messages=[])
            self.messages.clear()
            self.deleted.clear()
            self.bridge.submit(self.bridge.history, int(value), channel_id=int(value))
        elif action == 'refresh':
            self.bridge.submit(self.bridge.publish_servers)
            if self.state['server_id']:
                self.bridge.submit(self.bridge.channels, int(self.state['server_id']))
            if self.state['channel_id']:
                cid = int(self.state['channel_id'])
                self.bridge.submit(self.bridge.history, cid, channel_id=cid)
        elif action == 'send' and self.state['channel_id'] and text.strip():
            cid = int(self.state['channel_id'])
            self.bridge.submit(self.bridge.send_text, cid, text,
                               int(reply_id) if reply_id else None, channel_id=cid)

    @staticmethod
    def row(message):
        return dict(id=str(message.id), author_id=str(message.author.id),
                    author=message.author.display_name, text=message_text(message))

    def snapshot(self):
        for _ in range(1000):
            try:
                kind, key, data = self.events.get_nowait()
            except queue.Empty:
                break
            current = str(key) == self.state['channel_id']
            if kind == 'ready':
                self.state.update(connected=True, busy=False, status=f'연결됨: {data}')
            elif kind == 'fatal':
                self.state.update(connected=False, busy=False, status=data)
            elif kind == 'status':
                self.state.update(connected=False, status=data)
            elif kind == 'error':
                self.state['status'] = data
            elif kind == 'servers':
                self.state['servers'] = [[str(i), name] for i, name in data]
                if self.state['server_id'] and self.state['server_id'] not in {str(i) for i, _ in data}:
                    self.state.update(server_id='', channel_id='', channels=[], messages=[])
                    self.messages.clear()
            elif kind == 'channels' and str(key) == self.state['server_id']:
                self.state['channels'] = [[str(i), name] for i, name in data]
                if self.state['channel_id'] and self.state['channel_id'] not in {str(i) for i, _ in data}:
                    self.state.update(channel_id='', messages=[])
                    self.messages.clear()
            elif kind == 'history' and current:
                for message in data:
                    if message.id not in self.deleted:
                        self.messages.setdefault(message.id, self.row(message))
            elif kind == 'message' and current and data.id not in self.deleted:
                self.messages[data.id] = self.row(data)
            elif kind == 'deleted' and current:
                self.deleted.add(data)
                self.messages.pop(data, None)
            elif kind == 'sent' and current:
                self.state['sent'] += 1
                self.state['status'] = '전송 완료'
            self.messages = dict(sorted(self.messages.items())[-500:])
        self.state['messages'] = list(self.messages.values())
        return json.dumps(self.state, ensure_ascii=False)


client = MobileClient()
