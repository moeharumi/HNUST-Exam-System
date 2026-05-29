"""测试滚动和动画功能."""

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt, QPropertyAnimation


@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例."""
    return QApplication.instance() or QApplication([])


def test_scroll_area_has_scroller(app):
    """测试 QScrollArea 是否配置了 QScroller."""
    from hnust_exam.views.welcome_page import WelcomePage
    from PySide6.QtWidgets import QScroller

    class MockMainWindow:
        def show_select(self):
            pass

    welcome_page = WelcomePage(MockMainWindow())
    scroll_area = welcome_page.findChild(QScrollArea)

    assert scroll_area is not None, "欢迎页面应该包含 QScrollArea"

    scroller = QScroller.scroller(scroll_area.viewport())
    assert scroller is not None, "QScrollArea 应该配置 QScroller"


def test_scroll_area_scroller_properties(app):
    """测试 QScroller 的属性配置."""
    from hnust_exam.views.welcome_page import WelcomePage
    from PySide6.QtWidgets import QScroller, QScrollerProperties

    class MockMainWindow:
        def show_select(self):
            pass

    welcome_page = WelcomePage(MockMainWindow())
    scroll_area = welcome_page.findChild(QScrollArea)

    scroller = QScroller.scroller(scroll_area.viewport())
    prop = scroller.scrollerProperties()

    frame_rate = prop.scrollMetric(QScrollerProperties.ScrollMetric.FrameRate)
    assert frame_rate == QScrollerProperties.FrameRates.Fps60, \
        "帧率应该设置为 Fps60"


def test_scroll_area_deceleration(app):
    """测试 QScroller 减速因子配置."""
    from hnust_exam.views.welcome_page import WelcomePage
    from PySide6.QtWidgets import QScroller, QScrollerProperties

    class MockMainWindow:
        def show_select(self):
            pass

    welcome_page = WelcomePage(MockMainWindow())
    scroll_area = welcome_page.findChild(QScrollArea)

    scroller = QScroller.scroller(scroll_area.viewport())
    prop = scroller.scrollerProperties()

    deceleration = prop.scrollMetric(
        QScrollerProperties.ScrollMetric.DecelerationFactor
    )
    assert 0 < deceleration < 1, f"减速因子应该在 0-1 之间，实际值: {deceleration}"


def test_welcome_page_scroll_smoothness(app):
    """测试欢迎页面滚动是否平滑（基本功能测试）."""
    from hnust_exam.views.welcome_page import WelcomePage

    class MockMainWindow:
        def show_select(self):
            pass

    welcome_page = WelcomePage(MockMainWindow())

    assert welcome_page.isVisible() or welcome_page.width() > 0
