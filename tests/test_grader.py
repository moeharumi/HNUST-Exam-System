"""判分服务测试."""

import pytest

from hnust_exam.services.grader import (
    _sanitize_answer,
    check_fill_in,
    check_program_answer,
    grade_exam,
    normalize_punctuation,
    strip_comments,
    get_program_tokens,
)
from hnust_exam.models.exam import Exam
from hnust_exam.models.question import Question


class TestCheckFillIn:
    """填空题判分测试."""

    def test_exact_match(self):
        assert check_fill_in("abc", "abc") is True

    def test_case_insensitive(self):
        assert check_fill_in("Abc", "abc") is True

    def test_multi_blank_semicolon(self):
        assert check_fill_in("a;b;c", "a;b;c") is True

    def test_multi_blank_comma(self):
        assert check_fill_in("a,b,c", "a,b,c") is True

    def test_multi_blank_mismatch_count(self):
        assert check_fill_in("a;b", "a;b;c") is False

    def test_whitespace_trimmed(self):
        assert check_fill_in("  a ; b  ", "a;b") is True

    def test_wrong_answer(self):
        assert check_fill_in("xyz", "abc") is False

    def test_answer_with_space_not_split(self):
        # 答案包含空格时不应被拆分（如 "for loop" 作为单个答案）
        assert check_fill_in("for loop", "for loop") is True
        assert check_fill_in("for loop", "for") is False


class TestCheckProgramAnswer:
    """程序题判分测试."""

    def test_exact_match(self):
        assert check_program_answer("print(1)", "print(1)") is True

    def test_whitespace_normalized(self):
        assert check_program_answer("  print(1)  \n", "print(1)") is True

    def test_quote_normalization(self):
        assert check_program_answer("print('hello')", 'print("hello")') is True

    def test_multiline_exact(self):
        code = "for i in range(5):\n    print(i)"
        assert check_program_answer(code, code) is True

    def test_similar_code(self):
        # 差异极小的代码应通过（相似度>=0.9）
        user = "print('hello world')"
        correct = "print( 'hello world' )"
        assert check_program_answer(user, correct) is True

    def test_completely_wrong(self):
        assert check_program_answer("import os", "print('hello')") is False


class TestGradeExam:
    """整卷判分测试."""

    def _make_exam(self, questions_data: list[dict]) -> Exam:
        exam = Exam()
        exam.questions = []
        for idx, qd in enumerate(questions_data):
            q = Question(
                index=idx,
                number=qd["number"],
                q_type=qd["type"],
                text=qd.get("text", ""),
                correct_answer=qd["correct"],
                score=qd.get("score", 2),
            )
            exam.questions.append(q)
            exam.answer_map[qd["number"]] = qd.get("user", "")
        return exam

    def test_single_choice_all_correct(self):
        exam = self._make_exam([
            {"number": "1", "type": "单选", "correct": "A", "user": "A", "score": 2},
            {"number": "2", "type": "单选", "correct": "B", "user": "B", "score": 3},
        ])
        results = grade_exam(exam)
        assert len(results) == 2
        assert results[0].is_correct is True
        assert results[1].is_correct is True

    def test_judge_type(self):
        exam = self._make_exam([
            {"number": "1", "type": "判断", "correct": "A", "user": "对", "score": 2},
            {"number": "2", "type": "判断", "correct": "B", "user": "错", "score": 2},
        ])
        results = grade_exam(exam)
        assert results[0].is_correct is True
        assert results[1].is_correct is True

    def test_fill_in_multi_blank(self):
        exam = self._make_exam([
            {"number": "1", "type": "填空", "correct": "a;b", "user": "a;b", "score": 4},
        ])
        results = grade_exam(exam)
        assert results[0].is_correct is True

    def test_unanswered(self):
        exam = self._make_exam([
            {"number": "1", "type": "单选", "correct": "A", "user": "", "score": 2},
        ])
        results = grade_exam(exam)
        assert results[0].is_correct is False
        assert results[0].user_answer == "未作答"


