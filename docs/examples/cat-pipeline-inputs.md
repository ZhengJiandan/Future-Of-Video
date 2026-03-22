# 猫主题视频生成样例输入

这份文件基于下面两套测试档案整理：

- 写实猫咪特工风：`backend/sql/seed_cat_profiles.sql`
- 可爱猫咪短片风：`backend/sql/seed_cute_cat_profiles.sql`

适用目标：

- 测试“用户输入 -> 角色分析 -> 剧本生成 -> 场景拆分 -> 首帧生成 -> 视频生成”整条链路
- 测试“自动匹配角色/场景”和“高级约束手动指定角色/场景”两种模式
- 测试不同风格下，大模型是否能正确利用角色档案和场景档案

## 使用方式

在前端主流程页：

- `用户输入`：直接复制下面的 `user_input`
- `视觉风格`：填写对应 `style`
- `目标总时长`：填写对应 `target_total_duration`
- `高级约束（可选）`：
  - 如果 `selected_character_ids` / `selected_scene_ids` 为空，就不要手动选，测试自动分析
  - 如果不为空，就手动勾选这些角色/场景，测试强约束链路

## 用例 1: 写实单主角潜入

- `project_title`: 黑猫队长雨夜潜入
- `style`: 写实战术电影感，低照度，胶片颗粒，动作克制，角色一致性优先
- `target_total_duration`: `40`
- `selected_character_ids`: `[]`
- `selected_scene_ids`: `[]`
- `test_goal`: 测试系统是否能从纯文本中自动识别黑猫队长和雨夜后巷潜入氛围

`user_input`:

```text
一只冷静的黑猫队长在雨夜的旧城区后巷执行潜入任务。它先在高处观察，再贴墙进入鱼铺后侧巷道，途中短暂停下确认路线，最后在转角前压低身体，准备继续深入。整体希望像写实短片，镜头干净克制，动作不要夸张。
```

预期更容易命中的档案：

- 角色: `cat_char_xuan_hujiao`
- 场景: `cat_scene_rain_alley`

## 用例 2: 写实双角色屋顶追逐

- `project_title`: 屋顶追缉橘大盗
- `style`: 写实都市夜戏，速度感强，镜头稳定，追逐压迫感，电影感
- `target_total_duration`: `50`
- `selected_character_ids`:
  - `cat_char_xuan_hujiao`
  - `cat_char_lihuaqi`
  - `cat_char_juwan`
- `selected_scene_ids`:
  - `cat_scene_rooftop_chase`
- `test_goal`: 测试高级约束下，多角色关系是否稳定继承到剧本、分段和视频阶段

`user_input`:

```text
黑猫队长带着狸花侦察员在旧城区屋顶追踪一只狡猾的橘猫盗贼。前半段是快速穿越屋顶和水箱之间的追逐，中段橘猫回头挑衅，后半段三只猫在狭窄屋脊上短暂对峙，最后橘猫突然再次起跳逃走。希望整段有强烈速度感和高处危险感。
```

## 用例 3: 写实据点救援过渡

- `project_title`: 书店密室急救部署
- `style`: 写实剧情短片，情绪克制，暖冷混光，人物互动细腻
- `target_total_duration`: `45`
- `selected_character_ids`:
  - `cat_char_xuan_hujiao`
  - `cat_char_mianhua`
  - `cat_char_lanwei`
- `selected_scene_ids`:
  - `cat_scene_bookstore_hideout`
- `test_goal`: 测试对话、包扎、部署这种非追逐类镜头，看看分段是否仍能保持信息丰富

`user_input`:

```text
一次行动结束后，黑猫队长带队回到藏在旧书店深处的密室。白猫医生先帮同伴检查伤口并包扎，灰蓝猫技术员在桌边接入终端确认下一段路线，黑猫队长一边看手绘地图一边重新部署。希望画面安全但不松懈，像行动前的短暂喘息。
```

## 用例 4: 可爱单主角厨房闹剧

- `project_title`: 蜜桃追番茄
- `style`: 可爱短片风，暖色，圆润，轻喜剧，动作夸张但柔软
- `target_total_duration`: `30`
- `selected_character_ids`: `[]`
- `selected_scene_ids`: `[]`
- `test_goal`: 测试系统是否能从可爱文本中自动匹配到可爱猫咪档案，而不是误用写实特工档案

`user_input`:

