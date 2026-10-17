"""生成 Box 定位教程：受控探针、场景裁剪、缺失守卫和可审计结论。"""
from pathlib import Path

import nbformat as nbf


def md(source):
    return nbf.v4.new_markdown_cell(source.strip())


def code(source, **metadata):
    return nbf.v4.new_code_cell(source.strip(), metadata=metadata)


def build_box_notebook():
    cells = [
        md("""# 07 · Box 定位：给相册做一个自动特写助手

照片里有戒指盒，能否自动裁出特写？双人合照怎样保留两个人的可见身体？目标不在图里时，程序该怎么办？

本册沿着 **定义目标 → 定位 → 对照标注 → 决定是否裁剪** 做实验。Box 回答“在哪里”，代码决定如何使用这个答案。
依据为 [官方 Box 文档](https://docs.typesafe.ai/go/box)、[图像输入文档](https://docs.typesafe.ai/go/images)
与[知识库 42 号](../11_知识库/jev-cookbook/42-jev-1-14/article.md)，接口于 2026-10-17 核对。

**运行状态：本版正式文件未执行新实验的真实 API。** 旧版保存的输出另存于
[历史记录](box_records/legacy-20261016.json)；它们不能替代本版新问题的运行结果。

| 实验 | 固定什么、改变什么 | 可以回答什么 |
|---|---|---|
| 受控定位 | 同一画布、同一目标，改变位置或大小 | 这些条件下的定位误差 |
| 目标缺失 | 相同画面，移除目标 | 存在性判断能否阻止误裁 |
| 戒指盒特写 | 固定图片、问题与人工参考框 | 当前样本的定位与裁剪质量 |
| 双人裁剪 | 同一合照，整体问法与分开定位 | 两种策略对两个参考框的覆盖 |
| 扩边策略 | 固定真值，构造偏紧、偏宽、错位框 | 扩边的几何收益与代价 |

图像与 Box 仍属 **dreamer-ready 实验特性**。本册提供教学探针，不宣称生产可靠性或总体准确率。"""),
        md("""## 0. 准备：先选择运行来源

环境需要 Python ≥ 3.10、typesafe-sdk ≥ 0.7.5、Pillow、nbformat 和 nbclient。
在 main 目录配置环境，缺少图像依赖时运行：

    .venv/bin/python -m pip install 'typesafe-sdk>=0.7.5' pillow nbformat nbclient

实时运行：启动 Jupyter 前设置 TYPESAFE_API_KEY，JEV_RUN_MODE 默认为 live。
密钥已保存在项目根目录 .env 时，可在 main 目录运行：

    .venv/bin/python generators/execute_box_notebook.py --mode live --env-file ../.env

执行器将 TYPESAFE_API_KEY（或本项目已有的 jev-key）读入进程环境，不执行 .env 中的命令，也不打印密钥。
离线运行：启动前设置 JEV_RUN_MODE=offline。离线数据是刻意包含错误的人工示例，只检验分析代码和控制流。
本册不会安装或升级包；缺密钥、401、400 等异常均停止实时运行，不自动换成示例答案。"""),
        code("""import hashlib
import json
import math
import os
from datetime import datetime, timezone
from importlib.metadata import version
from io import BytesIO
from pathlib import Path

from IPython.display import Image as DisplayImage, Markdown, display
from PIL import Image as PILImage, ImageDraw
from typesafe_sdk import Box, Image, Noul, RetryPolicy, SystemOneResponse, TypeSafeClient

MODE = os.environ.get("JEV_RUN_MODE", "live")
MODEL = "jev-1.14.0"
if MODE not in {"live", "offline"}:
    raise ValueError("JEV_RUN_MODE 只能是 live 或 offline")
KEY = os.environ.get("TYPESAFE_API_KEY", "")
if MODE == "live" and not KEY:
    raise RuntimeError("缺少 TYPESAFE_API_KEY；演示代码请显式设置 JEV_RUN_MODE=offline")
client = (TypeSafeClient(api_key=KEY, model=MODEL, timeout=45,
                         retry=RetryPolicy(max_retries=0)) if MODE == "live" else None)
DANGER_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
CALLS = []
print(f"来源={MODE} | 请求模型={MODEL} | SDK={version('typesafe-sdk')}")"""),
        md("""### 0.1 固定数据、问题与策略

受控图为 800×600 PNG；两个场景图沿用第六册的仓库素材。场景图是生成的照片风格素材，
不能据此推断真实相机分布的表现。图片、标注及其哈希一并固定，标签不会进入模型的 state。

IoU≥0.5、框覆盖率≥0.98、存在性阈值 0.8、confidence 阈值 0.6 和扩边 0.06 都是预先选定的教学参数。
这些阈值没有经过业务验证；先固定再运行，避免根据结果挑阈值。"""),
        code("""IOU_THRESHOLD = 0.5
COVERAGE_THRESHOLD = 0.98
MIN_VISIBLE, MIN_CONFIDENCE, PAD = 0.8, 0.6, 0.06
SIZE = (800, 600)

def locate_chapter():
    override = os.environ.get("JEV_BOX_DIR")
    if override:
        return Path(override).resolve()
    for root in (Path.cwd(), *Path.cwd().parents):
        for rel in ("", "02_核心概念", "main/02_核心概念"):
            candidate = root / rel
            if (candidate / "scenes/box_annotations.json").is_file():
                return candidate
    raise FileNotFoundError("找不到 scenes/box_annotations.json；请设置 JEV_BOX_DIR")

CHAPTER = locate_chapter()
ANNOTATIONS = json.loads((CHAPTER / "scenes/box_annotations.json").read_text())
print("参考标注版本：", ANNOTATIONS["version"])"""),
        md("""### 0.2 示例答案集中放置

下面所有小数都是人工构造的离线答案，包含“高 confidence 但框偏宽”和“目标不存在仍返回框”。
它们不是旧版实测的替代品，也没有用于评价 Jev 的能力。实时模式完全不使用这些答案。"""),
        code("""def demo_box(edges, confidence):
    return {"type": "box", "box": dict(zip(("left", "top", "right", "bottom"), edges)),
            "confidence": confidence}

def demo_response(edges, confidence, visible):
    return {"target": demo_box(edges, confidence),
            "visible": {"type": "noul", "noul": visible}}

OFFLINE = {
    "base": demo_response((.11, .27, .395, .56), .88, .96),
    "translated": demo_response((.53, .27, .825, .57), .91, .97),
    "small": demo_response((.14, .31, .39, .55), .94, .93),
    "boundary": demo_response((.71, .27, .96, .57), .55, .94),
    "absent": demo_response((.32, .20, .41, .42), .83, .12),
    "ring": demo_response((.60, .55, .91, .78), .90, .95),
    "couple": {
        "group": demo_box((.18, .26, .54, .99), .43),
        "left_person": demo_box((.19, .27, .54, .99), .66),
        "right_person": demo_box((.17, .20, .91, .99), .70),
        "left_visible": {"type": "noul", "noul": .96},
        "right_visible": {"type": "noul", "noul": .95}},
}"""),
        md("""### 0.3 统一调用，并留下来源记录

同一个请求可混用 Box 与 Noul；每个问题都读取同一个 state。返回一个低存在性概率不会取消同请求中的 Box 计算。
若想在不存在时省掉定位请求，需要另做“先 Noul、再条件调用 Box”的两阶段流程。"""),
        code("""def call(label, image, questions):
    started = datetime.now(timezone.utc).isoformat()
    if MODE == "offline":
        response = SystemOneResponse.model_validate({
            "model": "offline-demo", "answers": OFFLINE[label],
            "usage": {"input_tokens": 0, "output_tokens": 0}})
    else:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        response = client.system_one(
            state={"photo": Image(buffer.getvalue())}, questions=questions,
            extra_headers=DANGER_HEADERS)
    if set(response.answers) != set(questions):
        raise ValueError("答案 ID 与问题不一致")
    CALLS.append({"label": label, "source": MODE, "started_at_utc": started,
                  "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                  "questions": {k: q.model_dump(mode="json") for k, q in questions.items()},
                  "response": response.model_dump(mode="json")})
    return response.answers"""),
        md("""调用记录包含请求模型、实际返回模型、图像像素哈希、问题、答案和 token 用量，不包含密钥。
默认完成 **7 次业务请求、17 个问题**；不额外发送连通性请求。
离线模式同样走完整样本列表，不能把只跑一个示例当成全部验证。"""),
        md("""## 1. 理论与判分：格式、位置、完整性各自检查

Box 只需要 type 与 instructions，没有 criteria。答案中的 left/right 是图宽分数，top/bottom 是图高分数。
每个问题只返回一个矩形；格式合法不保证选对对象、框得紧或保留了整个目标。

本册内部统一用 **(left, top, right, bottom)**。像素框使用半开区间：宽=right−left、高=bottom−top。
裁剪时左上向下取整、右下向上取整，减少取整造成的切边。"""),
        code("""EDGES = ("left", "top", "right", "bottom")

def as_box(box):
    if isinstance(box, dict):
        values = tuple(box[k] for k in EDGES)
    elif isinstance(box, (tuple, list)):
        values = tuple(box)
    else:
        values = tuple(getattr(box, k) for k in EDGES)
    if len(values) != 4:
        raise ValueError("边界框必须有四条边")
    l, t, r, b = map(float, values)
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (l, t, r, b)):
        raise ValueError("边必须是 0–1 范围内的有限值")
    if not l < r or not t < b:
        raise ValueError("边界框必须有正面积")
    return l, t, r, b

def to_pixels(box, size):
    l, t, r, b = as_box(box)
    w, h = size
    return math.floor(l*w), math.floor(t*h), math.ceil(r*w), math.ceil(b*h)"""),
        md("""### IoU 与框覆盖率回答不同问题

IoU=交集面积/并集面积，偏紧和偏宽都会扣分。
框覆盖率=交集面积/参考框面积，检查裁剪框覆盖了多少参考区域。
面积比=裁剪框面积/参考框面积，帮助发现过宽裁剪。

参考框包含背景，框覆盖率不是人体或物体像素的召回率；它也不能判断“照片是否好看”。
空目标没有参考框，IoU 应记为不可用，不能给 0 或把整幅图当作真值。"""),
        code("""def area(box):
    l, t, r, b = as_box(box)
    return (r-l) * (b-t)

def intersection(a, b):
    a, b = as_box(a), as_box(b)
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(
        0, min(a[3], b[3])-max(a[1], b[1]))

def metrics(prediction, reference):
    inter = intersection(prediction, reference)
    return {"iou": inter / (area(prediction)+area(reference)-inter),
            "coverage": inter / area(reference),
            "area_ratio": area(prediction) / area(reference)}

def union_box(*boxes):
    boxes = [as_box(b) for b in boxes]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))

def padded(box, pad=PAD):
    l, t, r, b = as_box(box)
    return max(0, l-pad), max(0, t-pad), min(1, r+pad), min(1, b+pad)"""),
        md("""### 先校验尺子，再评测模型

用能手算的例子检查指标：同框 IoU=1；平移半个框宽后 IoU=1/3；
完全包含目标的宽框 coverage=1，但 IoU 会下降。这些检查不调用 API。"""),
        code("""UNIT = (.2, .2, .6, .6)
assert math.isclose(metrics(UNIT, UNIT)["iou"], 1)
assert math.isclose(metrics((.4, .2, .8, .6), UNIT)["iou"], 1/3)
wide_metrics = metrics((.1, .1, .7, .7), UNIT)
assert math.isclose(wide_metrics["coverage"], 1)
assert wide_metrics["iou"] < 1
assert to_pixels((0, 0, 1, 1), SIZE) == (0, 0, *SIZE)
print("几何与取整检查通过")"""),
        md("""### 画框时保留原图比例

红框是参考，绿框是预测，蓝框是扩边或合并后的候选裁剪。
预览只做等比缩放；模型始终接收原始测试尺寸，避免拉伸预览掩盖位置误差。"""),
        code("""def encoded(image):
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return DisplayImage(data=buffer.getvalue(), format="jpeg")

def overlay(image, reference=None, prediction=None, candidate=None):
    shown = image.copy()
    draw = ImageDraw.Draw(shown)
    for box, color in ((reference, "#e63946"), (prediction, "#16a34a"),
                       (candidate, "#2563eb")):
        if box is not None:
            l, t, r, b = to_pixels(box, image.size)
            draw.rectangle((l, t, r-1, b-1), outline=color, width=4)
    shown.thumbnail((560, 480))
    return encoded(shown)

def show_crop(image, box):
    cropped = image.crop(to_pixels(box, image.size))
    cropped.thumbnail((560, 400))
    display(encoded(cropped))

def table(rows):
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(row[k]) for k in keys) + " |" for row in rows]
    display(Markdown(chr(10).join(lines)))"""),
        md("""## 2. 受控定位：同一目标改变位置和大小

蓝色矩形为目标，红色圆形为固定干扰物。基准与平移图只改变横向位置；小目标图保持基准中心、缩小尺寸。
贴边图检查图像右边界附近的行为。标签由绘图坐标直接产生。

这些是**几何探针**。它们不能作为照片实验的对照组来归因光照、反光或语义难度，因为两类素材改变了太多因素。"""),
        code("""RECTANGLES = {
    "base": (80, 160, 320, 340),
    "translated": (420, 160, 660, 340),
    "small": (140, 205, 260, 295),
    "boundary": (560, 160, 800, 340),
    "absent": None,
}

def make_scene(rectangle):
    image = PILImage.new("RGB", SIZE, (236, 238, 242))
    draw = ImageDraw.Draw(image)
    draw.ellipse((340, 420, 420, 500), fill=(205, 75, 70))
    if rectangle is not None:
        l, t, r, b = rectangle
        draw.rectangle((l, t, r-1, b-1), fill=(48, 105, 190))
    return image

IMAGES = {name: make_scene(rect) for name, rect in RECTANGLES.items()}
REFERENCES = {name: (l/800, t/600, r/800, b/600)
              for name, rect in RECTANGLES.items() if rect is not None
              for l, t, r, b in [rect]}
display(overlay(IMAGES["base"], REFERENCES["base"]))"""),
        md("""### 2.1 问题保持不变

图片只通过 photo 字段给模型。样本名称、绘图坐标、参考框与难度描述均不发送。
这里选择颜色和形状足够明确的目标，避免把“包裹长什么样”的语义歧义混进坐标实验。"""),
        code("""RECT_QUESTIONS = {
    "visible": Noul(instructions="图片 photo 中是否有蓝色矩形？"),
    "target": Box(instructions="图片 photo 中的蓝色矩形整体。"),
}
RECT_ANSWERS = {}
for name, image in IMAGES.items():
    RECT_ANSWERS[name] = call(name, image, RECT_QUESTIONS)
    print(name, "已完成；来源=", MODE)"""),
        md("""### 2.2 先逐样本看，再汇总同一个任务

四张有目标图各计一次；不存在目标的图留给下一节。
均值只是这四个固定探针的描述统计。没有重复运行或独立样本，就不估计稳定性、准确率置信区间或因果效应。"""),
        code("""RECT_ROWS = []
for name, reference in REFERENCES.items():
    answer = RECT_ANSWERS[name]["target"]
    prediction = as_box(answer.box)
    values = metrics(prediction, reference)
    RECT_ROWS.append({"样本": name, "IoU": round(values["iou"], 3),
                     "框覆盖率": round(values["coverage"], 3),
                     "面积比": round(values["area_ratio"], 2),
                     "confidence": answer.confidence,
                     "P(存在)": RECT_ANSWERS[name]["visible"].noul})
table(RECT_ROWS)
display(overlay(IMAGES["boundary"], REFERENCES["boundary"],
                as_box(RECT_ANSWERS["boundary"]["target"].box)))"""),
        md("""### 怎样解释结果

位置改变后误差变大，只能说本次平移样本观察到变化；小目标读数更差，也不能只凭一对图推断通用的小目标规律。
若没有变化，就如实记录“这些样本未显示出差别”。下一次应增加预先固定的位置和尺度组合。

confidence 与 IoU 并列展示，不把 confidence=0.9 当成“90% 的框都正确”。
检查它能否排序错误，需要更多带标签的样本与预先定义的成功事件。"""),
        md("""## 3. 目标缺失：存在性守卫真的执行了吗

absent 与 base 的差别只有蓝色矩形被移除；红色圆形与背景相同。
这个负例的标签由生成过程保证。合照背景有人，不能拿它证明“没有第三个人”。

Box 没有“未找到”答案。下面真的执行应用分支：存在性概率低则不生成裁剪；概率足够高而 confidence 偏低则交给复核。"""),
        code("""def crop_action(visible, confidence):
    if visible < MIN_VISIBLE:
        return "skip"
    if confidence < MIN_CONFIDENCE:
        return "review"
    return "crop"

GUARD_ROWS = []
for name in ("base", "absent"):
    answers = RECT_ANSWERS[name]
    visible, box = answers["visible"].noul, answers["target"]
    action = crop_action(visible, box.confidence)
    GUARD_ROWS.append({"样本": name, "目标存在标签": name == "base",
                      "P(存在)": visible, "confidence": box.confidence,
                      "应用动作": action})
    if action == "crop":
        show_crop(IMAGES[name], as_box(box.box))
table(GUARD_ROWS)
print("负例仍返回合法框：", as_box(RECT_ANSWERS["absent"]["target"].box))"""),
        md("""### 守卫的结果也要接受检验

正确路径是 base 未被 skip，absent 被 skip；若没有触发，应报告本次失败，不改示例答案或阈值制造成功。
正例进入 review 是保守拒绝，不等于定位失败。一个正例和一个负例无法估计守卫的漏检率、误检率或线上覆盖率。

即便 Box 的 confidence 很高，存在性判断仍可低；本实验以独立标签检查动作，不能只根据两个模型分数互相认证。"""),
        md("""## 4. 戒指盒特写：先明确标注的是哪个目标

目标是**整个打开的戒指盒，包括盒盖和底座**。戒指本身是另一个任务，不能共用这个参考框。
两张场景图的像素框、标注说明、图像尺寸与 SHA-256 保存在
[box_annotations.json](scenes/box_annotations.json)。

标注为单人目视复核的教学参考，不是精确金标，误差范围未经测量。
本版在运行新问题前固定标注；若看过预测后才修标签，需记录修订并重算全部样本。"""),
        code("""def load_photo(name):
    item = ANNOTATIONS["images"][name]
    path = CHAPTER / "scenes" / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError(f"{name} 已变化；请重新核对并版本化标注")
    image = PILImage.open(path).convert("RGB")
    if list(image.size) != item["size"]:
        raise ValueError("图片尺寸与参考标注不一致")
    w, h = image.size
    references = {key: (l/w, t/h, r/w, b/h)
                  for key, target in item["targets"].items()
                  for l, t, r, b in [target["box_px"]]}
    return image, references

RING_IMAGE, RING_REF = load_photo("ring_box.jpg")
COUPLE_IMAGE, PERSON_REFS = load_photo("couple_photo.jpg")
display(overlay(RING_IMAGE, RING_REF["ring"]))"""),
        md("""### 4.1 在请求前核对参考框

红框应包含盒盖和底座。接着运行固定问题，画回绿框并裁出特写。
场景条件与受控矩形实验不同，两个任务分别报告，不混成“照片 vs 干净图”的能力排行。"""),
        code("""RING_QUESTIONS = {
    "visible": Noul(instructions="照片 photo 中是否有打开的戒指盒？"),
    "target": Box(instructions="照片 photo 中打开的戒指盒整体，包括盒盖和底座。"),
}
RING_ANSWERS = call("ring", RING_IMAGE, RING_QUESTIONS)
ring_answer = RING_ANSWERS["target"]
RING_PRED = as_box(ring_answer.box)
RING_METRICS = metrics(RING_PRED, RING_REF["ring"])
table([{"IoU": round(RING_METRICS["iou"], 3),
        "框覆盖率": round(RING_METRICS["coverage"], 3),
        "面积比": round(RING_METRICS["area_ratio"], 2),
        "confidence": ring_answer.confidence,
        "P(存在)": RING_ANSWERS["visible"].noul}])"""),
        md("""### 4.2 把读数对应回图像

框偏紧会切掉盒盖或底座；框偏宽会多带背景。
即使 IoU≥0.5，也可能不满足特写助手的“尽量完整保留”要求，因此继续检查框覆盖率。
只有离线可见的参考标签能计算这些评测指标；部署时无法直接用未知真值作守卫。"""),
        code("""display(overlay(RING_IMAGE, RING_REF["ring"], RING_PRED))
ring_action = crop_action(RING_ANSWERS["visible"].noul, ring_answer.confidence)
print("应用动作：", ring_action)
if ring_action == "crop":
    show_crop(RING_IMAGE, RING_PRED)
else:
    print("保留原图，等待复核或重新定位。")"""),
        md("""## 5. 双人裁剪：一个矩形与一个人的区别

“一问一框”规定了返回形状，并不证明矩形只能包含一个人。
要求整组人的框可能覆盖两个人，也可能遗漏或含混；要得到每人的框，官方建议分别描述可区分的目标。

在同一张图上比较：A 用一个问题找整组区域；B 分别找左、右前景人物，再在代码里取并集。
这是两个完整方案的探索比较：方案 B 多问问题，指令也更具体，不能把差异单独归因于“拆分”。"""),
        md("""### 5.1 参考范围包括鞋部

左侧人物的鞋部已经被原图底边截断，任何裁剪都恢复不了画面外的部分。
右侧人物绕到左侧的手臂也属于其可见身体，所以两人的参考框相交是正常的。
先画两个框确认范围，再计算组框的最小外包矩形。"""),
        code("""GROUP_REF = union_box(*PERSON_REFS.values())
display(overlay(COUPLE_IMAGE, PERSON_REFS["left_person"],
                PERSON_REFS["right_person"]))
print("红=左侧人物参考，绿=右侧人物参考；不是模型预测")"""),
        md("""### 5.2 固定整体与分别定位的问法

分别描述位置和衣着，避免把远处的人也纳入目标。
同请求的三个 Box 和两个 Noul 各自判断，没有“先看 group 答案再修正 left/right”的依赖关系。"""),
        code("""COUPLE_QUESTIONS = {
    "group": Box(instructions=(
        "照片 photo 中，包含长椅上并排坐着的两位前景人物全部可见身体与衣鞋的区域。")),
    "left_person": Box(instructions=(
        "照片 photo 中长椅上左侧穿花裙的前景人物，包含全部可见身体与衣鞋，不含随身包。")),
    "right_person": Box(instructions=(
        "照片 photo 中长椅上右侧穿白色上衣的前景人物，包含全部可见身体与衣鞋及其手臂。")),
    "left_visible": Noul(instructions=(
        "照片 photo 中长椅上是否有穿花裙的前景人物？")),
    "right_visible": Noul(instructions=(
        "照片 photo 中长椅上是否有穿白色上衣的前景人物？")),
}
COUPLE_ANSWERS = call("couple", COUPLE_IMAGE, COUPLE_QUESTIONS)
PERSON_PREDS = {k: as_box(COUPLE_ANSWERS[k].box) for k in PERSON_REFS}
GROUP_PRED = as_box(COUPLE_ANSWERS["group"].box)
UNION_PRED = union_box(*PERSON_PREDS.values())"""),
        md("""### 5.3 用同一把尺子比较裁剪方案

整体问法、分问并集、并集再扩边都与同一个 GROUP_REF 比较，同时报告每个参考框的覆盖率。
面积比只衡量矩形大小，不等于背景面积占比；两人的框都覆盖≥0.98 才记作本册的“框完整”事件。"""),
        code("""CROP_CANDIDATES = {
    "整体问法": GROUP_PRED,
    "分问并集": UNION_PRED,
    "并集加边": padded(UNION_PRED),
}
CROP_ROWS = []
for name, box in CROP_CANDIDATES.items():
    values = metrics(box, GROUP_REF)
    coverages = {k: metrics(box, ref)["coverage"] for k, ref in PERSON_REFS.items()}
    CROP_ROWS.append({"方案": name, "组框IoU": round(values["iou"], 3),
                     "左框覆盖率": round(coverages["left_person"], 3),
                     "右框覆盖率": round(coverages["right_person"], 3),
                     "面积比": round(values["area_ratio"], 2),
                     "两框完整": all(c >= COVERAGE_THRESHOLD for c in coverages.values())})
table(CROP_ROWS)"""),
        md("""单人的定位也值得单独检查：如果某个预测框已经包住两个人，就不能称为“精准分开定位”。
只看最终并集可能掩盖这类错误。"""),
        code("""table([{"目标": key, "IoU": round(metrics(box, PERSON_REFS[key])["iou"], 3),
        "框覆盖率": round(metrics(box, PERSON_REFS[key])["coverage"], 3),
        "confidence": COUPLE_ANSWERS[key].confidence}
       for key, box in PERSON_PREDS.items()])
for name, box in CROP_CANDIDATES.items():
    print(name)
    display(overlay(COUPLE_IMAGE, GROUP_REF, box))"""),
        md("""### 5.4 应用动作与离线评测分开看

应用只能看到存在性和 confidence：任一人物低存在性就跳过；任一定位低 confidence 就复核；
通过后才展示加边裁剪。这些分数不能保证完整性，最终效果仍应抽样审核。

并集只保证包含**两个预测框**，不保证包含真实人物。若两次都框错位置，或都切掉同一只脚，并集同样失败；
加边也可能仍然不足。下面不会根据参考标签悄悄换一个“看起来成功”的裁剪。"""),
        code("""person_actions = [
    crop_action(COUPLE_ANSWERS[side + "_visible"].noul,
                COUPLE_ANSWERS[side + "_person"].confidence)
    for side in ("left", "right")]
couple_action = ("skip" if "skip" in person_actions else
                 "review" if "review" in person_actions else "crop")
print("双人裁剪动作：", couple_action)
if couple_action == "crop":
    show_crop(COUPLE_IMAGE, padded(UNION_PRED))
else:
    print("保留原图，等待复核。")"""),
        md("""## 6. 扩边实验：测量收益，也测量代价

先把策略与模型分开：给同一个受控真值构造三个候选框——偏紧、偏宽、完全错位。
它们都是人工几何例子，没有模型调用，也不代表模型错误分布。
逐一比较扩边前后的 IoU、框覆盖率、面积比。"""),
        code("""PROPOSALS = {
    "偏紧": (.15, .30, .35, .52),
    "偏宽": (.04, .20, .46, .64),
    "错位": (.60, .10, .80, .30),
}
PADDING_ROWS = []
for name, proposal in PROPOSALS.items():
    for label, box in (("原框", proposal), ("加边", padded(proposal))):
        values = metrics(box, REFERENCES["base"])
        PADDING_ROWS.append({"候选": name, "策略": label,
                             "IoU": round(values["iou"], 3),
                             "框覆盖率": round(values["coverage"], 3),
                             "面积比": round(values["area_ratio"], 2)})
table(PADDING_ROWS)
display(overlay(IMAGES["base"], REFERENCES["base"], PROPOSALS["偏紧"],
                padded(PROPOSALS["偏紧"])))"""),
        md("""### 可由几何关系支持的结论

向外扩边不会降低参考框覆盖率，但它会增大裁剪面积，IoU 可能上升也可能下降。
偏宽框再扩只会更宽；错位框加一点边仍可能完全错过目标。
这些是矩形关系的结论，不是 Jev 的性能结论。并集也有同样的“保预测、不保真值”边界。"""),
        md("""### 6.1 再应用到本次低 confidence 样本

现在按预先固定的 0.6 阈值挑出受控实验中的低 confidence 框，实际计算扩边效果。
若没有这样的样本，明确记录策略没有在本次模型输出上触发；不能改用最低 IoU 样本来冒充 confidence 守卫。"""),
        code("""LOW_CONF_ROWS = []
for name, reference in REFERENCES.items():
    answer = RECT_ANSWERS[name]["target"]
    if answer.confidence >= MIN_CONFIDENCE:
        continue
    before, after = as_box(answer.box), padded(answer.box)
    mb, ma = metrics(before, reference), metrics(after, reference)
    LOW_CONF_ROWS.append({"样本": name, "confidence": answer.confidence,
                          "原IoU": round(mb["iou"], 3), "加边IoU": round(ma["iou"], 3),
                          "原覆盖率": round(mb["coverage"], 3),
                          "加边覆盖率": round(ma["coverage"], 3)})
if LOW_CONF_ROWS:
    table(LOW_CONF_ROWS)
else:
    print("没有低 confidence 样本；本次未检验该守卫的实际收益。")"""),
        md("""### 扩展：边缘检查需要新的实验

官方提供“裁出候选区域，再问目标是否越过左/上/右/下边缘”的 Noul 方法。
该文档有一组 36 个已知切边样本的示例，不能写成本册结果，也不能据此普遍断言四问一定更可靠。

这里没有复现边缘检查。若继续做，应固定完整与切边样本、统计误报和漏报，并记录额外请求成本；
再次送入 API 的裁图还需满足当时的最小尺寸限制。"""),
        md("""## 7. 旧结论复查：保留证据，撤回过度解释

旧输出保存于 [legacy-20261016.json](box_records/legacy-20261016.json)，其中保留旧标注和单元格文本。
记录日期来自旧正文，缺少独立执行时间戳与完整 HTTP 请求日志；它是历史输出快照，不是本次验收。

- 戒指盒第一次 IoU≈0.968，另两次为 0.935、0.958；不能写成“逐位一致”。
- 合照整体框 IoU≈0.409 是按旧参考框计算的；旧框 bottom=0.87 漏了脚部。
- 一问返回一个框不能解释为“矩形无法包含两个人”。
- 背景有人，“第三个人不存在”的标签不成立。
- 原扩边代码仅统计低 confidence 数量，没有裁剪或对照效果；当时数量为 0，不能宣称守卫已验证。
- 人工矩形和照片的目标、尺度、语义同时不同，其均值差不能归因为光照。

下面仅用旧版已保存的预测框重算参考标注变化的影响，**不会发起新请求**。"""),
        code("""LEGACY = json.loads((CHAPTER / "box_records/legacy-20261016.json").read_text())
HISTORICAL_ROWS = []
for key, photo, reference in (
    ("ring_first", "ring_box.jpg", RING_REF["ring"]),
    ("couple_group_0", "couple_photo.jpg", GROUP_REF)):
    prediction = LEGACY["saved_predictions"][key]["box"]
    old_ref = LEGACY["old_reference_ltrb"][photo]
    HISTORICAL_ROWS.append({"历史预测": key,
        "旧参考IoU": round(metrics(prediction, old_ref)["iou"], 3),
        "新参考IoU": round(metrics(prediction, reference)["iou"], 3),
        "新参考覆盖率": round(metrics(prediction, reference)["coverage"], 3)})
table(HISTORICAL_ROWS)
print("只重算历史预测；新参考仍是人工教学标注。")"""),
        md("""这段复查说明评测结果依赖目标定义与标注，不意味着“修改标注就能改善模型”。
修订标注应有原图依据并保留版本；如果修订发生在看过模型答案之后，后续需要独立复核或新留出样本。

旧版只问两次相同照片，也不足以估计服务稳定性；重复调用不是新图片样本。
本版将“同图重测”和“跨样本表现”留作两个独立扩展任务。"""),
        md("""## 8. 本次结果：由代码汇总，不写死胜负

以下数值只使用本次运行的四个受控正例、一个负例和两张场景图。
结论会标明来源；离线模式只能得到分析代码已跑通的证据。
每个场景分别报告，避免不同任务、重复请求和不同真值混成一个均值。"""),
        code("""mean_iou = sum(metrics(RECT_ANSWERS[name]["target"].box, ref)["iou"]
               for name, ref in REFERENCES.items()) / len(REFERENCES)
hits = sum(metrics(RECT_ANSWERS[name]["target"].box, ref)["iou"] >= IOU_THRESHOLD
           for name, ref in REFERENCES.items())
guard_ok = (crop_action(RECT_ANSWERS["base"]["visible"].noul,
                       RECT_ANSWERS["base"]["target"].confidence) != "skip"
            and crop_action(RECT_ANSWERS["absent"]["visible"].noul,
                            RECT_ANSWERS["absent"]["target"].confidence) == "skip")
label = "真实 API：仅本次样本" if MODE == "live" else "人工示例：不能用于评价 Jev"
display(Markdown(
    f"**来源：{label}**\\n\\n"
    f"- 受控正例 {len(RECT_ROWS)} 张：平均 IoU={mean_iou:.3f}，"
    f"IoU≥{IOU_THRESHOLD} 为 {hits}/{len(RECT_ROWS)}。\\n"
    f"- 配对存在性动作符合预设标签：{guard_ok}（仅一正一负）。\\n"
    f"- 戒指盒：IoU={RING_METRICS['iou']:.3f}，"
    f"框覆盖率={RING_METRICS['coverage']:.3f}。\\n"
    f"- 双人方案是否完整见第 5 节逐框覆盖表，不预设哪种胜出。\\n"
    f"- 低 confidence 扩边触发 {len(LOW_CONF_ROWS)} 次。"))"""),
        md("""### 2026-10-17 已归档的实测观察

本段对应[已归档的真实记录](box_records/live-20261017.json)：7 次请求、17 个问题、实际模型均为 jev-1.14.0，
无离线回退。它描述这次固定样本；重新运行时，应同时阅读上面的动态汇总。

| 检查 | 本次观察 | 能支持的解释 |
|---|---|---|
| 四张几何正例 | 平均 IoU 0.869；各图 0.779–0.937，均达到预设的 0.5 | 本次位置与尺度探针可定位，不是总体准确率 |
| 配对缺失守卫 | 正例 P(存在)=0.99；负例=0.00，动作分别为 crop/skip | 这对样本正确分流；负例仍返回了一个 Box |
| 戒指盒特写 | IoU、框覆盖率均为 0.938；confidence=0.95 | 高 confidence 未保证达到框覆盖率≥0.98 的完整性要求 |
| 双人整体问法 | 组框 IoU=0.428，预测主要覆盖左侧人物 | 当前问法遗漏右侧人物，不能归因为输出形状限制 |
| 分问并集 → 加边 | 组框 IoU 0.915 → 0.857；右框覆盖率 0.917 → 1.000；面积比 0.92 → 1.17 | 本样本以更大裁剪面积换来参考框覆盖，但 IoU 下降 |
| 实际双人裁剪动作 | 右侧人物 confidence=0.22，程序进入 review | 加边候选在离线判分中覆盖参考框，应用仍按预设策略等待复核 |
| 第 6.1 节低置信扩边 | 四张受控正例没有 confidence<0.6 的样本 | 本次未覆盖这一模型输出分支，不调整阈值制造命中 |

本次逐格核对了真实响应、指标表、画框预览与应用分支；参考框仍是教学人工标注，没有增加独立金标或统计校准证据。"""),
        md("""### 哪些结论还不能下

本册没有代表线上分布的独立测试集，没有标注者一致性测量，也没有 confidence 校准实验。
不能据此报告 Jev 的总体定位准确率、场景可靠性、confidence 正确概率或拆分问题的普遍收益。
阈值若需投入应用，应在独立开发集选定，再到未用于调参的测试集检查误裁、漏裁、背景代价与拒绝率。"""),
        md("""### 运行记录

末尾输出是机器可读记录，记录本次来源、问题、响应、参数和素材版本。
正式文件由生成器产出；离线执行器将带输出的副本写到 validation/box，不覆盖正式文件。
真实执行成功才写回正式 Notebook；报错不会回退或保存为“成功”。"""),
        code("""AUDIT = {
    "kind": "jev_box_execution_audit",
    "run_mode": MODE, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "requested_model": MODEL, "sdk_version": version("typesafe-sdk"),
    "annotation_version": ANNOTATIONS["version"],
    "annotation_sha256": hashlib.sha256(
        (CHAPTER / "scenes/box_annotations.json").read_bytes()).hexdigest(),
    "thresholds": {"iou": IOU_THRESHOLD, "coverage": COVERAGE_THRESHOLD,
                   "visible": MIN_VISIBLE, "confidence": MIN_CONFIDENCE, "pad": PAD},
    "real_calls": sum(c["source"] == "live" for c in CALLS),
    "offline_calls": sum(c["source"] == "offline" for c in CALLS),
    "results": {"controlled": RECT_ROWS, "guard": GUARD_ROWS, "crops": CROP_ROWS,
                "ring": RING_METRICS, "low_confidence_padding": LOW_CONF_ROWS},
    "calls": CALLS,
}
if client is not None:
    client.close()
print(json.dumps(AUDIT, ensure_ascii=False, indent=2))""", tags=["box-execution-audit"]),
        md("""## 带走的能力与下一步

你现在能把 Box 的归一化边转换为像素裁剪，检查 IoU、框覆盖率与面积代价；
能对不存在的目标执行守卫，并验证并集与扩边是否真正帮助当前任务。

建议先复盘第 2、3、5、6 节的表格，再换自己的固定素材。保存目标定义、参考标注和失败样本，
分别记录教学示例、历史归档与本次真实调用。对需要多目标列表或像素轮廓的任务，应另选检测或分割方案。

继续阅读：[第二章目录](README.md)、[第六章模型评测](../06_模型评测/README.md)、
[官方 Box 文档](https://docs.typesafe.ai/go/box)。"""),
    ]
    nb = nbf.v4.new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    nb.metadata["jev_cookbook"] = {
        "chapter": "box", "generated_by": "generators/build_box_notebook.py",
        "live_validation": "pending", "annotation_version": "2026-10-17-v1",
    }
    return nb


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="覆盖已有输出；历史记录需先保存")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "02_核心概念/07_box定位.ipynb"
    if destination.exists() and not args.force:
        existing = nbf.read(destination, as_version=4)
        if any(c.get("outputs") for c in existing.cells):
            parser.error("已有执行输出；请先归档，再用 --force 重新生成。")
    notebook = build_box_notebook()
    nbf.validate(notebook)
    nbf.write(notebook, destination)
    codes = [c for c in notebook.cells if c.cell_type == "code"]
    markdown_count = sum(c.cell_type == "markdown" for c in notebook.cells)
    print(f"{destination.name}: {markdown_count} md / {len(codes)} code, "
          f"最长 {max(len(c.source.splitlines()) for c in codes)} 行")
