"""
ResNet 网络定义(ResNet-18 / ResNet-34 / ResNet-50)

结构参考 PyTorch 官方实现:
    - BasicBlock 用于 resnet18 / resnet34, Bottleneck 用于 resnet50;
    - Bottleneck 采用 ResNet v1.5 写法: 3x3 卷积承担 stride, 1x1 卷积步距为 1
      (相比原论文在 top1 上约有 0.5% 提升)。
"""

from pathlib import Path

import torch
import torch.nn as nn
from torch import Tensor

# ImageNet 预训练权重文件名, 放在 config.PRE_MODEL_DIR 下
PRETRAINED_WEIGHTS = {
    "resnet18": "resnet18-f37072fd.pth",
    "resnet34": "resnet34-333f7ec4.pth",
    "resnet50": "resnet50-19c8e357.pth",
}


class BasicBlock(nn.Module):
    """ ResNet-18 / 34 使用的基础残差块(两层 3x3 卷积) """

    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super().__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=3, stride=stride, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.relu(out)

        return out


class Bottleneck(nn.Module):
    """
    ResNet-50 使用的瓶颈残差块(1x1 -> 3x3 -> 1x1)

    注意: 原论文虚线残差结构的第一个 1x1 卷积步距为 2, 第二个 3x3 卷积步距为 1;
    这里采用 PyTorch 官方实现的 ResNet v1.5, 即第一个 1x1 步距为 1, 第二个 3x3 步距为 stride。
    """

    expansion: int = 4

    def __init__(self, inplanes, planes, stride=1, downsample=None, groups=1, base_width=64, dilation=1):
        super().__init__()
        width = int(planes * (base_width / 64.0)) * groups
        self.conv1 = nn.Conv2d(inplanes, width, kernel_size=1, stride=1, bias=False)
        self.bn1 = nn.BatchNorm2d(width)
        self.conv2 = nn.Conv2d(width, width, kernel_size=3, stride=stride, padding=dilation, bias=False)
        self.bn2 = nn.BatchNorm2d(width)
        self.conv3 = nn.Conv2d(width, planes * self.expansion, kernel_size=1, stride=1, bias=False)
        self.bn3 = nn.BatchNorm2d(planes * self.expansion)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.relu(out)

        return out


class ResNet(nn.Module):
    """ 由残差块堆叠而成的 ResNet 主干 + 全局平均池化 + 全连接分类头 """

    def __init__(self, block, layers, num_classes=1000):
        """
        parameters:block:残差块类型(BasicBlock / Bottleneck)
                layers:四个 stage 的残差块数量, 如 resnet18 为 [2, 2, 2, 2]
                num_classes:分类数, ImageNet 预训练权重对应 1000
        """
        super().__init__()

        self.inplanes = 64
        self.dilation = 1

        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512 * block.expansion, num_classes)

    def _make_layer(self, block, planes, blocks, stride=1):
        """ 堆叠 blocks 个残差块; 尺寸或通道数变化时用 1x1 卷积做 shortcut """
        downsample = None

        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = [block(self.inplanes, planes, stride, downsample)]
        self.inplanes = planes * block.expansion
        for _ in range(1, blocks):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)

    def forward(self, x: Tensor) -> Tensor:
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        x = self.fc(x)

        return x


def resnet18(num_classes=1000):
    """ ResNet-18, 权重: https://download.pytorch.org/models/resnet18-f37072fd.pth """
    return ResNet(BasicBlock, [2, 2, 2, 2], num_classes=num_classes)


def resnet34(num_classes=1000):
    """ ResNet-34, 权重: https://download.pytorch.org/models/resnet34-333f7ec4.pth """
    return ResNet(BasicBlock, [3, 4, 6, 3], num_classes=num_classes)


def resnet50(num_classes=1000):
    """ ResNet-50, 权重: https://download.pytorch.org/models/resnet50-19c8e357.pth """
    return ResNet(Bottleneck, [3, 4, 6, 3], num_classes=num_classes)


def create_resnet(arch="resnet18", num_classes=1000):
    """
    按名称创建 ResNet 模型

    parameters:arch:resnet18 / resnet34 / resnet50
                num_classes:分类数
    """
    builders = {"resnet18": resnet18, "resnet34": resnet34, "resnet50": resnet50}
    if arch not in builders:
        raise ValueError(f"不支持的 ResNet 结构: {arch}, 可选 {list(builders)}")
    return builders[arch](num_classes=num_classes)


def load_state_dict(path, map_location="cpu"):
    """ 兼容不同 torch 版本加载权重(weights_only 参数只在较新版本可用) """
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except TypeError:
        return torch.load(path, map_location=map_location)


def load_pretrained(model, weight_path):
    """
    加载 ImageNet 预训练权重

    parameters:model:ResNet 实例(类别数需与权重一致, 通常为 1000)
                weight_path:权重文件路径

    returns:加载成功返回 True; 文件不存在时打印提示并返回 False(调用方继续随机初始化)
    """
    weight_path = Path(weight_path)
    if not weight_path.is_file():
        print(f"预训练权重不存在, 使用随机初始化: {weight_path}")
        return False
    model.load_state_dict(load_state_dict(weight_path))
    print(f"已加载预训练权重: {weight_path}")
    return True


if __name__ == '__main__':
    from torchsummary import summary

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = resnet18(num_classes=3).to(device)
    print(summary(model, (3, 224, 224)))

