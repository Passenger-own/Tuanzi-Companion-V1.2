"""
桌面宠物配置文件 v8.0.0 (V1.1)
V1.0：视频渲染重构、专注模式退出规则、全动作过渡优化、窗口置顶
V1.1 P0：八状态交互注册表、浮动工具栏入口重构、新手引导、
         AI 流式输出 + 轮次摘要压缩 + 强化人设约束 + 多情绪人设
V1.1 P1：GIF 预缩放渲染（帧率优化）、自定义素材上传

获取 DeepSeek API Key: https://platform.deepseek.com/
"""
import os

# ============ DeepSeek API 配置 ============
# 优先从环境变量读取（推荐），也可直接在下方填写
# 开源发布时请保持此处为空，通过环境变量 DEEPSEEK_API_KEY 注入
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ============ AI 对话增强（V1.1 P0） ============
# 流式输出：SSE 逐字上屏，降低首字等待感知，提升 C 端对话流畅度
AI_STREAM_ENABLED = True
AI_TEMPERATURE = 0.8
AI_MAX_TOKENS = 300
AI_REQUEST_TIMEOUT = 60

# 轮次摘要压缩的历史管理策略：
# 发给模型的上下文 = 人设 system + 早期对话摘要 system + 最近 N 轮全文
# 解决「全量历史堆积 → 上下文稀释 → 人设漂移」的核心痛点
CHAT_RECENT_TURNS = 6          # 最近 6 轮（12 条）保留全文
CHAT_COMPRESS_AFTER_TURNS = 12  # 聊满 12 轮后触发早期历史压缩
CHAT_SUMMARY_MAX_CHARS = 200   # 摘要长度约束

# 多情绪 AI 人设（长期方向落地：3 套可选，强化身份锁定防止人设漂移）
AI_DEFAULT_PERSONA = "energetic"
AI_PERSONAS = {
    "energetic": {
        "name": "元气团子",
        "traits": "元气满满、活泼好动，是主人的加油担当，喜欢给主人打气",
        "tone": "语气明快有感染力，适度使用感叹号和可爱颜文字",
    },
    "gentle": {
        "name": "温柔治愈",
        "traits": "温柔安静、细腻体贴，善于倾听，能察觉并安抚主人的情绪",
        "tone": "语气轻柔舒缓，像抱抱一样温暖，颜文字使用克制",
    },
    "playful": {
        "name": "俏皮吐槽",
        "traits": "俏皮机灵，偶尔善意吐槽主人，像损友一样陪伴，幽默但不冒犯",
        "tone": "语气轻松诙谐，可以小调侃但绝不阴阳怪气、不打击主人",
    },
}

# ============ 提醒设置 ============
# 久坐提醒已改名「活动提醒」（坐久了起来动一动）；锻炼提醒不再单独设间隔，
# 仅保留锻炼打卡入口，EXERCISE_REMINDER_INTERVAL/MSG 保留作历史兼容
SIT_REMINDER_INTERVAL = 60
WATER_REMINDER_INTERVAL = 45
EXERCISE_REMINDER_INTERVAL = 60
SIT_REMINDER_MSG = "坐久啦，起来走两步～"
WATER_REMINDER_MSG = "该喝水了，保持水分摄入很重要哦～"
EXERCISE_REMINDER_MSG = "坐久啦，起来走两步～"

# ============ 宠物设置 ============
PET_NAME = "团子"
PET_SIZE = 150
ANIMATION_INTERVAL = 3000

# ============ 动画触发时间配置 ============
IDLE_TIMEOUT = 30000
SLEEP_TIMEOUT = 300000
LIE_SIDE_CHAT_TIMEOUT = 600000
LIE_BACK_CLICK_COUNT = 3
LIE_BACK_CLICK_WINDOW = 800  # 800ms滚动窗口内连续三击触发撒娇

# ============ 动作冷却配置 ============
ACTION_COOLDOWN = {
    "lie_back": 6000,
    "eat": 0,
    "stretch": 0,
    "happy": 0,
    "idle": 0,
    "lie_side": 0,
    "sleep": 0,
}

# ============ 动画优先级 ============
ACTION_PRIORITY = {
    "idle": 1,
    "lie_side": 2,
    "lie_back": 2,
    "happy": 3,
    "eat": 3,
    "stretch": 3,
    "sleep": 4,
}

# ============ 互斥规则 ============
SLEEP_BLOCKED_ACTIONS = {"happy", "eat", "stretch", "lie_back", "lie_side"}

