"""仅供构建脚本使用：把顶层模块旁的 ``.pyi`` 也打进 wheel。

元数据全在 pyproject.toml。这里只做一件事：**把 ``py/moz_openscad.pyi`` 补进 wheel**——
setuptools 的 ``package-data`` 只能挂在包（package）上，管不到 ``py-modules`` 旁边的文件，
而 PEP 561 要求存根与 ``.py`` 同目录，所以打包完成后手工补进去（并更新 RECORD 里的哈希）。

打包时用**带平台标签的纯 Python wheel**（``py3-none-linux_x86_64`` 这种）：libmozopenscad.so
是纯 C ABI 动态库、不是 CPython 扩展模块，所以不需要 cp3xx 标签，但平台标签必须有
（否则会在别的平台上被装上）。`scripts/build_wheel.sh` 负责传 --plat-name。
"""

import base64
import hashlib
import zipfile
from pathlib import Path

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel

ROOT = Path(__file__).parent
EXTRA_FILES = {"moz_openscad.pyi": ROOT / "py" / "moz_openscad.pyi"}


def _record_line(name, data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


class WheelWithStubs(bdist_wheel):
    """打包完成后把 EXTRA_FILES 补进 wheel（含 RECORD）。"""

    def run(self):
        super().run()
        version = self.distribution.get_version()
        name = f"{self.distribution.get_name().replace('-', '_')}-{version}"
        wheel = Path(self.dist_dir or ".") / f"{name}-{'-'.join(self.get_tag())}.whl"
        missing = {target: source for target, source in EXTRA_FILES.items() if not source.exists()}
        if missing or not wheel.exists():
            return

        with zipfile.ZipFile(wheel) as archive:
            entries = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        record_name = next(key for key in entries if key.endswith(".dist-info/RECORD"))
        for target, source in EXTRA_FILES.items():
            entries[target] = source.read_bytes()

        lines = [line for line in entries[record_name].decode().splitlines() if line.strip()]
        for target in EXTRA_FILES:
            lines = [line for line in lines if not line.startswith(f"{target},")]
            lines.append(_record_line(target, entries[target]))
        entries[record_name] = ("\n".join(sorted(lines)) + "\n").encode()

        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry, data in entries.items():
                archive.writestr(entry, data)


setup(cmdclass={"bdist_wheel": WheelWithStubs})
