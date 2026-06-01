"""Python 环境检测对话框."""

from __future__ import annotations

import os
import sys
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
)

from hnust_exam.services.python_env import find_system_python, normalize_python_selection
from hnust_exam.utils.theme import Theme
from hnust_exam.utils.ui_helpers import themed_info, themed_warning


class PythonEnvDialog(QDialog):
    """未找到 Python 环境时的配置对话框."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.python_path: str | None = None
        self.setWindowTitle("Python 环境配置")
        self.setMinimumSize(480, 380)
        self._build_ui()

    def _build_ui(self) -> None:
        c = Theme.get_current_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题栏
        header = QFrame()
        header.setStyleSheet(f"background-color: {c['DANGER']}; padding: 12px 20px;")
        header_layout = QHBoxLayout(header)
        title = QLabel("未找到 Python 环境")
        title.setStyleSheet("color: white; font-size: 14pt; font-weight: bold;")
        header_layout.addWidget(title)
        layout.addWidget(header)

        # 主体
        body = QFrame()
        body.setStyleSheet(f"background-color: {c['WHITE']}; padding: 24px;")
        body_layout = QVBoxLayout(body)

        desc = QLabel(
            "本试卷包含程序题，需要 Python 环境。\n"
            "请选择以下操作："
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; padding-bottom: 15px;")
        body_layout.addWidget(desc)

        # 自动搜索
        auto_btn = QPushButton("自动搜索 Python")
        auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        auto_btn.setStyleSheet(
            f"background-color: {c['PRIMARY']}; color: white; font-size: 11pt; "
            f"font-weight: bold; padding: 8px 20px; border: none; border-radius: 4px;"
        )
        auto_btn.clicked.connect(self._auto_search)
        body_layout.addWidget(auto_btn)

        # 手动选择
        manual_text = "手动选择 Python / IDLE.app" if sys.platform == "darwin" else "手动选择 Python"
        manual_btn = QPushButton(manual_text)
        manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manual_btn.setStyleSheet(
            f"background-color: {c['SURFACE']}; color: {c['TEXT']}; font-size: 11pt; "
            f"padding: 8px 20px; border: none; border-radius: 4px;"
        )
        manual_btn.clicked.connect(self._manual_select)
        body_layout.addWidget(manual_btn)

        # 去官网下载
        download_btn = QPushButton("去官网下载 Python")
        download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        download_btn.setStyleSheet(
            f"background-color: {c['SURFACE']}; color: {c['TEXT']}; font-size: 11pt; "
            f"padding: 8px 20px; border: none; border-radius: 4px;"
        )
        download_btn.clicked.connect(self._download_python)
        body_layout.addWidget(download_btn)

        body_layout.addSpacing(10)

        # 跳过
        skip_btn = QPushButton("跳过（仅做非程序题）")
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.setStyleSheet(
            f"background-color: transparent; color: {c['MUTED']}; font-size: 9pt; border: none;"
        )
        skip_btn.clicked.connect(self.reject)
        body_layout.addWidget(skip_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(body, 1)

    def _auto_search(self) -> None:
        python_path = find_system_python()
        if python_path:
            self.python_path = python_path
            themed_info(self, "找到 Python", f"已找到：\n{python_path}")
            self.accept()
        else:
            themed_warning(self, "未找到", "自动搜索未找到 Python。\n请手动选择或安装。")

    def _manual_select(self) -> None:
        initial_dir, title, name_filter = self._manual_dialog_options()

        path, _ = QFileDialog.getOpenFileName(
            self, title, initial_dir, name_filter
        )
        selected = normalize_python_selection(path)
        if selected:
            self.python_path = selected
            self.accept()
        elif path:
            themed_warning(
                self,
                "无法使用",
                "请选择 Python 解释器，或选择 Python 安装目录中的 IDLE.app。",
            )

    def _manual_dialog_options(self) -> tuple[str, str, str]:
        if sys.platform == "darwin":
            initial_dir = self._mac_python_initial_dir()
            return (
                initial_dir,
                "选择 Python 或 IDLE.app",
                "Python / IDLE (python python3 pythonw python* *.app);;所有文件 (*)",
            )

        if os.name == "nt":
            initial_dir = os.environ.get("ProgramFiles", "C:\\")
            local_app = os.environ.get("LOCALAPPDATA", "")
            python_dir = os.path.join(local_app, "Programs", "Python")
            if os.path.isdir(python_dir):
                initial_dir = python_dir
            return initial_dir, "选择 python.exe", "python.exe (python.exe);;所有文件 (*)"

        return "/", "选择 Python", "Python (python python3 python*);;所有文件 (*)"

    def _mac_python_initial_dir(self) -> str:
        apps_dir = "/Applications"
        if not os.path.isdir(apps_dir):
            return os.path.expanduser("~")

        python_dirs: list[str] = []
        for name in os.listdir(apps_dir):
            path = os.path.join(apps_dir, name)
            if name.startswith("Python ") and os.path.isdir(path):
                python_dirs.append(path)

        def version_key(path: str) -> tuple[int, ...]:
            version = os.path.basename(path).replace("Python ", "")
            parts: list[int] = []
            for part in version.split("."):
                try:
                    parts.append(int(part))
                except ValueError:
                    parts.append(-1)
            return tuple(parts)

        python_dirs.sort(key=version_key, reverse=True)
        return python_dirs[0] if python_dirs else apps_dir

    def _download_python(self) -> None:
        webbrowser.open("https://www.python.org/downloads/")
        msg = "下载安装后请重新打开本程序。"
        if sys.platform == "win32":
            msg += "\n安装时务必勾选 \"Add Python to PATH\"！"
        themed_info(
            self, "提示",
            msg
        )
