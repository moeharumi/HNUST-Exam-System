"""HNUST 仿真平台入口."""

import os
import sys

# PyInstaller --onefile 模式下，设置 Qt 平台插件路径
if getattr(sys, "frozen", False):
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    plugin_candidates = [
        os.path.join(base_dir, "PySide6", "Qt", "plugins"),
        os.path.join(base_dir, "PySide6", "plugins"),
        os.path.abspath(
            os.path.join(
                os.path.dirname(sys.executable),
                "..",
                "Frameworks",
                "PySide6",
                "Qt",
                "plugins",
            )
        ),
    ]
    for plugin_path in plugin_candidates:
        if os.path.isdir(plugin_path):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path
            break

from hnust_exam.app import run

if __name__ == "__main__":
    run()
