"""
团子陪伴 · 长期记忆系统

每次 AI 对话结束后，后台静默调用 DeepSeek 从最近 3 轮对话中提取用户关键信息
（名字 / 最近在忙 / 偏好 / 重要的事），去重合并到本地 user_memory.json；
发起新对话时把记忆自然注入 System Prompt。所有数据仅存储在本地。

持久化格式（user_memory.json）：
{
  "version": 1,
  "entries": [{"category": "user_name", "content": "小苏", "ts": 1234567890}, ...]
}
"""

import os
import re
import json
import time
import logging

import requests
from PyQt5.QtCore import QThread, pyqtSignal

import config

logger = logging.getLogger(__name__)

# 记忆分类与中文标签（供管理弹窗展示）
MEMORY_CATEGORIES = (
    "user_name", "current_focus", "preferences",
    "todo_item", "shared_moments", "important_notes",
)
CATEGORY_LABELS = {
    "user_name": "名字",
    "current_focus": "最近在忙",
    "preferences": "偏好",
    "todo_item": "待办事项",
    "shared_moments": "一起的经历",
    "important_notes": "重要的事",
}

# 同类条目上限：克制存储，超出后淘汰最旧条目
_MAX_ENTRIES_PER_CATEGORY = 8


def build_extract_prompt(recent_messages):
    """构建记忆提取请求（精简 System Prompt + 最近对话文本）"""
    dialogue = "\n".join(
        f"{'用户' if msg.get('role') == 'user' else '团子'}：{msg.get('content', '')}"
        for msg in recent_messages
    )
    system = (
        "你是信息抽取助手。从桌面宠物与用户的对话中提取用户的关键信息，"
        "只输出一个 JSON 对象，字段为：\n"
        '{"user_name": "用户提到的名字", "current_focus": "用户最近在忙什么", '
        '"preferences": "用户偏好", "todo_item": "用户让你记住的事或待办（如帮我记一下/提醒我）", '
        '"shared_moments": "你们一起经历的场景（如深夜还在工作、一起赶完某个任务），尽量带上时间信息", '
        '"important_notes": "其他重要信息"}\n'
        "对话中没有提到的字段填空字符串。只输出 JSON，不要解释，不要 markdown 代码块。"
    )
    user = f"最近对话：\n{dialogue}\n请输出 JSON。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class MemoryExtractWorker(QThread):
    """后台静默提取工作线程：非流式调用 DeepSeek，产出用户信息 JSON（不阻塞对话主流程）"""

    extracted = pyqtSignal(dict)

    def __init__(self, recent_messages, parent=None):
        super().__init__(parent)
        self.messages = recent_messages

    def run(self):
        try:
            headers = {
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": config.DEEPSEEK_MODEL,
                "messages": build_extract_prompt(self.messages),
                "stream": False,
                "temperature": 0.2,
                "max_tokens": 200,
            }
            resp = requests.post(
                config.DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=20,  # 静默后台任务用短超时，不拖累退出
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            data = self._parse_json(text)
            if data:
                self.extracted.emit(data)
        except Exception as e:
            # 静默失败：记忆提取不影响对话主流程
            logger.debug(f"[长期记忆] 提取失败: {e}")

    @staticmethod
    def _parse_json(text):
        """宽容解析：剥离 markdown 代码块 / 前后杂文，取首个完整 JSON 对象"""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            return None


class UserMemoryManager:
    """长期记忆管理器：加载 / 去重合并 / 删除 / 清空 / 注入 System Prompt"""

    def __init__(self, path=None):
        self._path = path or config.USER_MEMORY_FILE
        self.entries = []  # [{"category", "content", "ts"}]
        self.load()

    # ---------- 持久化 ----------

    def load(self):
        """从本地 JSON 恢复记忆条目"""
        self.entries = []
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("entries", []) if isinstance(data, dict) else []:
                if not isinstance(entry, dict):
                    continue
                category = entry.get("category")
                content = str(entry.get("content", "") or "").strip()
                if category in MEMORY_CATEGORIES and content:
                    self.entries.append({
                        "category": category,
                        "content": content,
                        "ts": int(entry.get("ts", time.time())),
                    })
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.debug(f"[长期记忆] 加载失败，使用空记忆: {e}")

    def save(self):
        """持久化到本地 JSON（数据仅存本地，不上传服务器）"""
        try:
            payload = {"version": 1, "entries": self.entries}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.debug(f"[长期记忆] 保存失败: {e}")

    # ---------- 合并 ----------

    @staticmethod
    def _norm(text):
        """归一化比较：去空白 + 小写，避免「小苏 」与「小苏」重复入库"""
        return re.sub(r"\s+", "", str(text or "")).lower()

    def merge_extracted(self, data):
        """合并提取结果：已有信息不重复存，新信息追加；名字变更时替换旧名字"""
        if not isinstance(data, dict):
            return False
        changed = False
        now = int(time.time())
        for category in MEMORY_CATEGORIES:
            value = str(data.get(category, "") or "").strip()
            if not value:
                continue
            value = value[:80]
            if any(
                e["category"] == category and self._norm(e["content"]) == self._norm(value)
                for e in self.entries
            ):
                continue  # 已有信息不重复存
            if category == "user_name":
                # 名字唯一：变更时替换旧名字
                self.entries = [e for e in self.entries if e["category"] != "user_name"]
            else:
                same = [e for e in self.entries if e["category"] == category]
                if len(same) >= _MAX_ENTRIES_PER_CATEGORY:
                    self.entries.remove(same[0])  # 淘汰最旧，克制存储
            self.entries.append({"category": category, "content": value, "ts": now})
            changed = True
            logger.info(f"[长期记忆] 新增 {category}: {value}")
        if changed:
            self.save()
        return changed

    # ---------- 管理 ----------

    def remove_entry(self, index):
        """按索引删除单条记忆"""
        if 0 <= index < len(self.entries):
            removed = self.entries.pop(index)
            self.save()
            logger.info(f"[长期记忆] 删除: {removed['category']} - {removed['content']}")
            return True
        return False

    def clear(self):
        """清空所有记忆"""
        self.entries = []
        self.save()
        logger.info("[长期记忆] 已清空全部记忆")

    # ---------- 注入 ----------

    def as_prompt(self):
        """把记忆转为自然融入的 System Prompt 片段（无记忆时返回空串）"""
        if not self.entries:
            return ""
        lines = [
            f"· {CATEGORY_LABELS.get(e['category'], e['category'])}：{e['content']}"
            for e in self.entries
        ]
        return (
            "你已经认识这个用户一段时间了，关于TA你记得：\n"
            + "\n".join(lines)
            + "\n自然地运用这些记忆，不要生硬背诵，不要每次都提「我记得你说过」或「根据我的记忆」。"
        )