# ============ 场景限定动作 ============
SCENE_LIMITED_ACTIONS = {"eat", "stretch", "sleep", "lie_side"}
GENERAL_ACTIONS = {"idle", "lie_back", "happy"}
IDLE_ROTATION_TIMEOUT = 60000
IDLE_ROTATION_ACTIONS = []

# ============ lie_back 撒娇 ============
# 撒娇贴贴为一次性动作：只播放一轮后自动回待机（新素材较长，不再循环 2 轮）
LIE_BACK_LOOP_COUNT = 1

# ============ 状态自动降级 ============
SLEEP_AUTO_DOWNGRADE_TIMEOUT = 600000
LIE_SIDE_AUTO_DOWNGRADE_TIMEOUT = 900000

# ============ 事件排队机制 ============
EVENT_QUEUE_ENABLED = True

# ============ 八状态交互系统注册表 ============
# 产品定义：宠物任意时刻处于以下八种交互状态之一。
# 状态机由 pet_window.play_action 做优先级仲裁 + 柔性事件队列，
# 规范 AI 弹窗与交互动画节奏，解决「随机打断工作流」的竞品共性痛点。
INTERACTION_STATES = {
    "idle":     {"name": "待机陪伴", "action": "idle",     "priority": 1, "loop": True,
                 "desc": "默认常驻，呼吸起伏偶尔眨眼，所有动画播完后回归"},
    "happy":    {"name": "开心互动", "action": "happy",    "priority": 3, "loop": False,
                 "desc": "悬停/打卡/面板打开触发，双爪举起"},
    "lie_back": {"name": "撒娇贴贴", "action": "lie_back", "priority": 2, "loop": False,
                 "desc": "三击触发仰躺撒娇，循环2轮后自动回待机"},
    "lie_side": {"name": "轻度专注", "action": "lie_side", "priority": 2, "loop": True,
                 "desc": "轻度专注陪伴态，屏蔽悬停挥手等主动打扰"},
    "eat":      {"name": "喝水",     "action": "eat",      "priority": 3, "loop": False,
                 "desc": "喝水提醒/喝水打卡专属场景动作"},
    "stretch":  {"name": "伸展唤醒", "action": "stretch",  "priority": 3, "loop": False,
                 "desc": "久坐提醒/专注退出/睡眠唤醒的过渡动作"},
    "sleep":    {"name": "深度专注", "action": "sleep",    "priority": 4, "loop": True,
                 "desc": "熟睡屏蔽全部主动交互，最高优先级不可打断"},
    "drag":     {"name": "拖拽移动", "action": None,       "priority": 0, "loop": False,
                 "desc": "全场景长按拖拽移动窗口，不打断当前动画"},
}

# ============ 浮动工具栏（V1.1 P0 入口重构） ============
# 解决可用性测试暴露的「纯隐藏式右键入口 → 59% 用户无法快速触发功能」问题：
# 悬停猫咪即浮现九宫格快捷入口，兼顾视觉纯净度与功能可发现性
TOOLBAR_ENABLED = True
TOOLBAR_AUTO_HIDE_MS = 2500   # 鼠标离开后延迟隐藏

# ============ 新手引导（V1.1 P0） ============
ONBOARDING_ENABLED = True
ONBOARDING_VERSION = 1        # 引导内容版本，升级后可对新版本用户重播

# ============ 气泡交互配置 ============
BUBBLE_ENABLED = True
BUBBLE_DURATION_MS = 3500
BUBBLE_BG_COLOR = (255, 228, 235, 210)      # 浅粉半透明
BUBBLE_TEXT_COLOR = (110, 110, 110)          # 浅灰软圆字体
BUBBLE_ROUNDED_RADIUS = 14
BUBBLE_SHOW_DELAY_MS = 500                   # 动作播放 0.5s 后弹出气泡

# ============ 专注模式退出反馈气泡 ============
# 退出专注时的气泡文案已改为按专注时长分档（见 pet_window._show_focus_exit_bubble）：
# ≤15min / 15-45min / >45min 三档反馈，本常量保留作历史兼容
FOCUS_EXIT_BUBBLE_TEXT = "我睡醒啦！ฅ՞・ᴥ・՞ฅ~"
FOCUS_EXIT_BUBBLE_DELAY_MS = 500  # 伸懒腰播放0.5s后弹出
FOCUS_EXIT_ANIMATION = "stretch"

