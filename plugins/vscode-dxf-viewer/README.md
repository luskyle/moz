# Moz DXF/DWG Viewer —— VS Code 插件

在 VS Code 里**点开即看** DXF/DWG 图纸：资源管理器里单击/双击任意 `.dxf` / `.dwg`，
直接进入看图编辑器——不是导出的图片，而是**可交互的原始图纸**：

- **图层开关**：右上角图层面板，勾选/全选/全隐藏，实时显隐
- **悬停看图元**：鼠标悬停显示图元种类与所属图层
- **点选高亮**：单击图元高亮 + 状态栏显示详情
- **向量级缩放平移**：滚轮锚点缩放、左键拖动平移、双击还原（分辨率无关，任意放大不糊）

> 想看原文/二进制内容？`Open With… → Text Editor`（Open With… 对话框里有
> 「Text Editor」一项）；改完再点文件名就回到看图器。

## 渲染不是浏览器端近似，是真实解析后端

扩展自带**完整渲染后端**（Python + `libmozcadio.so`，打进 vsix 随扩展分发），
复用本仓库打磨过的 libdxfrw 2.0.0 解析通路：

- libdxfrw 读 DXF/DWG（DWG 覆盖面 R1.40–2018+，含编码页、动态块等）
- 真曲线：样条（有理 de Boor）、椭圆/弧、多段线 bulge、剖面线边界（含样条段）
- 块与标注展开、`\U+XXXX` 转义与 MTEXT 排版码解译、图片像素（读得到文件时）、
  PDF 底图页渲染、多线/多重引线/网格/遮罩/形状/底图等实体族
- 后端产出**规范化图元 JSON**（`--model-json`：图元折线 + 文字，颜色/线型已按浅色方案算好），
  Webview 用 Canvas 把它画成可交互图纸——后端**不依赖 PySide6**，只有 Python 3.8+ 就行

## 目录结构

```text
plugins/vscode-dxf-viewer/
├── package.json            # 扩展清单（customEditors/命令/菜单/设置）
├── scripts/
│   └── bundle-backend.sh   # 把 py 后端 + libmozcadio.so 拷进 python/（npm run package 会先跑）
├── src/
│   ├── extension.ts        # CustomReadonlyEditorProvider（点开即看）、命令入口
│   └── backend.ts          # 定位后端（自带 python/ > 设置 > 仓库）、跑 --model-json
├── media/
│   ├── viewer.js           # Canvas 交互渲染：图层/悬停/点选/缩放平移
│   └── viewer.css
├── python/                 # npm run bundle-backend 生成：自带后端（py + .so），不入库
└── README.md
```

CI/CD 两个 workflow 在仓库根 `.github/workflows/`（GitHub 只认根目录下的 workflows）：
`dxf-viewer-ci.yml`（编译 + 编 .so + 打包 vsix + 端到端冒烟）与 `dxf-viewer-release.yml`
（打 tag 出 vsix 并挂 GitHub Release；有市场 Token 才发到 VS Code Marketplace）。

## 安装 / 运行（装好即用，无需仓库/编译/PySide6）

```bash
# 从 GitHub Release（tag vscode-dxf-viewer-v*）或 CI 产物下载 vsix，直接装：
code --install-extension moz-dxf-viewer-0.2.0.vsix
```

装完就能用，不需要 moz 仓库检出、不需要 cmake/g++/PySide6。机器上只要有一个
**Python 3.8+** 解释器（默认找 `python3`；Windows 可在设置里填 `python.exe` 路径）——
后端是纯 Python + 动态库，跑 `python -m moz_cadview <图> --model-json out.json` 摊平图元。

开发调试（改扩展本体时）：

```bash
cd plugins/vscode-dxf-viewer
npm install            # 开发期依赖：typescript / vsce
npm run compile        # tsc 严格模式
# F5 起 Extension Development Host；先在仓库根 bash scripts/build_moz_cadio.sh 编一次 .so
```

## 平台说明（重要）

随 vsix 打包的 `libmozcadio.so` 是**构建平台版**（当前在 x86-64 Linux 上构建）。
换平台（Windows/macOS/ARM）时：

- 下载**对应平台构建**的 vsix（各平台 CI/Release 各出一份）；或
- 有 moz 仓库检出时用仓库后端：编出本机 `.so`，在设置 `mozDxfViewer.backendPyDir`
  指向仓库 `py/`；或
- 源码自建：`bash scripts/build_moz_cadio.sh` 后 `npm run package` 打本机版 vsix。

## 设置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mozDxfViewer.python` | `python3` | 跑后端的解释器（Python 3.8+ 即可，无需 PySide6）；Windows 可写 `python.exe` 完整路径 |
| `mozDxfViewer.backendPyDir` | 自动 | 优先用扩展自带 `python/`；填了就用仓库/本机 `py/`（开发或换 .so 时） |
| `mozDxfViewer.buildBackend` | `true` | 用仓库后端时，`.so` 缺失自动跑 `scripts/build_moz_cadio.sh` |

## 打 VSIX / 发布

```bash
cd plugins/vscode-dxf-viewer
npm run package          # = bundle-backend（拷 py + .so → python/）&& vsce package
                         # 产出 moz-dxf-viewer-0.2.0.vsix（内含 python/ + libmozcadio.so）
```

- **GitHub Release（自动）**：给仓库打 tag `vscode-dxf-viewer-v*`，release workflow
  会编译、打 vsix、挂到对应 GitHub Release —— 团队成员直接下载 vsix 安装。
- **VS Code Marketplace（可选）**：release workflow 里再加一个仓库 secret
  `MARKETPLACE_TOKEN`（vsce publisher 的 `Personal Access Token`，发布者名 `luskyle`），
  存在时自动 `vsce publish`；不存在就只出 vsix，不报错。

## 开发

```bash
cd plugins/vscode-dxf-viewer
npm run compile          # tsc 严格模式
npm run watch            # 增量编译
```

扩展本体没有单测（薄集成层 + Webview），CI 用**端到端**钉住：编译 → 编 libmozcadio.so →
`npm run package` 打成 vsix → **解包 vsix 校验内置 python/ 与 .so** → 用解包后的自带后端
真实跑 `python -m moz_cadview <语料图纸> --model-json out.json` 并断言模型非空、图元带颜色。
任何后端或打包退化都会被它拦下来。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 「扩展自带的 libmozcadio.so 缺失或平台不匹配」 | 下载对应平台的 vsix（见上「平台说明」），或用仓库后端 + `backendPyDir` |
| 报 `ModuleNotFoundError: moz_cadview` | `python/` 没打进去（装了旧 vsix？）——重装 `npm run package` 出的新 vsix |
| 「找不到渲染后端」 | 装了不带后端的旧版：升级 vsix；或手动设 `backendPyDir` 指到仓库 `py/` |
| 打开大图很慢 | `--model-json` 每次摊平一张图（一般 1-2 秒），期间有读取进度提示 |
| 图纸里有 SHAPE/某些文字没画全 | 与仓库看图器同限制：`.shx` 字形、DGN/DWF 底图不渲染；PDF 底图会渲染第 1 页 |

## 许可

- 扩展的 TS/Webview 代码：**Apache-2.0**（见 LICENSE）。
- **vsix 内置的 `libmozcadio.so` 是 GPLv2-or-later 派生物**（链接了 libdxfrw）：
  随 vsix 分发它触发 GPL 对应义务（源码可从仓库 `3rd/libdxfrw` 及其打包脚本取得），
  详见 LICENSE 与仓库 `docs/third-party.md`。