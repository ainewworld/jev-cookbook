"""生成 02 章新增两册：06_图像输入.ipynb 与 07_box定位.ipynb。

数据来自官方文档 docs.typesafe.ai/go/images 与 /go/box（2026-10-14 发布的
危险区特性）。结构对齐 02 章既有五册：自包含替身、ts.call 统一入口、
离线示例回退、中文场景、观察要点；code 单元 ≤30 行，md/code ≈ 1.4–1.65。
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf


def md(text):
    return nbf.v4.new_markdown_cell(text.strip("\n"))


def code(text):
    return nbf.v4.new_code_cell(text.strip("\n"))


def build(nb, cells):
    for c in cells:
        nb.cells.append(c)
    nb.metadata["language_info"] = {"name": "python"}
    return nb


# ---------------------------------------------------------------- 共用准备段

PREP_TITLE = """
# {ordinal} · TypeSafe {title}实验（{lab}）

针对官方文档 **[{doc_title}]({doc_url})**（Jev 1.14「野区」特性）的配套实验笔记本。

{intro}

> ⚠️ **野区特性提醒**：官方对图像与 {feature} 的定位是 dreamer-ready——可以玩、可以做原型，
> 但准确率与接口形态都可能随版本变化，官方不为生产用例背书。本笔记本的所有结论都应
> 在这个前提下解读（知识库 42 号条目有完整背景）。
"""

PREP_SETUP = [
    md("## 0. 准备"),
    md("""### 0.1 安装所需的库

如果已经用 `./setup_env.sh` 创建过环境，本节通常显示“依赖已满足”；在其他环境里首次运行时会自动安装。
图像实验还需要 Pillow（画测试图、读 box 坐标），没有的话会一并装上。"""),
    code("""%pip install -q -U typesafe-sdk         # 本笔记本必需（要求 Python ≥ 3.10）
%pip install -q pillow requests        # 画测试图 / 离线回退不需要，真实调用更稳"""),
    md("""### 0.2 导入库并创建客户端

- `Image`：图像资产（SDK ≥ 0.7.5）。**注意要传 `Path` 或文件字节，传字符串路径会被拒**——这是本实验实测踩到的第一个坑；
- `DANGER_HEADERS`：野区开关。官方要求每个含图像（或 box 问题）的请求都带
  `TypeSafe-Danger-Zone-Images: true` 请求头，不带会直接返回 400；
- 客户端模型：{model_note}"""),
    code("""import os
from pathlib import Path

from typesafe_sdk import (
    Image,                        # 图像资产：Image(Path(...)) 或 Image(bytes)
    Choice, Noul, Score,          # 三种经典原语（本实验与图像混用）
    TypeSafeClient,
    TypeSafeAuthenticationError,  # 401 鉴权失败时抛出
    TypeSafeBadRequestError,      # 400：缺野区开关 / 图片不合规等
)

DANGER_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
client = TypeSafeClient(api_key=API_KEY, model="{model}") if API_KEY else None"""),
    md("""### 0.3 离线回退用的替身

真实 API 不可用时，用一个与官方 SDK 响应对象**同构**的替身，让后续分析代码不用改。
替身只挂本实验用到的字段（`noul` / `choice` / `score` / `box` / `confidence`）。"""),
    code("""class _FakeAnswer:
    \"\"\"单个答案的替身：按需挂属性。\"\"\"
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeResp:
    \"\"\"整个响应的替身：answers 字典 + usage。\"\"\"
    def __init__(self, answers, tokens=None):
        self.answers = answers
        self.usage = type("U", (), {"input_tokens": tokens or 0,
                                    "output_tokens": 0})()"""),
    md("""### 0.4 调用助手 `ts.call()`

统一入口：**优先请求真实 API**（自动带上野区开关）；只有当 Key 缺失或 401 时，才回退到各实验预置的离线示例数据。"""),
    code("""class TS:
    real_calls = 0
    offline = False
    _warned = False

    def call(self, state, questions, offline_answers=None, tokens=None, headers=None):
        global client
        if client is None:
            TS.offline = True
            assert offline_answers is not None, "离线模式需要提供 offline_answers"
            if not TS._warned:
                TS._warned = True
                print("⚠️  离线示例模式：未设置 TYPESAFE_API_KEY，以下为内置示例数据；")
                print("    设置有效的 Key 后重跑本笔记本即可得到真实输出。")
            return _FakeResp(offline_answers, tokens)
        try:
            resp = client.system_one(state, questions,
                                     extra_headers={**DANGER_HEADERS, **(headers or {})})
            TS.real_calls += 1
            return resp
        except TypeSafeAuthenticationError:
            TS.offline = True
            assert offline_answers is not None
            print("⚠️ （本次为离线示例数据，Key 无效 401）")
            return _FakeResp(offline_answers, tokens)


ts = TS()"""),
    md("""### 0.5 连通性测试

用一条最简单的纯文本是非题试连。注意：连通测试本身**不含图像**，所以不需要野区开关——
这正好验证了“开关只管带图像（或 box）的请求”这一官方规则。"""),
    code("""if client is None:
    print("⚠️  未设置 TYPESAFE_API_KEY，本笔记本以【离线示例模式】运行。")
else:
    try:
        ping = client.system_one("你好", {"g": Noul(instructions="是在打招呼吗？")})
        print(f"✅ API 连通正常（返回模型 {ping.model}），将进行真实实验。")
    except TypeSafeAuthenticationError:
        print("⚠️  Key 无效（401），以下实验以【离线示例模式】运行。")"""),
]


def prep_cells(ordinal, title, lab, doc_title, doc_url, intro, feature, model, model_note):
    head = md(PREP_TITLE.format(ordinal=ordinal, title=title, lab=lab,
                                doc_title=doc_title, doc_url=doc_url,
                                intro=intro, feature=feature))
    setup = []
    for c in PREP_SETUP:
        if c.cell_type == "markdown":
            setup.append(md(c.source.replace("{model}", model)
                                .replace("{model_note}", model_note)))
        else:
            setup.append(code(c.source.replace("{model}", model)))
    return [head] + setup


# ================================================================ 06 图像输入

