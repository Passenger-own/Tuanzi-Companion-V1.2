"""
团子陪伴 · 浮动工具栏（情感型 AI 伙伴 · 最终形态）

1. 单列竖向胶囊，仅 3 个按钮：💬 AI对话 / 🌙😴 专注模式 / 💧 喂团子喝水；
   效率类能力（待办、计算器、记事本、快捷键、打卡）统一收敛到 AI 对话完成，
   不再提供独立窗口入口
2. 专注模式单按钮循环：未开启 → 轻度（🌙）→ 深度（😴）→ 退出；当前档位高亮
3. 自动隐藏为光标轮询：光标在猫咪身体 OR 工具栏区域内即保持显示；
   同时离开后才启动 2.5s 倒计时，杜绝"从猫移向工具栏途中提前消失"
4. 弹出方向自适应：猫咪在屏幕左半 → 工具栏向右弹；右半 → 向左弹，避免越界
5. 专注模式下工具栏完全隐藏（双击猫本体退出专注），退出后恢复
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QGraphicsDropShadowEffect, QApplication
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint
from PyQt5.QtGui import QColor, QFont, QCursor

import config

# 单列按钮：(动作 key, 图标, 提示文案)
PRIMARY_BUTTONS = [
    ("chat",  "💬", "AI 对话"),
    ("focus", "🌙", "专注模式"),
    ("water", "💧", "喂团子喝水"),
]

_TOOLBAR_QSS = """
QWidget#toolbarCapsule {
    background-color: rgba(255, 228, 235, 235);
    border: 1px solid rgba(255, 255, 255, 200);
    border-radius: 22px;
}
QPushButton {
    background: transparent;
    border: none;
    border-radius: 16px;
    font-size: 15px;
    padding: 2px;
}
QPushButton:hover { background: rgba(255, 182, 193, 180); }
QPushButton:pressed { background: rgba(255, 150, 175, 200); }
QPushButton[active="true"] { background: rgba(255, 182, 193, 220); }
"""

_CURSOR_POLL_MS = 200  # 光标位置轮询间隔


def _make_capsule(parent, buttons_def, font, on_click):
    """创建一个胶囊容器及其按钮，返回 (capsule, {key: QPushButton})"""
    capsule = QWidget(parent)
    capsule.setObjectName("toolbarCapsule")
    layout = QVBoxLayout(capsule)
    layout.setContentsMargins(6, 8, 6, 8)
    layout.setSpacing(2)
    buttons = {}
    for key, icon, tip in buttons_def:
        btn = QPushButton(icon, capsule)
        btn.setFont(font)
        btn.setFixedSize(32, 32)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tip)
        btn.clicked.connect(lambda _=False, k=key: on_click(k))
        layout.addWidget(btn)
        buttons[key] = btn
    return capsule, buttons


class FloatingToolbar(QWidget):
    """悬停宠物出现的单列竖向胶囊工具栏（3 个按钮：对话 / 专注 / 喂水）"""

    action_triggered = pyqtSignal(str)

    def __init__(self, pet_window):
        super().__init__()
        self._pet = pet_window
        self._focus_blocked = False   # 专注模式下完全隐藏
        self._pinned = False          # 新手引导等场景钉住，跳过自动隐藏
        self._side = "left"           # 当前弹出方向（相对宠物）

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        font = QFont(config.GLASS_FONT_FAMILY, 12)

        # 单列胶囊：4 个高频按钮
        capsule, self._buttons = _make_capsule(
            self, PRIMARY_BUTTONS, font, self._on_button
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(capsule)
        self.setStyleSheet(_TOOLBAR_QSS)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(0, 2)
        capsule.setGraphicsEffect(shadow)
        self.adjustSize()

        # 自动隐藏倒计时
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_with_fade)

        # 光标轮询：覆盖"宠物→工具栏"移动间隙，比 enter/leave 事件更可靠
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_cursor)

        # 淡入淡出动画
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self.setWindowOpacity(0.0)
        self.hide()

    # ---------- 按钮分发 ----------

    def _on_button(self, key):
        self.action_triggered.emit(key)

    # ---------- 显隐 ----------

    def show_near_pet(self):
        """定位到宠物身侧并淡入；专注模式下完全隐藏不弹出"""
        if self._focus_blocked:
            return
        self._reposition()
        self._hide_timer.stop()
        if not self.isVisible():
            self.show()
            self.raise_()
        self._fade.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._poll_timer.start(_CURSOR_POLL_MS)

    def schedule_hide(self):
        """延迟自动隐藏；已钉住或在倒计时不重复启动"""
        if self._pinned or self._focus_blocked:
            return
        if not self._hide_timer.isActive():
            self._hide_timer.start(config.TOOLBAR_AUTO_HIDE_MS)

    def cancel_hide(self):
        self._hide_timer.stop()

    def hide_with_fade(self):
        self._poll_timer.stop()
        self._fade.stop()
        self._fade.setDuration(220)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._fade.finished.connect(self._on_fade_out_done)
        self._fade.start()

    def _on_fade_out_done(self):
        try:
            self._fade.finished.disconnect(self._on_fade_out_done)
        except (TypeError, RuntimeError):
            pass
        self.hide()

    # ---------- 光标轮询防误隐 ----------

    def _cursor_in_safe_zone(self):
        """光标是否在猫咪身体 / 工具栏任一区域内"""
        pos = QCursor.pos()
        rects = [self._pet.frameGeometry(), self.frameGeometry()]
        return any(r.contains(pos) for r in rects)

    def _poll_cursor(self):
        """光标在任一相关区域内保持显示；同时离开所有区域才倒计时隐藏"""
        if not self.isVisible():
            self._poll_timer.stop()
            return
        if self._pinned:
            return
        if self._cursor_in_safe_zone():
            self.cancel_hide()
        else:
            self.schedule_hide()

    # ---------- 定位（方向自适应） ----------

    def _reposition(self):
        """猫咪在屏幕左半 → 向右弹；右半 → 向左弹；垂直居中并夹在屏幕内"""
        screen = QApplication.primaryScreen().availableGeometry()
        pet_pos = self._pet.pos()
        pet_center_x = pet_pos.x() + self._pet.width() // 2
        gap = 8
        if pet_center_x < screen.center().x():
            self._side = "right"
            x = pet_pos.x() + self._pet.width() + gap
        else:
            self._side = "left"
            x = pet_pos.x() - self.width() - gap
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = pet_pos.y() + (self._pet.height() - self.height()) // 2
        y = max(screen.top(), min(y, screen.bottom() - self.height()))
        self.move(QPoint(x, y))

    def follow_pet(self):
        """宠物被拖拽时同步位置"""
        if self.isVisible():
            self._reposition()

    # ---------- 鼠标事件：悬停期间不自动隐藏 ----------

    def enterEvent(self, event):
        self.cancel_hide()
        event.accept()

    def leaveEvent(self, event):
        self.schedule_hide()
        event.accept()

    # ---------- 状态同步 ----------

    def set_focus_state(self, focus_mode, dnd_mode):
        """专注状态同步：单按钮 🌙(轻度)/😴(深度) 切换图标，当前档位高亮"""
        btn = self._buttons["focus"]
        btn.setText("😴" if dnd_mode else "🌙")
        active = bool(focus_mode or dnd_mode)
        btn.setProperty("active", "true" if active else "false")
        if dnd_mode:
            tip = "专注模式（当前：深度专注，再点退出）"
        elif focus_mode:
            tip = "专注模式（当前：轻度专注，再点切深度）"
        else:
            tip = "专注模式"
        btn.setToolTip(tip)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def set_focus_blocked(self, blocked):
        """专注模式开关：开启时立即完全隐藏并禁止弹出，退出后恢复"""
        self._focus_blocked = blocked
        if blocked:
            self._hide_timer.stop()
            self._poll_timer.stop()
            self.hide()

    @property
    def pinned(self):
        return self._pinned

    def set_pinned(self, pinned):
        """钉住/松开：钉住期间跳过自动隐藏（新手引导指向工具栏时使用）"""
        self._pinned = pinned
        if not pinned:
            self.schedule_hide()