class TestSanitizeAnswer:
    """标准答案预清洗测试."""

    def test_chinese_quotes_to_english(self):
        assert _sanitize_answer("“你好”") == '"你好"'

    def test_chinese_comma_to_english(self):
        assert _sanitize_answer("a，b") == "a,b"

    def test_chinese_semicolon_to_english(self):
        assert _sanitize_answer("a；b") == "a;b"

    def test_chinese_parens_to_english(self):
        assert _sanitize_answer("（abc）") == "(abc)"

    def test_trailing_comma_stripped(self):
        assert _sanitize_answer("A,") == "A"

    def test_consecutive_semicolons_stripped(self):
        # 单个分号保留（可能是代码语句结尾），连续多个才清理
        assert _sanitize_answer("A;") == "A;"
        assert _sanitize_answer("A;;") == "A"

    def test_trailing_semicolon_in_code(self):
        # 单个结尾分号不应被当作多余分隔符去除
        assert _sanitize_answer("int x = 1;") == "int x = 1;"

    def test_unmatched_trailing_double_quote(self):
        assert _sanitize_answer('[1,2,3]"') == "[1,2,3]"

    def test_unmatched_leading_double_quote(self):
        assert _sanitize_answer('"hello') == "hello"

    def test_matched_quotes_preserved(self):
        assert _sanitize_answer('"hello"') == '"hello"'

    def test_unmatched_trailing_single_quote(self):
        assert _sanitize_answer("hello'") == "hello"

    def test_odd_quotes_middle(self):
        assert _sanitize_answer('hel"lo') == "hello"

    def test_no_change_on_clean_input(self):
        # 配对的引号不应被修改
        assert _sanitize_answer("print('hello world')") == "print('hello world')"


class TestCheckFillInSanitize:
    """填空题清洗集成测试."""

    def test_chinese_punctuation_in_correct(self):
        # 标准答案含中文逗号，经清洗后转为英文逗号，与用户答案一致
        assert check_fill_in("A,B", "A，B") is True

    def test_basic_fill_in_unchanged(self):
        assert check_fill_in("A,B", "A,B") is True

    def test_program_blank_trailing_quote(self):
        assert check_fill_in("[1,2,3]", "[1,2,3]") is True


class TestCheckProgramAnswerSanitize:
    """程序题清洗集成测试."""

    def test_trailing_unmatched_quote(self):
        assert check_program_answer("[1,2,3]", '[1,2,3]"') is True

    def test_chinese_quotes_in_correct(self):
        # 标准答案含中文引号，经清洗后与用户英文引号答案一致
        assert check_program_answer('"hello"', "“hello”") is True

    def test_clean_answer_still_works(self):
        assert check_program_answer("print(1)", "print(1)") is True


class TestNormalizePunctuation:
    """归一化工具函数测试."""

    def test_fullwidth_to_halfwidth(self):
        # normalize_punctuation 处理全角标点，不处理全角字母
        assert normalize_punctuation("A，B") == "a,b"

    def test_chinese_punctuation(self):
        assert normalize_punctuation("你好；世界") == "你好;世界"

    def test_merge_whitespace(self):
        assert normalize_punctuation("a   b  c") == "a b c"

    def test_lowercase(self):
        assert normalize_punctuation("Hello World") == "hello world"

    def test_chinese_quotes(self):
        assert normalize_punctuation("“hello”") == '"hello"'

    def test_chinese_parens(self):
        assert normalize_punctuation("（abc）") == "(abc)"

    def test_mixed(self):
        result = normalize_punctuation("  A，b；c  ")
        assert result == "a,b;c"


class TestStripComments:
    """注释剥离测试."""

    def test_python_line_comment(self):
        assert strip_comments("print(1) # comment", "python") == "print(1) "

    def test_python_full_line_comment(self):
        assert strip_comments("# comment", "python") == ""

    def test_c_line_comment(self):
        assert strip_comments("int x = 1; // comment", "c") == "int x = 1; "

    def test_c_block_comment(self):
        code = "int x = /* comment */ 1;"
        assert strip_comments(code, "c") == "int x =  1;"

    def test_c_multiline_block_comment(self):
        code = "int x = 1;\n/* block\ncomment */\nint y = 2;"
        result = strip_comments(code, "c")
        assert "block" not in result
        assert "int x = 1;" in result
        assert "int y = 2;" in result

    def test_unknown_lang_no_change(self):
        assert strip_comments("# comment", "java") == "# comment"


