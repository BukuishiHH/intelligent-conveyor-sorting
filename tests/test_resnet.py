""" conveyor.resnet 的单元测试 """

import torch

from conveyor.resnet import (PRETRAINED_WEIGHTS, BasicBlock, Bottleneck, ResNet,
                             create_resnet, load_pretrained, load_state_dict,
                             resnet18, resnet34, resnet50)


def test_block_expansion():
    assert BasicBlock.expansion == 1
    assert Bottleneck.expansion == 4


def test_bottleneck_v15_stride():
    """ ResNet v1.5: 1x1 卷积不做下采样, stride 由 3x3 卷积承担 """
    downsample = torch.nn.Sequential(
        torch.nn.Conv2d(64, 256, kernel_size=1, stride=2, bias=False),
        torch.nn.BatchNorm2d(256),
    )
    block = Bottleneck(64, 64, stride=2, downsample=downsample)

    assert block.conv1.stride == (1, 1)
    assert block.conv2.stride == (2, 2)


def test_resnet18_structure_and_forward():
    model = resnet18(num_classes=3)

    assert isinstance(model, ResNet)
    assert [len(model.layer1), len(model.layer2), len(model.layer3), len(model.layer4)] == [2, 2, 2, 2]
    assert model.fc.in_features == 512
    assert model.fc.out_features == 3

    model.eval()
    with torch.no_grad():
        output = model(torch.randn(2, 3, 64, 64))
    assert output.shape == (2, 3)


def test_resnet34_and_resnet50_forward():
    for builder, layers in ((resnet34, [3, 4, 6, 3]), (resnet50, [3, 4, 6, 3])):
        model = builder(num_classes=3)
        assert [len(model.layer1), len(model.layer2), len(model.layer3), len(model.layer4)] == layers
        model.eval()
        with torch.no_grad():
            output = model(torch.randn(1, 3, 64, 64))
        assert output.shape == (1, 3)


def test_create_resnet():
    assert isinstance(create_resnet("resnet18", num_classes=5), ResNet)
    assert create_resnet("resnet18", num_classes=5).fc.out_features == 5

    try:
        create_resnet("resnet101")
    except ValueError as exc:
        assert "resnet101" in str(exc)
    else:
        raise AssertionError("不支持的 arch 应该抛出 ValueError")


def test_pretrained_weight_names():
    assert PRETRAINED_WEIGHTS == {
        "resnet18": "resnet18-f37072fd.pth",
        "resnet34": "resnet34-333f7ec4.pth",
        "resnet50": "resnet50-19c8e357.pth",
    }


def test_load_pretrained_missing_file(tmp_path, capsys):
    model = resnet18(num_classes=3)

    loaded = load_pretrained(model, tmp_path / "not-exist.pth")

    assert loaded is False
    assert "预训练权重不存在" in capsys.readouterr().out


def test_load_pretrained_roundtrip(tmp_path):
    """ 保存 state_dict 后应能严格加载, 且参数保持一致 """
    source = resnet18(num_classes=3)
    weight_path = tmp_path / "resnet18-test.pth"
    torch.save(source.state_dict(), weight_path)

    target = resnet18(num_classes=3)
    loaded = load_pretrained(target, weight_path)

    assert loaded is True
    assert torch.equal(target.conv1.weight, source.conv1.weight)
    assert torch.equal(target.fc.weight, source.fc.weight)


def test_load_state_dict_reads_checkpoint(tmp_path):
    model = resnet18(num_classes=3)
    weight_path = tmp_path / "checkpoint.pth"
    torch.save(model.state_dict(), weight_path)

    state_dict = load_state_dict(weight_path)

    assert "conv1.weight" in state_dict
    assert state_dict["fc.weight"].shape == (3, 512)
