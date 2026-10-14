#!/usr/bin/env python3
"""jsoncheck —— 本地 JSON 正确性检查器（零依赖，Python 3.6+）。

用法示例：
    ./jsoncheck.py a.json b.json          # 检查若干文件
    ./jsoncheck.py -r ./config            # 递归检查目录下所有 .json / .jsonl
    cat a.json | ./jsoncheck.py           # 从 stdin 读
    ./jsoncheck.py --jsonl logs.txt       # 按 JSON Lines 逐行校验
    ./jsoncheck.py --dup-keys error *.json

退出码：0 = 全部通过；1 = 存在错误；2 = 用法 / IO 问题。
"""

import argparse
import io
import json
import os
import sys

__version__ = "1.0.0"

DEFAULT_EXTS = (".json", ".jsonl", ".ndjson", ".geojson")
LINE_EXTS = (".jsonl", ".ndjson")


# ---------------------------------------------------------------- 终端着色

class Style(object):
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        if not self.enabled:
            return text
        return "\033[%sm%s\033[0m" % (code, text)

    def red(self, t):
        return self._wrap("31", t)

    def green(self, t):
        return self._wrap("32", t)

    def yellow(self, t):
        return self._wrap("33", t)

    def dim(self, t):
        return self._wrap("2", t)

    def bold(self, t):
        return self._wrap("1", t)


# ------------------------------------------------- 重复键 / 非标准值检测

class _TrackedDict(dict):
    """记住自己解析时出现过哪些重复 key 的 dict。"""
    __slots__ = ("dup_keys",)


def _pairs_hook(pairs):
    d = _TrackedDict()
    dups = []
    for key, value in pairs:
        if key in d:
            dups.append(key)
        d[key] = value
    if dups:
        d.dup_keys = dups
    return d


def _collect_dup_paths(node, path, out):
    if isinstance(node, dict):
        for key in getattr(node, "dup_keys", ()):
            out.append("%s.%s" % (path, key) if path else key)
        for key, value in node.items():
            child = "%s.%s" % (path, key) if path else str(key)
            _collect_dup_paths(value, child, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _collect_dup_paths(value, "%s[%d]" % (path, index), out)


def _make_const_hook(sink):
    def hook(name):
        sink.append(name)
        return {"NaN": float("nan"),
                "Infinity": float("inf"),
                "-Infinity": float("-inf")}[name]
    return hook


# --------------------------------------------------------------- 结果对象

class Issue(object):
    """一条问题记录。level 为 'error' 或 'warning'。"""

    def __init__(self, level, message, line=None, column=None, detail=None):
        self.level = level
        self.message = message
        self.line = line
        self.column = column
        self.detail = detail


class FileResult(object):
    def __init__(self, name):
        self.name = name
        self.issues = []

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self):
        return not self.errors


# ------------------------------------------------------------------ 校验

def check_text(text, dup_keys="warn", allow_nan="warn"):
    """校验一段 JSON 文本，返回 Issue 列表。"""
    issues = []

    if text.startswith("﻿"):
        issues.append(Issue("warning", "文件以 BOM 开头（U+FEFF），部分解析器会报错"))
        text = text.lstrip("﻿")

    if not text.strip():
        issues.append(Issue("error", "内容为空，不是合法 JSON"))
        return issues

    constants = []
    try:
        data = json.loads(text,
                          object_pairs_hook=_pairs_hook,
                          parse_constant=_make_const_hook(constants))
    except json.JSONDecodeError as exc:
        issues.append(Issue("error", exc.msg, exc.lineno, exc.colno,
                            _snippet(text, exc.lineno, exc.colno)))
        return issues
    except RecursionError:
        issues.append(Issue("error", "嵌套层级过深，超出解析器递归上限"))
        return issues

    if constants and allow_nan != "ignore":
        level = "error" if allow_nan == "error" else "warning"
        uniq = sorted(set(constants))
        issues.append(Issue(level,
                            "包含非标准字面量 %s（标准 JSON 不支持，跨语言解析会失败）"
                            % "、".join(uniq)))

    if dup_keys != "ignore":
        paths = []
        _collect_dup_paths(data, "", paths)
        if paths:
            level = "error" if dup_keys == "error" else "warning"
            for path in paths:
                issues.append(Issue(level, "重复的键：%s（后者覆盖前者）" % path))

    return issues


def _snippet(text, lineno, colno):
    """给出错位置生成一段带 ^ 指针的上下文。"""
    lines = text.splitlines()
    if not lines or lineno < 1 or lineno > len(lines):
        return None
    start = max(0, lineno - 3)
    out = []
    width = len(str(lineno))
    for index in range(start, lineno):
        out.append("  %*d | %s" % (width, index + 1, lines[index]))
    caret_pad = " " * (width + 5 + max(0, colno - 1))
    out.append(caret_pad + "^")
    return "\n".join(out)


