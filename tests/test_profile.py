""" conveyor.profile 的单元测试 """

import time

from conveyor.profile import Profile


def test_profile_measures_elapsed_time():
    """ with 块结束后 t / dt 都应大于 0, 且单次 dt 等于累计 t """
    with Profile() as profile:
        time.sleep(0.01)

    assert profile.t >= 0.01
    assert profile.dt >= 0.01
    assert profile.t == profile.dt


def test_profile_accumulates_multiple_blocks():
    """ 同一个实例重复进入 with 时耗时累加 """
    profile = Profile()
    with profile:
        time.sleep(0.005)
    first = profile.t
    with profile:
        time.sleep(0.005)

    assert profile.dt >= 0.005
    assert profile.t >= first + 0.005


def test_profile_with_initial_value():
    """ 构造时可以带入已有耗时, 便于把多段测量合并 """
    profile = Profile(t=1.5)

    with profile:
        time.sleep(0.001)

    assert profile.t >= 1.501


def test_profile_as_decorator():
    """ 作为装饰器时不影响被装饰函数的返回值与参数 """
    @Profile()
    def add(left, right=0):
        time.sleep(0.001)
        return left + right

    assert add(1, right=2) == 3