# 每个动作配套气泡文案（随机切换）
ACTION_BUBBLE_TEXTS = {
    "idle": [
        "乖乖陪你办公中 (๑・̀ㅂ・́)و✧~",
        "安安静静蹲旁边，不打扰你哦ฅ˙Ⱉ˙ฅ",
        "今天天气真好呀～要不要摸摸我？",
        "主人在忙什么呢？需要休息一下吗？",
        "我在这里哦～(=^･ω･^=)",
        "发呆中...思考猫生哲学～",
        "伸个懒腰～主人要不要也活动一下？",
        "看到你就很开心～(๑•̀ㅂ•́)و✧",
    ],
    "lie_back": [
        "软软躺平贴贴你～ฅ՞・ﻌ・՞ฅ~",
        "被你摸舒服啦～蜷成小棉花꒰ঌ˶・༝・˶໒꒱",
    ],
    "lie_side": [
        "瘫成一团小毛球，懒懒放空中～૮₍˶・ᴗ・˶₎ა",
        "晒晒太阳躺平，万事不用急ฅ՞・ﻌ・՞ฅ",
    ],
    "sleep": [
        "呼呼 zzz… 浅浅睡一会，等你叫我～",
        "眼皮沉沉，先打个小盹ฅ˙Ⱉ˙ฅ",
    ],
    "happy": [
        "看到你超开心！挥爪打招呼૮₍˶・༝・˶₎ა",
        "今天也要元气满满喵～ฅ՞・ᴥ・՞ฅ",
    ],
    "eat": [
        "咕嘟咕嘟喝水水🥛~ 你也该喝水啦～",
        "喝水变水润小猫ฅ˙Ⱉ˙ฅ你变成水润小人了吗～",
    ],
    "stretch": [
        "伸个懒腰充充电～",
    ],
}

# ============ 数据存储 ============
# 检测是否在 .app 包内运行：如果是，数据目录放到 ~/Library/Application Support（可写）
# 否则使用项目目录下的 data/（开发模式）
_APP_MODE = os.path.dirname(os.path.abspath(__file__)).endswith("Resources") or \
            ".app/Contents/Resources" in os.path.dirname(os.path.abspath(__file__))

