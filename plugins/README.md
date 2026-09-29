# plugins —— 周边插件

把 moz 的看图/建模能力包成编辑器插件。目前有一个：

| 目录 | 插件 | 做什么 | 入口 |
| --- | --- | --- | --- |
| [`vscode-dxf-viewer/`](vscode-dxf-viewer/) | **Moz DXF/DWG Viewer** | 在 VS Code 里直接查看 DXF/DWG 图纸（复用 libdxfrw + PySide6 渲染后端，Webview 缩放/平移） | 右键图纸 → 「Moz: 查看 DXF/DWG 图纸」；`Ctrl+Shift+P` 同命令 |

## 约定

- 每个插件目录自包含：`package.json`（清单）、`src/`（TS）、`media/`（Webview）、`README.md`。
- **CI/CD 在仓库根 `.github/workflows/`**（GitHub Actions 只认根目录的 workflows）：
  `dxf-viewer-ci.yml` 编译+打包+后端冒烟；`dxf-viewer-release.yml` 打 tag 出 vsix。
- 插件通常只是**薄集成层**，重活（解析、渲染、几何）都调用仓库里已有的 Python/C
  后端——不被入 vsix，规避重复维护与许可纠缠（详见各插件 README）。