```text
一只奶油橘白的小猫在早晨的厨房里发现一颗滚动的小番茄，它先试探着靠近，接着突然扑上去，结果滑了一下撞进软垫里。它愣了一秒，又立刻开心地继续追。整个视频想要像温暖可爱的猫咪短片，节奏轻快，画面软乎乎的。
```

预期更容易命中的档案：

- 角色: `cute_cat_mitao`
- 场景: `cute_scene_sun_kitchen`

## 用例 5: 可爱多角色毛毯城堡

- `project_title`: 毛毯城堡躲猫猫
- `style`: 萌宠日常短片，柔焦感，暖黄灯光，互动治愈，轻微搞笑
- `target_total_duration`: `35`
- `selected_character_ids`:
  - `cute_cat_mitao`
  - `cute_cat_naigai`
  - `cute_cat_buding`
- `selected_scene_ids`:
  - `cute_scene_blanket_fort`
- `test_goal`: 测试多角色可爱互动，看看角色绑定、镜头拆分和首帧生成是否更稳定

`user_input`:

```text
三只小猫在客厅里发现了一个用毛毯和抱枕搭起来的小城堡。橘白小猫先钻进去探头，奶牛猫慢吞吞跟进去，蓝眼布偶幼猫最后抱着玩具也挤进来。它们一会儿在里面躲猫猫，一会儿挤在一起贴贴休息，整体希望非常温馨可爱。
```

## 用例 6: 可爱阳台探索

- `project_title`: 花盆阳台探险
- `style`: 清新可爱，午后阳光，微风，日常治愈系
- `target_total_duration`: `30`
- `selected_character_ids`:
  - `cute_cat_mitao`
  - `cute_cat_buding`
- `selected_scene_ids`:
  - `cute_scene_balcony_garden`
- `test_goal`: 测试探索型、弱剧情短片是否能拆成自然连续的几个片段，而不是硬拆成重复镜头

`user_input`:

```text
午后的家用小阳台上，两只小猫围着花盆和风铃慢慢探索。橘白小猫先被风吹动的叶子吸引，蓝眼布偶幼猫在后面探头张望，接着它们一起靠近窗边偷看外面的小鸟，最后在晒暖的地面上趴下休息。整体要有微风、阳光和治愈感。
```

## 用例 7: 可爱社区零食短片

- `project_title`: 小卖部窗口等零食
- `style`: 轻快可爱，社区日常，颜色明亮，短视频节奏
- `target_total_duration`: `25`
- `selected_character_ids`:
  - `cute_cat_mitao`
  - `cute_cat_naigai`
  - `cute_cat_tangyuan`
- `selected_scene_ids`:
  - `cute_scene_snack_corner`
- `test_goal`: 测试外景可爱短片、多角色轻喜剧和短时长视频质量

`user_input`:

```text
三只小猫站在社区小卖部窗口前等零食。橘白小猫最先扒到窗口边看，奶牛猫围着牛奶箱转圈，灰白小猫则偷偷去拨旁边的纸风车。它们听到零食袋声后一起抬头，最后兴奋地围到窗口前。整体像一支明亮可爱的萌宠短片。
```

## 用例 8: 写实高潮对峙

- `project_title`: 地铁通道终局对峙
- `style`: 写实悬疑动作片，低照度，红色警示灯，压迫感强
- `target_total_duration`: `50`
- `selected_character_ids`:
  - `cat_char_xuan_hujiao`
  - `cat_char_lanwei`
  - `cat_char_juwan`
- `selected_scene_ids`:
  - `cat_scene_subway_tunnel`
- `test_goal`: 测试高潮段、低照度环境、逼近与突然爆发动作的连续性

`user_input`:

```text
在废弃地铁检修通道里，黑猫队长和灰蓝猫技术员一路逼近，终于在断续闪烁的红色警示灯下堵住了橘猫盗贼。前半段是谨慎靠近和观察，中段是短暂对话和彼此试探，后半段突然爆发冲突。整体要压迫、克制、危险。
```

## 最推荐的回归测试组合

如果你只想快速回归整条链路，优先跑这 4 条：

1. 用例 1：测试自动角色分析
2. 用例 2：测试高级约束 + 多角色
3. 用例 4：测试自动匹配可爱风
4. 用例 5：测试可爱风多角色互动

## 观察重点

每条用例建议重点看这些点：

- 角色确认阶段是否选中了正确档案
- 剧本里是否保留了角色设定和场景约束
- 场景拆分后，片段是否各自有区别，不会重复
- 首帧是否符合风格，且角色稳定
- 视频生成时，后续片段是否承接前一片段的尾帧逻辑
- 最终成片是否与输入风格一致
