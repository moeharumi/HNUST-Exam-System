"""判分服务：对考试答案进行评判."""

from __future__ import annotations

import re
import tokenize
import io
import difflib
from typing import TYPE_CHECKING

from hnust_exam.models.result import Result
from hnust_exam.services.config_manager import ConfigManager
from hnust_exam.utils.helpers import (
    normalize_answer,
    normalize_code,
    normalize_code_flexible,
)

if TYPE_CHECKING:
    from hnust_exam.models.exam import Exam


def normalize_punctuation(s: str) -> str:
    """将全角标点转为半角，合并连续空白为一个空格，统一小写。

    用于填空题等文本答案的归一化比较。
    """
    # 全角标点 → 半角（用 dict 逐字符替换，避免 maketrans 引号拼接问题）
    _punct_map = {
        "，": ",",   # ，
        "。": ".",   # 。
        "！": "!",   # ！
        "？": "?",   # ？
        "；": ";",   # ；
        "：": ":",   # ：
        "“": '"',   # "
        "”": '"',   # "
        "‘": "'",   # '
        "’": "'",   # '
        "（": "(",   # （
        "）": ")",   # ）
        "【": "[",   # 【
        "】": "]",   # 】
        "《": "<",   # 《
        "》": ">",   # 》
    }
    s = "".join(_punct_map.get(ch, ch) for ch in s)
    # 合并连续空白为一个空格
    s = re.sub(r"\s+", " ", s)
    # 统一小写
    s = s.lower().strip()
    return s


def strip_comments(code: str, lang: str) -> str:
    """移除代码中的注释。

    Python: 移除 ``#`` 行注释。
    C: 移除 ``//`` 行注释和 ``/* */`` 块注释。
    """
    if lang.lower() == "python":
        # 移除 # 行注释，保留字符串内的 #
        return re.sub(r"#.*$", "", code, flags=re.MULTILINE)
    elif lang.lower() == "c":
        # 先移除块注释 /* ... */
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
        # 再移除行注释 //
        code = re.sub(r"//.*$", "", code, flags=re.MULTILINE)
        return code
    return code


def get_program_tokens(code: str, lang: str) -> list[str]:
    """提取程序的核心 token 序列，忽略注释、空白、缩进。

    Python: 使用 ``tokenize`` 模块。
    C: 使用增强归一化（去注释 + normalize_code）。
    """
    lang = lang.lower()
    if lang == "python":
        code = strip_comments(code, "python")
        tokens: list[str] = []
        try:
            readline = io.StringIO(code).readline
            for tok in tokenize.generate_tokens(readline):
                if tok.type not in (
                    tokenize.COMMENT,
                    tokenize.NL,
                    tokenize.NEWLINE,
                    tokenize.INDENT,
                    tokenize.DEDENT,
                    tokenize.ENCODING,
                ):
                    tokens.append(tok.string)
        except tokenize.TokenError:
            # tokenize 失败时回退到归一化
            return normalize_code(code).split()
        return tokens
    elif lang == "c":
        cleaned = strip_comments(code, "c")
        normalized = normalize_code(cleaned)
        return normalized.split()
    # 未知语言，回退
    return normalize_code(code).split()


def _sanitize_answer(ans: str, q_type: str = "") -> str:
    """预清洗标准答案，修正题库录入时的人为错误。

    只应用于 correct_ans，不要用于 user_ans。
    """
    s = str(ans)

    # 通用：中文标点 → 英文
    s = s.replace("“", '"').replace("”", '"')   # " "
    s = s.replace("‘", "'").replace("’", "'")   # ' '
    s = s.replace("，", ",")                           # ，
    s = s.replace("；", ";")                           # ；
    s = s.replace("（", "(").replace("）", ")")   # （）

    # 引号配对修复（双引号 + 单引号）
    s = _fix_quote_pairs(s, '"')
    s = _fix_quote_pairs(s, "'")

    # 去掉首尾多余分隔符（逗号总是去除，分号仅去除连续 2+ 个的）
    s = re.sub(r"^[,]+|[,]+$", "", s.strip())
    s = re.sub(r"^[;]{2,}|[;]{2,}$", "", s.strip())

    return s


def _fix_quote_pairs(s: str, q: str) -> str:
    """修复字符串中指定引号的配对问题。"""
    count = s.count(q)
    if count % 2 == 0:
        return s
    # 奇数个引号：先删尾部，再删头部
    if s.endswith(q):
        s = s[:-1]
    if s.count(q) % 2 != 0 and s.startswith(q):
        s = s[1:]
    if s.count(q) % 2 != 0:
        # 仍未配对，删除最后一个
        idx = s.rfind(q)
        if idx >= 0:
            s = s[:idx] + s[idx + 1:]
    return s


