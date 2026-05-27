"""选卷页：先选考试类别，再选具体试卷（列表版，效果对齐原版）"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QStackedWidget,
)

from hnust_exam.models.exam import Exam
from hnust_exam.utils.theme import Theme
from hnust_exam.utils.helpers import get_resource_path
from hnust_exam.utils.ui_helpers import themed_warning, themed_critical
from hnust_exam.views.animated_card_delegate import AnimatedCardDelegate

if TYPE_CHECKING:
    from hnust_exam.views.main_window import MainWindow


class _ToggleListWidget(QListWidget):
    """支持"再次点击已选中项取消选择" + 惯性滚动的列表控件."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._target_value = None
        self._inertia_start = None
        self._inertia_t0 = None
        self._inertia_duration = 0.5
        self._inertia_timer = QTimer(self)
        self._inertia_timer.setInterval(16)
        self._inertia_timer.timeout.connect(self._inertia_tick)

    # ─── 滚轮惯性 ───
    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        """三次缓出，手感比指数缓出更平滑"""
        return 1.0 - (1.0 - t) ** 3

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if delta == 0:
            return

        sb = self.verticalScrollBar()
        pixel_delta = delta // 3

        current = sb.value()
        new_target = current - pixel_delta
        new_target = max(sb.minimum(), min(sb.maximum(), new_target))

        if self._inertia_timer.isActive() and self._target_value is not None:
            self._target_value = max(sb.minimum(), min(sb.maximum(),
                                     self._target_value - pixel_delta))
        else:
            self._target_value = new_target

        self._inertia_start = current
        self._inertia_t0 = time.time()

        if not self._inertia_timer.isActive():
            self._inertia_timer.start()

        e.accept()

    def _inertia_tick(self):
        sb = self.verticalScrollBar()
        if self._target_value is None or self._inertia_t0 is None:
            self._inertia_timer.stop()
            return

        elapsed = time.time() - self._inertia_t0
        t = min(elapsed / self._inertia_duration, 1.0)
        progress = self._ease_out_cubic(t)

        start = self._inertia_start
        target = self._target_value
        current = int(start + (target - start) * progress)
        sb.setValue(current)

        if t >= 1.0:
            sb.setValue(self._target_value)
            self._target_value = None
            self._inertia_start = None
            self._inertia_t0 = None
            self._inertia_timer.stop()

    # ─── 点击取消选择 ───
    def mousePressEvent(self, e: QMouseEvent):
        item = self.itemAt(e.pos())
        if item:
            delegate = self.itemDelegate()
            if hasattr(delegate, 'pressed_row'):
                delegate.pressed_row = self.row(item)
                self.update(self.visualItemRect(item))

        if item and item == self.currentItem():
            self.clearSelection()
            self.setCurrentItem(None)
            return

        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        delegate = self.itemDelegate()
        if hasattr(delegate, 'pressed_row'):
            old_row = delegate.pressed_row
            delegate.pressed_row = -1
            if old_row >= 0:
                item = self.item(old_row)
                if item:
                    self.update(self.visualItemRect(item))
        super().mouseReleaseEvent(e)


