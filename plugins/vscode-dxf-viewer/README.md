# Moz DXF/DWG Viewer —— VS Code 插件

在 VS Code 里**直接查看 DXF/DWG 图纸**：从资源管理器/编辑器右键，或命令面板执行
「Moz: 查看 DXF/DWG 图纸」，图纸渲染到侧边面板里，**滚轮缩放、拖动平移、双击还原**。

渲染不是"画一笔四不像的浏览器端近似"，而是复用本仓库打磨过的**真实解析与渲染后端**：

- libdxfrw（上游 2.0.0）读 DXF/DWG（DWG 覆盖面 R1.40–2018+，含编码页、动态块等）
- 真曲线：样条（有理 de Boor）、椭圆/弧、多段线 bulge、剖面线边界（含样条段）
- 块与标注展开、`\U+XXXX` 转义与 MTEXT 排版码解译、图片像素（读得到文件时）、
  PDF 底图页渲染、多线/多重引线/网格/遮罩/形状/底图等实体族
- 规范化模型 → 浅色 SVG（黑线白底），再交给 Webview 展示

## 目录结构

```text
plugins/vscode-dxf-viewer/
├── package.json            # 扩展清单（命令/菜单/设置）
├── src/
│   ├── extension.ts        # 命令入口、Webview 面板管理
│   └── backend.ts          # 定位/构建 Python 后端，导出 SVG
├── media/
│   ├── viewer.js           # Webview：SVG 展示 + 缩放/平移
│   └── viewer.css
└── README.md
```

CI/CD 两个 workflow 在仓库根 `.github/workflows/`（GitHub 只认根目录下的 workflows）：
`dxf-viewer-ci.yml`（编译 + 打包 vsix + 后端端到端冒烟）与 `dxf-viewer-release.yml`
（打 tag 出 vsix 并挂 GitHub Release；有市场 Token 才发到 VS Code Marketplace）。

## 前置条件（后端是 Python，不是 JS）

扩展本体不需要 Node 依赖（零 runtime 依赖），但它**调用 moz 仓库的 Python、
PySide6 渲染后端**，所以要有：

| 依赖 | 说明 |
| --- | --- |
| 本仓库的检出 | 扩展需要仓库的 `py/` 目录（渲染后端）——把仓库根作为工作区打开即可自动探测 |
| Python 3.10+ | 运行 `python -m moz_cadview`；PySide6 也要装在同一解释器里 |
| PySide6 | `pip install PySide6`（Webview 用的 SVG 由 Qt 离屏导出） |
| cmake + g++（仅首次） | 编译 `libmozcadio.so`：`bash scripts/build_moz_cadio.sh`；扩展设置
  `mozDxfViewer.buildBackend` 开着时会自动替你跑 |

## 安装 / 运行

```bash
# 1) 仓库根：构建 C 后端（约 1-2 分钟，只需一次）
bash scripts/build_moz_cadio.sh

# 2) 插件的依赖（开发期：typescript / vsce）
cd plugins/vscode-dxf-viewer
npm install

# 3) 编译
npm run compile

# 4) 在 VS Code 里按 F5（Extension Development Host）调试；把仓库根当工作区打开
```

装好后的日常使用（不用重新编译，除非改了 src/）：

- 资源管理器里右键任意 `.dxf` / `.dwg` → 「Moz: 查看 DXF/DWG 图纸」
- 打开任意图纸文件的编辑器标题栏右键，同一项
- 命令面板 `Ctrl+Shift+P` → 「Moz: 查看 DXF/DWG 图纸」（会用当前活动编辑器里的文件）

## 设置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mozDxfViewer.python` | `python3` | 跑后端的解释器；Windows 可写 `python.exe` 完整路径 |
| `mozDxfViewer.backendPyDir` | 自动 | moz 仓库 `py/` 目录；自动探测失败时手动指定 |
| `mozDxfViewer.buildBackend` | `true` | `.so` 缺失时自动跑 `scripts/build_moz_cadio.sh` |

## 打 VSIX / 发布

```bash
cd plugins/vscode-dxf-viewer
npm run package          # 生成 moz-dxf-viewer-0.1.0.vsix
```

- **GitHub Release（自动）**：给仓库打 tag `vscode-dxf-viewer-v*`，release workflow
  会编译、打 vsix、挂到对应 GitHub Release —— 团队成员直接下载 vsix 安装。
- **VS Code Marketplace（可选）**：release workflow 里再加一个仓库 secret
  `MARKETPLACE_TOKEN`（vsce publisher 的 `Personal Access Token`，发布者名 `luskyle`），
  存在时自动 `vsce publish`；不存在就只出 vsix，不报错。

## 独立安装（不联网 build 也行）

```bash
code --install-extension plugins/vscode-dxf-viewer/moz-dxf-viewer-0.1.0.vsix
```

## 开发

```bash
cd plugins/vscode-dxf-viewer
npm run compile          # tsc 严格模式
npm run watch            # 增量编译
npm test                 # CI 用（见下）
```

扩展本体没有单测（薄命令层 + Webview 薄壳），CI 用**端到端**钉住：编译 → `vsce package`
打成 vsix → 装 Python/PySide6、编译 `libmozcadio.so` → 真实跑 `python -m moz_cadview
<语料图纸> --export-svg --light` 并断言 SVG 非空。任何后端渲染退化都会被它拦下来。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 「找不到渲染后端」 | 扩展需要 moz 仓库的 `py/`：把仓库根作为工作区打开，或设 `mozDxfViewer.backendPyDir` |
| 「缺少 libmozcadio.so」 | 仓库根 `bash scripts/build_moz_cadio.sh`；或保持 `buildBackend` 为 true 让它自动编 |
| 报 `ModuleNotFoundError: PySide6` | `pip install PySide6`（装到 `mozDxfViewer.python` 指的那个解释器） |
| 打开大图很慢 | 后端每次导出一张图（Qt 离屏渲染，一般 1-2 秒）；这是第一次打开的开销，之后切换面板缓存了 |
| 图纸里有 SHAPE/某些文字没画全 | 与仓库看图器同限制：`.shx` 字形、DGN/DWF 底图不渲染；PDF 底图会渲染第 1 页 |

## 许可

- 扩展的 TS/Webview 代码：**Apache-2.0**（见 LICENSE）。
- 它调用的 `.so` 是 **GPLv2-or-later 派生物**（链接了 libdxfrw）——按仓库
  `docs/third-party.md` 的说明对待分发义务；扩展不把后端代码打进 vsix、
  不经 licensing 问题。