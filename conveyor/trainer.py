"""
ResNet 训练 / 验证 / 评估流程

流程与原始示例一致:
    1. 固定随机种子, 优先使用 GPU;
    2. 训练集 RandomResizedCrop + 水平翻转 + 归一化, 验证集 Resize + 归一化;
    3. 加载 pre_model 下的 ImageNet 权重, 把 fc 换成自定义分类数;
    4. 每个 epoch 训练 + 验证, 按验证集准确率保存 best.pth, 同时保存 last.pth;
    5. 载入 best.pth 评估验证集, 输出准确率并绘制混淆矩阵。
"""

import random
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
from sklearn.metrics import confusion_matrix
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from tqdm import tqdm

from conveyor import config
from conveyor.resnet import PRETRAINED_WEIGHTS, create_resnet, load_pretrained, load_state_dict


def setup_seed(seed):
    """ 固定 Python / Numpy / PyTorch / CUDA 随机种子, 并关闭 cudnn 加速保证可复现 """
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


class ResNetTrainer():
    """ 按类别目录训练 ResNet 的类(数据来自 dataset_split/train 与 valid) """

    def __init__(self, data_root=config.DATASET_SPLIT_ROOT, pre_model_dir=config.PRE_MODEL_DIR,
                 model_dir=config.MODEL_DIR, arch=config.MODEL_ARCH, epochs=config.EPOCHS,
                 batch_size=config.BATCH_SIZE, valid_batch_size=config.VALID_BATCH_SIZE,
                 lr=config.LEARNING_RATE, image_size=config.IMAGE_SIZE,
                 num_workers=config.NUM_WORKERS, seed=config.SEED, device=None,
                 pretrained=True, verbose=True):
        """
        parameters:data_root:划分后的数据集根目录(其下含 train / valid)
                pre_model_dir:ImageNet 预训练权重目录
                model_dir:训练输出目录(best.pth / last.pth / confusion_matrix.png)
                arch:resnet18 / resnet34 / resnet50
                epochs:训练轮数
                batch_size:训练批大小
                valid_batch_size:验证批大小
                lr:Adam 学习率
                image_size:输入图片边长
                num_workers:DataLoader 进程数
                seed:全局随机种子
                device:训练设备, None 表示有 GPU 用 GPU, 否则用 CPU
                pretrained:是否加载 pre_model 下的 ImageNet 权重
                verbose:是否打印进度与指标
        """
        self.data_root = Path(data_root)
        self.pre_model_dir = Path(pre_model_dir)
        self.model_dir = Path(model_dir)
        self.arch = arch
        self.epochs = epochs
        self.batch_size = batch_size
        self.valid_batch_size = valid_batch_size
        self.lr = lr
        self.image_size = image_size
        self.num_workers = num_workers
        self.seed = seed
        self.pretrained = pretrained
        self.verbose = verbose
        self.device = torch.device(device) if device is not None else \
            torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.train_dataset = None
        self.valid_dataset = None
        self.train_loader = None
        self.valid_loader = None
        self.model = None
        self.criterion = None
        self.optimizer = None
        self.history = []
        self.best_path = self.model_dir / "best.pth"
        self.last_path = self.model_dir / "last.pth"
        self.confusion_matrix_path = self.model_dir / "confusion_matrix.png"

    def setup(self):
        """ 固定随机种子, 构建数据集 / DataLoader / 模型 / 损失函数与优化器 """
        setup_seed(self.seed)
        self.log(f"使用设备: {self.device}")
        self.build_datasets()
        self.build_loaders()
        self.model = self.build_model(len(self.train_dataset.classes))
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr)

    def build_transforms(self):
        """ 训练集做随机裁剪与翻转增强, 验证集只做 Resize, 均使用 ImageNet 均值方差 """
        normalize = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        train_transform = transforms.Compose([
            transforms.RandomResizedCrop(size=self.image_size),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize,
        ])
        valid_transform = transforms.Compose([
            transforms.Resize((self.image_size, self.image_size)),
            transforms.ToTensor(),
            normalize,
        ])
        return {"train": train_transform, "valid": valid_transform}

    def build_datasets(self):
        """ 用 ImageFolder 读取 train / valid, 并校验两边类别顺序一致 """
        transform = self.build_transforms()
        self.train_dataset = datasets.ImageFolder(self.data_root / "train", transform=transform["train"])
        self.valid_dataset = datasets.ImageFolder(self.data_root / "valid", transform=transform["valid"])
        if self.train_dataset.classes != self.valid_dataset.classes:
            raise ValueError(f"train 与 valid 类别不一致: {self.train_dataset.classes} != "
                             f"{self.valid_dataset.classes}")
        self.log(f"训练集: {len(self.train_dataset)} 张, 验证集: {len(self.valid_dataset)} 张, "
                 f"类别: {self.train_dataset.classes}")

    def build_loaders(self):
        """ 构建 DataLoader: 训练集打乱, 验证集保持顺序 """
        pin_memory = self.device.type == "cuda"
        self.train_loader = DataLoader(self.train_dataset, batch_size=self.batch_size, shuffle=True,
                                       num_workers=self.num_workers, pin_memory=pin_memory)
        self.valid_loader = DataLoader(self.valid_dataset, batch_size=self.valid_batch_size, shuffle=False,
                                       num_workers=self.num_workers, pin_memory=pin_memory)

    def build_model(self, num_classes):
        """ 创建 ResNet, 加载预训练权重, 并把 fc 换成当前分类数 """
        model = create_resnet(self.arch, num_classes=1000)
        loaded = False
        if self.pretrained:
            weight_path = self.pre_model_dir / PRETRAINED_WEIGHTS[self.arch]
            loaded = load_pretrained(model, weight_path)
        fc_inputs = model.fc.in_features
        model.fc = nn.Linear(fc_inputs, num_classes)
        model = model.to(self.device)
        if self.verbose:
            state = "预训练权重" if loaded else "随机初始化"
            print(f"模型: {self.arch}({state}), 分类数: {num_classes}")
        return model

    def log(self, message):
        """ verbose 为 True 时打印 """
        if self.verbose:
            print(message)

    def train_one_epoch(self, epoch):
        """ 训练一轮, 返回按样本数平均的 loss 与 accuracy """
        self.model.train()
        train_loss = 0.0
        train_acc = 0.0
        train_num = len(self.train_dataset)
        bar = tqdm(self.train_loader, file=sys.stdout, disable=not self.verbose,
                   desc=f"epoch[{epoch}/{self.epochs}]")
        for images, labels in bar:
            images = images.to(self.device, non_blocking=True)
            labels = labels.to(self.device, non_blocking=True)

            outputs = self.model(images)
            loss = self.criterion(outputs, labels)

            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

            train_loss += loss.item()
            predict_y = torch.max(outputs, dim=1)[1]
            train_acc += torch.eq(predict_y, labels).sum().item()
            if self.verbose:
                bar.set_description(f"epoch[{epoch}/{self.epochs}] train_loss:{loss.item():.3f}")
        return train_loss / train_num, train_acc / train_num

    def validate(self, epoch):
        """ 在验证集上计算 loss 与 accuracy(不更新梯度) """
        self.model.eval()
        val_loss = 0.0
        val_acc = 0.0
        val_num = len(self.valid_dataset)
        with torch.no_grad():
            bar = tqdm(self.valid_loader, file=sys.stdout, disable=not self.verbose,
                       desc=f"epoch[{epoch}/{self.epochs}] valid")
            for images, labels in bar:
                images = images.to(self.device, non_blocking=True)
                labels = labels.to(self.device, non_blocking=True)

                outputs = self.model(images)
                loss = self.criterion(outputs, labels)
                val_loss += loss.item()

                predict_y = torch.max(outputs, dim=1)[1]
                val_acc += torch.eq(predict_y, labels).sum().item()
                if self.verbose:
                    bar.set_description(f"epoch[{epoch}/{self.epochs}] val_loss:{loss.item():.3f}")
        return val_loss / val_num, val_acc / val_num

    def save_checkpoint(self, filename):
        """ 保存模型 state_dict 到 model_dir, 返回保存路径 """
        self.model_dir.mkdir(parents=True, exist_ok=True)
        path = self.model_dir / filename
        torch.save(self.model.state_dict(), path)
        return path

    def fit(self):
        """ 逐轮训练并验证, 验证准确率提升时保存 best.pth, 每轮保存 last.pth """
        most_acc = -1.0                 # 第一轮必定保存 best.pth
        self.history = []
        for epoch in range(1, self.epochs + 1):
            train_loss, train_acc = self.train_one_epoch(epoch)
            val_loss, val_acc = self.validate(epoch)
            self.log(f"epoch[{epoch}/{self.epochs}] train_loss: {train_loss:.3f}  "
                     f"train_acc: {train_acc:.3f}  val_loss: {val_loss:.3f}  val_acc: {val_acc:.3f}")

            self.history.append({
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
            })

            if val_acc > most_acc:
                most_acc = val_acc
                self.save_checkpoint("best.pth")
                self.log(f"验证准确率提升到 {val_acc:.3f}, 已保存 {self.best_path}")
            self.save_checkpoint("last.pth")
        return self.history

    def predict(self):
        """ 用当前模型对验证集推理, 返回真实标签与预测标签列表 """
        self.model.eval()
        predicted_labels = []
        true_labels = []
        with torch.no_grad():
            for images, labels in self.valid_loader:
                images = images.to(self.device)
                outputs = self.model(images)
                _, predicted = torch.max(outputs.data, 1)
                predicted_labels.extend(predicted.cpu().numpy().tolist())
                true_labels.extend(labels.cpu().numpy().tolist())
        return true_labels, predicted_labels

    def plot_confusion_matrix(self, matrix, class_names):
        """ 用 seaborn 绘制并保存混淆矩阵图片 """
        self.model_dir.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", cbar=False,
                    xticklabels=class_names, yticklabels=class_names, ax=ax)
        ax.set_xlabel("Predicted Labels")
        ax.set_ylabel("True Labels")
        ax.set_title("Confusion Matrix")
        fig.tight_layout()
        fig.savefig(self.confusion_matrix_path, dpi=150)
        plt.close(fig)
        return self.confusion_matrix_path

    def evaluate(self, load_best=True):
        """ 载入 best.pth 评估验证集, 返回准确率 / 混淆矩阵 / 标签 """
        if load_best and self.best_path.is_file():
            self.model.load_state_dict(load_state_dict(self.best_path, map_location=self.device))
            self.log(f"已载入最优模型: {self.best_path}")

        true_labels, predicted_labels = self.predict()
        total = len(true_labels)
        correct = sum(int(predicted == true) for predicted, true in zip(predicted_labels, true_labels))
        accuracy = correct / total if total else 0.0

        class_names = self.train_dataset.classes
        matrix = confusion_matrix(true_labels, predicted_labels, labels=list(range(len(class_names))))
        self.plot_confusion_matrix(matrix, class_names)
        self.log(f"验证集准确率: {accuracy * 100:.2f}%, 混淆矩阵已保存: {self.confusion_matrix_path}")
        return {
            "accuracy": accuracy,
            "confusion_matrix": matrix,
            "true_labels": true_labels,
            "predicted_labels": predicted_labels,
        }

    def run(self):
        """ 完整流程: 构建 -> 训练/验证 -> 载入最优模型评估 """
        self.setup()
        history = self.fit()
        result = self.evaluate()
        result["history"] = history
        result["best_model"] = str(self.best_path)
        result["last_model"] = str(self.last_path)
        result["confusion_matrix_path"] = str(self.confusion_matrix_path)
        return result