def check_fill_in(user_ans: str, correct_ans: str) -> bool:
    """检查填空题答案（支持多空，用分号/逗号分隔，最多10空）.

    先调用 ``normalize_punctuation`` 归一化，再用 ``[,;]+`` 拆分。
    """
    user_norm = normalize_punctuation(user_ans)
    correct_norm = normalize_punctuation(correct_ans)
    user_parts = re.split(r"[,;]+", user_norm)
    correct_parts = re.split(r"[,;]+", correct_norm)
    user_parts = [p.strip() for p in user_parts if p.strip()]
    correct_parts = [p.strip() for p in correct_parts if p.strip()]
    # 最多支持10个空
    if len(user_parts) > 10 or len(correct_parts) > 10:
        return False
    if len(user_parts) != len(correct_parts):
        return False
    return all(u == c for u, c in zip(user_parts, correct_parts))


def check_program_answer(user_ans: str, correct_ans: str, lang: str = "python") -> bool:
    """检查程序题答案：token 比对 + 归一化 + 灵活比对.

    优先用 ``get_program_tokens`` 提取 token 序列比对；
    失败时用归一化 + 剥注释后 ``SequenceMatcher``，阈值从 config_manager 读取（默认 0.85）。
    """
    correct_ans = _sanitize_answer(correct_ans)

    # 优先：token 级比对
    try:
        user_tokens = get_program_tokens(user_ans, lang)
        correct_tokens = get_program_tokens(correct_ans, lang)
        if user_tokens == correct_tokens:
            return True
    except Exception:
        pass

    # 后备1：精确比对
    if normalize_code(user_ans) == normalize_code(correct_ans):
        return True
    if normalize_code_flexible(user_ans) == normalize_code_flexible(correct_ans):
        return True

    # 后备2：归一化 + 剥注释后 SequenceMatcher
    user_clean = strip_comments(normalize_code_flexible(user_ans), lang)
    correct_clean = strip_comments(normalize_code_flexible(correct_ans), lang)
    seq = difflib.SequenceMatcher(None, user_clean, correct_clean)

    # 从配置读取阈值，默认 0.85
    try:
        cfg = ConfigManager().load_config()
        threshold = cfg.get("grading_threshold", 0.85)
    except Exception:
        threshold = 0.85

    return seq.ratio() >= threshold


def grade_exam(exam: Exam, strictness: str = "normal") -> list[Result]:
    """对整份试卷判分，返回每题结果.

    Parameters
    ----------
    strictness:
        ``"strict"`` — 原始精确比对（不归一化）。
        ``"normal"`` — 归一化后精确比对（默认）。
        ``"lenient"`` — 归一化 + SequenceMatcher 阈值 0.8。
    """
    results = []
    for q in exam.questions:
        q_type = q.q_type
        score = q.score
        user_ans_raw = exam.get_answer(q.number)
        is_correct = False

        if user_ans_raw:
            if strictness == "strict":
                # strict: 原始精确比对（不归一化，区分大小写）
                if q_type in ("填空", "程序填空"):
                    user_parts = re.split(r"[,;]+", user_ans_raw.strip())
                    correct_parts = re.split(r"[,;]+", q.correct_answer.strip())
                    user_parts = [p for p in user_parts if p]
                    correct_parts = [p for p in correct_parts if p]
                    is_correct = user_parts == correct_parts
                elif q_type in ("程序设计", "程序改错"):
                    is_correct = (
                        normalize_code(user_ans_raw) == normalize_code(q.correct_answer)
                    )
                else:
                    is_correct = (
                        user_ans_raw.strip() == q.correct_answer.strip()
                    )
            elif strictness == "lenient":
                # lenient: 归一化 + SequenceMatcher 阈值 0.8
                user_ans = normalize_answer(user_ans_raw, q_type)
                correct_ans = normalize_answer(q.correct_answer, q_type)
                if q_type in ("填空", "程序填空"):
                    is_correct = check_fill_in(user_ans, correct_ans)
                elif q_type in ("程序设计", "程序改错"):
                    user_clean = strip_comments(
                        normalize_code_flexible(user_ans_raw), getattr(q, "language", "python")
                    )
                    correct_clean = strip_comments(
                        normalize_code_flexible(q.correct_answer), getattr(q, "language", "python")
                    )
                    seq = difflib.SequenceMatcher(None, user_clean, correct_clean)
                    is_correct = seq.ratio() >= 0.8
                else:
                    is_correct = user_ans == correct_ans
            else:
                # normal (默认): 归一化后精确比对
                user_ans = normalize_answer(user_ans_raw, q_type)
                correct_ans = normalize_answer(q.correct_answer, q_type)
                if q_type in ("填空", "程序填空"):
                    is_correct = check_fill_in(user_ans, correct_ans)
                elif q_type in ("程序设计", "程序改错"):
                    lang = getattr(q, "language", "python")
                    is_correct = check_program_answer(user_ans_raw, q.correct_answer, lang)
                else:
                    is_correct = user_ans == correct_ans

        results.append(
            Result(
                question_number=q.number,
                q_type=q_type,
                score=score,
                user_answer=user_ans_raw if user_ans_raw else "未作答",
                correct_answer=q.correct_answer,
                is_correct=is_correct,
                question_text=q.text,
            )
        )
    return results