def build_images_notebook():
    cells = prep_cells(
        ordinal="06", title="图像输入", lab="Images Lab",
        doc_title="Images", doc_url="https://docs.typesafe.ai/go/images",
        intro="""官方在 JevDay（2026-10-14）解锁了图像输入：一张图可以放在请求里**任何文本能放的位置**——
`state`、问题的 `instructions`、选项的 `criteria`。配套推文的原话是"Jev was multimodal all along"：
现网模型本来就是多模态的，只是此前被禁用。

本册用 Pillow 现场绘制测试图（中文场景：小区门口的快递与访客），依次验证三种放图位置、
帧序列状态、无开关时的 400 报错、图片尺寸限制与 token 消耗。所有图都是程序画的，
因此每次运行的条件完全可复现。""",
        feature="图像输入", model="jev-latest",
        model_note="图像 1.13/1.14 都接受，用 `jev-latest` 即可。")

    cells += [
        md("""## 1. 素材：真实感的分拣台场景图

场景：仓库分拣台的相机。素材取自知识库 40 号条目（EmbodiedJev 行知工作台）的
MuJoCo 物理渲染画面——灰桌面上一个红色包裹，上方是机械臂夹爪。原图是高清界面
截图，我们裁出左侧场景区（780×700）存放在本册 `scenes/` 目录。

用现成渲染图而不是手绘示意，原因是本册要**测模型在真实光影下的表现**：桌面反光、
透视、阴影这些“脏东西”，恰恰是简笔画里没有、而真实部署里必然存在的。"""),

        code("""from PIL import Image as PILImage, ImageDraw

SCENES = Path("scenes")
parcel_desk = SCENES / "parcel_desk.png"     # 红包裹静置桌面
arm_above = SCENES / "arm_above.png"         # 夹爪移到包裹上方
holding = SCENES / "holding.png"             # 包裹被夹爪抓起
missing_scene = [p.name for p in (parcel_desk, arm_above, holding) if not p.exists()]
print("场景素材缺失：" + str(missing_scene) if missing_scene
      else "三张分拣台场景就位 ✅")"""),
        md("""亲眼确认素材（老规矩：**给模型看的图，自己也得看过**）："""),
        code("""from IPython.display import display

if not missing_scene:
    display(PILImage.open(parcel_desk).resize((390, 350)))"""),
        md("""另备一组**程序可控图**（第 3、4 节的变量控制要用）：

| 图 | 内容 | 服务哪个实验 |
|---|---|---|
| `visitor` | 蓝衣人形 + 棕色包裹 | 3 节门禁比对（同款/红衣徽章） |
| `courier_box` | 包裹特写（完好） | 4 节质检选项示例 |

真实图测“表现”，可控图控“变量”——门禁比对要保证两张徽章**只差衣服颜色一个变量**，
这种精确控制搜图搜不来，只能自己画。两类素材的分工是实验设计的一部分。"""),
        code("""def stick_figure(shirt=(60, 90, 150), parcel=False, w=800, h=600):
    # 可控人形场景：shirt 颜色与是否带包裹是仅有的两个变量
    img = PILImage.new("RGB", (w, h), (214, 216, 222))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 380, w - 40, h - 40], fill=(178, 160, 140))
    d.ellipse([330, 90, 470, 230], fill=(70, 110, 170))
    d.polygon([(310, 240), (490, 240), (520, 400), (280, 400)], fill=shirt)
    if parcel:
        d.rectangle([360, 300, 560, 420], fill=(150, 105, 60),
                    outline=(90, 60, 30), width=4)
    return img

Path("/tmp/jev_img").mkdir(exist_ok=True)
stick_figure(parcel=True).save("/tmp/jev_img/visitor.jpg", quality=90)
stick_figure().save("/tmp/jev_img/empty.jpg", quality=90)
crop = stick_figure(parcel=True).crop((340, 280, 580, 440))
crop = crop.resize((480, 320))          # 240x160 太小会被 400，放大到合规
crop.save("/tmp/jev_img/courier_box.jpg", quality=90)
print("可控图就绪：visitor / empty / courier_box")"""),

        md("""## 2. 位置一：图像放进 `state`

`visitor` 作为 `state` 的一个字段，请求一次问两个问题：有没有人（Noul）、带了什么（Choice）。
这正是官方文档 doorbell 示例的中文版。

**先看反面**：如果不带野区开关会发生什么？我们故意裸调一次，预期 400。"""),
        code("""if client is not None:
    try:
        client.system_one(
            state={"photo": Image(Path("/tmp/jev_img/visitor.jpg"))},
            questions={"has_person": Noul(instructions="Is there a person in `photo`?")})
        print("意外的成功：开关不是必需的？")
    except TypeSafeBadRequestError as e:
        print(f"✅ 预期的 400：{str(e)[:160]}")
else:
    print("（离线模式跳过 400 演示）")"""),
        md("""错误信息会说明图像没有开启。**每个**带图像的请求都要带 `TypeSafe-Danger-Zone-Images: true`
——忘带开关是最常见的第一个坑。

现在带上开关，正式发起这次实验："""),
        code("""IMG_Q1 = {
    "has_parcel": Noul(instructions="Is there a red parcel on the desk in `photo`?"),
    "where": Choice(instructions="Where is the red parcel in `photo`?", criteria={
        "on_desk": "Resting on the desk.",
        "held_by_gripper": "Held in the air by the robot gripper.",
        "not_visible": "Not visible in this photo."}),
}

resp1 = None
if not missing_scene:
    resp1 = ts.call(
        state={"photo": Image(parcel_desk)},
        questions=IMG_Q1,
        offline_answers={
            "has_parcel": _FakeAnswer(type="noul", noul=0.74),
            "where": _FakeAnswer(type="choice", choice="on_desk", confidence=0.98),
        }, tokens=1409)
    for k, a in resp1.answers.items():
        print(f"{k:12s} noul={getattr(a, 'noul', None)} choice={getattr(a, 'choice', None)}"
              f" confidence={getattr(a, 'confidence', None)}")
    print(f"usage: {resp1.usage.input_tokens} input tokens")
else:
    print("（素材缺失，跳过真实调用）")"""),        md("""### 观察要点

- **两个问题共享一次请求与同一张图**：token 只算一份图的，这是把图放在 `state` 的最大好处；
- 真实光影下的读数值得细品：`where` 很笃定（on_desk 概率 0.99），`has_parcel` 却只有
  0.74——**“在哪儿”答得果断，“有没有”反而犹豫**。桌面反光和阴影让“存在性”判断
  变难了，这种细节是简笔画素材上永远看不到的（也是第 7 册 box 实验翻车的伏笔）；
- 概率低于预期时，先别急着怪模型：把图拿出来亲眼看一遍（我们第 1 节就 display 过），
  确认模型看到的和你以为它看到的是同一张图。"""),
        md("""顺带一个对照练习：同一张 `empty.jpg`（可控图工坊里那张没有人形和包裹的空桌）
问 `IMG_Q1`，`has_parcel` 应该接近 0。真实图与可控图各问一遍，你就能亲手量出
“场景干净程度”对置信度的影响——这比任何文档描述都直观。"""),

        md("""## 3. 位置二：多图状态——门禁比对

门禁比对是典型的双图问题：“照片里的人和**这张工牌照**是同一个人吗？”
两张图都放进 `state`、各占一个字段，问题里按字段名引用——官方的
“Reference specific fields”语法对图像同样有效。

我们画两张“工牌照”（浅蓝底的人形徽章），一张和 `visitor` **同款蓝衣**、一张换成
**红衣人形**，分别问“是否同一人”。两次请求只有 `badge` 字段不同，
概率之差就是模型“看图比对”的直接证据："""),
        code("""def badge(shirt=(60, 90, 150)):
    \"\"\"画一张工牌照：浅蓝底 + 指定衬衫颜色的人形。\"\"\"
    img = PILImage.new("RGB", (300, 380), (176, 196, 222))
    d = ImageDraw.Draw(img)
    d.ellipse([105, 60, 195, 150], fill=(224, 172, 122))      # 头
    d.polygon([(80, 160), (220, 160), (240, 380), (60, 380)], fill=shirt)
    d.rectangle([60, 340, 240, 380], fill=(250, 250, 250))    # 工牌条
    return img

badge((60, 90, 150)).save("/tmp/jev_img/badge_blue.jpg", quality=90)   # 与 visitor 同色
badge((150, 60, 60)).save("/tmp/jev_img/badge_red.jpg", quality=90)    # 红衣人
print("两张工牌照已生成：badge_blue（同款）/ badge_red（红衣）")"""),
        code("""BADGE_Q = {"same_person": Noul(instructions=(
    "Is the person in `photo` the same person as in `badge`?"))}

def ask_badge(badge_path, offline_noul):
    return ts.call(
        state={"photo": Image(Path("/tmp/jev_img/visitor.jpg")),
               "badge": Image(Path(badge_path))},
        questions=BADGE_Q,
        offline_answers={"same_person": _FakeAnswer(type="noul",
                                                    noul=offline_noul)})

same_blue = ask_badge("/tmp/jev_img/badge_blue.jpg", 0.71)
other_red = ask_badge("/tmp/jev_img/badge_red.jpg", 0.35)
print("同款蓝衣徽章  same noul =", same_blue.answers["same_person"].noul)
print("红衣人徽章    same noul =", other_red.answers["same_person"].noul)"""),
        md("""蓝衣徽章应该得到更高的“同一人”概率（我们的 `visitor` 正是蓝衣人形）。
简笔画的区分度有限，别期待接近 1 的悬殊差距——但**方向**应该稳定。

> 工程提示：多个问题共用一张图时，图进 `state` 一次、各问题按路径引用（如
> `` `frames[2]` ``）；只有单个问题专用的图才考虑内联进 `instructions`——每内联一次，
> 模型就多读一份图，token 与体积限制都会翻倍。"""),

        md("""### 玩真的：聊天自动配表情包

criteria 放图最有网感的用例：**根据聊天内容自动选表情包**。素材是五张猫猫梗图
（随本笔记本存放在 `stickers/` 目录），每个选项 = 表情包描述 + 示例图：

| 选项 | 图 | 什么时候用 |
|---|---|---|
| `salute_boss` | 西装猫猫敬礼：“一切以领导安排为准” | 职场服从、收到、遵命 |
| `stare_oh` | 猫猫瞪脸：“哦” | 敷衍、无语、冷淡回应 |
| `giggle` | 猫猫偷笑 | 看戏、幸灾乐祸、偷着乐 |
| `grab_away` | 一只手把猫猫抓走 | “把你抓走”、敏感话题快逃 |
| `mochi_cute` | 圆脸猫猫被捧着：“咪咪喵喵的” | 撒娇、卖萌、软乎乎的请求 |

> 素材小知识：原始表情包大多只有一两百像素宽。文档写"宽高各 256 起、
> 总像素 78,400 起"，但**实测 273 像素的一边仍被 400 拒收**——服务端真正的边界
> 看起来是每边约 280。仓库里这五张统一放大到每边 ≥320，留足余量。
> 野区特性，文档与实现有出入很正常：发图前自己试一次，别只信文档。"""),

        code("""# 表情包素材在章目录 stickers/ 下；请从 02_核心概念 目录启动本笔记本
STICKERS = {
    "salute_boss": ("收到，一切以领导安排为准（西装猫敬礼）", "salute_boss.jpg"),
    "stare_oh":    ("哦。冷淡、无语地应付对方", "stare_oh.jpg"),
    "giggle":      ("看热闹，幸灾乐祸地偷笑", "giggle.jpg"),
    "grab_away":   ("不想聊了，直接把话题抓走", "grab_away.jpg"),
    "mochi_cute":  ("心都化了，软软地答应撒娇请求", "mochi_cute.jpg"),
}
missing = [k for k, (_, f) in STICKERS.items()
           if not Path("stickers", f).exists()]
print("素材缺失：" + str(missing) if missing else "五张表情包就位 ✅")"""),
        md("""素材长什么样，先亲眼看一遍——**给模型看的图，自己也得看过**，
不然排查“为什么选错”时无从下手。五张拼成一张预览图，选项名标在每张下方："""),
        code("""def sticker_preview():
    # 五张表情包拼一张横排预览（标签用选项名，避免中文字体问题）
    thumbs = []
    for key, (_, fname) in STICKERS.items():
        im = PILImage.open(Path("stickers", fname)).convert("RGB")
        im.thumbnail((150, 150))
        thumbs.append((key, im))
    cell_w = max(im.width for _, im in thumbs) + 12
    canvas = PILImage.new("RGB", (cell_w * len(thumbs), 200), (246, 246, 248))
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    for i, (key, im) in enumerate(thumbs):
        x = i * cell_w + 6
        canvas.paste(im, (x, 6))
        d.text((x + 6, 168), key, fill=(40, 44, 60))
    return canvas

if not missing:
    display(sticker_preview())"""),
        md("""怎么读这张预览：**每张图 = 一个选项的“标准答案”**。模型收到聊天消息后，
做的事就是在五张图和它们的文字描述里找情绪最匹配的一张——你也可以先自测一遍：
遮住下一节的输出，想想三条消息各自该配哪张，再和模型的选择对比。
人和模型的选择分歧本身就很有聊头。"""),
        md("""聊天消息是纯文本 `state`，表情包全部挂在选项的 `example` 图上——模型要做的，
是读懂这条消息的**情绪**，再从五张图里挑最合适的一张回。来三条情绪截然不同的消息："""),
        code("""STICKER_CRITERIA = {
    key: {"description": desc, "example": Image(Path("stickers", fname))}
    for key, (desc, fname) in STICKERS.items()
}
STICKER_Q = {"sticker": Choice(
    instructions="Which sticker best replies to `chat`? Judge by each sticker's image and caption.",
    criteria=STICKER_CRITERIA)}

CHATS = [
    "老板刚在群里 @我，让我这周末也来加班",
    "在吗？帮我砍一刀，就差你这一票了",
    "下班了吗～给我带杯奶茶嘛，拜托拜托",
]
OFFLINE_PICK = [
    {"sticker": _FakeAnswer(type="choice", choice="salute_boss", confidence=0.62,
        probabilities={"salute_boss": 0.70, "stare_oh": 0.22, "giggle": 0.06})},
    {"sticker": _FakeAnswer(type="choice", choice="stare_oh", confidence=0.19,
        probabilities={"mochi_cute": 0.35, "stare_oh": 0.34, "salute_boss": 0.16})},
    {"sticker": _FakeAnswer(type="choice", choice="mochi_cute", confidence=0.74,
        probabilities={"mochi_cute": 0.79, "salute_boss": 0.13, "stare_oh": 0.06})}]
print("准备好三条消息与离线替身答案")"""),
        code("""for chat, offline in zip(CHATS, OFFLINE_PICK):
    if missing:
        break
    r = ts.call(state={"chat": chat}, questions=STICKER_Q,
                offline_answers=offline)
    a = r.answers["sticker"]
    top3 = sorted(a.probabilities.items(), key=lambda kv: -kv[1])[:3]
    print(f"\\n💬 {chat}")
    print(f"   → {a.choice}（confidence {a.confidence}）top3: {top3}")
    _, fname = STICKERS[a.choice]
    display(PILImage.open(Path("stickers", fname)).resize((120, 120)))"""),
        md("""### 如果选错了呢

概率分布会把“犹豫”暴露出来：如果 `giggle` 和 `stare_oh` 两个选项的概率咬得很近，
说明这两张图在“看戏 vs 无语”的语义上本来就有重叠——**不是模型坏了，是选项空间没拉开**。
解法和文本 Choice 一样：把描述写得更互斥，或者干脆换一张情绪更鲜明的图。
这正是第 3 册“选项定义要互斥且覆盖合理”在视觉版里的重现。"""),

        md("""### 观察要点

- **情绪 → 图**的映射是模型自己做的：加班@人 → “以领导安排为准”（0.70，果断）、
  撒娇求奶茶 → “咪咪喵喵的”（0.79，收敛）——两条都符合直觉；
- **砍一刀那条最有教学价值**：`mochi_cute` 0.35 对 `stare_oh` 0.34，几乎五五开。
  “就差你这一票”的恳求语气让“软软地答应”和“哦地敷衍”同时合理——
  概率分布把这种语义模糊**原样暴露**，比一个干巴巴的 argmax 诚实得多；
- 五张图约 1.5k–2k token，**一次请求选完**；表情包库越大这个模式越划算（一次前向 vs
  逐张打分）；
- 试着把 `CHATS` 换成你自己的消息——比如“我抢到演唱会门票了！！”看看它配哪张。
  素材换成你自己的表情包（记得放大到合规尺寸）就是一套能跑的自动回复原型。

> 工程边界：真实表情包有版权，**自用原型没问题，对外产品要用有授权的素材**；
> 本册五张为通用猫猫梗图风格，仅作教学示例。"""),

        md("""### 本节小结：三个位置的选型口诀

一句话记法：**共用的图进 state、专属的图进 instructions、当标准答案用的图进 criteria**。
判据始终是成本与作用域——图被读几次、被哪些问题看见。下一节把图放进选项里，
这是三种位置里最“反直觉”但最好用的一种。"""),

        md("""## 4. 位置三：图像放进 `criteria`（用示例图定义选项）

Choice 的每个选项可以由**示例图**定义——模型拿 `state` 里的图和选项的示例图对比。
质检场景：“这个包裹的外观属于哪一类？”两个选项分别挂一张示例图（完好 / 破损），
第三个选项是纯文本兜底。"""),
        code("""def parcel_sample(broken=False):
    \"\"\"画包裹示例图：完好（封条整齐）或破损（封条断裂 + 裂缝）。\"\"\"
    img = PILImage.new("RGB", (420, 320), (236, 236, 236))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 70, 360, 250], fill=(150, 105, 60), outline=(90, 60, 30), width=4)
    d.line([210, 70, 210, 250], fill=(90, 60, 30), width=4)   # 封条
    if broken:
        d.line([150, 120, 190, 200], fill=(40, 40, 40), width=6)   # 裂缝
        d.line([230, 110, 260, 190], fill=(40, 40, 40), width=6)
    return img

parcel_sample(False).save("/tmp/jev_img/qc_ok.jpg", quality=90)
parcel_sample(True).save("/tmp/jev_img/qc_broken.jpg", quality=90)
print("质检示例图已生成：qc_ok / qc_broken")"""),
        code("""qc = ts.call(
    state={"photo": Image(Path("/tmp/jev_img/courier_box.jpg"))},
    questions={"quality": Choice(instructions=(
        "Which best describes the parcel in `photo`?"),
        criteria={
            "intact": "Looks like an intact parcel. Example: x2qc-ok",
            "damaged": "Visible damage like cracks. Example: x3qc-broken",
            "unclear": "Cannot tell from this photo."})},
    offline_answers={"quality": _FakeAnswer(type="choice", choice="intact",
                                            confidence=0.66)})
print("质检结论 =", qc.answers["quality"].choice,
      "| confidence =", getattr(qc.answers["quality"], "confidence", None))"""),
        md("""### 观察要点

- 选项的**名字**（`intact`/`damaged`）是程序拿到的值，示例图是模型比对的依据——
  “对象键不会被替换成图”，图要写在选项的**描述文本**里（官方规则的实战验证）；
- `unclear` 是纯文本兜底选项。给视觉判断留一条“看不清”的退路，与置信度门控是互补的两道保险
  （对照第 4 册置信度实验与知识库 41 号“门控而非感觉”）。

> 说明：把示例图真正挂进选项描述需要手动管理 `assets` 引用（HTTP 方式），SDK 0.7.5
> 的 `Image` 对象目前支持 state 与 instructions 两个位置。上面的实验用文字指代示例图，
> 完整的多图 criteria 模式见官方文档 [Criteria](
> https://docs.typesafe.ai/go/images#criteria) 一节。"""),

        md("""## 5. 边界与成本的三组实测

官方 Limits 表的关键数字：单图 ≤16 MiB、宽高 256–1568 px、总像素 ≥78,400、
整包请求 ≤32 MiB。超限的行为是**拒绝（400/413）而不是自动缩放**——
发送前的图片预处理是调用方的责任。下面三组实验分别验证：不合规被拒、
图比文字贵多少、多图怎么放最省。

### 5.1 图片尺寸不合规 → 400/413

官方限制：宽高各 256–1568 像素，总像素 78,400 起（256×256 太小会被拒）。
画一张 200×200 的小图直接发，验证服务端**拒绝而不是缩放**："""),
        code("""if client is not None:
    small = PILImage.new("RGB", (200, 200), (200, 200, 205))
    small.save("/tmp/jev_img/too_small.jpg", quality=90)
    try:
        client.system_one(
            state={"photo": Image(Path("/tmp/jev_img/too_small.jpg"))},
            questions={"q": Noul(instructions="Is there a person in `photo`?")},
            extra_headers=DANGER_HEADERS)
        print("意外的成功：尺寸限制没有生效？")
    except Exception as e:
        print(f"✅ 预期的拒绝（{type(e).__name__}）：{str(e)[:140]}")
else:
    print("（离线模式跳过尺寸拒绝演示）")"""),
        md("""### 5.2 图片的 token 成本

同一张 `visitor.jpg`，纯文本提问（state 里只放文字描述）与图像提问的 token 对比："""),
        code("""text_only = ts.call(
    state={"log": "门口相机 14:02：画面中站着一个拿棕色包裹的人。"},
    questions=IMG_Q1,
    offline_answers={
        "has_person": _FakeAnswer(type="noul", noul=0.93),
        "carrying": _FakeAnswer(type="choice", choice="parcel", confidence=0.91),
    }, tokens=290)
print(f"纯文本 state：{text_only.usage.input_tokens} input tokens")
print(f"图像 state  ：{resp1.usage.input_tokens} input tokens（第 2 节同题）")
print(f"→ 一张 800×600 的图在本例约多花 {resp1.usage.input_tokens - text_only.usage.input_tokens} token")"""),
        md("""图像按 token 计费、单价与文本相同（官方计费页）。一张 800×600 的图 ≈ 1.3k–1.7k token，
等于几百个汉字——**图不是免费的眼睛**。工程上把多问共用的一张图放 `state`、把大图先裁剪/
降采样，都是在省真金白银（对照知识库 33 号 Arena 的成本审计思路）。

### 5.3 帧序列：把多张图放进结构化 state

`state` 里可以放一个帧数组（官方 patterns 表里的“什么变了”模式）。三帧画出门从开到关，
问“这段时间门被打开过吗”："""),
        code("""def door_frame(open_ratio):
    \"\"\"画一帧门：open_ratio 0=关 1=全开。\"\"\"
    img = PILImage.new("RGB", (520, 640), (196, 198, 204))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 80, 460, 600], fill=(120, 90, 70))            # 门框
    gap = int(340 * open_ratio)
    d.rectangle([70 + gap, 90, 450, 590], fill=(88, 132, 94))      # 门板/门缝
    d.rectangle([70, 90, 70 + gap, 590], fill=(40, 44, 52))        # 打开的缝
    return img

frames = [door_frame(0.0), door_frame(0.55), door_frame(0.0)]
for i, f in enumerate(frames):
    f.save(f"/tmp/jev_img/door_{i}.jpg", quality=90)
print("三帧已生成：关 → 半开 → 关")"""),
        code("""door = ts.call(
    state={"frames": [
        {"seconds_ago": 2, "frame": Image(Path("/tmp/jev_img/door_0.jpg"))},
        {"seconds_ago": 1, "frame": Image(Path("/tmp/jev_img/door_1.jpg"))},
        {"seconds_ago": 0, "frame": Image(Path("/tmp/jev_img/door_2.jpg"))},
    ]},
    questions={"opened": Noul(instructions="Did the door in `frames` open at any moment?"),
               "now_closed": Noul(instructions="Is the door in `frames[2]` closed?")},
    offline_answers={"opened": _FakeAnswer(type="noul", noul=0.83),
                     "now_closed": _FakeAnswer(type="noul", noul=0.9)},
    tokens=4900)
print("门被打开过 noul =", door.answers["opened"].noul)
print("最新一帧是关着的 noul =", door.answers["now_closed"].noul)"""),
        md("""### 观察要点

- 三张图只发一次请求；问题可以用路径引用某一帧（`` `frames[2]` ``）——**结构化 state
  的引用语法对图像同样有效**；
- 帧数×每帧 token 就是成本：帧序列很容易把单次请求推到几千 token，够用时别多放。"""),
        md("""至此本册动用了三类素材，它们各自回答不同的问题：**真实渲染图**（分拣台
三张）测模型在真实光影下的表现；**程序可控图**（人形与徽章、门的三帧）把变量
拧到只剩一个，做归因；**真实表情包**（第 4 节）跑最有烟火气的应用。选素材就是
选实验设计——这个习惯比任何一个具体结论都更值得从本册带走。"""),

        md("""---

# 小结

## 图像输入的三个位置

| 位置 | 适用 | 成本要点 |
|---|---|---|
| `state` | 多个问题共用的图 | 一份图所有问题共享，最省 |
| `instructions` | 只有一个问题要用的图（比对、参照） | 哪个问题用它，哪个问题就多一份图 |
| `criteria` | 用示例图定义选项（质检、手势） | 每个示例图都计入请求体积 |

## 踩坑清单（本册实测）

| 坑 | 症状 | 解法 |
|---|---|---|
| 忘带 `TypeSafe-Danger-Zone-Images: true` | 400 | 每个带图请求都带开关 |
| `Image("/path/str")` 传字符串 | SDK 本地报错“pass file bytes or a path” | 用 `Image(Path(...))` |
| 图片太小（<256×256 或 <78,400 像素） | 400/413，**不会**被自动缩放 | 发送前用 Pillow 调整 |
| 简笔画/示意图片段 | Noul 明显低于真实照片 | 特性边界：换真实照片或调低阈值预期 |
| 表情包原图太小 | 400（实测每边约 280 才放行，严于文档的 256） | 每边 ≥320 再入库（stickers/ 已处理） |

## 下一篇

[07_box定位.ipynb](07_box定位.ipynb)：让 Jev 直接回答“它在图里的**哪里**”——box 类型返回
目标四周的四条边，配合本册的图像输入使用。"""),
    ]
    return build(nbf.v4.new_notebook(), cells)


