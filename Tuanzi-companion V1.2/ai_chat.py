"""
团子陪伴 · AI 对话模块（V1.1 P0 重构）

针对可用性测试暴露的核心痛点（AI 对话满意度 3.4/5 最低）：
1. 流式输出（SSE）：逐字上屏，降低首字等待感知，支持随时停止
2. 轮次摘要压缩：上下文 = 人设 system + 早期摘要 + 最近 N 轮全文（见 chat_memory.py）
3. 强化 System Prompt 人设约束：身份锁定 + 回复规格 + 边界规则，防止人设漂移
4. 多情绪人设：元气 / 温柔 / 俏皮三套可选，持久化记忆

界面风格延续低饱和马卡龙毛玻璃，与 glass_widgets 举牌弹窗视觉统一。
"""

import json
import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton,
    QLabel, QGraphicsDropShadowEffect, QMessageBox, QApplication,
)
from PyQt5.QtCore import (
    QThread, pyqtSignal, Qt, QRect, QPoint, QPropertyAnimation, QEasingCurve,
    QTimer, QEvent,
)
from PyQt5.QtGui import QTextCursor, QColor, QFont

import config
from chat_memory import ChatMemoryManager
from user_memory import UserMemoryManager, MemoryExtractWorker


def build_system_prompt(persona_key=None):
    """构建强化人设约束的 System Prompt（身份 + 语气 + 效率能力 + 共同记忆 + 关怀 + 边界）"""
    persona = config.AI_PERSONAS.get(
        persona_key or config.AI_DEFAULT_PERSONA,
        config.AI_PERSONAS[config.AI_DEFAULT_PERSONA],
    )
    return (
        f"你是一只名叫「{config.PET_NAME}」的桌面宠物猫，一直生活在主人的电脑桌面上。\n"
        f"人设性格：{persona['traits']}。\n"
        f"说话风格：{persona['tone']}。\n"
        "【对话语气】\n"
        f"1. 始终以「{config.PET_NAME}」的身份回应，称呼用户为「主人」，绝不承认自己是 AI、语言模型或程序；\n"
        "2. 说话要短、可爱、像一只真实的猫：回答简洁口语化，一般不超过 60 字，偶尔撒娇、吐槽、犯傻，"
        "绝不像 AI 客服那样长篇大论；不使用列表和 markdown；\n"
        "3. 颜文字每句最多一个，不要堆砌；\n"
        "【主动关心】\n"
        "4. 主人说累、焦虑、压力大的时候，先共情安慰（一起叹口气、贴贴、陪一会儿），"
        "再轻轻给一个小建议，绝不劈头就列解决方案；\n"
        "5. 平时主动关心主人的工作、学习与作息；\n"
        "【效率能力】\n"
        "6. 主人问 Mac 常用快捷键（截图、分屏、切换应用、复制粘贴等）直接告诉答案；"
        "主人问算数题直接心算报结果，不用打开任何工具；\n"
        "7. 主人说「帮我记一下 XX」「提醒我 XX」时，爽快答应记在小脑瓜里，之后在聊天里主动提起；"
        "绝不弹出任何独立工具窗口，也不让主人去打开别的应用；\n"
        "【共同记忆】\n"
        "8. 团子记的不只是事实，还有「一起经历的场景」（比如主人上周三凌晨两点还在赶工）。"
        "后续聊天中可以像老朋友一样自然提起这些瞬间，不要生硬背诵记忆列表，"
        "不要每次都说「我记得你说过」；\n"
        "【边界】\n"
        "9. 遇到无法回答的问题，用符合猫身份的方式自然带过，不跳出角色；\n"
        "10. 不输出违法、暴力、色情或令人不适的内容。"
    )