class TestGetProgramTokens:
    """程序 token 提取测试."""

    def test_python_tokens(self):
        code = "print(1)"
        tokens = get_program_tokens(code, "python")
        assert "print" in tokens
        assert "1" in tokens

    def test_python_ignores_comments(self):
        code = "print(1)  # comment"
        tokens = get_program_tokens(code, "python")
        assert "comment" not in tokens

    def test_c_tokens(self):
        code = "int x = 1;"
        tokens = get_program_tokens(code, "c")
        assert "int" in tokens
        assert "x" in tokens

    def test_c_ignores_comments(self):
        code = "int x = 1; // comment"
        tokens = get_program_tokens(code, "c")
        assert "comment" not in tokens

    def test_token_match(self):
        # 两个等价 Python 代码的 token 序列应相同
        code1 = "print( 1 )"
        code2 = "print(1)"
        assert get_program_tokens(code1, "python") == get_program_tokens(code2, "python")


class TestCheckProgramAnswerC:
    """C 语言程序题判分测试."""

    def test_c_exact_match(self):
        code = 'printf("hello");'
        assert check_program_answer(code, code, lang="c") is True

    def test_c_whitespace_normalized(self):
        user = '  printf("hello");  '
        correct = 'printf("hello");'
        assert check_program_answer(user, correct, lang="c") is True

    def test_c_comment_ignored(self):
        user = 'printf("hello"); // output'
        correct = 'printf("hello");'
        assert check_program_answer(user, correct, lang="c") is True

    def test_c_block_comment_ignored(self):
        user = '/* header */\nprintf("hello");'
        correct = 'printf("hello");'
        assert check_program_answer(user, correct, lang="c") is True


class TestGradeExamStrictness:
    """判分严格度测试."""

    def _make_exam(self, questions_data: list[dict]) -> Exam:
        exam = Exam()
        exam.questions = []
        for idx, qd in enumerate(questions_data):
            q = Question(
                index=idx,
                number=qd["number"],
                q_type=qd["type"],
                text=qd.get("text", ""),
                correct_answer=qd["correct"],
                score=qd.get("score", 2),
                language=qd.get("lang", "python"),
            )
            exam.questions.append(q)
            exam.answer_map[qd["number"]] = qd.get("user", "")
        return exam

    def test_strict_mode_exact(self):
        # strict 模式要求完全匹配（含大小写）
        exam = self._make_exam([
            {"number": "1", "type": "单选", "correct": "A", "user": "a", "score": 2},
        ])
        results = grade_exam(exam, strictness="strict")
        # strict 模式下，大小写不匹配应该判错
        assert results[0].is_correct is False

    def test_normal_mode_case_insensitive(self):
        exam = self._make_exam([
            {"number": "1", "type": "单选", "correct": "A", "user": "a", "score": 2},
        ])
        results = grade_exam(exam, strictness="normal")
        assert results[0].is_correct is True

    def test_lenient_mode_similar_code(self):
        # lenient 模式下，相似代码应通过（阈值 0.8）
        user = "print('hello world!')"
        correct = "print('hello world')"
        exam = self._make_exam([
            {"number": "1", "type": "程序设计", "correct": correct, "user": user, "score": 5},
        ])
        results = grade_exam(exam, strictness="lenient")
        assert results[0].is_correct is True

    def test_normal_with_chinese_punctuation(self):
        exam = self._make_exam([
            {"number": "1", "type": "填空", "correct": "a，b", "user": "a,b", "score": 2},
        ])
        results = grade_exam(exam, strictness="normal")
        assert results[0].is_correct is True

    def test_strict_with_chinese_punctuation(self):
        # strict 模式不归一化，中文逗号和英文逗号不匹配
        exam = self._make_exam([
            {"number": "1", "type": "填空", "correct": "a，b", "user": "a,b", "score": 2},
        ])
        results = grade_exam(exam, strictness="strict")
        assert results[0].is_correct is False

    def test_c_language_grading(self):
        user = 'printf("hello"); // output'
        correct = 'printf("hello");'
        exam = self._make_exam([
            {"number": "1", "type": "程序设计", "correct": correct, "user": user, "score": 5, "lang": "c"},
        ])
        results = grade_exam(exam, strictness="normal")
        assert results[0].is_correct is True
