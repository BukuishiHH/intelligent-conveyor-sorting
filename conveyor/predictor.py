"""
单图推理: 加载训练好的 ResNet 权重, 判断单张桃子的成熟度

流程与原始示例一致:
    1. 加载 best.pth(结构与分类数可配置, 缺失时直接报错而不是随机初始化);
    2. 预处理: BGR -> RGB, Resize(image_size), ToTensor, ImageNet 均值方差归一化;
    3. 预热: 先用全零输入跑一次, 把首次推理的内存分配 / 算子加载开销排除在计时之外;
    4. 推理: eval + no_grad, softmax 后取概率最大的类别;
    5. 可视化: matplotlib 显示原图与预测类别 / 概率, 可保存为图片。

注意: 类别顺序必须与训练时 ImageFolder 的目录排序(按名称升序)一致,
项目默认取 config.DATASET_CATEGORIES, 即 half-ripe / raw / ripe。
"""

from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from torchvision import transforms

from conveyor import config
from conveyor.profile import Profile
from conveyor.resnet import create_resnet, load_state_dict


class ResNetPredictor():
    """ 用训练好的 ResNet 对单张图片做成熟度推理 """

    def __init__(self, model_path=config.PREDICT_MODEL, arch=config.MODEL_ARCH,
                 num_classes=config.NUM_CLASSES, image_size=config.IMAGE_SIZE,
                 class_names=None, device=None, result_path=config.PREDICT_RESULT,
                 verbose=True):
        """
        parameters:model_path:模型权重路径, 默认 model/best.pth
                arch:resnet18 / resnet34 / resnet50, 需与训练时一致
                num_classes:分类数, 需与权重里的 fc 输出一致
                image_size:输入图片边长, 需与训练时一致
                class_names:类别名称列表, 默认取 config.DATASET_CATEGORIES
                device:推理设备, None 表示有 GPU 用 GPU, 否则用 CPU
                result_path:可视化默认输出路径
                verbose:是否打印模型加载信息
        """
        self.model_path = Path(model_path)
        self.arch = arch
        self.num_classes = num_classes
        self.image_size = image_size
        self.class_names = list(class_names) if class_names is not None \
            else list(config.DATASET_CATEGORIES)
        if len(self.class_names) != num_classes:
            raise ValueError(f"类别名称数量与分类数不一致: {len(self.class_names)} != {num_classes}")
        self.result_path = Path(result_path)
        self.verbose = verbose
        self.device = torch.device(device) if device is not None else \
            torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.model = None
        self.load_time = 0.0                    # 最近一次加载模型的耗时(毫秒)
        self.warmed_up = False                  # 是否已完成预热
        self.transform = self.build_transform()

    def build_transform(self):
        """ 推理预处理: ToPILImage -> Resize -> ToTensor -> ImageNet 均值方差归一化 """
        normalize = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        return transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((self.image_size, self.image_size)),
            transforms.ToTensor(),
            normalize,
        ])

    def load_model(self):
        """ 创建 ResNet 并加载权重, 切换到 eval 模式; 返回模型并记录加载耗时(毫秒) """
        if not self.model_path.is_file():
            raise FileNotFoundError(f"模型文件不存在, 请先训练: {self.model_path}")
        with Profile() as profile:
            model = create_resnet(self.arch, num_classes=self.num_classes)
            model.load_state_dict(load_state_dict(self.model_path, map_location=self.device))
            model = model.to(self.device)
            model.eval()
        self.model = model
        self.load_time = profile.t * 1E3
        self.warmed_up = False
        self.log(f"已加载模型: {self.model_path}, 设备: {self.device}")
        return model

    def read_image(self, image_path):
        """
        读取图片并转换为 RGB ndarray

        用 np.fromfile + cv2.imdecode 而不是 cv2.imread:
        cv2.imread 在 Windows 中文路径下会静默返回 None。
        """
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"图片不存在: {image_path}")
        data = np.fromfile(str(image_path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"图片解码失败: {image_path}")
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def preprocess(self, image):
        """ RGB ndarray -> (1, C, H, W) 的输入张量并移到推理设备 """
        input_tensor = self.transform(image)
        return input_tensor.unsqueeze(0).to(self.device)

    def forward(self, input_batch):
        """ eval + no_grad 下前向推理, 返回 softmax 概率向量(长度为分类数) """
        with torch.no_grad():
            output = self.model(input_batch)
            return F.softmax(output[0], dim=0)

    def warmup(self):
        """ 用全零输入跑一次, 让显存分配与算子加载在正式计时前完成 """
        with torch.no_grad():
            self.model(torch.zeros(1, 3, self.image_size, self.image_size, device=self.device))
        self.warmed_up = True

    def predict(self, image_path):
        """
        对单张图片推理

        parameters:image_path:图片路径(支持中文路径)

        returns:结果字典:
                class_index:预测类别下标
                class_name:预测类别名称
                probability:该类别概率
                probabilities:所有类别概率列表
                image:推理用的 RGB 原图(便于可视化)
                input_shape:送入网络的张量形状, 如 (1, 3, 224, 224)
                timings:各阶段耗时(毫秒), 含 load / preprocess / warmup / inference
        """
        timings = {"load": 0.0, "preprocess": 0.0, "warmup": 0.0, "inference": 0.0}
        if self.model is None:
            self.load_model()
            timings["load"] = self.load_time

        with Profile() as preprocess:
            image = self.read_image(image_path)
            input_batch = self.preprocess(image)
        timings["preprocess"] = preprocess.t * 1E3

        if not self.warmed_up:                  # 只预热一次, 后续推理不再重复
            with Profile() as warmup:
                self.warmup()
            timings["warmup"] = warmup.t * 1E3

        with Profile() as inference:
            probabilities = self.forward(input_batch)
        timings["inference"] = inference.t * 1E3

        probability, predicted_index = torch.max(probabilities, dim=0)
        index = int(predicted_index.item())
        return {
            "class_index": index,
            "class_name": self.class_names[index],
            "probability": float(probability.item()),
            "probabilities": probabilities.cpu().tolist(),
            "image": image,
            "input_shape": tuple(input_batch.shape),
            "timings": timings,
        }

    def save_visualization(self, image, result, save_path=None, show=False):
        """
        用 matplotlib 绘制原图与预测结果

        parameters:image:RGB ndarray(predict 返回的 image)
                result:predict 返回的结果字典
                save_path:保存路径, 默认 self.result_path
                show:是否弹窗显示(无界面环境下保持 False)

        returns:可视化图片的保存路径
        """
        save_path = Path(save_path) if save_path is not None else self.result_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.imshow(image)
        ax.set_title(f"Predicted class: {result['class_name']}, "
                     f"probability: {result['probability']:.4f}")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(save_path, dpi=150)
        if show:
            plt.show()
        plt.close(fig)
        return save_path

    def log(self, message):
        """ verbose 为 True 时打印 """
        if self.verbose:
            print(message)
