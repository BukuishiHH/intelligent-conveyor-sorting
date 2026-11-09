"""
数据集采集: 从 MQTT 接收 base64 图片并保存到本地

报文格式(JSON):
    {"image": "<base64编码的图片>"}

保存规则:
    - 保存目录不存在时自动创建;
    - 文件按 img0.jpg、img1.jpg ... 递增命名;
    - 启动时扫描目录内已有文件, 从下一个序号继续, 不会覆盖历史数据。
"""

import base64
import queue
import threading
from pathlib import Path

import cv2
import numpy as np

from conveyor import config


class GetData():
    """
    从MQTT队列取图像报文并保存到本地目录的类
    """

    def __init__(self, mqtt_client, folder_path, image_key=config.KEY_IMAGE):
        """
        parameters:mqtt_client:Mqtt_Clt实例(需已连接并订阅图像上报主题)
                folder_path:图片保存目录, 不存在时自动创建
                image_key:报文里表示图片的键名, 默认"image"
        """
        self.mqtt_client = mqtt_client
        self.folder_path = Path(folder_path)
        self.image_key = image_key
        self.make_dir(self.folder_path)
        self.count = self.next_index()                              # 从已有文件的下一号开始, 避免覆盖
        self._stop_event = threading.Event()
        self.t_recv_data = threading.Thread(target=self.recv_data, daemon=True)
        self.t_recv_data.start()                                    # 启动接收数据的子线程

    def recv_data(self):
        """ 子线程函数: 循环从MQTT队列取报文, 解析base64图片并保存 """
        while not self._stop_event.is_set():
            try:
                message = self.mqtt_client.mqtt_queue.get(timeout=0.5)
            except queue.Empty:
                continue                                            # 队列暂无数据, 继续等待
            if not isinstance(message, dict) or self.image_key not in message:
                continue                                            # 非字典或非图像报文(如设备状态), 直接跳过
            self.save_image(message[self.image_key])

    def save_image(self, image_base64):
        """
        解码base64图片并保存到本地

        parameters:image_base64:base64编码的图片字符串

        returns:保存成功返回图片路径(Path), 失败返回None
        """
        try:
            image_data = base64.b64decode(image_base64)             # base64字符串 -> 二进制字节
            image_array = np.frombuffer(image_data, np.uint8)       # 字节 -> numpy uint8数组
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)     # 解码为BGR图片
        except Exception as e:
            print("图片解码错误: ", e)
            return None
        if image is None:                                           # 数据不是合法的图片格式
            print("图片解码失败, 已跳过该报文")
            return None

        image_path = self.folder_path / f"img{self.count}{config.IMAGE_SUFFIX}"
        try:
            ok, buffer = cv2.imencode(config.IMAGE_SUFFIX, image)    # 先编码为图片字节
            if not ok:
                print("图片编码失败, 已跳过该报文")
                return None
            # 用Path写文件而不是cv2.imwrite: Windows下cv2.imwrite不支持中文路径
            image_path.write_bytes(buffer.tobytes())
        except Exception as e:
            print("图片写入失败: ", e)
            return None
        print(f"图片{self.count}已保存: {image_path}")
        self.count += 1                                             # 序号递增, 下一张存为 img1.jpg
        return image_path

    def make_dir(self, folder_path):
        """ 文件夹不存在时就创建(含多级父目录) """
        folder_path = Path(folder_path)
        if folder_path.exists():
            print(f"{folder_path}已存在, 无需创建")
            return
        folder_path.mkdir(parents=True)
        print(f"{folder_path}已创建")

    def next_index(self):
        """ 扫描目录里已有的 img*.jpg, 返回下一个可用的序号 """
        indexes = []
        for path in self.folder_path.glob(f"img*{config.IMAGE_SUFFIX}"):
            suffix = path.stem[len("img"):]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return max(indexes) + 1 if indexes else 0

    def close(self):
        """ 停止接收线程并关闭MQTT连接 """
        self._stop_event.set()
        if self.t_recv_data.is_alive():
            self.t_recv_data.join(timeout=2)                        # 等子线程退出, 避免半写文件
        self.mqtt_client.close()