if _APP_MODE:
    _SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/桌面宠物")
    DATA_DIR = os.path.join(_SUPPORT_DIR, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

os.makedirs(DATA_DIR, exist_ok=True)
TODO_FILE = os.path.join(DATA_DIR, "todo.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
CONFIG_FILE = os.path.join(DATA_DIR, "pet_config.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")
# 健康提醒状态持久化（总开关 / 自定义间隔 / 每日打卡记录），重启不丢失
REMINDER_STATE_FILE = os.path.join(DATA_DIR, "reminder_state.json")
# 新手引导完成标记（含引导版本号）
ONBOARDING_FLAG_FILE = os.path.join(DATA_DIR, "onboarding.json")
# 自定义素材（P1）：用户上传的 GIF/视频复制到此目录，映射关系持久化
CUSTOM_ASSETS_DIR = os.path.join(DATA_DIR, "custom_assets")
CUSTOM_MAPPING_FILE = os.path.join(DATA_DIR, "custom_assets.json")
os.makedirs(CUSTOM_ASSETS_DIR, exist_ok=True)
# 长期记忆（任务3）：AI 对话后静默提取的用户关键信息，仅存本地
USER_MEMORY_FILE = os.path.join(DATA_DIR, "user_memory.json")

# ============ 视频动画设置 ============
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
VIDEO_DIR = os.path.join(ASSETS_DIR, "video")

VIDEO_EXTENSIONS = [".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".gif"]

# 绿幕抠像
CHROMA_KEY_ENABLED = True
CHROMA_KEY_COLOR = (0, 255, 0)
CHROMA_KEY_THRESHOLD = 100

# 动作名称 → 视频文件名关键词映射
VIDEO_MAPPING = {
    "idle": "idle",
    "lie_back": "lie_back",
    "lie_side": "lie_side",
    "sleep": "sleep",
    "happy": "happy",
    "eat": "eat",
    "stretch": "stretch",
}

VIDEO_ALIASES = {
    "idle": ["待机", "idle", "sit", "default"],
    "lie_back": ["躺平", "露肚皮", "lie_back", "back", "belly"],
    "lie_side": ["侧躺", "lie_side", "side"],
    "sleep": ["睡觉", "睡眠", "sleep", "sleeping"],
    "happy": ["开心", "蹦跳", "happy", "joy", "play"],
    "eat": ["进食", "喝水", "eat", "drink", "eating"],
    "stretch": ["伸懒腰", "蹭屏幕", "stretch", "yawn"],
}

# 视频重试机制
VIDEO_LOAD_RETRY_COUNT = 3
VIDEO_LOAD_RETRY_DELAY_MS = 200  # 重试间隔

# ============ GIF 渲染优化（V1.1 P1 帧率优化） ============
# 原生 GIF 直出（QMovie，替代 Canvas 逐帧解析）基础上：
# 按宠物显示尺寸预缩放解码，paint 时命中同尺寸直接绘制，
# 免去每帧 SmoothTransformation 重采样，降低 CPU 占用、稳定帧率
GIF_PRESCALED_RENDER = True

# ============ GIF 一次性动作时长上限（毫秒） ============
# 交互素材普遍长达 8~20 秒且自带 loop forever，代码层按时长上限截断：
# 一次性动作只播 2.5~5 秒即冻结收尾回待机，绝不出现 20 秒异常长动作；
# 自定义短素材（总帧数播完仍在上限内）则按总帧数播完一轮即停。
GIF_ONE_SHOT_MAX_MS = {
    "happy": 2000,     # 挥手打招呼（2 秒）
    "eat": 3500,       # 喝水（3.5 秒，素材长 20s，过短会截断动作）
    "stretch": 4000,   # 伸懒腰 / 打哈欠（4 秒，素材长 8s）
    "lie_back": 3000,  # 撒娇贴贴（3 秒，素材长 9s）
}
GIF_ONE_SHOT_DEFAULT_MAX_MS = 3000  # 未登记动作的默认上限

# ============ 全动作过渡配置 ============
# 过渡模式下的淡入淡出时长（毫秒）
TRANSITION_FADE_IN_MS = 150   # 画面淡入
TRANSITION_FADE_OUT_MS = 150  # 画面淡出

# 切回待机（idle）的淡入淡出过渡时长：0.3s，动作收尾不生硬跳切
TRANSITION_RETURN_IDLE_MS = 300

# 分类差异化过渡时长
TRANSITION_SHORT_MS = 200      # 短时微动作（eat）
TRANSITION_LONG_MS = 400       # 长交互动作（stretch/lie_back/sleep）
TRANSITION_FOCUS_EXIT_MS = 600  # 专注模式退出专属过渡（stretch→idle 丝滑衔接）

# 需要独立缓存的高频动作
HIGH_FREQUENCY_ACTIONS = {"idle", "stretch"}

# 预加载缓存数量
PRELOAD_CACHE_SIZE = 5

# ============ 窗口置顶配置 ============
WINDOW_TOP_HINT = True          # 窗口永久置顶
WINDOW_INTERACT_THROUGH = False  # 交互穿透（点击穿透到桌面）
WINDOW_RESTART_PERSIST = True   # 重启后恢复置顶

# 支持的视频文件扩展名（支持macOS CoreMedia格式）
SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mov"]

# ============ 事件 → 触发动作映射 ============
EVENT_ACTION_MAP = {
    "on_launch": "idle",
    "on_hover": "happy",
    "on_drag": "happy",
    "on_click": "idle",
    "on_multi_click": "lie_back",
    "on_chat_open": "idle",
    "on_chat_end": "happy",
    "on_reminder_sit": "stretch",
    "on_reminder_water": "eat",
    "on_water_log": "eat",
    "on_rest_log": "happy",
    "on_intimacy_up": "happy",
    "on_idle_short": "idle",
    "on_idle_long": "sleep",
    "on_no_chat_long": "lie_side",
    "on_focus_mode": "lie_side",
    "on_dnd_mode": "sleep",
}

# ============ 亲密度系统 ============
INTIMACY_ENABLED = True

# ============ 健康提醒增强配置 ============
# 总开关默认值（运行时从 reminder_state.json 恢复）
HEALTH_REMINDER_ENABLED = True
# 自定义间隔范围（分钟）
HEALTH_REMINDER_MIN_MINUTES = 1
HEALTH_REMINDER_MAX_MINUTES = 90
# 稍后提醒延迟（毫秒）：喝水延后 10 分钟，久坐/锻炼延后 15 分钟
WATER_SNOOZE_DELAY_MS = 10 * 60 * 1000
SIT_SNOOZE_DELAY_MS = 15 * 60 * 1000
EXERCISE_SNOOZE_DELAY_MS = 15 * 60 * 1000
# 提醒触发时的随机气泡文案（不粗暴打断当前动画，平滑过渡）
WATER_REMINDER_BUBBLES = [
    "咕嘟咕嘟补水啦💧~ฅ՞•ﻌ•՞ฅ",
    "该喝口水润润嗓子哦",
]
SIT_REMINDER_BUBBLES = [
    "坐久啦，起来走两步～",
]
EXERCISE_REMINDER_BUBBLES = [
    "起来锻炼一下，元气满满💪～",
    "伸伸胳膊踢踢腿，身体棒棒哦～",
]
# 打卡完成后的反馈气泡
WATER_DONE_BUBBLE = "真棒！多喝水皮肤好好～"
SIT_DONE_BUBBLE = "活动完更有精神啦！"
EXERCISE_DONE_BUBBLE = "锻炼完成，元气满满！💪"
# 喂团子喝水（纯互动，不记录数据）
WATER_FEED_BUBBLE = "咕噜咕噜～谢谢主人💧"
# 计算器完成反馈气泡
CALC_DONE_BUBBLE = "算好啦～ฅ˙Ⱉ˙ฅ"

# 工具面板打开时的气泡文案（每个功能不同）
TOOL_PANEL_BUBBLES = {
    "todo": "一起看看今天要做些什么吧～📋",
    "calc": "需要算什么？我来帮你～🧮",
    "notes": "随手记下重要的事情吧～📝",
    "shortcuts": "常用快捷键都在这里啦～⌨️",
    "reminder_settings": "来调整喝水和久坐提醒吧～⏰",
    "memory": "这些都是团子记住的关于你的事哦～🧠",
}

# ============ 主动陪伴与无言陪伴（情感型 AI 伙伴） ============
QUIET_LIE_DOWN_SEC = 5 * 60            # 5 分钟未与团子互动（可能在思考）→ 安静趴着，不主动冒泡
FOCUS_WATCH_AFTER_SEC = 40 * 60        # 专注满 40 分钟 → 默默挪到光标附近，坐着看主人（不弹气泡）
FOCUS_HEARTACHE_AFTER_SEC = 2 * 3600   # 今日累计专注满 2 小时 → 团子做一个「心疼」小动作，不弹文字

# ============ 日间作息自动切换（任务7） ============
# 按系统时间自动切换猫咪状态，无需用户触发；每种状态变化每天最多 SCHEDULE_MAX_PER_DAY 次
SCHEDULE_MORNING = (9, 11)      # 9-11 点：伸懒腰/打哈欠，像刚醒来
SCHEDULE_AFTERNOON = (14, 16)   # 14-16 点：趴着眯眼，犯困状态
SCHEDULE_NIGHT_START = 23       # 23 点后：慢慢挪到屏幕角落蜷睡，安静不主动冒泡
SCHEDULE_NIGHT_END = 7          # 早 7 点前均视为夜间
SCHEDULE_MAX_PER_DAY = 2        # 每种状态变化每天最多触发次数
SCHEDULE_MOVE_MS = 3000         # 挪到角落的动画时长（缓慢挪动）
SCHEDULE_FADE_MS = 300          # 状态切换 0.3 秒淡入过渡

# ============ 毛玻璃举牌弹窗统一样式 ============
# 低饱和马卡龙毛玻璃，28px 大圆角，柔和浅粉/奶蓝半透底色
GLASS_FADE_MS = 150              # 统一 0.15s 淡入淡出
GLASS_RADIUS = 28                # 大圆角
GLASS_PINK_BG = "rgba(255, 228, 235, 200)"   # 浅粉半透明
GLASS_BLUE_BG = "rgba(220, 232, 245, 200)"   # 奶蓝半透明
GLASS_TEXT_COLOR = "#6E6E6E"     # 浅灰软圆字体
GLASS_FONT_FAMILY = "PingFang SC, Microsoft YaHei"
# 弹簧弹出缓动动画时长
GLASS_SPRING_MS = 260
# 环形进度条（猫咪头顶常驻，展示距离下次提醒剩余时长）
RING_PROGRESS_SIZE = 26
RING_PROGRESS_COLOR = (255, 182, 193)   # 浅粉
RING_PROGRESS_BG = (230, 230, 230)      # 浅灰底
