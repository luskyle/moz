# plugins —— 周边插件

把 moz 的看图/建模能力包成编辑器插件。目前有一个：

| 目录 | 插件 | 做什么 | 入口 |
| --- | --- | --- | --- |
| [`vscode-dxf-viewer/`](vscode-dxf-viewer/) | **Moz DXF/DWG Viewer** | 在 VS Code 里**点开即看** DXF/DWG 图纸：可交互原始图纸（图层开关/悬停/点选/缩放平移），自带 Python + `libmozcadio.so` 后端打进 vsix，装好即用 | 资源管理器单击 `.dxf`/`.dwg` 直接进看图器；`Open With… → Text Editor` 看原文 |

## 约定

- 每个插件目录自包含：`package.json`（清单）、`src/`（TS）、`media/`（Webview）、`README.md`。
- **CI/CD 在仓库根 `.github/workflows/`**（GitHub Actions 只认根目录的 workflows）：
  `dxf-viewer-ci.yml` 编译+编 .so+打包+端到端冒烟；`dxf-viewer-release.yml` 打 tag 出 vsix。
- 插件是**薄集成层 + 随包自带后端**：重活（解析、渲染、几何）由打进 vsix 的 Python/C 后端
  干（`scripts/bundle-backend.sh` 把 `py/moz_cadview.py`、`py/moz_cadio.py`、
  `build/lib/libmozcadio.so` 拷进扩展的 `python/`）。⚠️ `.so` 是 GPLv2-or-later 派生物
  （链接 libdxfrw），随 vsix 分发要带明示（各 LICENSE 已写）；换平台要换对应平台构建的 vsix。