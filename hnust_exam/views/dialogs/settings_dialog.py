"""设置对话框：即时反馈、深色模式、字体缩放."""

from __future__ import annotations

import importlib
import sys
import time
from threading import Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QFrame,
    QWidget,
    QScrollArea,
    QMessageBox,
    QComboBox,
)

from hnust_exam.services.config_manager import ConfigManager
from hnust_exam.services.update_checker import fetch_latest_release_info
from hnust_exam.utils import constants
from hnust_exam.utils.helpers import version_tuple
from hnust_exam.utils.theme import Theme
from hnust_exam.utils.ui_helpers import themed_question, themed_info, themed_warning
from hnust_exam.views.dialogs.update_dialog import UpdateDialog
from hnust_exam.views.widgets.toggle_switch import ToggleSwitch


class _SmoothScrollArea(QScrollArea):
    """设置页使用的平滑滚动区域."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._target_value: int | None = None
        self._inertia_start: int | None = None
        self._inertia_t0: float | None = None
        self._inertia_duration = 0.5
        self._inertia_timer = QTimer(self)
        self._inertia_timer.setInterval(4)
        self._inertia_timer.timeout.connect(self._inertia_tick)

    @staticmethod
    def _ease_out_expo(t: float) -> float:
        if t >= 1.0:
            return 1.0
        return 1.0 - pow(2, -10 * t)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return

        sb = self.verticalScrollBar()
        current = sb.value()
        pixel_delta = delta
        new_target = max(sb.minimum(), min(sb.maximum(), current - pixel_delta))

        if self._inertia_timer.isActive() and self._target_value is not None:
            self._target_value = max(
                sb.minimum(),
                min(sb.maximum(), self._target_value - pixel_delta),
            )
        else:
            self._target_value = new_target

        self._inertia_start = current
        self._inertia_t0 = time.time()

        if not self._inertia_timer.isActive():
            self._inertia_timer.start()

        event.accept()

    def _inertia_tick(self) -> None:
        sb = self.verticalScrollBar()
        if (
            self._target_value is None
            or self._inertia_start is None
            or self._inertia_t0 is None
        ):
            self._inertia_timer.stop()
            return

        elapsed = time.time() - self._inertia_t0
        t = min(elapsed / self._inertia_duration, 1.0)
        progress = self._ease_out_expo(t)
        current = int(
            self._inertia_start + (self._target_value - self._inertia_start) * progress
        )
        sb.setValue(current)

        if t >= 1.0:
            sb.setValue(self._target_value)
            self._target_value = None
            self._inertia_start = None
            self._inertia_t0 = None
            self._inertia_timer.stop()


class SettingsDialog(QDialog):
    """个性化设置对话框."""

    def __init__(self, config_mgr: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._orig_dark = Theme._is_dark
        self._orig_scale = Theme._font_scale
        self._marks_cleared = False
        self._checking_update = False
        self._checking_qb = False

        self._cfg = config_mgr.load_config()
        self._show_immediately = self._cfg.get("show_answer_immediately", False)
        self._student_name = self._cfg.get("student_name", "")
        self._student_id = self._cfg.get("student_id", "")

        self.setWindowTitle("个性化设置")
        self.setMinimumSize(520, 520)
        self.resize(580, 720)
        self.setSizeGripEnabled(True)
        self._build_ui()

    def _build_ui(self) -> None:
        c = Theme.get_current_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._make_header(c))

        scroll = _SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {c['BG']}; border: none; }}"
            f"QScrollBar:vertical {{"
            f"  width: 6px; background: transparent; margin: 4px 2px 4px 0;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {c['BORDER']}; border-radius: 3px; min-height: 24px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: {c['TEXT']}66;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        body = QWidget()
        body.setStyleSheet(f"background-color: {c['BG']};")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 12)
        body_layout.setSpacing(10)

        card_base = f"background-color: {c['WHITE']}; border: 1px solid {c['BORDER']}; border-radius: 8px;"

        body_layout.addWidget(self._make_info_card(c, card_base))
        body_layout.addWidget(self._make_toggle_row(c, card_base, "答题后立即显示对错", "开启后选择答案即时显示对错，关闭后交卷统一评判", "feedback"))
        body_layout.addWidget(self._make_toggle_row(c, card_base, "深色模式", "切换深色/浅色主题，减少视觉疲劳", "dark",
                                                      extra_tip="建议关闭应用重新启动，有恶性bug，主包不会修太难了"))
        body_layout.addWidget(self._make_font_card(c, card_base))
        body_layout.addWidget(self._make_grading_card(c, card_base))
        body_layout.addWidget(self._make_update_card(c, card_base))
        body_layout.addWidget(self._make_question_bank_card(c, card_base))
        body_layout.addWidget(self._make_mark_card(c, card_base))

        self._status_hint = QLabel("")
        self._status_hint.setStyleSheet(
            f"color: {c['PRIMARY']}; font-size: 9pt; padding: 4px 0;"
        )
        body_layout.addWidget(self._status_hint)

        self._update_hint()
        body_layout.addStretch()

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        # ── 底部 ──
        footer = QFrame()
        footer.setStyleSheet(f"background-color: {c['WHITE']}; border-top: 1px solid {c['BORDER']};")
        btn_layout = QHBoxLayout(footer)
        btn_layout.setContentsMargins(20, 10, 20, 14)
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent; color: {c['MUTED']}; font-size: 10pt;"
            f"  padding: 7px 20px; border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {c['SURFACE']}; color: {c['TEXT']}; }}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addSpacing(8)

        done_btn = QPushButton("完 成")
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        done_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['PRIMARY']}; color: white; font-size: 11pt; font-weight: 700;"
            f"  padding: 7px 36px; border: none; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {c['PRIMARY_HOVER']}; }}"
        )
        done_btn.clicked.connect(self._on_done)
        btn_layout.addWidget(done_btn)

        layout.addWidget(footer)

    # ───────── 头部 ─────────

    def _make_header(self, c: dict) -> QFrame:
        header = QFrame()
        header.setStyleSheet(f"background-color: {c['PRIMARY']}; padding: 6px 20px;")
        h_layout = QHBoxLayout(header)
        h_layout.setSpacing(10)

        icon = QLabel("⚙")
        icon.setStyleSheet("color: white; font-size: 18pt;")
        h_layout.addWidget(icon)

        title = QLabel("个性化设置")
        title.setStyleSheet("color: white; font-size: 16pt; font-weight: 700;")
        h_layout.addWidget(title)

        sub = QLabel("自定义你的使用体验")
        sub.setStyleSheet(f"color: {c['HEADER_SUB_TEXT']}; font-size: 9pt; padding-top: 4px;")
        h_layout.addWidget(sub)
        h_layout.addStretch()

        return header

    # ───────── 个人信息卡片 ─────────

    def _make_info_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        ic = QVBoxLayout(card)
        ic.setContentsMargins(16, 14, 16, 14)
        ic.setSpacing(10)

        header_row = QVBoxLayout()
        header_row.setSpacing(2)
        ic_title = QLabel("个人信息")
        ic_title.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        header_row.addWidget(ic_title)
        ic_desc = QLabel("设置姓名和学号，将在考试页面顶部显示")
        ic_desc.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        header_row.addWidget(ic_desc)
        ic.addLayout(header_row)

        input_style = (
            f"QLineEdit {{"
            f"  background-color: {c['SURFACE']}; color: {c['TEXT']};"
            f"  border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"  padding: 7px 12px; font-size: 10pt;"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {c['PRIMARY']}; }}"
        )

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_label = QLabel("姓名")
        name_label.setStyleSheet(f"color: {c['TEXT']}; font-size: 10pt; min-width: 36px; border: none;")
        self._name_input = QLineEdit(self._student_name)
        self._name_input.setPlaceholderText("请输入姓名")
        self._name_input.setStyleSheet(input_style)
        name_row.addWidget(name_label)
        name_row.addWidget(self._name_input)
        ic.addLayout(name_row)

        id_row = QHBoxLayout()
        id_row.setSpacing(10)
        id_label = QLabel("学号")
        id_label.setStyleSheet(f"color: {c['TEXT']}; font-size: 10pt; min-width: 36px; border: none;")
        self._id_input = QLineEdit(self._student_id)
        self._id_input.setPlaceholderText("请输入学号")
        self._id_input.setStyleSheet(input_style)
        id_row.addWidget(id_label)
        id_row.addWidget(self._id_input)
        ic.addLayout(id_row)

        return card

    # ───────── 开关行（即时反馈 / 深色模式 共用）─────────

    def _make_toggle_row(self, c: dict, base: str, title: str, desc: str, kind: str,
                         extra_tip: str | None = None) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        text_col.addWidget(lbl)
        dd = QLabel(desc)
        dd.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        text_col.addWidget(dd)

        if extra_tip:
            tip = QLabel(extra_tip)
            tip.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
            text_col.addWidget(tip)

        row.addLayout(text_col)
        row.addStretch()

        toggle = ToggleSwitch()
        if kind == "feedback":
            self.feedback_check = toggle
            toggle.setChecked(self._show_immediately)
        else:
            self.dark_check = toggle
            toggle.setChecked(Theme._is_dark)

        toggle.toggled.connect(lambda: self._update_hint() if hasattr(self, '_status_hint') else None)
        row.addWidget(toggle)

        return card

    # ───────── 字体卡片（MIUI 风格滑块）─────────

    def _make_font_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        header = QVBoxLayout()
        header.setSpacing(2)
        fl_title = QLabel("字体大小")
        fl_title.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        header.addWidget(fl_title)
        fl_desc = QLabel("调整界面文字大小（80% ~ 150%）")
        fl_desc.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        header.addWidget(fl_desc)
        lay.addLayout(header)

        # MIUI 风格滑块
        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)

        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(80, 150)
        self._scale_slider.setValue(int(Theme._font_scale * 100))

        bg_track = c['BORDER']
        fill_track = c['PRIMARY']
        handle_color = c['WHITE']
        handle_border = c['BORDER']

        self._scale_slider.setStyleSheet(
            f"QSlider {{ background: transparent; }}"
            f"QSlider::groove:horizontal {{"
            f"  background: {bg_track}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::sub-page:horizontal {{"
            f"  background: {fill_track}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::add-page:horizontal {{"
            f"  background: {bg_track}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {handle_color}; border: 1.5px solid {c['BORDER']};"
            f"  width: 14px; height: 14px; margin: -7px 0; border-radius: 7px;"
            f"}}"
            f"QSlider::handle:horizontal:hover {{"
            f"  background: {c['SURFACE']};"
            f"  border: 1.5px solid {fill_track};"
            f"}}"
        )

        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        slider_row.addWidget(self._scale_slider)

        # 百分比芯片
        self._scale_label = QLabel(f"{int(Theme._font_scale * 100)}%")
        self._scale_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scale_label.setFixedSize(48, 28)
        self._scale_label.setStyleSheet(
            f"color: {c['PRIMARY']}; font-size: 10pt; font-weight: 700;"
            f"background-color: {c['HINT_BG']};"
            f"border: 1px solid {c['PRIMARY']}40; border-radius: 14px;"
        )
        slider_row.addWidget(self._scale_label)

        lay.addLayout(slider_row)

        # 步进标签
        step_row = QHBoxLayout()
        step_row.setContentsMargins(0, 0, 0, 0)
        small = QLabel("小")
        small.setStyleSheet(f"color: {c['MUTED']}; font-size: 8pt; border: none;")
        step_row.addWidget(small)
        step_row.addStretch()
        large = QLabel("大")
        large.setStyleSheet(f"color: {c['MUTED']}; font-size: 8pt; border: none;")
        step_row.addWidget(large)
        lay.addLayout(step_row)

        # 预览区
        preview = QFrame()
        preview.setStyleSheet(
            f"background-color: {c['SURFACE']}; border: 1px solid {c['BORDER']}; border-radius: 6px;"
        )
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_layout.setSpacing(3)

        self._preview_title = QLabel("这是标题文字的预览效果")
        self._preview_title.setStyleSheet(
            f"color: {c['TEXT']}; font-size: {max(9, int(12 * Theme._font_scale))}pt; "
            f"font-weight: 700; border: none; padding: 2px 0;"
        )
        preview_layout.addWidget(self._preview_title)

        self._preview_body = QLabel("这是正文内容的预览效果，用于确认字体大小是否合适")
        self._preview_body.setStyleSheet(
            f"color: {c['TEXT']}; font-size: {max(8, int(11 * Theme._font_scale))}pt; border: none; padding: 2px 0;"
        )
        preview_layout.addWidget(self._preview_body)

        self._preview_small = QLabel("这是小字标注的预览效果")
        self._preview_small.setStyleSheet(
            f"color: {c['MUTED']}; font-size: {max(7, int(9 * Theme._font_scale))}pt; border: none; padding: 2px 0;"
        )
        preview_layout.addWidget(self._preview_small)

        lay.addWidget(preview)

        return card

    # ───────── 判分严格度卡片 ─────────

    def _make_grading_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        gl = QLabel("判分严格度")
        gl.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        text_col.addWidget(gl)
        gd = QLabel("调整程序题和填空题的判分标准")
        gd.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        text_col.addWidget(gd)
        row.addLayout(text_col)
        row.addStretch()

        self._strictness_combo = QComboBox()
        self._strictness_combo.addItems(["严格", "标准", "宽松"])
        self._strictness_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {c['SURFACE']}; color: {c['TEXT']};"
            f"  border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"  padding: 6px 12px; font-size: 10pt; min-width: 80px;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox::down-arrow {{ image: none; }}"
        )

        strictness_map = {"strict": 0, "normal": 1, "lenient": 2}
        current_strictness = self._cfg.get("grading_strictness", "normal")
        self._strictness_combo.setCurrentIndex(strictness_map.get(current_strictness, 1))
        row.addWidget(self._strictness_combo)

        return card

    # ───────── 软件更新卡片 ─────────

    def _make_update_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        ut = QLabel("软件更新")
        ut.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        text_col.addWidget(ut)
        ud = QLabel(f"当前版本：{self._get_current_version()}，手动检查 GitHub 最新版本")
        ud.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        text_col.addWidget(ud)
        row.addLayout(text_col)
        row.addStretch()

        self._check_update_btn = QPushButton("检查更新")
        self._check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_update_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['SURFACE']}; color: {c['TEXT']}; font-size: 9pt;"
            f"  padding: 6px 16px; border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {c['BORDER']}; }}"
        )
        self._check_update_btn.clicked.connect(self._check_update_now)
        row.addWidget(self._check_update_btn)

        return card

    # ───────── 题库更新卡片 ─────────

    def _make_question_bank_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        qt = QLabel("题库更新")
        qt.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        text_col.addWidget(qt)
        qd = QLabel("从 Gitee 远程检查并同步最新题库文件")
        qd.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        text_col.addWidget(qd)
        row.addLayout(text_col)
        row.addStretch()

        self._check_qb_btn = QPushButton("检查题库更新")
        self._check_qb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_qb_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['SURFACE']}; color: {c['TEXT']}; font-size: 9pt;"
            f"  padding: 6px 16px; border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {c['BORDER']}; }}"
        )
        self._check_qb_btn.clicked.connect(self._check_question_bank_now)
        row.addWidget(self._check_qb_btn)

        return card

    def _check_question_bank_now(self) -> None:
        if self._checking_qb:
            return
        self._checking_qb = True
        self._check_qb_btn.setEnabled(False)
        self._check_qb_btn.setText("检查中...")

        from hnust_exam.services.resource_pack_updater import check_pack_update_async, PackUpdateResult

        def _on_result(result: PackUpdateResult) -> None:
            self._checking_qb = False
            self._check_qb_btn.setEnabled(True)
            self._check_qb_btn.setText("检查题库更新")

            if not result.success:
                error_msg = result.message
                if result.error_type == "network":
                    error_msg = "网络连接失败，请检查网络设置或稍后重试"
                elif result.error_type == "duplicate":
                    error_msg = "更新检查正在进行中，请稍候"
                themed_info(self, "题库更新", f"更新失败：{error_msg}")
                return

            if "已是最新" in result.message:
                themed_info(self, "题库更新", "当前题库已是最新，无需更新")
            else:
                themed_info(self, "题库更新", result.message)

        check_pack_update_async(callback=_on_result)

    # ───────── 试卷标记管理卡片 ─────────

    def _make_mark_card(self, c: dict, base: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(base)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        mt = QLabel("试卷标记管理")
        mt.setStyleSheet(f"color: {c['TEXT']}; font-size: 11pt; font-weight: 700; border: none;")
        text_col.addWidget(mt)
        md = QLabel("查看标记含义说明，或清除所有试卷的完成标记")
        md.setStyleSheet(f"color: {c['MUTED']}; font-size: 9pt; border: none;")
        text_col.addWidget(md)
        row.addLayout(text_col)
        row.addStretch()

        btn_col = QHBoxLayout()
        btn_col.setSpacing(8)

        legend_btn = QPushButton("标记说明")
        legend_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        legend_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['SURFACE']}; color: {c['TEXT']}; font-size: 9pt;"
            f"  padding: 5px 14px; border: 1px solid {c['BORDER']}; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {c['BORDER']}; }}"
        )
        legend_btn.clicked.connect(self._show_mark_legend)
        btn_col.addWidget(legend_btn)

        clear_btn = QPushButton("清除标记")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {c['SURFACE']}; color: {c['DANGER']}; font-size: 9pt;"
            f"  padding: 5px 14px; border: 1px solid {c['DANGER']}40; border-radius: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #fee; }}"
        )
        clear_btn.clicked.connect(self._clear_all_marks)
        btn_col.addWidget(clear_btn)

        row.addLayout(btn_col)

        return card

    # ───────── 业务方法 ─────────

    def _on_scale_changed(self, value: int) -> None:
        self._scale_label.setText(f"{value}%")
        Theme._font_scale = value / 100.0
        Theme.update_fonts()
        c = Theme.get_current_colors()
        self._preview_title.setStyleSheet(
            f"color: {c['TEXT']}; font-size: {max(9, int(12 * Theme._font_scale))}pt; "
            f"font-weight: 700; border: none; padding: 2px 0;"
        )
        self._preview_body.setStyleSheet(
            f"color: {c['TEXT']}; font-size: {max(8, int(11 * Theme._font_scale))}pt; border: none; padding: 2px 0;"
        )
        self._preview_small.setStyleSheet(
            f"color: {c['MUTED']}; font-size: {max(7, int(9 * Theme._font_scale))}pt; border: none; padding: 2px 0;"
        )
        self._update_hint()

    def _on_done(self) -> None:
        self._show_immediately = self.feedback_check.isChecked()
        Theme.set_dark_mode(self.dark_check.isChecked())

        strictness_values = ["strict", "normal", "lenient"]
        strictness = strictness_values[self._strictness_combo.currentIndex()]

        new_cfg = {
            "font_scale": Theme._font_scale,
            "dark_mode": Theme._is_dark,
            "show_answer_immediately": self._show_immediately,
            "user_python_path": self.config_mgr.load_config().get("user_python_path", ""),
            "student_name": self._name_input.text().strip(),
            "student_id": self._id_input.text().strip(),
            "grading_strictness": strictness,
        }
        old_cfg = self.config_mgr.load_config()
        for k in old_cfg:
            if k not in new_cfg:
                new_cfg[k] = old_cfg[k]
        self.config_mgr.save_config(new_cfg)
        self.accept()

    def _on_cancel(self) -> None:
        Theme._font_scale = self._orig_scale
        Theme.update_fonts()
        Theme.set_dark_mode(self._orig_dark)
        self.reject()

    def _update_hint(self) -> None:
        mode = "即时反馈" if self.feedback_check.isChecked() else "考试模式"
        theme = "深色" if self.dark_check.isChecked() else "浅色"
        scale = int(Theme._font_scale * 100)
        is_active = self.feedback_check.isChecked()
        preview_dark = self.dark_check.isChecked()
        colors = Theme._DARK if preview_dark else Theme._LIGHT
        color = colors["SUCCESS"] if is_active else colors["PRIMARY"]
        self._status_hint.setText(f"答题：{mode}  |  主题：{theme}  |  字体：{scale}%")
        self._status_hint.setStyleSheet(f"color: {color}; font-size: 9pt; padding: 5px 0;")

    def _show_mark_legend(self) -> None:
        c = Theme.get_current_colors()
        themed_info(
            self, "标记说明",
            "✓ 已完成 — 已交卷的试卷，后面显示最高得分\n\n"
            "○ 进行中 — 已开始但尚未交卷的试卷\n\n"
            "（无标记）— 尚未打开过的试卷"
        )

    def _clear_all_marks(self) -> None:
        progress = self.config_mgr.load_progress()
        if not progress:
            themed_info(self, "提示", "当前没有任何标记记录")
            return
        reply = themed_question(
            self, "确认清除",
            "确定要清除所有试卷的完成标记吗？\n\n"
            "清除后，所有试卷的完成状态和得分记录将被重置。\n"
            "此操作不可撤销。",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.save_progress({})
            self._marks_cleared = True
            themed_info(self, "完成", "所有标记已清除")

    def _check_update_now(self) -> None:
        if self._checking_update:
            return
        self._checking_update = True
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText("检查中...")

        class _Sig(QObject):
            done = Signal(object)

        sig = _Sig(self)
        sig.done.connect(self._on_manual_update_result)

        def _worker():
            try:
                token = self.config_mgr.load_config().get("github_token", "")
                info = fetch_latest_release_info(github_token=token)
            except Exception:
                info = None
            sig.done.emit(info)

        Thread(target=_worker, daemon=True).start()

    def _on_manual_update_result(self, info: dict | None) -> None:
        self._checking_update = False
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText("检查更新")

        if not info:
            themed_warning(
                self,
                "检查失败",
                "暂时无法获取最新版本信息。\n请检查网络连接后再试。",
            )
            return

        current_version = self._get_current_version()
        latest_version = info["latest_ver"]
        if version_tuple(latest_version) > version_tuple(current_version):
            info = dict(info)
            info["current_ver"] = current_version
            dlg = UpdateDialog(info, self.config_mgr, self)
            dlg.exec()
            return

        themed_info(
            self,
            "检查更新",
            f"已经是最新版本啦！\n\n当前版本：{current_version}\n最新版本：{latest_version}",
        )

    @staticmethod
    def _get_current_version() -> str:
        if not getattr(sys, "frozen", False):
            try:
                importlib.reload(constants)
            except Exception:
                pass
        return constants.CURRENT_VERSION
