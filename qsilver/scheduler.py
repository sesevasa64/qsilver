import logging
from collections import deque
from .handlers import SocketHandler
from .base_handler import BaseHandler, StopObject
from .coro_proxy import CoroProxy, SendProxy, CancelProxy
from .base_scheduler import BaseScheduler, CancelCoroutine
from typing import Coroutine, Callable, Dict, List

__all__ = ('Scheduler', )

class Scheduler(BaseScheduler):
    def __init__(self):
        self.tasks: deque[CoroProxy] = deque()
        self.handlers: List[BaseHandler] = []
        self.route: Dict[StopObject, BaseHandler] = {}
        self.stopped = {}
    def add_handler(self, cls):
        handler: BaseHandler = cls(self)
        self.handlers.append(handler)
        self.route.update({handler.acceptable(): handler})
    def add_task(self, task: Callable, *args, **kwargs):
        coro = task(*args, **kwargs)
        self.add_coro(coro)
    def add_coro(self, coro: Coroutine):
        self.tasks.append(SendProxy(coro))
    def cancel_coro(self, coro: Coroutine):
        proxy = SendProxy(coro)
        r = filter(lambda p: p == proxy, self.tasks)
        try:
            self.tasks.remove(next(r))
        except StopIteration:
            obj_type, object = self.stopped[proxy]
            handler = self.route[obj_type]
            handler.cancel(proxy, object)
            self.resume(proxy)
        self.tasks.append(CancelProxy(coro))
    def add_proxy(self, proxy):
        self.tasks.append(proxy)
    def set_timeout(self, timeout):
        handler: SocketHandler = self.route[StopObject.socket]
        handler.set_timeout(timeout)
    def resume(self, task):
        self.stopped.pop(task)
    def run_forever(self):
        while any((*self.handlers, self.tasks)): # always True
            size = len(self.tasks)
            for _ in range(size):
                task: CoroProxy = self.tasks.popleft()
                task_name = task.getfullname()
                try:
                    object, obj_type = task.resume()
                    handler = self.route[obj_type]
                    handler.add_object(object, task)
                except KeyboardInterrupt:
                    raise
                except StopIteration:
                    logging.debug(f"Core: Task {task_name} is done")
                except CancelCoroutine:
                    logging.debug(f"Core: Task {task_name} canceled")
                except BaseException:
                    logging.exception(f"Core: Unhandled exception in a {task_name} coroutine")
            for handler in self.handlers:
                handler.proceed()