class SelectPage(QWidget):
    """选择试卷页面：先选考试类别，再选具体试卷."""

    def __init__(self, main_window: MainWindow, parent=None) -> None:
        super().__init__(parent)
        self.main_window = main_window
        # 类别状态
        self._selected_category = ""
        # 试卷列表状态
        self.exam_files: list[str] = []
        self._selected_file: str = ""
        self._list_widget: _ToggleListWidget | None = None
        self._build_ui()

    def showEvent(self, event) -> None:
        """每次显示时回到类别选择模式."""
        super().showEvent(event)
        self._switch_to_category()

    def _build_ui(self) -> None:
        c = Theme.get_current_colors()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- 顶部标题栏 ----
        header = QFrame()
        header.setStyleSheet(
            f"background-color: {c['PRIMARY']}; padding: 10px 20px;"
        )
        header_layout = QHBoxLayout(header)

        # 返回按钮（类别模式隐藏，试卷列表模式显示）
        self._back_btn = QPushButton("← 返回")
        self._back_btn.setStyleSheet(
            f"background-color: transparent; color: white; border: none; "
            f"font-size: 11pt; padding: 5px 10px;"
        )
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back)
        self._back_btn.setVisible(False)
        header_layout.addWidget(self._back_btn)

        # Logo
        logo_label = QLabel()
        logo_pixmap = QPixmap(get_resource_path("hnust_exam/resources/logo.png"))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(
                logo_pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            logo_label.setStyleSheet("padding-right: 6px;")
        header_layout.addWidget(logo_label)

        title = QLabel("HNUST仿真平台")
        title.setStyleSheet("color: white; font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        settings_btn = QPushButton("⚙ 设置")
        settings_btn.setStyleSheet(
            f"background-color: transparent; color: white; border: none; "
            f"font-size: 11pt; padding: 5px 10px;"
        )
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._on_settings)
        header_layout.addWidget(settings_btn)

        root_layout.addWidget(header)

        # ---- 主内容区域（QStackedWidget 切换两种模式） ----
        main_frame = QFrame()
        main_frame.setStyleSheet(f"background-color: {c['BG']};")
        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(20, 20, 20, 20)

        self._content_stack = QStackedWidget()
        main_layout.addWidget(self._content_stack, 1)
        root_layout.addWidget(main_frame, 1)

        # 页面 0：类别选择
        self._category_page = QWidget()
        self._build_category_ui()
        self._content_stack.addWidget(self._category_page)  # index 0

        # 页面 1：试卷列表
        self._exam_page = QWidget()
        self._build_exam_ui()
        self._content_stack.addWidget(self._exam_page)  # index 1

        self._content_stack.setCurrentIndex(0)

    # ================================================================
    #  类别选择 UI
    # ================================================================
    def _build_category_ui(self) -> None:
        c = Theme.get_current_colors()
        layout = QVBoxLayout(self._category_page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 标题
        title = QLabel("请选择考试类别")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {c['TEXT']}; font-size: 24pt; font-weight: bold; "
            f"padding: 40px 0 30px 0;"
        )
        layout.addWidget(title)

        # 类别卡片容器
        card_container = QHBoxLayout()
        card_container.setSpacing(40)
        card_container.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Python 卡片
        self._py_btn = QPushButton("Python")
        self._py_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._py_btn.setCheckable(True)
        self._py_btn.clicked.connect(lambda: self._on_category_click("Python"))
        self._py_btn.installEventFilter(self)
        self._style_category_card(self._py_btn, c)
        card_container.addWidget(self._py_btn)

        # C语言 卡片
        self._c_btn = QPushButton("C语言")
        self._c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._c_btn.setCheckable(True)
        self._c_btn.clicked.connect(lambda: self._on_category_click("C语言"))
        self._c_btn.installEventFilter(self)
        self._style_category_card(self._c_btn, c)
        card_container.addWidget(self._c_btn)

        layout.addLayout(card_container)
        layout.addSpacing(30)

        # 确认按钮
        self._confirm_btn = QPushButton("确认选择")
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_btn.setStyleSheet(
            f"background-color: {c['PRIMARY']}; color: white; font-size: 16pt; "
            f"font-weight: bold; padding: 12px 40px; border: none; border-radius: 4px;"
        )
        self._confirm_btn.clicked.connect(self._on_confirm_category)
        self._confirm_btn.setEnabled(False)
        layout.addWidget(self._confirm_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # 底部提示
        hint = QLabel("该程序免费提供给HNUST学生使用，禁止任何形式的商用售卖")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {c['MUTED']}; font-size: 8pt; padding-top: 10px;"
        )
        layout.addWidget(hint)

    def _style_category_card(self, btn: QPushButton, c: dict) -> None:
        """设置类别卡片的样式。"""
        btn.setFixedSize(260, 180)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['SURFACE']};"
            f"  border: 2px solid {c['BORDER']};"
            f"  border-radius: 12px;"
            f"  font-size: 18pt;"
            f"  font-weight: bold;"
            f"  color: {c['TEXT']};"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {c['PRIMARY']};"
            f"  border-color: {c['PRIMARY']};"
            f"  color: white;"
            f"}}"
            f"QPushButton:hover:!checked {{"
            f"  background-color: {c['NAV_ACTIVE']};"
            f"  border-color: {c['PRIMARY']};"
            f"}}"
        )

    def _on_category_click(self, category: str) -> None:
        """点击类别卡片."""
        self._selected_category = category

        # 互斥选中
        self._py_btn.setChecked(category == "Python")
        self._c_btn.setChecked(category == "C语言")

        # 检查该类别是否有试卷
        files = Exam.list_exam_files_by_category(category)
        if files:
            self._confirm_btn.setEnabled(True)
        else:
            self._confirm_btn.setEnabled(False)
            themed_warning(self, "提示", f"「{category}」类别下暂时没有试卷")

    def _on_confirm_category(self) -> None:
        """确认选择类别，切换到试卷列表."""
        if not self._selected_category:
            return
        self._switch_to_exam_list()

    def _on_back(self) -> None:
        """返回类别选择."""
        self._switch_to_category()

    # ================================================================
    #  试卷列表 UI
    # ================================================================
    def _build_exam_ui(self) -> None:
        c = Theme.get_current_colors()
        layout = QVBoxLayout(self._exam_page)
        layout.setContentsMargins(20, 0, 20, 20)
        layout.setSpacing(12)

        # 标题（显示当前类别）
        self._exam_title = QLabel("请选择试卷")
        self._exam_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._exam_title.setStyleSheet(
            f"color: {c['TEXT']}; font-size: 24pt; font-weight: bold; "
            f"padding: 40px 0 20px 0;"
        )
        layout.addWidget(self._exam_title, 0, Qt.AlignmentFlag.AlignCenter)

        # ========== 试卷列表（stretch 吃满剩余高度） ==========
        self._list_widget = _ToggleListWidget()
        self._list_widget.itemDoubleClicked.connect(lambda _: self._on_start())
        self._list_widget.setSpacing(0)
        self._list_widget.setMinimumWidth(500)
        self._list_widget.setMaximumWidth(640)
        self._list_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list_widget.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list_widget.setContentsMargins(8, 8, 8, 8)

        self._card_delegate = AnimatedCardDelegate(c, self._list_widget)
        self._list_widget.setItemDelegate(self._card_delegate)

        self._list_widget.selectionModel().currentChanged.connect(
            self._on_paper_selection_changed
        )
        self._list_widget.currentItemChanged.connect(self._on_current_changed)

        self._list_widget.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {c['SURFACE']};"
            f"  border: 1px solid {c['BORDER']};"
            f"  border-radius: 8px;"
            f"  outline: none;"
            f"  padding: 3px;"
            f"}}"
            f"QScrollBar:vertical {{"
            f"  width: 6px; background: transparent;"
            f"  margin: 8px 2px 8px 0; border: none;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {c['BORDER']}; border-radius: 3px; min-height: 30px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: {c['TEXT']}66;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"  height: 0; background: none;"
            f"}}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            f"  background: none;"
            f"}}"
        )

        self._list_widget.installEventFilter(self)

        # 关键：stretch=1 吃满剩余空间，AlignHCenter 水平居中
        layout.addWidget(self._list_widget, 1, Qt.AlignmentFlag.AlignHCenter)

        # ---- 开始按钮 ----
        self.start_btn = QPushButton("开始考试")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet(
            f"background-color: {c['PRIMARY']}; color: white; font-size: 16pt; "
            f"font-weight: bold; padding: 12px 40px; border: none; border-radius: 4px; "
        )
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # ---- 底部提示 ----
        hint = QLabel("该程序免费提供给HNUST学生使用，禁止任何形式的商用售卖")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {c['MUTED']}; font-size: 8pt;"
        )
        layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)

    # ================================================================
    #  模式切换
    # ================================================================
    def _switch_to_category(self) -> None:
        """切换到类别选择模式."""
        self._selected_category = ""
        self._py_btn.setChecked(False)
        self._c_btn.setChecked(False)
        self._confirm_btn.setEnabled(False)
        self._back_btn.setVisible(False)
        self._refresh_category_counts()
        self._content_stack.setCurrentIndex(0)

    def _refresh_category_counts(self) -> None:
        """刷新类别卡片上的试卷数量."""
        cats = Exam.get_available_categories()
        py_count = len(cats.get("Python", []))
        self._py_btn.setText(f"Python\n{py_count} 份试卷")
        c_count = len(cats.get("C语言", []))
        self._c_btn.setText(f"C语言\n{c_count} 份试卷")

    def _switch_to_exam_list(self) -> None:
        """切换到试卷列表模式."""
        self._back_btn.setVisible(True)
        self._exam_title.setText(f"请选择试卷  —  {self._selected_category}")
        self._refresh_exam_list()
        self._content_stack.setCurrentIndex(1)

    # ================================================================
    #  键盘事件过滤
    # ================================================================
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            if obj is self._py_btn:
                self._on_category_click("Python")
                if self._confirm_btn.isEnabled():
                    self._on_confirm_category()
                return True
            if obj is self._c_btn:
                self._on_category_click("C语言")
                if self._confirm_btn.isEnabled():
                    self._on_confirm_category()
                return True
        if obj is self._list_widget:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._on_start()
                    return True
        return super().eventFilter(obj, event)

    # ================================================================
    #  列表项文本构造（显示进度标记）
    # ================================================================
    def _make_item_text(self, fname: str, progress: dict) -> str:
        """返回列表项显示的文字，如：PY程序填空  ✓ 85%"""
        display = os.path.splitext(fname)[0]
        entry = progress.get(fname, {})
        status = entry.get("status", "")
        if status == "completed":
            score = entry.get("best_score", "")
            display += f"    ✓ {score}%" if score else "    ✓"
        elif status == "started":
            display += "    ○"
        return display

    def _make_tooltip(self, fname: str, progress: dict) -> str:
        """构造多行 Tooltip"""
        entry = progress.get(fname, {})
        lines = []
        if entry.get("last_completed"):
            lines.append(f"上次完成：{entry['last_completed']}")
        if entry.get("best_score") is not None:
            lines.append(f"最高得分：{entry['best_score']}%")
        if entry.get("last_started"):
            lines.append(f"上次开始：{entry['last_started']}")
        return "\n".join(lines)

    # ================================================================
    #  刷新试卷列表（按类别过滤）
    # ================================================================
    def _refresh_exam_list(self) -> None:
        """从题库文件夹获取当前类别的试卷文件并显示在列表中"""
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        self._selected_file = ""

        self.exam_files = Exam.list_exam_files_by_category(self._selected_category)
        progress = self.main_window.config_mgr.load_progress()

        if not self.exam_files:
            self.start_btn.setEnabled(False)
            placeholder = QListWidgetItem("该类别下没有试卷文件")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list_widget.addItem(placeholder)
            self._list_widget.blockSignals(False)
            return

        for fname in self.exam_files:
            text = self._make_item_text(fname, progress)
            tooltip = self._make_tooltip(fname, progress)

            item = QListWidgetItem(text)
            if tooltip:
                item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, fname)
            item.setFont(QFont("Microsoft YaHei", 13))
            self._list_widget.addItem(item)

        self._list_widget.blockSignals(False)

    # ================================================================
    #  列表选择事件
    # ================================================================
    def _on_current_changed(self, current, previous):
        """更新当前选中的试卷文件名"""
        if current:
            self._selected_file = current.data(Qt.ItemDataRole.UserRole)
            self.start_btn.setEnabled(True)
        else:
            self._selected_file = ""
            self.start_btn.setEnabled(False)

    def _on_paper_selection_changed(self, current, previous):
        """选择变化时触发弹性动画"""
        cur_row = current.row()
        if cur_row < 0:
            return
        prev_row = previous.row() if previous.isValid() else -1
        self._card_delegate.animateTo(cur_row, prev_row)

    # ================================================================
    #  开始考试
    # ================================================================
    def _on_start(self) -> None:
        item = self._list_widget.currentItem()
        if not item:
            themed_warning(self, "警告", "请先选择一份试卷")
            return

        exam_file = item.data(Qt.ItemDataRole.UserRole)
        exam_name = os.path.splitext(exam_file)[0]

        exam = Exam()
        file_path = exam.find_exam_file(exam_name)
        if not file_path:
            themed_critical(self, "错误", "找不到试卷文件")
            return

        error = exam.load_from_excel(file_path)
        if error:
            themed_critical(self, "错误", error)
            return

        self.main_window.exam_page.setup_exam(exam, file_path)
        self.main_window.show_exam()

    def _on_settings(self) -> None:
        """打开设置对话框."""
        from hnust_exam.views.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.main_window.config_mgr, self)
        dlg.exec()
        self.main_window._refresh_theme()