# Silex 审查报告

> 审查对象：本仓库（基于 [Shugabuga/Silica](https://github.com/Shugabuga/Silica) 二次开发）
> 参考对照：`Silica-master/`（上游原版）
> 日期：2026-09-19

---

## 一、核心问题：Sileo 里各插件展示样式不一致

### 症状
- `弹幕助手` 在 Sileo 里是**原生现代样式**（大 banner、原生卡片、原生「获取」按钮）
- `微信虚拟定位`、`咸鱼助手`、`虚拟权限` 等则是**旧式样式**

### 根因
Sileo 依据 Packages 索引里的 `SileoDepiction` / `ModernDepiction` 决定用哪种样式渲染。
而索引字段来自 **deb 内部的 control**，流程是：

```
CompileControl()  算出完整 control（含 Depiction / SileoDepiction /
                  ModernDepiction / Icon / Author / Maintainer ...）
        ↓
CreateDEB()       只把其中 4 个字段（Description / Package / Section / Name）
                  补丁回 deb
        ↓
dpkg-scanpackages 扫描 deb 的 control 生成索引
        ↓
结果：索引里有没有 depiction 字段，取决于【源 deb 里原本带了什么】
```

实测证据：

| 包 | 源 deb control 里 depiction/icon 字段数 |
|---|---|
| 弹幕助手（显示正常） | **4** |
| 其余全部包 | **0** |

`CompileControl()` 明明算出了这些字段，却被丢弃了 —— 所以只有"手工往 deb 里塞过字段"的弹幕助手看起来是正常的。

### 修复
`util/DebianPackager.py` → `CreateDEB()`：
把 `CompileControl()` 的全部字段套用到 deb，而不再只补 4 个。
`Architecture` / `Version` / `Package` 仍以 deb 自身为准；
`Name` 采用 `index.json`（仓库展示元数据的唯一来源）。

### 验证
修复后所有包在索引里都是 **4/4** 字段齐全：

```
Package                        Name                              Section   4字段
danmutool                      弹幕助手                              Tweaks    4/4
fanqiefn                       番茄净化                              Tweaks    4/4
im.mjh.alipay2nfc              Alipay2NFC                        Tweaks    4/4
im.mjh.alipay2nfc.roothide     Alipay2NFC · 碰一碰转接 (Roothide)     Roothide  4/4
im.mjh.fakeperm                虚拟权限 · Fake Permission            Tweaks    4/4
im.mjh.fakeperm.roothide       虚拟权限 · Fake Permission (Roothide)  Roothide  4/4
im.mjh.wclocate                微信虚拟定位                            Tweaks    4/4
im.mjh.xianyuhelper            咸鱼助手                              Tweaks    4/4
```

---

## 二、顺序依赖 bug：roothide 条目的 Section/Name 会被套成 arm64 的

### 根因
`CreateDEB()` 里查找 `tweak_data` 的条件是：

```python
if t['bundle_id'] == bundle_id or t['bundle_id'] == internal.package:
```

同一个包常同时有 arm64 条目（`im.mjh.xxx`）与 roothide 条目（`im.mjh.xxx.roothide`），
两者 `bundle_id` 不同，但 **deb 内部的 Package 名相同**（都是 `im.mjh.xxx`）。
于是处理 roothide 包时，若 arm64 条目恰好排在前面，就会先被
`t['bundle_id'] == internal.package` 命中 → 拿到 arm64 的 `Section`/`Name`
→ roothide 包被套上 `Section: Tweaks`、丢掉 `(Roothide)` 后缀。

**结果取决于 `os.listdir` 顺序**，所以表现为"有的包对、有的包错"。

### 修复
改为**精确 `bundle_id` 优先**，匹配不到再退回按 `internal.package` 匹配。

---

## 三、与上游不兼容：数据目录名被改名

上游 Silica 用 `silica_data/`，本 fork 改名成了 `silex_data/`。
从上游迁移过来的包（只有 `silica_data/`）会被判定为"未配置"，
进而触发**交互式脚手架**（在非交互环境下直接 `EOFError` 崩溃）：

```
EOFError: EOF when reading a line
  output['developer']['email'] = input("What is the original author's email address? ")
```

### 修复
`util/PackageLister.py` 新增 `NormalizeDataDirs()`，在编译开始时为这类包
建立 `silex_data -> silica_data` 的**软链接别名**：

- 非破坏性：不改动原目录、不移动文件
- 可逆：删掉软链接即可
- 现有全部代码无需改动

建议后续逐步把数据目录统一迁移为 `silex_data`，届时可移除该兼容层。

---

## 四、其他观察（未改，供决策）

1. **`architecture` 字段缺失**
   `弹幕助手`、`咸鱼助手`、`番茄净化` 的 `index.json` 没有 `architecture`，
   编译时回落到默认 `iphoneos-arm64`。建议显式补上，避免将来出多架构包时出错。

2. **描述质量差异极大**
   `咸鱼助手` 186 字节、`弹幕助手` 231 字节、`虚拟权限` 2996 字节。
   原生 depiction 会按 markdown 渲染，内容过少时页面会显得很空 ——
   这属于内容问题而非代码问题，但正是"看起来不一样"的观感来源之一。

3. **空截图 View**
   所有包都会生成一个 `HiddenDepictionScreenshotsView` 且 `screenshots: []`。
   目前不影响渲染，但无截图时可以不生成该 view，减少一层无意义节点。

4. **上游 `Silica-master/` 已保留**在本目录内，便于随时 diff。

---

## 五、如何应用到源

```bash
# 1. 在源工程目录执行编译（会自动建立 silex_data 兼容别名）
python3 index.py

# 2. 检查产物
#    docs/Packages.bz2  里每个包都应有 Depiction/SileoDepiction/ModernDepiction/Icon

# 3. 推送
cd docs && git add . && git commit -m "更新源" && git push origin master --force
```
