# -*- coding: utf-8 -*-
"""
check_dict.py -- Mainui_Cn/GameUI/Valve 本地化字典校验器

忠实模拟引擎侧 COM_ParseFileSafe(flags=0) + MenuStrings::Localize_AddToDictionary
的解析流程，用来在部署前发现「会在运行时静默出错」的字典问题：

  * 头部不合法（lang / { / Language / Tokens / {）
  * 引号未闭合导致后续条目整体错位
  * 空译文（会让菜单项变成空白）
  * 重复键（后者覆盖前者）
  * 未转义的半角双引号
  * 格式占位符与英文原版不一致（%s %d %s1 ...）

用法：
  python check_dict.py <dict.txt> [english_ref.txt] [more_dicts...]

第二个参数是可选英文原版，用于格式串回归比对。
"""

import re
import sys

# COM_IsSingleChar( flags = 0 ) 会单独成 token 的字符
SINGLE = set("{}") | {",", "'", "(", ")", "\n"}

PLACEHOLDER = re.compile(r"%[-0-9.#+ ]*[sdiufxX%]")


def parse_token(data, i):
    """返回 (token, next_index)；token 为 None 表示到达文件尾。"""
    n = len(data)
    while i < n and ord(data[i]) <= 32:
        i += 1
    if i >= n:
        return None, i

    c = data[i]

    # 行注释：COM_ParseFile 在 token 起始处无条件跳过 //
    if c == "/" and i + 1 < n and data[i + 1] == "/":
        while i < n and data[i] != "\n":
            i += 1
        return parse_token(data, i)

    # 引号字符串：可跨行，仅 \" 被还原为 "
    if c == '"':
        i += 1
        out = []
        while True:
            if i >= n:
                return "".join(out), i
            ch = data[i]
            i += 1
            if ch == "\\" and i < n and data[i] == '"':
                out.append('"')
                i += 1
                continue
            if ch == '"':
                return "".join(out), i
            out.append(ch)

    if c in SINGLE:
        return c, i + 1

    out = []
    while True:
        out.append(data[i])
        i += 1
        if i >= n:
            break
        c2 = data[i]
        if c2 in SINGLE or ord(c2) <= 32:
            break
    return "".join(out), i


def process_string(s):
    """MenuStrings::Localize_ProcessString：只处理 \\n 与 \\\\"""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            if s[i + 1] == "\\":
                out.append("\\")
                i += 2
                continue
            if s[i + 1] == "n":
                out.append("\n")
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def read_dict(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        text = raw[2:].decode("utf-16le")
    elif raw[:2] == b"\xfe\xff":
        text = raw[2:].decode("utf-16be")
    else:
        text = raw.decode("utf-8-sig")
    return text.replace("\r\n", "\n")


def simulate(path):
    text = read_dict(path)
    i = 0
    errors = []

    def tok():
        nonlocal i
        value, i = parse_token(text, i)
        return value

    head = tok()
    if head is None:
        return ["文件为空"], []
    if head.lower() != "lang":
        errors.append("头部应为 lang，实际为 %r" % head)

    if tok() != "{":
        errors.append('lang 之后应为 "{"')
    if (tok() or "").lower() != "language":
        errors.append('应为 "Language"')
    tok()  # 语言名，跳过
    if (tok() or "").lower() != "tokens":
        errors.append('应为 "Tokens"')
    if tok() != "{":
        errors.append('Tokens 之后应为 "{"')

    entries = []
    while True:
        key = tok()
        if key is None or key == "}":
            break
        value = tok()
        if value is None:
            errors.append("键 %r 没有对应译文" % key)
            break
        if value == "}":
            break
        entries.append((process_string(key), process_string(value)))

    return errors, entries


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    targets = argv[1:]
    ref = None
    if len(targets) >= 2:
        ref = targets[1]
        targets = targets[:1] + targets[2:]

    ref_map = {}
    if ref:
        r = simulate(ref)
        if not isinstance(r, list):
            ref_map = dict(r[1])

    failed = False
    for path in targets:
        result = simulate(path)
        print("== %s" % path)
        if isinstance(result, list):
            print("   致命错误: %s" % result)
            failed = True
            continue

        errors, entries = result
        print("   条目数: %d" % len(entries))
        for e in errors:
            print("   [错误] %s" % e)
            failed = True

        empty = [k for k, v in entries if not v.strip()]
        if empty:
            print("   [错误] 空译文: %s" % empty[:10])
            failed = True

        seen = {}
        for k, _ in entries:
            seen[k] = seen.get(k, 0) + 1
        dup = [k for k, n in seen.items() if n > 1]
        if dup:
            print("   [错误] 重复键: %s" % dup[:10])
            failed = True

        raw_hint = [k for k, v in entries if '"' in v or '"' in k]
        if raw_hint:
            print("   [警告] 译文中出现半角双引号（建议改用 “ ”）: %s" % raw_hint[:5])

        if ref_map:
            diverge = []
            for k, v in entries:
                if k not in ref_map:
                    continue
                if sorted(PLACEHOLDER.findall(ref_map[k])) != sorted(PLACEHOLDER.findall(v)):
                    diverge.append((k, ref_map[k], v))
            if diverge:
                print("   [错误] 与英文原版占位符不一致: %d 条" % len(diverge))
                for k, en, cn in diverge[:15]:
                    print("        %s\n            EN: %r\n            CN: %r" % (k, en[:80], cn[:80]))
                failed = True

            missing = [k for k in ref_map if k not in seen]
            if missing:
                print("   [提示] 英文原版有但本文件没有的键: %d 条（沿用英文）" % len(missing))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
