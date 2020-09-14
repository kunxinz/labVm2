import os
import threading
import time

def oj(*args):
    return os.path.join(*args)

def ls(*args):
    return os.listdir(*args)

def oe(path):
    return os.path.exists(path)

def kdefaultdict():

    return True

class pollExec(object):
    def __init__(self, ival, func, *args, **kws):
        self.func = func
        self.ival = ival
        self.args = args
        self.kws = kws
        self.pauseFlag = False
        self.timer = threading.Timer(interval=self.ival, function=self.f)

    def start(self):
        self.timer.start()

    def pause(self):
        self.pauseFlag = True

    def restart(self):
        self.pauseFlag = False

    def cancel(self):
        self.timer.cancel()

    def f(self):
        while self.pauseFlag:
            time.sleep(1)
        self.func(*self.args, **self.kws)
        self.timer = threading.Timer(interval=self.ival, function=self.f)
        self.timer.start()