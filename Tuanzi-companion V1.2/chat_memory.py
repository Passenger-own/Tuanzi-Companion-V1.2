"""
团子陪伴 · AI 对话记忆管理（V1.1 P0）

策略：轮次摘要压缩（rolling summary）
- 发给模型的上下文 = 人设 system + 早期对话摘要 + 最近 N 轮全文
- 全量历史堆积会导致上下文稀释、人设漂移（可用性测试中 AI 对话满意度 3.4/5 的核心痛点）
- 超过阈值后，由 ai_chat 调用一次摘要请求，把更早的对话压缩成一段摘要

持久化格式（chat_history.json v2）：
{
  "version": 2,
  "summary": "早期对话摘要…",
  "messages": [{"role": "user"/"assistant", "content": "...", "ts": 1234567890}, ...]
}
兼容 v1（纯消息 list），加载时自动迁移。
"""

import os
import json
import time
import logging

import config

logger = logging.getLogger(__name__)


class ChatMemoryManager:
    """轮次摘要压缩的对话历史管理器"""

    SUMMARY_PREFIX = "【早期对话摘要】"

    def __init__(self, path=None):
        self._path = path or config.CHAT_HISTORY_FILE
        self.summary = ""
        self.messages = []  # [{"role","content","ts"}]，仅 user/assistant
        self.persona = config.AI_DEFAULT_PERSONA  # 当前选择的情绪人设
        self.load()

    # ---------- 持久化 ----------

    def load(self):
        """加载历史；兼容 v1 纯 list 格式自动迁移"""
        self.summary = ""
        self.messages = []
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # v1：纯消息数组 → 全量作为未压缩历史迁移
                for msg in data:
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        self.messages.append({
                            "role": msg["role"],
                            "content": msg["content"],
                            "ts": int(time.time()),
                        })
                logger.info(f"[记忆] 迁移 v1 历史 {len(self.messages)} 条")
            elif isinstance(data, dict):
                self.summary = str(data.get("summary", "") or "")
                persona = str(data.get("persona", "") or "")
                if persona in config.AI_PERSONAS:
                    self.persona = persona
                for msg in data.get("messages", []):
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        self.messages.append({
                            "role": msg["role"],
                            "content": str(msg["content"]),
                            "ts": int(msg.get("ts", time.time())),
                        })
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.debug(f"[记忆] 加载失败，使用空历史: {e}")

    def save(self):
        """持久化到本地 JSON（数据本地存储、对话零二次分发）"""
        try:
            payload = {
                "version": 2,
                "summary": self.summary,
                "persona": self.persona,
                "messages": self.messages,
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.debug(f"[记忆] 保存失败: {e}")

    # ---------- 写入 ----------

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content, "ts": int(time.time())})
        self.save()

    def add_exchange(self, user_text, assistant_text):
        self.add_message("user", user_text)
        self.add_message("assistant", assistant_text)

    def clear(self):
        self.summary = ""
        self.messages = []
        self.save()

    # ---------- 上下文构建 ----------

    def turn_count(self):
        """一轮 = 一次 user + 一次 assistant"""
        return len(self.messages) // 2

    def _recent_messages(self):
        keep = config.CHAT_RECENT_TURNS * 2
        return self.messages[-keep:] if keep > 0 else []

    def build_context(self, system_prompt):
        """构建发给模型的 messages：人设 system + 摘要 system + 最近 N 轮全文"""
        context = [{"role": "system", "content": system_prompt}]
        if self.summary:
            context.append({
                "role": "system",
                "content": f"{self.SUMMARY_PREFIX}{self.summary}",
            })
        for msg in self._recent_messages():
            context.append({"role": msg["role"], "content": msg["content"]})
        return context

    # ---------- 压缩 ----------

    def needs_compression(self):
        """超过阈值且存在未被摘要覆盖的早期内容时触发"""
        return self.turn_count() > config.CHAT_COMPRESS_AFTER_TURNS

    def get_compressible_messages(self):
        """取出待压缩的早期消息（最近 N 轮之前的部分），返回副本供摘要请求使用"""
        keep = config.CHAT_RECENT_TURNS * 2
        overflow = len(self.messages) - keep
        if overflow <= 0:
            return []
        return list(self.messages[:overflow])

    def build_summary_request(self, old_messages):
        """构建摘要请求的 messages：合并已有摘要 + 早期对话 → 新摘要"""
        lines = []
        for msg in old_messages:
            speaker = "主人" if msg["role"] == "user" else config.PET_NAME
            lines.append(f"{speaker}：{msg['content']}")
        dialogue = "\n".join(lines)
        prior = f"已有摘要：{self.summary}\n\n" if self.summary else ""
        prompt = (
            f"{prior}以下是桌面宠物「{config.PET_NAME}」与主人的早期对话记录。\n"
            f"请把已有摘要与这些对话合并，用第三人称提炼为一段不超过 "
            f"{config.CHAT_SUMMARY_MAX_CHARS} 字的摘要，保留：\n"
            "1. 主人的称呼/偏好/重要个人信息\n"
            "2. 主人的情绪状态与重要事件\n"
            "3. 双方形成的默契或约定\n"
            "只输出摘要正文，不要解释、不要列表、不要引号。\n\n"
            f"对话记录：\n{dialogue}"
        )
        return [{"role": "user", "content": prompt}]

    def apply_compression(self, old_messages, new_summary):
        """摘要完成后应用：仅当被压缩的消息仍是当前历史前缀时才替换，避免竞态丢消息"""
        new_summary = (new_summary or "").strip()
        if not new_summary:
            return False
        n = len(old_messages)
        if self.messages[:n] != old_messages:
            # 压缩期间历史已变化（理论上单用户顺序聊天不会触发），放弃本次合并
            logger.warning("[记忆] 历史已变化，跳过摘要合并")
            return False
        self.messages = self.messages[n:]
        self.summary = new_summary[: config.CHAT_SUMMARY_MAX_CHARS * 2]
        self.save()
        logger.info(f"[记忆] 压缩完成：移除早期 {n} 条，摘要 {len(self.summary)} 字")
        return True
