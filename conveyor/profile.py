"""
代码段耗时测量

用法与 YOLOv5 的 Profile 一致:
    with Profile() as profile:          # 上下文管理器, profile.t 为累计耗时(秒)
        ...
    @Profile()                          # 装饰器, 累计耗时记录在装饰器实例内部
    def work():
        ...

GPU 上 torch 的算子是异步下发的, 计时前必须先 synchronize,
否则测到的是"下发耗时"而不是"执行耗时"。
"""

import contextlib
import time

import torch


class Profile(contextlib.ContextDecorator):
    """ 测量代码段执行时间, 可累加多次; CUDA 可用时先同步再取时间戳 """

    def __init__(self, t=0.0):
        self.t = t
        self.cuda = torch.cuda.is_available()

    def __enter__(self):
        """ 进入 with 代码块前记录起始时间 """
        self.start = self.time()
        return self

    def __exit__(self, type, value, traceback):
        """ 离开 with 代码块后累加本次耗时(秒), 异常照常向上抛出 """
        self.dt = self.time() - self.start
        self.t += self.dt

    def time(self):
        """ 返回当前时间戳; CUDA 可用时先等待 GPU 上的算子全部完成 """
        if self.cuda:
            torch.cuda.synchronize()
        return time.time()