def check_lines(text, dup_keys="warn", allow_nan="warn"):
    """JSON Lines 模式：逐行校验，空行跳过。"""
    issues = []
    for offset, raw in enumerate(text.splitlines()):
        lineno = offset + 1
        if not raw.strip():
            continue
        for issue in check_text(raw, dup_keys, allow_nan):
            issue.detail = None
            issue.line = lineno
            issues.append(issue)
    if not issues and not text.strip():
        issues.append(Issue("error", "内容为空，没有任何 JSON 行"))
    return issues


def check_file(path, jsonl=None, dup_keys="warn", allow_nan="warn"):
    result = FileResult(path)
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except UnicodeDecodeError as exc:
        result.issues.append(Issue("error", "不是合法的 UTF-8 文本：%s" % exc))
        return result
    except (IOError, OSError) as exc:
        result.issues.append(Issue("error", "无法读取：%s" % exc.strerror))
        return result

    use_lines = jsonl if jsonl is not None else path.lower().endswith(LINE_EXTS)
    checker = check_lines if use_lines else check_text
    result.issues = checker(text, dup_keys, allow_nan)
    return result


# ------------------------------------------------------------ 路径展开

def expand_paths(paths, recursive, exts):
    files = []
    for path in paths:
        if os.path.isdir(path):
            if not recursive:
                print("跳过目录 %s（加 -r 递归检查）" % path, file=sys.stderr)
                continue
            for root, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d != "node_modules"]
                for name in sorted(filenames):
                    if name.lower().endswith(exts):
                        files.append(os.path.join(root, name))
        else:
            files.append(path)
    return files


# -------------------------------------------------------------- 输出报告

def report(result, style, quiet, verbose):
    lines = []
    for issue in result.issues:
        mark = style.red("✗") if issue.level == "error" else style.yellow("!")
        where = result.name
        if issue.line:
            where += ":%d" % issue.line
            if issue.column:
                where += ":%d" % issue.column
        lines.append("%s %s: %s" % (mark, style.bold(where), issue.message))
        if issue.detail:
            lines.append(style.dim(issue.detail))

    if not lines and verbose and not quiet:
        lines.append("%s %s" % (style.green("✓"), result.name))

    for line in lines:
        print(line)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="jsoncheck",
        description="检查 JSON 文件是否合法，并定位出错的行列。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 全部通过 / 1 存在错误 / 2 用法或 IO 问题")
    parser.add_argument("paths", nargs="*",
                        help="文件或目录；留空或写 - 表示读 stdin")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="递归检查目录")
    parser.add_argument("--jsonl", dest="jsonl", action="store_true",
                        default=None, help="强制按 JSON Lines 逐行校验")
    parser.add_argument("--no-jsonl", dest="jsonl", action="store_false",
                        help="强制按整份 JSON 校验（即使扩展名是 .jsonl）")
    parser.add_argument("--dup-keys", choices=("ignore", "warn", "error"),
                        default="warn", help="重复键的处理方式（默认 warn）")
    parser.add_argument("--allow-nan", choices=("ignore", "warn", "error"),
                        default="warn",
                        help="NaN / Infinity 的处理方式（默认 warn）")
    parser.add_argument("--strict", action="store_true",
                        help="等价于 --dup-keys error --allow-nan error")
    parser.add_argument("--ext", default=",".join(DEFAULT_EXTS),
                        help="递归时匹配的扩展名，逗号分隔（默认 %s）"
                             % ",".join(DEFAULT_EXTS))
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="只用退出码表示结果，不打印")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="通过的文件也逐个打印")
    parser.add_argument("--no-color", action="store_true", help="关闭颜色")
    parser.add_argument("--version", action="version",
                        version="jsoncheck %s" % __version__)
    args = parser.parse_args(argv)

    if args.strict:
        args.dup_keys = "error"
        args.allow_nan = "error"

    style = Style(sys.stdout.isatty() and not args.no_color
                  and os.environ.get("NO_COLOR") is None)
    exts = tuple(e if e.startswith(".") else "." + e
                 for e in args.ext.lower().split(",") if e)

    results = []
    if not args.paths or args.paths == ["-"]:
        text = sys.stdin.read()
        result = FileResult("<stdin>")
        checker = check_lines if args.jsonl else check_text
        result.issues = checker(text, args.dup_keys, args.allow_nan)
        results.append(result)
    else:
        files = expand_paths(args.paths, args.recursive, exts)
        if not files:
            print("没有找到要检查的文件", file=sys.stderr)
            return 2
        for path in files:
            results.append(check_file(path, args.jsonl,
                                      args.dup_keys, args.allow_nan))

    if not args.quiet:
        for result in results:
            report(result, style, args.quiet, args.verbose)

    bad = [r for r in results if not r.ok]
    warned = [r for r in results if r.ok and r.warnings]

    if not args.quiet and len(results) > 1:
        summary = "%d 个文件：%s 通过" % (len(results),
                                    style.green(str(len(results) - len(bad))))
        if warned:
            summary += "（%s 带警告）" % style.yellow(str(len(warned)))
        if bad:
            summary += "，%s 失败" % style.red(str(len(bad)))
        print(summary)

    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
