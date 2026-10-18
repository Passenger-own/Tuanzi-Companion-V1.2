"""
团子陪伴 · 新手引导（V1.1 P0 入口重构）

与浮动工具栏配套解决「59% 用户无法快速触发功能」的可发现性问题：
首次启动时通过分步气泡 + 指引卡片，带用户走一遍核心交互；
完成后写入本地标记，可通过右键菜单「新手引导」随时重看。
"""

import os
import json
import logging

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt, QObject, QPoint
from PyQt5.QtGui import QColor, QFont

import config

logger = logging.getLogger(__name__)

ONBOARDING_VERSION = 3

# 分步引导脚本（最终版 4 步）：(气泡文案, 卡片说明)
STEPS = [
    (
        "嗨，我是团子！这是你的桌面小伙伴",
        "欢迎！团子会一直待在你的桌面上陪你。\n点击「下一步」快速认识它。",
    ),
    (
        "把鼠标移到团子身上，会弹出快捷工具栏",
        "悬停团子 → 弹出快捷工具栏：\n💬 AI 对话 / 🌙 专注模式 / 💧 喂团子喝水，一键直达。",
    ),
    (
        "双击团子，打开 AI 对话和它聊天",
        "双击团子 → AI 对话：流式回复、三种性格切换，\n团子还会记住你说过的事（只存在本地）。",
    ),
    (
        "需要专注时，点工具栏的 🌙 开启专注模式",
        "🌙 轻度＝安静侧躺陪你，再点一下 😴 深度＝熟睡不打扰，\n第三次点击退出专注；专注中双击团子也能退出。",
    ),
]

_CARD_QSS = """
QWidget#guideCard {
    background-color: rgba(255, 228, 235, 245);
    border: 1px solid rgba(255, 255, 255, 220);
    border-radius: 18px;
}
QLabel { background: transparent; color: #6E6E6E; }
QLabel#stepLabel { color: #B84B66; font-weight: bold; }
QPushButton {
    background: rgba(255, 182, 193, 220);
    color: #ffffff;
    border: none;
    border-radius: 14px;
    padding: 6px 16px;
    font-weight: bold;
}
QPushButton:hover { background: rgba(255, 200, 215, 240); }
QPushButton#skipBtn { background: rgba(255, 255, 255, 150); color: #6E6E6E; }
QPushButton#skipBtn:hover { background: rgba(255, 182, 193, 180); }
"""


class GuideCard(QWidget):
    """引导说明卡片：跟随宠物上方，含步骤指示与下一步/跳过按钮"""

    def __init__(self, on_next, on_skip):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        card = QWidget(self)
        card.setObjectName("guideCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.step_label = QLabel("", card)
        self.step_label.setObjectName("stepLabel")
        self.step_label.setFont(QFont(config.GLASS_FONT_FAMILY, 9))
        layout.addWidget(self.step_label)

        self.text_label = QLabel("", card)
        self.text_label.setFont(QFont(config.GLASS_FONT_FAMILY, 10))
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self.skip_btn = QPushButton("跳过", card)
        self.skip_btn.setObjectName("skipBtn")
        self.skip_btn.setFont(QFont(config.GLASS_FONT_FAMILY, 9))
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(on_skip)
        btn_row.addWidget(self.skip_btn)
        self.next_btn = QPushButton("下一步", card)
        next_font = QFont(config.GLASS_FONT_FAMILY, 9)
        next_font.setBold(True)
        self.next_btn.setFont(next_font)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(on_next)
        btn_row.addWidget(self.next_btn)
        layout.addLayout(btn_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.setStyleSheet(_CARD_QSS)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 3)
        card.setGraphicsEffect(shadow)

        self.setFixedWidth(320)
        self.adjustSize()

    def set_step(self, index, total, text):
        self.step_label.setText(f"新手引导 {index + 1} / {total}")
        self.text_label.setText(text)
        self.next_btn.setText("完成" if index == total - 1 else "下一步")
        self.adjustSize()

    def show_above(self, pet_window):
        """定位到宠物上方居中；上方空间不足时放下方"""
        pet_pos = pet_window.pos()
        x = pet_pos.x() + (pet_window.width() - self.width()) // 2
        y = pet_pos.y() - self.height() - 60
        if y < 0:
            y = pet_pos.y() + pet_window.height() + 12
        self.move(QPoint(x, y))
        self.show()
        self.raise_()


class OnboardingGuide(QObject):
    """新手引导控制器：分步驱动气泡 + 指引卡片，完成后持久化标记"""

    def __init__(self, pet_window):
        super().__init__()
        self._pet = pet_window
        self._step = 0
        self._card = None

    # ---------- 标记持久化 ----------

    @staticmethod
    def should_show():
        """首次启动（或引导版本升级）时返回 True"""
        if not config.ONBOARDING_ENABLED:
            return False
        try:
            if os.path.exists(config.ONBOARDING_FLAG_FILE):
                with open(config.ONBOARDING_FLAG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return not (data.get("done") and data.get("version", 0) >= ONBOARDING_VERSION)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return True

    @staticmethod
    def mark_done():
        try:
            with open(config.ONBOARDING_FLAG_FILE, "w", encoding="utf-8") as f:
                json.dump({"done": True, "version": ONBOARDING_VERSION}, f)
        except OSError as e:
            logger.debug(f"[引导] 标记写入失败: {e}")

    # ---------- 流程控制 ----------

    @property
    def running(self):
        return self._card is not None

    def start(self):
        self._step = 0
        self._card = GuideCard(self._next, self._skip)
        self._show_step()

    def _show_step(self):
        bubble_text, card_text = STEPS[self._step]
        # 气泡复用宠物头顶气泡（第 2/3 步指向猫咪；第 4 步额外指向工具栏区域）
        self._pet._show_temp_bubble(bubble_text, 6000)
        toolbar = getattr(self._pet, "_toolbar", None)
        if toolbar is not None:
            if self._step == len(STEPS) - 1:
                # 第 4 步专注教学：展示并钉住工具栏，让用户看清专注按钮位置
                toolbar.set_pinned(True)
                toolbar.show_near_pet()
            elif toolbar.pinned:
                toolbar.set_pinned(False)
                toolbar.schedule_hide()
        self._card.set_step(self._step, len(STEPS), card_text)
        self._card.show_above(self._pet)

    def _next(self):
        self._step += 1
        if self._step >= len(STEPS):
            self._finish()
        else:
            self._show_step()

    def _skip(self):
        self._finish()

    def _finish(self):
        if self._card is not None:
            self._card.close()
            self._card.deleteLater()
            self._card = None
        # 释放引导期间钉住的工具栏
        toolbar = getattr(self._pet, "_toolbar", None)
        if toolbar is not None and toolbar.pinned:
            toolbar.set_pinned(False)
            toolbar.schedule_hide()
        self.mark_done()
        logger.info("[引导] 新手引导完成")

    def follow_pet(self):
        """宠物被拖拽时卡片跟随"""
        if self._card is not None and self._card.isVisible():
            self._card.show_above(self._pet)

    def close(self):
        if self._card is not None:
            self._card.close()
            self._card = None
