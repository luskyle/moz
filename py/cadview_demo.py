"""示例：方便地打开 DXF/DWG 看图纸（`moz-cadview` 的"随手可用"版本）。

```bash
PYTHONPATH=py python3 py/cadview_demo.py                  # 启动时弹选择框：选择文件 / 选择目录
PYTHONPATH=py python3 py/cadview_demo.py 你的图.dwg        # 直接开（也可以把图纸拖进窗口）
PYTHONPATH=py python3 py/cadview_demo.py 图纸目录/          # 打开目录：里面每张都能点着切换
PYTHONPATH=py python3 py/cadview_demo.py --samples         # 列出随包样例图纸（无窗口）
PYTHONPATH=py python3 py/cadview_demo.py 图.dxf --report   # 其余开关原样转发给 moz_cadview
```

窗口里：右侧「图纸」面板列出目录里的图纸（点一下就换），「图层」面板按图层开关；
`Ctrl+O` 打开文件、`Ctrl+Shift+O` 打开目录、把图纸**或整个目录**拖进来、`Home` 重置视角。
对话框默认开在**项目根目录**（有 `pyproject.toml`/`.git` 的那层，装成 wheel 时退回随包样例）。
没有显示器（没有 `DISPLAY`）时开不了窗口，会打印样例清单与用法提示。

数据来自 `py/moz_cadio.py`（libdxfrw 抽取，DWG 覆盖面 R1.40–2018+）；DXF 读不通时自动用
ezdxf 兜底。细节见 docs/python-api.md §17、docs/librecad-integration.md。
"""

import argparse
import os
import sys

import moz_cadio
import moz_cadview

CAD_SUFFIXES = (".dxf", ".dwg")


def sample_dir():
    """随包分发的样例图纸目录（`py/moz_data/drawings/`；装在 wheel 里也在它旁边）。"""
    return os.path.join(os.path.dirname(os.path.abspath(moz_cadview.__file__)), "moz_data", "drawings")


def samples():
    """随包样例图纸的路径列表。"""
    directory = sample_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, name) for name in os.listdir(directory)
                  if name.lower().endswith(CAD_SUFFIXES))


def start_dir():
    """对话框的默认目录：**本项目所在路径**（有 `pyproject.toml` / `.git` 的那一层）。

    装成 wheel（不在仓库里）时退回随包样例目录——总得是个有图纸可挑的地方。
    """
    root = project_root()
    if root:
        return root
    return sample_dir() if os.path.isdir(sample_dir()) else os.getcwd()


def project_root():
    """本项目的根目录；认不出来（例如装成 wheel）返回 ``None``。

    `py/moz_cadview.py` 的上一级就是仓库根；再退一层是兜底（模块被挪进子目录的情况）。
    """
    here = os.path.dirname(os.path.abspath(moz_cadview.__file__))
    for candidate in (os.path.dirname(here), here):
        for marker in ("pyproject.toml", ".git"):
            if os.path.exists(os.path.join(candidate, marker)):
                return candidate
    return None


def print_samples(stream=None):
    stream = sys.stdout if stream is None else stream          # 运行期取，才能被测试捕获
    entries = samples()
    if not entries:
        print("（没找到随包样例图纸）", file=stream)
        return
    print("随包样例图纸（也可以把自己的图纸路径直接给它）：", file=stream)
    for path in entries:
        print(f"  {os.path.relpath(path, os.getcwd())}  （{os.path.getsize(path) // 1024} KB）",
              file=stream)
    print("\n用法：PYTHONPATH=py python3 py/cadview_demo.py <图纸.dxf|dwg>", file=stream)


def ask_choice():
    """启动时的选择框：**两个按钮** —— 选择文件 / 选择目录（外加取消）。

    返回 ``"file"`` / ``"directory"`` / ``None``（取消或直接关掉）。
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox()
    box.setWindowTitle("打开图纸")
    box.setText("要看 DXF/DWG：选一个文件，或选一个装着图纸的目录")
    box.setInformativeText("选目录的话，里面的图纸（含子目录）会列在右侧「图纸」面板里，点一下就切换。")
    # 两个动作按钮用同一种 role，Qt 才会把它们排在一起（否则"取消"会插到中间）
    file_button = box.addButton("选择文件…", QMessageBox.AcceptRole)
    directory_button = box.addButton("选择目录…", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(file_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked is file_button:
        return "file"
    if clicked is directory_button:
        return "directory"
    return None


def choose_and_show(application):
    """启动流程：两个按钮 → 对应的文件/目录对话框 → 打开。"""
    from PySide6.QtWidgets import QFileDialog

    choice = ask_choice()
    if choice == "file":
        path, _selected = QFileDialog.getOpenFileName(
            None, "选择图纸", start_dir(), "图纸 (*.dxf *.DXF *.dwg *.DWG);;所有文件 (*)")
    elif choice == "directory":
        path = QFileDialog.getExistingDirectory(None, "选择图纸目录", start_dir())
    else:
        path = ""
    if not path:
        print("没选。也可以直接把路径给它（图纸或目录），例如：")
        print_samples()
        return 0
    return show(path, application)


def prepare(path):
    """``(cad, directory, recursive)``：给目录就看里面第一张，并把整个目录交给图纸列表。"""
    if os.path.isdir(path):
        entries = moz_cadview.list_drawings(path, recursive=True)
        if not entries:
            raise moz_cadio.CadIoError(f"这个目录里没有 DXF/DWG：{path}")
        print(f"目录里有 {len(entries)} 张图纸，先看第一张：{os.path.basename(entries[0])}")
        return moz_cadview.load(entries[0]), path, True
    return moz_cadview.load(path), None, False


def show(path, application):
    """打开窗口看一张图（或一个目录里的所有图纸）。返回退出码。"""
    try:
        cad, directory, recursive = prepare(path)
    except moz_cadio.CadIoError as exc:
        print(f"读不了：{exc}", file=sys.stderr)
        return 2
    view = moz_cadview.CadView(cad, directory=directory, recursive=recursive)
    view.show()
    if directory:
        print(f"右侧「图纸」面板里可以点着切换（共 {view.drawings.count()} 张）。")
    else:
        print(cad.report())
    print("\n窗口里：右侧「图纸」点着换图、「图层」开关图层；"
          "Ctrl+O 开文件、Ctrl+Shift+O 开目录、拖图纸或目录进来、Home 重置视角。")
    return application.exec()


def main(argv=None):
    parser = argparse.ArgumentParser(description="打开 DXF/DWG 看图纸（示例）")
    parser.add_argument("path", nargs="?", help="要看的 DXF/DWG，或装着图纸的目录")
    parser.add_argument("--samples", action="store_true", help="列出随包样例图纸（不开窗口）")
    args, extra = parser.parse_known_args(argv)

    if args.samples:
        print_samples()
        return 0

    if extra:
        # 转发给命令行入口：--report/--layers/--stats/--export-png/--export-svg（无窗口）
        if not args.path:
            print("这些开关需要先给图纸路径（或目录），例如 --report：", file=sys.stderr)
            return 2
        return moz_cadview.main([args.path, *extra])

    if not args.path:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            print("没有显示器（DISPLAY/WAYLAND_DISPLAY 都没设），打不开窗口。", file=sys.stderr)
            print_samples(sys.stderr)
            return 1
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([sys.argv[0]])
        return choose_and_show(application)

    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([sys.argv[0]])
    return show(args.path, application)


if __name__ == "__main__":
    sys.exit(main())