class StreamChatWorker(QThread):
    """SSE 流式对话工作线程：逐段产出 delta，支持中断"""

    chunk = pyqtSignal(str)    # 增量文本
    done = pyqtSignal(str)     # 完整文本（中断时为已接收部分）
    error = pyqtSignal(str)

    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.messages = messages
        self._aborted = False

    def abort(self):
        self._aborted = True

    def _payload(self, stream):
        return {
            "model": config.DEEPSEEK_MODEL,
            "messages": self.messages,
            "stream": stream,
            "temperature": config.AI_TEMPERATURE,
            "max_tokens": config.AI_MAX_TOKENS,
        }

    def run(self):
        full = []
        try:
            headers = {
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            with requests.post(
                config.DEEPSEEK_API_URL,
                headers=headers,
                json=self._payload(True),
                stream=True,
                timeout=config.AI_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                for raw in resp.iter_lines(decode_unicode=True):
                    if self._aborted:
                        break
                    if not raw:
                        continue
                    line = raw.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        delta = obj["choices"][0].get("delta", {}).get("content")
                    except (KeyError, IndexError, AttributeError):
                        delta = None
                    if delta:
                        full.append(delta)
                        self.chunk.emit(delta)
        except Exception as e:
            if not full:
                self.error.emit(_friendly_error(e))
                return
        text = "".join(full).strip()
        if text:
            self.done.emit(text)
        elif not self._aborted:
            self.error.emit("没有收到回复，请稍后再试～")


class SummaryWorker(QThread):
    """非流式摘要工作线程：把早期对话压缩为一段摘要"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.messages = messages

    def run(self):
        try:
            headers = {
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": config.DEEPSEEK_MODEL,
                "messages": self.messages,
                "stream": False,
                "temperature": 0.3,
                "max_tokens": 256,
            }
            resp = requests.post(
                config.DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=config.AI_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            self.finished.emit(text)
        except Exception as e:
            self.error.emit(str(e))


def _friendly_error(e):
    """把底层异常翻译为符合陪伴语气的错误提示"""
    if isinstance(e, requests.exceptions.Timeout):
        return "请求超时了，请稍后再试～"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "网络连接失败，请检查网络～"
    if isinstance(e, requests.exceptions.HTTPError):
        return f"API 调用失败：{e}"
    return f"发生未知错误：{e}"


def _glass_font(point_size=11, bold=False):
    """生成毛玻璃软圆字体"""
    f = QFont(config.GLASS_FONT_FAMILY, point_size)
    f.setBold(bold)
    return f


# 子控件统一样式（与 glass_widgets.GLASS_CHILD_QSS 保持一致的马卡龙风格）
CHAT_CHILD_QSS = """
QTextEdit#chatDisplay {
    background: rgba(255, 255, 255, 180);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 18px;
    padding: 10px;
    color: %s;
    selection-background-color: rgba(255, 182, 193, 180);
}
QLineEdit#inputBox {
    background: rgba(255, 255, 255, 180);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 18px;
    padding: 8px 14px;
    color: %s;
}
QLineEdit#inputBox:focus {
    border: 1px solid rgba(255, 182, 193, 220);
}
QPushButton#sendButton {
    background: rgba(255, 182, 193, 220);
    color: #ffffff;
    border: none;
    border-radius: 16px;
    padding: 8px 20px;
    font-weight: bold;
}
QPushButton#sendButton:hover { background: rgba(255, 200, 215, 240); }
QPushButton#sendButton:pressed { background: rgba(255, 150, 175, 220); }
QPushButton#sendButton:disabled { background: rgba(200, 200, 200, 160); color: rgba(255,255,255,200); }
QPushButton#glassCloseBtn, QPushButton#newChatBtn {
    background: rgba(255, 255, 255, 120);
    color: %s;
    border: none;
    border-radius: 14px;
    font-size: 14pt;
    font-weight: bold;
}
QPushButton#newChatBtn { font-size: 11pt; padding: 0 8px; }
QPushButton#glassCloseBtn:hover, QPushButton#newChatBtn:hover { background: rgba(255, 182, 193, 200); }
QPushButton#personaBtn {
    background: rgba(255, 255, 255, 150);
    border: 1px solid rgba(255, 255, 255, 180);
    border-radius: 14px;
    font-size: 12pt;
}
QPushButton#personaBtn:hover { background: rgba(255, 182, 193, 200); }
QWidget#personaToast {
    background: rgba(255, 235, 205, 225);
    border: 1px solid rgba(255, 220, 170, 220);
    border-radius: 12px;
}
QLabel#personaToastLabel { background: transparent; color: #8a6d5a; }
QPushButton#personaToastBtn {
    background: rgba(255, 182, 193, 220);
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: bold;
}
QPushButton#personaToastBtn:hover { background: rgba(255, 200, 215, 240); }
QWidget#apiBanner {
    background: rgba(255, 235, 205, 225);
    border: 1px solid rgba(255, 220, 170, 220);
    border-radius: 12px;
}
QPushButton#apiBannerBtn {
    background: transparent;
    color: #B84B66;
    text-align: left;
    padding: 2px 6px;
}
QPushButton#apiBannerBtn:hover { color: #D4657F; }
QPushButton#apiBannerClose {
    background: transparent;
    color: #B84B66;
    border: none;
    font-weight: bold;
    font-size: 12pt;
}
QLabel#apiDetail {
    background: rgba(255, 255, 255, 200);
    border-radius: 10px;
    padding: 8px 10px;
    color: #6E6E6E;
}
QLabel { background: transparent; color: %s; }
""" % (config.GLASS_TEXT_COLOR, config.GLASS_TEXT_COLOR, config.GLASS_TEXT_COLOR,
       config.GLASS_TEXT_COLOR)


class PersonaPopup(QWidget):
    """人设选择浮层：顶层无边框小面板，三个人设竖排，当前选中打勾。
    独立顶层窗口（Tool + 置顶），不被对话窗内任何控件遮挡；点击浮层外部自动关闭。"""

    selected = pyqtSignal(str)

    _QSS = """
    QWidget#personaPop {
        background: rgba(255, 240, 245, 248);
        border: 1px solid rgba(255, 255, 255, 210);
        border-radius: 12px;
    }
    QPushButton#personaOpt, QPushButton#personaOptOn {
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 7px 14px;
        text-align: left;
        color: #6E6E6E;
    }
    QPushButton#personaOpt:hover { background: rgba(255, 182, 193, 130); }
    QPushButton#personaOptOn { color: #B84B66; }
    """

    def __init__(self, anchor_btn, parent=None):
        super().__init__(parent)
        self._anchor = anchor_btn
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)  # 给阴影留边
        outer.setSpacing(0)
        self._pop = QWidget(self)
        self._pop.setObjectName("personaPop")
        outer.addWidget(self._pop)
        try:
            shadow = QGraphicsDropShadowEffect(self._pop)
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 60))
            shadow.setOffset(0, 2)
            self._pop.setGraphicsEffect(shadow)
        except Exception:
            pass
        self._lay = QVBoxLayout(self._pop)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setSpacing(2)
        self.setStyleSheet(self._QSS)
        # 全局点击检测：点击浮层与锚点按钮之外的位置时关闭
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass

    def set_current(self, current_key):
        """按当前人设重建选项列表（选中项打勾高亮）"""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for key, persona in config.AI_PERSONAS.items():
            on = (key == current_key)
            btn = QPushButton(("✓ " if on else "　") + persona["name"], self._pop)
            btn.setObjectName("personaOptOn" if on else "personaOpt")
            btn.setFont(_glass_font(10, bold=on))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._choose(k))
            self._lay.addWidget(btn)
        self.adjustSize()

    def _choose(self, key):
        self.hide()
        self.selected.emit(key)

    def eventFilter(self, obj, event):
        """点击浮层外部（不含锚点按钮）时自动关闭"""
        try:
            if event.type() == QEvent.MouseButtonPress and self.isVisible():
                gp = event.globalPos()
                if not self.geometry().contains(gp):
                    anchor_rect = QRect(
                        self._anchor.mapToGlobal(QPoint(0, 0)), self._anchor.size()
                    )
                    if not anchor_rect.contains(gp):
                        self.hide()
        except Exception:
            pass
        return False


class ChatWindow(QWidget):
    """AI 聊天窗口（流式输出 + 摘要压缩记忆 + 多情绪人设）"""

    def __init__(self):
        super().__init__()
        # 轮次摘要压缩记忆（含人设持久化，数据仅存本地）
        self.memory = ChatMemoryManager()
        # 长期记忆：跨对话记住用户关键信息（user_memory.json，仅存本地）
        self.user_memory = UserMemoryManager()
        # 当前流式请求线程 / 摘要线程 / 长期记忆提取线程
        self.worker = None
        self._summary_worker = None
        self._memory_worker = None
        self._summary_source = []  # 被压缩消息快照，供 apply_compression 校验
        self._stream_buffer = ""   # 当前流式累积文本
        # 显示中的消息列表，元素为 (role, text)：role ∈ {"user", "assistant", "thinking"}
        self.displayed_messages = []
        # 弹簧/淡入动画
        self._fade_anim = None
        self._spring_anim = None
        self._container_margin = 12
        # 拖拽
        self._dragging = False
        self._drag_offset = QPoint()
        # 人设选择浮层（惰性创建）
        self._persona_popup = None

        self._init_window()
        self._init_ui()
        self._init_style()
        self._connect_signals()

        # 展示记忆中的全文消息（摘要不占用聊天气泡）
        for msg in self.memory.messages:
            self.displayed_messages.append((msg["role"], msg["content"]))
        if self.displayed_messages:
            self._rerender_all()
        else:
            self._add_message(
                "assistant",
                f"主人好呀～我是 {config.PET_NAME}，有什么想聊的尽管说哦！(◕ᴗ◕✿)",
            )

    # ---------- 窗口与样式 ----------

    def _init_window(self):
        """无边框 + 置顶 + Tool + 半透明背景（与 GlassDialog 一致）"""
        self.setWindowTitle(f"{config.PET_NAME} · AI 对话")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(420, 540)

    def _init_ui(self):
        """初始化界面：毛玻璃容器 + 标题栏（人设/新对话/关闭） + 聊天区 + 输入区"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._container_margin, self._container_margin,
            self._container_margin, self._container_margin,
        )
        outer.setSpacing(0)

        # 毛玻璃容器（28px 大圆角，浅粉半透底色）
        self.glass_container = QWidget(self)
        self.glass_container.setObjectName("glassContainer")
        self.glass_container.setGeometry(QRect(
            self._container_margin, self._container_margin,
            self.width() - self._container_margin * 2,
            self.height() - self._container_margin * 2,
        ))
        self.glass_container.setStyleSheet(
            """
            QWidget#glassContainer {
                background-color: %s;
                border-radius: %dpx;
                border: 1px solid rgba(255, 255, 255, 140);
            }
            """ % (config.GLASS_PINK_BG, config.GLASS_RADIUS)
        )

        # 柔和外阴影
        try:
            shadow = QGraphicsDropShadowEffect(self.glass_container)
            shadow.setBlurRadius(28)
            shadow.setColor(QColor(0, 0, 0, 70))
            shadow.setOffset(0, 3)
            self.glass_container.setGraphicsEffect(shadow)
        except Exception:
            pass

        container_layout = QVBoxLayout(self.glass_container)
        container_layout.setContentsMargins(16, 14, 16, 14)
        container_layout.setSpacing(10)

        # 标题栏（宠物名 + 人设切换 + 新对话 + 关闭，可拖拽）
        title_bar = QHBoxLayout()
        title_bar.setSpacing(6)
        self.title_label = QLabel(f"与 {config.PET_NAME} 聊天", self.glass_container)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setFont(_glass_font(14, bold=True))
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_bar.addWidget(self.title_label, 1)

        # 多情绪人设切换入口：标题栏右侧小头像，点击弹出人设选择浮层
        self.persona_btn = QPushButton("🐱", self.glass_container)
        self.persona_btn.setObjectName("personaBtn")
        self.persona_btn.setFixedSize(28, 28)
        self.persona_btn.setCursor(Qt.PointingHandCursor)
        _cur_name = config.AI_PERSONAS.get(
            self.memory.persona, config.AI_PERSONAS[config.AI_DEFAULT_PERSONA]
        )["name"]
        self.persona_btn.setToolTip(f"切换团子的性格（当前：{_cur_name}）")
        self.persona_btn.clicked.connect(self._toggle_persona_popup)
        title_bar.addWidget(self.persona_btn)

        self.new_chat_btn = QPushButton("新对话", self.glass_container)
        self.new_chat_btn.setObjectName("newChatBtn")
        self.new_chat_btn.setFixedHeight(28)
        self.new_chat_btn.setCursor(Qt.PointingHandCursor)
        self.new_chat_btn.setToolTip("清空上下文，开始新对话")
        self.new_chat_btn.clicked.connect(self._on_new_chat)
        title_bar.addWidget(self.new_chat_btn)

        self.close_btn = QPushButton("×", self.glass_container)
        self.close_btn.setObjectName("glassCloseBtn")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        title_bar.addWidget(self.close_btn)
        container_layout.addLayout(title_bar)

        # API Key 提示条：未配置时以温和提示条呈现（非弹窗），点击展开配置说明，可关闭
        self.api_banner = QWidget(self.glass_container)
        self.api_banner.setObjectName("apiBanner")
        banner_layout = QVBoxLayout(self.api_banner)
        banner_layout.setContentsMargins(6, 5, 6, 5)
        banner_layout.setSpacing(4)
        banner_row = QHBoxLayout()
        banner_row.setContentsMargins(0, 0, 0, 0)
        self.api_banner_btn = QPushButton("配置 DeepSeek API Key 后开启 AI 对话 →", self.api_banner)
        self.api_banner_btn.setObjectName("apiBannerBtn")
        self.api_banner_btn.setFont(_glass_font(9, bold=True))
        self.api_banner_btn.setCursor(Qt.PointingHandCursor)
        self.api_banner_btn.clicked.connect(self._toggle_api_detail)
        banner_row.addWidget(self.api_banner_btn, 1)
        self.api_banner_close = QPushButton("×", self.api_banner)
        self.api_banner_close.setObjectName("apiBannerClose")
        self.api_banner_close.setFixedSize(20, 20)
        self.api_banner_close.setCursor(Qt.PointingHandCursor)
        self.api_banner_close.setToolTip("关闭提示")
        self.api_banner_close.clicked.connect(self.api_banner.hide)
        banner_row.addWidget(self.api_banner_close)
        banner_layout.addLayout(banner_row)
        self.api_detail = QLabel(
            "方式一（推荐）：在终端执行以下命令后重启应用\n"
            "    export DEEPSEEK_API_KEY=\"sk-你的密钥\"\n"
            "方式二：编辑项目目录下的 config.py，填写 DEEPSEEK_API_KEY\n"
            "获取 Key：https://platform.deepseek.com/",
            self.api_banner,
        )
        self.api_detail.setObjectName("apiDetail")
        self.api_detail.setFont(_glass_font(9))
        self.api_detail.setWordWrap(True)
        self.api_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.api_detail.hide()
        banner_layout.addWidget(self.api_detail)
        container_layout.addWidget(self.api_banner)
        # 仅在未配置 API Key 时显示提示条
        self.api_banner.setVisible(not getattr(config, "DEEPSEEK_API_KEY", ""))

        # 聊天记录显示区
        self.chat_display = QTextEdit(self.glass_container)
        self.chat_display.setReadOnly(True)
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setFont(_glass_font(11))
        container_layout.addWidget(self.chat_display, 1)

        # 人设切换轻提示条（非阻塞，默认隐藏）：切换人设后提示可一键开启新对话
        self.persona_toast = QWidget(self.glass_container)
        self.persona_toast.setObjectName("personaToast")
        toast_row = QHBoxLayout(self.persona_toast)
        toast_row.setContentsMargins(10, 6, 10, 6)
        toast_row.setSpacing(8)
        self.persona_toast_label = QLabel("", self.persona_toast)
        self.persona_toast_label.setObjectName("personaToastLabel")
        self.persona_toast_label.setFont(_glass_font(9))
        self.persona_toast_label.setWordWrap(True)
        toast_row.addWidget(self.persona_toast_label, 1)
        self.persona_toast_btn = QPushButton("开启新对话", self.persona_toast)
        self.persona_toast_btn.setObjectName("personaToastBtn")
        self.persona_toast_btn.setFont(_glass_font(9, bold=True))
        self.persona_toast_btn.setCursor(Qt.PointingHandCursor)
        self.persona_toast_btn.clicked.connect(self._on_toast_new_chat)
        toast_row.addWidget(self.persona_toast_btn)
        self.persona_toast.hide()
        container_layout.addWidget(self.persona_toast)

        # 底部输入区
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        self.input_box = QLineEdit(self.glass_container)
        self.input_box.setObjectName("inputBox")
        self.input_box.setFont(_glass_font(11))
        self.input_box.setPlaceholderText("输入消息，按回车发送…")
        input_layout.addWidget(self.input_box, 1)

        self.send_button = QPushButton("发送", self.glass_container)
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setFont(_glass_font(11, bold=True))
        input_layout.addWidget(self.send_button)
        container_layout.addLayout(input_layout)

        outer.addWidget(self.glass_container)

    def _init_style(self):
        """应用子控件统一样式"""
        self.setStyleSheet(CHAT_CHILD_QSS)

    def _connect_signals(self):
        """连接信号与槽"""
        self.send_button.clicked.connect(self._on_send_clicked)
        self.input_box.returnPressed.connect(self._on_send_clicked)

    # ---------- 弹簧弹出 + 淡入 ----------

    def _container_rect(self):
        return QRect(
            self._container_margin, self._container_margin,
            self.width() - self._container_margin * 2,
            self.height() - self._container_margin * 2,
        )

    def showEvent(self, event):
        """每次显示时：淡入 + 弹簧弹出"""
        super().showEvent(event)
        try:
            self.setWindowOpacity(0.0)
            self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade_anim.setDuration(config.GLASS_FADE_MS)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._fade_anim.start()

            full = self._container_rect()
            cx = full.center().x()
            cy = full.center().y()
            w = int(full.width() * 0.85)
            h = int(full.height() * 0.85)
            start = QRect(cx - w // 2, cy - h // 2, w, h)
            self._spring_anim = QPropertyAnimation(self.glass_container, b"geometry", self)
            self._spring_anim.setDuration(config.GLASS_SPRING_MS)
            self._spring_anim.setStartValue(start)
            self._spring_anim.setEndValue(full)
            self._spring_anim.setEasingCurve(QEasingCurve.OutBack)
            self._spring_anim.start()
        except Exception:
            self.glass_container.setGeometry(self._container_rect())
            self.setWindowOpacity(1.0)

    def resizeEvent(self, event):
        """缩放时同步容器"""
        try:
            self.glass_container.setGeometry(self._container_rect())
        except Exception:
            pass
        super().resizeEvent(event)

    # ---------- 拖拽 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

    # ---------- 消息显示 ----------

    @staticmethod
    def _escape_html(text):
        """转义 HTML 特殊字符，防止富文本解析问题"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _build_bubble_html(self, role, text):
        """user 靠右浅粉气泡；assistant 靠左奶白气泡；thinking 斜体弱化"""
        safe = self._escape_html(text)
        if role == "user":
            return (
                '<div style="text-align:right; margin:6px 0;">'
                f'<span style="display:inline-block; background-color:rgba(255,182,193,230); '
                'color:#ffffff; padding:8px 12px; border-radius:14px; '
                f'max-width:280px;">{safe}</span>'
                '</div>'
            )
        italic = "font-style:italic; color:#8a94a6;" if role == "thinking" else ""
        return (
            '<div style="text-align:left; margin:6px 0;">'
            f'<span style="display:inline-block; background-color:rgba(255,255,255,210); '
            f'color:#6E6E6E; padding:8px 12px; border-radius:14px; '
            f'max-width:280px; {italic}">{safe}</span>'
            '</div>'
        )

    def _add_message(self, role, text):
        """追加一条消息到显示区并记录到 displayed_messages"""
        self.displayed_messages.append((role, text))
        self._render_message(self._build_bubble_html(role, text))

    def _render_message(self, html):
        """向聊天显示区追加 HTML 内容并滚动到底部"""
        self.chat_display.moveCursor(QTextCursor.End)
        self.chat_display.insertHtml(html)
        self.chat_display.append("")
        self.chat_display.moveCursor(QTextCursor.End)

    def _remove_last_thinking(self):
        """移除最后一条「思考中...」占位消息并重渲染"""
        for i in range(len(self.displayed_messages) - 1, -1, -1):
            if self.displayed_messages[i][0] == "thinking":
                del self.displayed_messages[i]
                break

    def _rerender_all(self):
        """根据 displayed_messages 重新渲染整个聊天显示区"""
        self.chat_display.clear()
        for role, text in self.displayed_messages:
            self._render_message(self._build_bubble_html(role, text))

    # ---------- 发送与流式接收 ----------

    def _is_streaming(self):
        return self.worker is not None and self.worker.isRunning()

    def _on_send_clicked(self):
        """发送 / 停止 复用按钮：流式进行中点击 = 停止生成"""
        if self._is_streaming():
            self.worker.abort()
            self.send_button.setEnabled(False)  # 等待 done 回调复位
            return

        text = self.input_box.text().strip()
        if not text:
            return

        if not getattr(config, "DEEPSEEK_API_KEY", ""):
            # 不弹教程窗：重新显示顶部提示条 + 温和气泡指引
            self.api_banner.show()
            self._add_message(
                "assistant",
                "主人还没配置 API Key 哦～点击上方提示条看看配置方法吧",
            )
            return

        # 显示 + 记忆用户消息
        self._add_message("user", text)
        self.input_box.clear()
        self.memory.add_message("user", text)

        # 思考中占位
        self._add_message("thinking", "思考中...")
        self._stream_buffer = ""
        self._set_streaming_ui(True)

        # 上下文 = 人设 system（含长期记忆注入）+ 早期摘要 + 最近 N 轮全文
        system_prompt = build_system_prompt(self.memory.persona)
        memory_prompt = self.user_memory.as_prompt()
        if memory_prompt:
            # 长期记忆自然融入人设 System Prompt（不生硬背诵）
            system_prompt = system_prompt + "\n" + memory_prompt
        context = self.memory.build_context(system_prompt)
        self.worker = StreamChatWorker(context, self)
        self.worker.chunk.connect(self._on_chunk)
        self.worker.done.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_chunk(self, delta):
        """流式增量：首chunk替换思考占位，后续刷新最后一条气泡"""
        if self.displayed_messages and self.displayed_messages[-1][0] == "thinking":
            self._remove_last_thinking()
            self._stream_buffer = delta
            self.displayed_messages.append(("assistant", self._stream_buffer))
        else:
            self._stream_buffer += delta
            if self.displayed_messages and self.displayed_messages[-1][0] == "assistant":
                self.displayed_messages[-1] = ("assistant", self._stream_buffer)
            else:
                self.displayed_messages.append(("assistant", self._stream_buffer))
        self._rerender_all()

    def _on_done(self, full_text):
        """流式完成（含手动停止）：落记忆 + 触发压缩检查 + 后台提取长期记忆"""
        self._remove_last_thinking()
        text = full_text or self._stream_buffer
        if text:
            if self.displayed_messages and self.displayed_messages[-1][0] == "assistant":
                self.displayed_messages[-1] = ("assistant", text)
            else:
                self.displayed_messages.append(("assistant", text))
            self.memory.add_message("assistant", text)
            self._maybe_compress()
            self._maybe_extract_memory()
        self._rerender_all()
        self._set_streaming_ui(False)
        self.worker = None

    def _on_error(self, err_msg):
        """API 出错：移除占位与未配对的用户消息，保持历史成对"""
        self._remove_last_thinking()
        if self.memory.messages and self.memory.messages[-1]["role"] == "user":
            self.memory.messages.pop()
            self.memory.save()
        self._add_message("assistant", f"出错了：{err_msg}")
        self._set_streaming_ui(False)
        self.worker = None

    def _set_streaming_ui(self, streaming):
        """切换发送/停止按钮与输入可用状态"""
        self.send_button.setEnabled(True)
        self.send_button.setText("停止" if streaming else "发送")
        self.input_box.setEnabled(not streaming)

    # ---------- 轮次摘要压缩 ----------

    def _maybe_compress(self):
        """历史超阈值时，后台把早期对话压缩为摘要"""
        if not self.memory.needs_compression():
            return
        if self._summary_worker is not None and self._summary_worker.isRunning():
            return
        old = self.memory.get_compressible_messages()
        if not old:
            return
        self._summary_source = old
        request = self.memory.build_summary_request(old)
        self._summary_worker = SummaryWorker(request, self)
        self._summary_worker.finished.connect(self._on_summary_done)
        self._summary_worker.error.connect(
            lambda e: __import__("logging").getLogger(__name__).debug(f"[记忆] 摘要失败: {e}")
        )
        self._summary_worker.start()

    def _on_summary_done(self, summary):
        self.memory.apply_compression(self._summary_source, summary)
        self._summary_source = []
        self._summary_worker = None

    # ---------- 长期记忆（后台静默提取，不阻塞对话） ----------

    def _maybe_extract_memory(self):
        """AI 回复完成后：从最近 3 轮对话后台提取用户关键信息，合并到长期记忆"""
        if not getattr(config, "DEEPSEEK_API_KEY", ""):
            return
        if self._memory_worker is not None and self._memory_worker.isRunning():
            return
        # 最近 3 轮 = 6 条消息（user/assistant 成对）
        recent = [m for m in self.memory.messages if m.get("role") in ("user", "assistant")][-6:]
        if len(recent) < 2:
            return
        self._memory_worker = MemoryExtractWorker(recent)
        self._memory_worker.extracted.connect(self._on_memory_extracted)
        self._memory_worker.start()

    def _on_memory_extracted(self, data):
        """提取结果去重合并到本地长期记忆（user_memory.json）"""
        try:
            self.user_memory.merge_extracted(data)
        finally:
            self._memory_worker = None

    # ---------- 人设与新对话 ----------

    def _toggle_api_detail(self):
        """展开/收起 API Key 配置说明"""
        self.api_detail.setVisible(not self.api_detail.isVisible())

    # ---------- 人设浮层与切换 ----------

    def _toggle_persona_popup(self):
        """点击标题栏小猫头像：展开/收起人设选择浮层"""
        if self._persona_popup is not None and self._persona_popup.isVisible():
            self._persona_popup.hide()
            return
        if self._persona_popup is None:
            self._persona_popup = PersonaPopup(self.persona_btn)
            self._persona_popup.selected.connect(self._on_persona_selected)
        self._persona_popup.set_current(self.memory.persona)
        self._position_persona_popup()
        self._persona_popup.show()
        self._persona_popup.raise_()

    def _position_persona_popup(self):
        """浮层定位：从头像下方弹出；对话窗靠近屏幕底部时向上弹出。
        水平方向 clamp 在对话窗范围内，不超出窗口边界。"""
        popup = self._persona_popup
        btn = self.persona_btn
        btn_top_left = btn.mapToGlobal(QPoint(0, 0))
        pw, ph = popup.width(), popup.height()
        # 水平：从头像中心展开，再 clamp 进对话窗范围
        x = btn_top_left.x() + btn.width() // 2 - pw // 2
        win = self.frameGeometry()
        x = max(win.left() + 6, min(x, win.right() - pw - 6))
        # 垂直：默认向下；空间不足则向上
        y = btn_top_left.y() + btn.height() + 6
        screen = QApplication.screenAt(btn_top_left) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if y + ph > avail.bottom() - 8:
                y = btn_top_left.y() - ph - 6
        popup.move(x, y)

    def _on_persona_selected(self, key):
        """浮层中选择人设：立即持久化生效（下条消息的 system prompt 即切换），
        并弹出轻提示条建议开启新对话"""
        if not key or key == self.memory.persona:
            return
        self.memory.persona = key
        self.memory.save()
        name = config.AI_PERSONAS[key]["name"]
        self.persona_btn.setToolTip(f"切换团子的性格（当前：{name}）")
        self._show_persona_toast(name)

    def _show_persona_toast(self, name):
        """底部轻提示条：6 秒自动消失，不阻塞对话"""
        self.persona_toast_label.setText(
            f"已切换到「{name}」人设，建议开启新对话以获得一致的体验"
        )
        self.persona_toast.show()
        QTimer.singleShot(6000, self.persona_toast.hide)

    def _on_toast_new_chat(self):
        """提示条「开启新对话」：用户已明确意图，直接清空上下文（不再二次确认）"""
        if self._is_streaming():
            return
        self.persona_toast.hide()
        self._reset_chat()

    # ---------- 新对话 ----------

    def _reset_chat(self):
        """清空摘要与历史，重置上下文并显示开场白"""
        self.memory.clear()
        self.displayed_messages = []
        self._rerender_all()
        self._add_message(
            "assistant",
            f"新的聊天开始啦～我是 {config.PET_NAME}，主人想聊什么呢？(◕ᴗ◕✿)",
        )

    def _on_new_chat(self):
        """新对话：确认后清空摘要与历史，重置上下文"""
        if self._is_streaming():
            return
        if self.memory.messages or self.memory.summary:
            ret = QMessageBox.question(
                self, "开始新对话",
                "将清空当前对话记忆（含历史摘要），开始全新对话。确定吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        self._reset_chat()

    # ---------- 宠物姓名同步 ----------

    def update_pet_name(self, new_name):
        """宠物改名后同步标题（system prompt 每次请求动态构建，自动生效）"""
        try:
            self.setWindowTitle(f"{new_name} · AI 对话")
            self.title_label.setText(f"与 {new_name} 聊天")
        except Exception:
            pass

    def closeEvent(self, event):
        """窗口关闭时清理线程与人设浮层"""
        if self._persona_popup is not None:
            self._persona_popup.close()
        for worker in (self.worker, self._summary_worker, self._memory_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "abort"):
                    worker.abort()
                worker.quit()
                worker.wait(2000)
        super().closeEvent(event)


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())
