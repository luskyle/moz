"""示例：方便地打开 DXF/DWG 看图纸（`moz-cadview` 的"随手可用"版本）。

```bash
PYTHONPATH=py python3 py/cadview_demo.py                  # 当前目录有图纸就直接开到"图纸列表"
PYTHONPATH=py python3 py/cadview_demo.py 你的图.dwg        # 直接开（也可以把图纸拖进窗口）
PYTHONPATH=py python3 py/cadview_demo.py 图纸目录/          # 打开目录：里面每张都能点着切换
PYTHONPATH=py python3 py/cadview_demo.py --samples         # 列出随包样例图纸（无窗口）
PYTHONPATH=py python3 py/cadview_demo.py 图.dxf --report   # 其余开关原样转发给 moz_cadview
```

窗口里：右侧「图纸」面板列出目录里的图纸（点一下就换），「图层」面板按图层开关；
`Ctrl+O` 打开文件、`Ctrl+Shift+O` 打开目录、把图纸**或整个目录**拖进来、`Home` 重置视角。
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
    """文件对话框的起始目录：当前目录里有图纸就用它，否则用随包的样例目录。"""
    here = os.getcwd()
    try:
        if any(name.lower().endswith(CAD_SUFFIXES) for name in os.listdir(here)):
            return here
    except OSError:
        pass
    return sample_dir() if os.path.isdir(sample_dir()) else here


def print_samples(stream=sys.stdout):
    entries = samples()
    if not entries:
        print("（没找到随包样例图纸）", file=stream)
        return
    print("随包样例图纸（也可以把自己的图纸路径直接给它）：", file=stream)
    for path in entries:
        print(f"  {os.path.relpath(path, os.getcwd())}  （{os.path.getsize(path) // 1024} KB）",
              file=stream)
    print("\n用法：PYTHONPATH=py python3 py/cadview_demo.py <图纸.dxf|dwg>", file=stream)


def open_dialog_and_show(application):
    """兜底：弹"打开图纸"对话框（起始目录见 start_dir）。"""
    from PySide6.QtWidgets import QFileDialog

    path, _selected = QFileDialog.getOpenFileName(
        None, "打开图纸", start_dir(), "图纸 (*.dxf *.DXF *.dwg *.DWG);;所有文件 (*)")
    if not path:
        print("没选文件。可以直接给路径（图纸或目录），例如：")
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
        # 当前目录里有图纸就直接开成"图纸列表"（最省事的那种），否则弹对话框
        if moz_cadview.list_drawings(os.getcwd()):
            return show(os.getcwd(), application)
        return open_dialog_and_show(application)

    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([sys.argv[0]])
    return show(args.path, application)


if __name__ == "__main__":
    sys.exit(main())
