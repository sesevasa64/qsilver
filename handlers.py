import time
from enum import Enum
from select import select
from queue import PriorityQueue
from .coro_proxy import CoroProxy
from concurrent.futures import Future
from .base_handler import BaseHandler, StopObject
from .base_scheduler import BaseScheduler
from typing import List

__all__ = (
    'SocketEvent', 'SocketProxy', 'SocketHandler',
    'FutureHandler', 'SleepHandler', 'WindowsInputHandler'
)

BUFFER_SIZE = 256

class SocketEvent(Enum):
    recv = 0
    send = 1

class SocketProxy:
    def __init__(self, socket, event):
        self.socket = socket
        self.event = event

class SocketHandler(BaseHandler):
    def __init__(self, sched: BaseScheduler):
        super().__init__(sched)
        self._select_timeout = 0.01
        self.recv_wait = {}
        self.send_wait = {}
        self.dummy = []
        self.route = {
            SocketEvent.recv: self.recv_wait,
            SocketEvent.send: self.send_wait,
        }
    def add_object(self, socket: SocketProxy, task):
        self.waiting_dict = self.route[socket.event]
        self.waiting_dict[socket.socket] = task
    def proceed(self):
        if not self:
            return time.sleep(self._select_timeout)
        can_recv, can_send, _ = select(self.recv_wait, self.send_wait, self.dummy, self._select_timeout)
        for r in can_recv:
            self.scheduler.add_proxy(self.recv_wait.pop(r))
        for s in can_send:
            self.scheduler.add_proxy(self.send_wait.pop(s))
    def __bool__(self):
        return any((self.recv_wait, self.send_wait))
    def acceptable(self):
        return StopObject.socket
    def set_timeout(self, timeout):
        self._select_timeout = timeout

class FutureHandler(BaseHandler):
    def __init__(self, sched: BaseScheduler):
        super().__init__(sched)
        self.future_wait = {}
    def add_object(self, future: Future, task):
        def future_done(future):
            task = self.future_wait.pop(future)
            self.scheduler.add_proxy(task)
        self.future_wait[future] = task
        future.add_done_callback(future_done)
    def proceed(self):
        pass
    def __bool__(self):
        return bool(self.future_wait)
    def acceptable(self):
        return StopObject.future

class SleepHandler(BaseHandler):
    def __init__(self, sched: BaseScheduler):
        super().__init__(sched)
        self.sleeping = PriorityQueue()
        self.counter = 0
    def add_object(self, deadline, task):
        self.sleeping.put_nowait((deadline, self.counter, task))
        self.counter += 1
    def proceed(self):
        for _ in range(self.sleeping.qsize()):
            deadline, _, task = self.sleeping.queue[0]
            if time.time() < deadline:
                break
            self.scheduler.add_proxy(task)
            self.sleeping.get_nowait()
    def __bool__(self):
        return not self.sleeping.empty()
    def acceptable(self):
        return StopObject.sleep
    def cancel(self, proxy: CoroProxy):
        sleeping_queue: List = self.sleeping.queue
        r = filter(lambda i: i[2] == proxy, sleeping_queue)
        try:
            sleeping_queue.remove(next(r))
        except StopIteration:
            pass

class WindowsInputHandler(BaseHandler):
    def __init__(self, sched: BaseScheduler):
        super().__init__(sched)
        self.waiting = []
    def add_object(self, handler, task):
        self.waiting.append((handler, task))
    def proceed(self):
        for handle, task in self.waiting:
            res = handle.PeekConsoleInput(15)
            if len(res) == 0:
                break
            entry = res[0]
            # Console is in focus
            if entry.EventType == 16:
                handle.ReadConsoleInput(1)
            # User press/release key
            elif entry.EventType == 1:
                # Skip pressing key
                if entry.KeyDown != True or ord(entry.Char) == 0:
                    handle.ReadConsoleInput(1)
                    continue
                self.scheduler.add_proxy(task)
                self.waiting.remove((handle, task))
    def __bool__(self):
        return bool(self.waiting)
    def acceptable(self):
        return StopObject.winput
