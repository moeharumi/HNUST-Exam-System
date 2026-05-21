"""全局常量定义."""

import os

CURRENT_VERSION = "v1.1.4"
GITHUB_USERNAME = "RyanTanC"
GITHUB_REPO_NAME = "HNUST-Exam-System"

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".hnust_exam")
CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
PROGRESS_FILE = os.path.join(_CONFIG_DIR, "progress.json")
SKIP_VERSION_FILE = os.path.join(_CONFIG_DIR, "skip_ver")
TELEMETRY_QUEUE_FILE = os.path.join(_CONFIG_DIR, "telemetry_queue.json")

# 用户本地题库缓存目录（持久化，断网可用）
QUESTION_BANK_DIR = os.path.join(_CONFIG_DIR, "question_bank")
QUESTION_BANK_FILES_DIR = os.path.join(QUESTION_BANK_DIR, "files")
MANIFEST_FILE = os.path.join(QUESTION_BANK_DIR, "manifest.json")

QUESTION_TYPE_ORDER = ["单选", "填空", "判断", "程序填空", "程序改错", "程序设计"]
PROGRAM_TYPES = {"程序设计", "程序填空", "程序改错"}

EXAM_TIME_SECONDS = 60 * 60

# 图片目录（相对于项目根目录）
IMAGES_DIR = "题库/试题图片"

REQUIRED_COLUMNS = {"题号", "题型", "题目", "正确答案", "分值"}

# 匿名使用统计 Worker 地址
TELEMETRY_BASE_URL = "https://hnust-exam-telemetry.hnust-exam-stats.workers.dev"
