# 古偶主链路测试输入

这份文件对应档案：

- [seed_ancient_romance_profiles.sql](/Users/zhenglei/git/future-of-video/backend/sql/seed_ancient_romance_profiles.sql)

适用目标：

- 测试古偶风格下，角色档案和场景档案是否能稳定约束剧本与分镜
- 测试“多角色权谋 + 情感拉扯 + 场景切换”的连续性
- 测试角色锚点在关键帧和视频阶段是否更稳

## 使用方式

- 先执行：

```sql
SOURCE backend/sql/seed_ancient_romance_profiles.sql;
```

- 然后在前端主流程页：
  - `用户输入`：复制下面任一 `user_input`
  - `视觉风格`：填写对应 `style`
  - `目标总时长`：填写对应 `target_total_duration`
  - 若要强约束测试，就手动勾选文中给出的角色和场景

## 用例 1：上元灯会误救世子

- `project_title`: 灯市误救
- `style`: 古偶写实质感，人物颜值稳定，灯火暧昧，权谋悬疑感，情绪克制
- `target_total_duration`: `40`
- `selected_character_ids`: `[]`
- `selected_scene_ids`: `[]`
- `test_goal`: 测试自动匹配角色和灯市场景，观察男女主是否能被正确识别

`user_input`:

```text
上元灯会的长街上，一名清冷医女在人群里意外救下一个中毒发作的年轻世子。她刚替他压下毒性，就发现追兵已经混入灯市。两人被迫在人潮与花灯之间穿行躲避，最后在灯火最盛的一处短暂对视，却都没有说出真实身份。整体希望像古偶开篇，热闹里藏着危险，人物克制但有强烈宿命感。
```

预期更容易命中的档案：

- 角色：`guou_char_shen_ningwan`
- 角色：`guou_char_xie_yanli`
- 场景：`guou_scene_lantern_street`

## 用例 2：药铺后院试探结盟

- `project_title`: 雨后试探
- `style`: 古偶夜戏，写实细腻，雨后潮气，近距离对话，暧昧克制
- `target_total_duration`: `35`
- `selected_character_ids`:
  - `guou_char_shen_ningwan`
  - `guou_char_xie_yanli`
- `selected_scene_ids`:
  - `guou_scene_medicine_courtyard`
- `test_goal`: 测试双角色静场戏，看看对话、疗伤、微表情能否拆成自然片段

`user_input`:

```text
雨后的药铺后院里，医女替受伤的世子取针止血。世子明明已经恢复，却仍装作虚弱，一边试探她是否知道旧案内情，一边暗中观察她的反应。医女察觉不对，却没有戳破，只在最后冷冷提醒他，若再不说实话，下次她不会救第二次。整体希望张力细腻，情感要克制但明显。
```

## 用例 3：宫灯长廊夜传密信

- `project_title`: 长廊传信
- `style`: 古偶权谋夜戏，宫廷压迫感，追逐与反转并存，角色一致性优先
- `target_total_duration`: `45`
- `selected_character_ids`:
  - `guou_char_shen_ningwan`
  - `guou_char_xie_yanli`
  - `guou_char_song_qinghe`
  - `guou_char_pei_chengjin`
- `selected_scene_ids`:
  - `guou_scene_palace_corridor`
- `test_goal`: 测试多角色宫廷戏和中段反转，观察场景压迫感、追逐和拦截是否清晰

`user_input`:

```text
深夜的昭华殿长廊中，掌灯女官悄悄把一封密信交给医女，信里藏着旧案证据。医女刚接过信，反派权臣公子的人就顺着长廊追来。世子从另一侧出现替她挡下一瞬，三个人在宫灯与雨声里形成短暂对峙，随后医女趁乱逃向更深处。整体要有压迫感、紧张感和明显反转。
```

## 用例 4：断崖祭庙真相揭开

- `project_title`: 断崖真相
- `style`: 古偶高潮戏，强风、火光、危险感，情感和权谋同时爆发，镜头电影感
- `target_total_duration`: `55`
- `selected_character_ids`:
  - `guou_char_shen_ningwan`
  - `guou_char_xie_yanli`
  - `guou_char_pei_chengjin`
- `selected_scene_ids`:
  - `guou_scene_cliff_temple`
- `test_goal`: 测试高潮对峙、动作延展和尾帧承接，看看人物在强情绪场景中会不会漂

`user_input`:

```text
一切证据都被逼到断崖祭庙。医女拿出旧玉佩和密诏残页，当面揭穿权臣公子当年陷害她父亲的真相。权臣公子却反咬一口，试图把所有罪名推到世子身上。强风卷起残幡，火盆映得每个人脸色明暗不定，三人先是对峙，随后爆发近身冲突。最后世子护着医女退到崖边，在最危险的一刻逼出反派最后一句真话。整体要跌宕、克制、充满宿命感。
```

## 最推荐的回归组合

如果你只想快速回归古偶链路，优先跑这 3 条：

1. 用例 1：测试自动匹配
2. 用例 3：测试多角色宫廷转折
3. 用例 4：测试高潮对峙和视频连续性

## 观察重点

- 角色确认阶段是否能正确匹配清冷医女、隐忍世子、宫廷内应和权臣反派
- 剧本里是否保留“旧案、密信、误会、护人、对峙”的核心剧情线
- 分段后是否自然形成“相遇 -> 试探 -> 转折 -> 高潮”的起伏
- 首帧和视频阶段，男女主脸部与服装是否稳定
- 宫廷与断崖场景是否没有跑成仙侠或现代古风混搭