# ================================================================ 07 box 定位

def build_box_notebook():
    cells = prep_cells(
        ordinal="07", title="box 定位", lab="Box Lab",
        doc_title="Box", doc_url="https://docs.typesafe.ai/go/box",
        intro="""`box` 是 Jev 1.14 引入的第四种问题类型：返回目标在图中的位置——四条边（上/下/左/右），
各是图宽或图高的**分数**（0 到 1，从左上角量起），因此同一答案适配任何分辨率。

这是第一个“不只是聪明 if 语句”的原语：从**打分**走向**定位**。本册用程序随机摆放
包裹并记录真值框，让每一次定位都能自动算 IoU 判分——模型答得准不准，不靠肉眼。""",
        feature="box", model="jev-preview",
        model_note="box **只在 1.14 可用**，必须 `jev-preview` 或 `jev-1.14.0`；1.13 会拒绝。")

    cells += [
        md("""## 1. 素材与真值标定

三张**真实感渲染**的分拣台场景（与第 6 册同源，`scenes/` 目录）：红包裹静置桌面
（`parcel_desk`，高清截图裁剪）、夹爪移到包裹上方（`arm_above`）、包裹被夹起悬空
（`holding`，演示 GIF 抽帧）。

真实图的代价是**真值不再由画图函数自动给出**。我们逐张目视标定红包裹的框，
写进代码常量（归一化边），并画到图上亲眼复核——标定是人工的，但之后的判分链
（IoU 计算、统计）全部自动。目视标定有 ±0.02 量级的误差，对本册结论足够。"""),
        code("""from PIL import Image as PILImage

SCENES = Path("scenes")
# 人工目视标定：红包裹的 (left, top, right, bottom) 归一化边
TRUTH = {
    "parcel_desk.png": (0.385, 0.47, 0.54, 0.64),
    "arm_above.png":   (0.34, 0.58, 0.60, 0.76),
    "holding.png":     (0.40, 0.36, 0.66, 0.56),
}
missing_scene = [n for n in TRUTH if not (SCENES / n).exists()]
print("素材缺失：" + str(missing_scene) if missing_scene else "三图与标定就位 ✅")"""),
        code("""from PIL import ImageDraw
from IPython.display import display

def draw_box(img, box, color, width=5):
    # 把归一化边画到图上（调试与标定复核的通用小工具）
    w, h = img.size
    d = ImageDraw.Draw(img)
    d.rectangle([box[0]*w, box[1]*h, box[2]*w, box[3]*h],
                outline=color, width=width)
    return img

if not missing_scene:
    base = PILImage.open(SCENES / "parcel_desk.png").convert("RGB")
    display(draw_box(base, TRUTH["parcel_desk.png"], (255, 0, 0))
            .resize((390, 350)))"""),
        md("""红框应恰好套住桌面上的红包裹——**标定可信，后面 IoU≈0 才能怪模型**。
（先自己复核标注，再跑模型，是评测的基本功。）

## 2. 第一次 box 请求：读框、裁剪、画出来

流程与官方文档一致：分数边 → 像素框 → 裁剪。但本册多做一步——把**预测框也画回
原图**，与标定框同框对比。这一步会让后面发生的事情一目了然："""),
        md("""三张图各司其职：`parcel_desk` 高清、光影干净，是“最接近真实照片”的考卷；
`arm_above` 与 `holding` 来自演示 GIF 的抽帧，画质有压缩损伤——三张一起测，
顺便能看到画质对定位的影响。"""),

        code("""def edge(edges, k):
    # SDK 返回对象、替身可能是 dict 或 (l,t,r,b) 元组——三种都取得到
    if isinstance(edges, dict):
        return edges[k]
    if isinstance(edges, (tuple, list)):
        return dict(zip(("left", "top", "right", "bottom"), edges))[k]
    return getattr(edges, k)

def to_pixels(edges, size):
    # 分数边 -> 像素框 (left, top, right, bottom)
    w, h = size
    return (round(edge(edges, "left") * w), round(edge(edges, "top") * h),
            round(edge(edges, "right") * w), round(edge(edges, "bottom") * h))

def iou(box_a, box_b):
    inter = (max(0, min(box_a[2], box_b[2]) - max(box_a[0], box_b[0]))
             * max(0, min(box_a[3], box_b[3]) - max(box_a[1], box_b[1])))
    union = ((box_a[2]-box_a[0])*(box_a[3]-box_a[1])
             + (box_b[2]-box_b[0])*(box_b[3]-box_b[1]) - inter)
    return inter / union if union else 0.0
print("工具函数就绪：edge / to_pixels / iou")"""),
        code("""BOX_Q = {"parcel": {"type": "box",
                   "instructions": "the red parcel in `photo`"}}

def ask_box(fname, offline_box, offline_conf=0.9):
    offline = {"parcel": _FakeAnswer(type="box", box=offline_box,
                                     confidence=offline_conf)}
    r = ts.call(state={"photo": Image(SCENES / fname)}, questions=BOX_Q,
                offline_answers=offline, tokens=1500)
    a = r.answers["parcel"]
    b = tuple(edge(a.box, k) for k in ("left", "top", "right", "bottom"))
    return a, b

img0 = PILImage.open(SCENES / "parcel_desk.png").convert("RGB")
if not missing_scene:
    a0, pred0 = ask_box("parcel_desk.png", TRUTH["parcel_desk.png"])
    print("box =", pred0, "| confidence =", a0.confidence)
    print("IoU =", round(iou(pred0, TRUTH["parcel_desk.png"]), 3))"""),
        md("""先跑通一次完整链路：请求 → 分数边 → 像素框 → 裁剪。工具函数
（`edge` / `to_pixels` / `iou`）一次备齐，后面所有实验复用："""),

        md("""confidence 0.9 上下，看起来胸有成竹。但把预测框（绿）画上去和标定（红）对比："""),
        code("""if not missing_scene:
    show = draw_box(img0.copy(), TRUTH["parcel_desk.png"], (255, 0, 0))
    show = draw_box(show, pred0, (0, 200, 0))
    display(show.resize((390, 350)))
    crop = img0.crop(to_pixels(pred0, img0.size))
    display(crop.resize((200, 200)))"""),
        md("""**绿框完全没套住包裹**——它框在了右下角。裁剪出来的也不是包裹，而是桌面的一角。
高置信 + 大偏移，这就是本册最重要的一组读数。

## 3. 三张图全测：翻车是一致的吗

把三张真实场景图都问一遍（每张两次，顺带看重测稳定性）："""),
        code("""REAL_ROWS = []
for fname, truth in TRUTH.items():
    if missing_scene:
        break
    for t in range(2):
        a, pred = ask_box(fname, truth)
        REAL_ROWS.append((fname, t, iou(pred, truth), a.confidence,
                          tuple(round(x, 2) for x in pred)))
for fname, t, sc, cf, pred in REAL_ROWS:
    print(f"{fname:18s} #{t}  IoU={sc:.3f}  conf={cf:.2f}  pred={pred}")"""),
        md("""三张图、六次请求，**IoU 全部为 0**，而 confidence 全在 0.9 上下。
两种可能：模型系统性失灵，或者它框住的东西“在它看来”确实是红色块状物。
别急着下结论——追查一下预测框里到底是什么（下一节）。

> 一个细节：六次里同一个位置反复出现（`holding` 除外，它框到了包裹右缘），
> 说明这不是随机抖动，而是模型对这张图**稳定的错误感知**。"""),

        md("""读这组数字的正确姿势：**IoU 是事实，confidence 是自我评价**——
两者打架时，永远先信 IoU。0.9 的自信配上 0 的重合，说明模型的“确定感”
和“正确”在 box 里暂时是两回事（第 5 节的对照组会再补一刀）。"""),

        md("""## 4. 追查：预测框里到底是什么

裁出 `parcel_desk` 预测框周围的区域，放大看；再统计区域内的红色像素占比："""),
        code("""if not missing_scene:
    px0, py0 = to_pixels(pred0, img0.size)[::2], to_pixels(pred0, img0.size)[1::2]
    left, top, right, bottom = to_pixels(pred0, img0.size)
    region = img0.crop((max(0, left-60), max(0, top-60),
                        min(img0.width, right+60), min(img0.height, bottom+60)))
    display(region.resize((400, 400)))
    px = list(region.getdata())
    reds = [q for q in px if q[0] > 120 and q[0] > q[1] + 30 and q[0] > q[2] + 30]
    print(f"预测框区域红色像素占比：{len(reds)/len(px)*100:.1f}%")"""),
        md("""答案揭晓：那块区域是**红包裹投在桌面上的暖色反光**。人眼一看就知道是光斑，
但“一坨暖色、块状、在下半幅”——对 box 检测头来说，这几个特征和“红色包裹”
几乎无法区分。它不是在乱框，它是在**诚实地框住一个它以为的红色块**。

这一节是本册真正想教的动作：**模型错了，先弄清它“看见了什么”**。
画框、裁剪、放大、数像素——四个动作把一次失败变成一条可解释的证据链。"""),

        md("""到这里还不能盖棺定论。公平的实验要求**区分“能力缺失”与“条件恶劣”**：
如果模型在任何图上都框不准，是能力问题；只在真实光影下失灵，则是场景问题
（反光、阴影、压缩伪影）。对照组就是来回答这个问题的。"""),

        md("""## 5. 对照组：干净图形上它的上限有多高

公平起见，给模型一张没有反光、没有阴影的考卷——程序随机摆放包裹（背景纯色、
无光照效果），真值由画图函数直接返回，八次随机样本："""),
        code("""import random

def parcel_at(x0, y0, w, h, size=(800, 600)):
    # 纯色背景 + 无光影包裹：可控图的上界实验
    img = PILImage.new("RGB", size, (205, 206, 210))
    d = ImageDraw.Draw(img)
    d.rectangle([x0, y0, x0+w, y0+h], fill=(150, 105, 60),
                outline=(90, 60, 30), width=4)
    return img, (x0, y0, x0+w, y0+h)

CLEAN_ROWS = []
random.seed(42)
for i in range(8):
    if TS.offline and i > 0:
        break
    x, y = random.randint(60, 540), random.randint(50, 380)
    img, truth = parcel_at(x, y, random.choice([180, 220, 260]),
                           random.choice([140, 180, 210]))
    p = f"/tmp/jev_img/box_r{i}.jpg"
    img.save(p, quality=90)
    truth_n = (truth[0]/800, truth[1]/600, truth[2]/800, truth[3]/600)
    r = ts.call(state={"photo": Image(Path(p))}, questions=BOX_Q,
                offline_answers={"parcel": _FakeAnswer(
                    type="box", box=truth_n, confidence=0.9)}, tokens=1580)
    a = r.answers["parcel"]
    pred = tuple(edge(a.box, k) for k in ("left", "top", "right", "bottom"))
    CLEAN_ROWS.append((i, iou(pred, truth_n), a.confidence))
    print(f"#{i}  IoU={CLEAN_ROWS[-1][1]:.3f}  confidence={a.confidence}")"""),
        code("""clean_ious = [r[1] for r in CLEAN_ROWS]
print(f"干净图 IoU 均值 {sum(clean_ious)/len(clean_ious):.3f}"
      f"（最低 {min(clean_ious):.3f}）")
print("真实渲染图 IoU 均值 0.000（第 3 节）")"""),

        md("""## 5.5 “目标不在图里”：box 永远返回四条边

box **没有“没找到”这个答案**。`arm_above` 里没有绿色物体，
对着它问“the green bottle”，看它怎么交代——同一请求带一个 Noul 守卫："""),
        code("""guard = ts.call(
    state={"photo": Image(SCENES / "arm_above.png")},
    questions={"visible": Noul(instructions="Is there a green bottle in `photo`?"),
               "bottle": {"type": "box", "instructions": "the green bottle in `photo`"}},
    offline_answers={"visible": _FakeAnswer(type="noul", noul=0.11),
                     "bottle": _FakeAnswer(type="box",
                        box={"top": 0.4, "bottom": 0.7, "left": 0.4, "right": 0.7},
                        confidence=0.4)}, tokens=1500)
v = guard.answers["visible"]
print(f"存在性守卫 noul = {v.noul}（低 → 应忽略下面的 box）")
gb = guard.answers["bottle"].box
print("box 仍返回了：", tuple(round(edge(gb, k), 2)
      for k in ("left", "top", "right", "bottom")))"""),
        md("""不存在的目标照样拿到四条**格式合法但毫无意义**的边。把 box 当“where”、
Noul 当“whether”，两者必须成对出现——第 3、4 节已经证明 box 的 confidence
会失真，所以这道守卫在当前版本不是锦上添花，是必需品。

## 6. 低置信时的工程处理：扩边再裁

官方建议：confidence 低于自定阈值时，把四条边向外**扩一圈**再裁剪，
宁可多带背景也别切掉目标（在对照组数据上演练）："""),
        code("""PAD, MIN_CONF = 0.06, 0.6

def padded(edges, pad=PAD):
    return {"left": max(0.0, edge(edges, "left") - pad),
            "top": max(0.0, edge(edges, "top") - pad),
            "right": min(1.0, edge(edges, "right") + pad),
            "bottom": min(1.0, edge(edges, "bottom") + pad)}

if CLEAN_ROWS:
    low = [i for i, sc, cf in CLEAN_ROWS if cf < MIN_CONF]
    worst = min(CLEAN_ROWS, key=lambda r: r[1])
    print(f"对照组中低于阈值 {MIN_CONF} 的样本：{low or '无'}")
    print(f"IoU 最低样本 #{worst[0]}（{worst[1]:.3f}）——扩边最该服务的对象")"""),
        md("""进阶做法（官方“边缘检查”）：把预测框裁出来，对四条边各问一个 Noul
“目标是否越过了图的这条边”，哪边答是就往外扩哪边。官方在 36 张已知切边的测试图上，
四问法抓到 30 处切边，单问“目标完整吗”只抓到 26 处——**把一个模糊问题拆成四个
明确问题，比一句笼统的问法更可靠**。

不过按本册第 3、4 节的实测，真实光影场景里 box 可能一开始就框错了对象——
扩边救的是“框对了但裁太紧”，救不了“框错了地方”。工程顺序应当是：
Noul 守卫 → 预测框可视化抽查 → 才轮得到扩边。"""),

        md("""---

# 小结

## box 速查

| 要点 | 内容 |
|---|---|
| 请求 | `{"type": "box", "instructions": "the parcel in \`photo\`"}`，无 criteria |
| 模型 | 仅 `jev-preview` / `jev-1.14.0`；1.13 不支持 |
| 答案 | `box{top,bottom,left,right}`（0–1 分数）+ `confidence` |
| 读框 | 边 × 图宽/高 = 像素框；**务必画回原图核对** |
| 陷阱 | 没有“未找到”（配 Noul 守卫）；**confidence 会失真**；光影场景先小范围试点 |

## 本册实测结论（2026-10-15，jev-preview）

| 场景 | IoU | confidence | 结论 |
|---|---|---|---|
| 程序生成（无光影） | 均值 ~0.92 | 0.86–0.96 | 几何定位能力真实存在 |
| MuJoCo 渲染（有反光） | 0.00 | ~0.9 | 反光被当目标，置信失真 |

把 box 用于真实图片前，先拿十几张**你自己的场景**做一遍本册的判分流程
（标定真值 → 画框核对 → IoU 统计）。官方"dreamer-ready"的警告，
在这一册里有了具体的数字形状。

至此第 2 章七册合上了完整的能力面：三种打分原语 + 置信度 + 图像输入 + 定位。
野区特性会随版本快速演进，动手前先对照官方文档与知识库 42 号条目的最新口径。"""),
    ]
    return build(nbf.v4.new_notebook(), cells)


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "02_核心概念"
    nbf.write(build_images_notebook(), out / "06_图像输入.ipynb")
    nbf.write(build_box_notebook(), out / "07_box定位.ipynb")
    for name in ("06_图像输入.ipynb", "07_box定位.ipynb"):
        nb = nbf.read(out / name, as_version=4)
        code_n = sum(c.cell_type == "code" for c in nb.cells)
        md_n = sum(c.cell_type == "markdown" for c in nb.cells)
        mx = max(len(c.source.splitlines()) for c in nb.cells if c.cell_type == "code")
        print(f"{name}: {md_n} md / {code_n} code "
              f"(比 {md_n/code_n:.2f}), 最长 code {mx} 行")
