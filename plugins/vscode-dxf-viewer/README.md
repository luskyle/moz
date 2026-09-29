# Moz DXF/DWG Viewer

![Moz DXF/DWG Viewer](icon.png)

在 VS Code 里**直接打开 DXF/DWG 图纸**——不需要安装 AutoCAD/LibreCAD，点开就能看、
能交互。图纸由扩展自带的解析后端（libdxfrw + `libmozcadio.so`）真实解析，不是一张
截图或导出图：所有图元都是可缩放、可点选的真实矢量。

## 它能做什么

- **点开即看**：在资源管理器里单击/双击 `.dxf`、`.dwg` 文件，直接进入看图界面——
  不用先开一个命令，也不用右键。
- **图层开关**：右上角图层面板按图层显示/隐藏图纸内容，「全部」「隐藏」一键切换。
- **看每个图元**：鼠标悬停显示它是什么（线、圆、文字…）在第几层；单击选中并高亮，
  左下角状态栏给出详情。
- **任意缩放平移**：滚轮以鼠标位置为中心缩放、左键拖动平移、双击还原整张图——矢量
  渲染，放大多少倍都不糊。
- **深浅主题都好看**：自动跟随 VS Code 主题配色，深色主题下黑线会翻白，不会"看不清"。
- **复杂图纸照常解析**：直线、圆弧、样条曲线、椭圆、多段线、剖面线、标注、块、图片、
  PDF 底图等常见实体都支持；DWG 兼容 R1.40–2018+。
- **想看文件的原始内容**：标签页菜单「重新打开方式… → Text Editor」可切回文本/二进制
  视图，看完再点文件名回到看图。

## 安装

从仓库 GitHub Releases（标签 `vscode-dxf-viewer-v*`）或 CI 产物下载 vsix 文件，然后：

```bash
code --install-extension moz-dxf-viewer-0.2.3.vsix
```

装完**立刻能用**，机器上只需一个 Python 3.8+（默认找 `python3`，Windows 可在设置里
填写 `python.exe` 路径）。不需要：克隆仓库、装 PySide6、装编译工具、现场编译。

> 换平台的用户请看「平台说明」。

## 怎么用

1. 把 `.dxf` / `.dwg` 文件拖进 VS Code，或直接在资源管理器里点击它——看图界面自动打开。
2. 右上角**图层面板**：勾选/取消勾选控制各图层显隐；「全部」「隐藏」一键操作。
3. 画布上：
   - **滚轮**：放大/缩小（以鼠标位置为中心）
   - **左键按住拖动**：平移图纸
   - **双击**：恢复显示整张图
   - **鼠标悬停**：看当前图元的种类和所在图层
   - **单击**：选中图元，左下角显示详情（种类、图层、文字内容/顶点数）
4. 深色/浅色主题都支持——跟着 VS Code 主题走，不用单独设置。

## 平台说明（重要）

扩展自带的 `libmozcadio.so` 是**构建平台版**。在别的平台（Windows、macOS、ARM）使用时：

- 优先下载**对应平台构建**的 vsix（各平台 CI/Release 会各出一份）；
- 或者用源码构建：克隆本仓库，根目录执行 `bash scripts/build_moz_cadio.sh`，再在设置
  里把 `mozDxfViewer.backendPyDir` 指向仓库的 `py/` 目录。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示「扩展自带的 libmozcadio.so 缺失或平台不匹配」 | 下载对应你平台的 vsix（见「平台说明」），或用仓库后端 |
| 提示找不到渲染后端 | 升级到 0.2.0+ 的 vsix（自带后端的版本），或在设置里手动指定 `backendPyDir` |
| 图纸打不开 / 报错 | 界面里会给出原因；DWG/BUG 特别新的文件可先在原软件里另存为低版本 |
| 有些文字/图形没显示 | 与仓库看图器同源限制：`.shx` 字体字形、DGN/DWF 底图不渲染；PDF 底图渲染第 1 页 |
| 打开大图纸很慢 | 首次解析一般 1–2 秒，期间有读取进度提示；之后重复打开不重新解析 |

## 设置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mozDxfViewer.python` | `python3` | 执行解析后端的 Python 解释器（Windows 可写 `python.exe` 完整路径） |
| `mozDxfViewer.backendPyDir` | 自动 | 优先用扩展自带的 `python/`；只有要用仓库后端时才需要设置 |
| `mozDxfViewer.buildBackend` | `true` | 用仓库后端时，`.so` 缺失自动编译 |

大多数用户不需要动任何设置。

## 许可

扩展的 TypeScript/Webview 代码为 Apache-2.0（见 LICENSE）。随 vsix 一起分发的
`libmozcadio.so` 基于 libdxfrw（GPLv2-or-later），分发时遵循 GPL 条款，其源码可从
moz 仓库（`3rd/libdxfrw`）取得。

---

## 给维护者

- 打包：`npm run package` = 清掉旧 vsix → 拷贝 `py/moz_cadio.py`、`py/moz_cadview.py`、
  `build/lib/libmozcadio.so` 进 `python/`（保持 `moz_cadio.py` 的默认查找布局）→
  `vsce package`。产物目录里**只保留最新一个 vsix**（旧的会被删掉）。
- 开发调试：`npm install && npm run compile`；先在仓库根 `bash scripts/build_moz_cadio.sh`
  编一次 `.so`，然后 F5 起 Extension Development Host。
- CI/CD：仓库根 `.github/workflows/` 下的 `dxf-viewer-ci.yml`（编译→编 .so→打包→解包
  校验 vsix 内含 python/ + .so→用自带后端跑 `--model-json` 冒烟）与
  `dxf-viewer-release.yml`（打 tag `vscode-dxf-viewer-v*` 出 vsix 挂 GitHub Release，
  并自动发 VS Code Marketplace）。
- **发布到 Marketplace**：把 VS Code Marketplace PAT（Azure DevOps 个人令牌页签发的
  令牌，发布者为 `luskyle`）存成 GitHub 加密机密 **`LUSKYLE`**（`Settings → Secrets
  and variables → Actions`，名字大小写不敏感）。然后升 `package.json` 的 `version`
  并打 tag `vscode-dxf-viewer-vX.Y.Z` 推送即可——`npm run deploy`（package.json 里的
  脚本，不含 token；token 由 `VSCE_PAT` 环境变量注入）负责发布。没有该 secret 时
  跳过市场发布，Release 里的 vsix 仍可手动安装。
- 后端交互协议：`python -m moz_cadview <图> --model-json out.json [--dark]` 产出图元
  JSON（折线 + 文字，颜色按主题深浅两套）；`model_as_json` 与 Qt 看图器共用同一套
  几何/颜色口径，文字带完整姿态（旋转+缩放+镜像）。