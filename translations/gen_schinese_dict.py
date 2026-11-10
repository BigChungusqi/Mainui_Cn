#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract every L("...") string from 3rdparty/Mainui_Cn and emit:
   1) translations/mainui_schinese.txt      -- engine-format dictionary worksheet
   2) translations/mainui_text_by_menu.txt  -- human readable, grouped by source file
"""
import os, re, io

ROOT = r'D:\xash\xash3d-fwgs\3rdparty\Mainui_Cn'
TR   = os.path.join(ROOT, 'translations')
OUT_DICT = os.path.join(TR, 'mainui_schinese.txt')
OUT_LIST = os.path.join(TR, 'mainui_text_by_menu.txt')
GAMEDIR  = r'D:\xash\xash3d-fwgs\bin\a_schinese\resource'

L_RE = re.compile(r'(?:^|[^A-Za-z0-9_])L\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)')

def walk_sources():
    files = []
    for folder, subs, names in os.walk(ROOT):
        rel = os.path.relpath(folder, ROOT)
        if rel.split(os.sep)[0] in ('sdk_includes', 'translations', '__pycache__',
                                    'vs2022', 'wscript', 'tests'):
            continue
        for n in names:
            if n.endswith(('.cpp', '.h')):
                files.append(os.path.join(folder, n))
    return sorted(files)

def scan():
    """-> list of (token, relpath, lineno)"""
    found = []
    for f in walk_sources():
        rel = os.path.relpath(f, ROOT).replace('\\', '/')
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            for i, line in enumerate(fh, 1):
                for m in L_RE.finditer(line):
                    found.append((m.group(1), rel, i))
    return found

def menu_string_defaults():
    """MenuStrings[] 数组默认值 + aliasStrings 里给空槽位准备的英文兜底值"""
    src = open(os.path.join(ROOT, 'MenuStrings.cpp'), encoding='utf-8', errors='replace').read()
    hdr = open(os.path.join(ROOT, 'MenuStrings.h'), encoding='utf-8', errors='replace').read()

    macro = {'EMPTY_STRINGS_1': 1, 'EMPTY_STRINGS_2': 2, 'EMPTY_STRINGS_5': 5,
             'EMPTY_STRINGS_10': 10, 'EMPTY_STRINGS_20': 20, 'EMPTY_STRINGS_50': 50,
             'EMPTY_STRINGS_100': 100}

    body = src.split('const char *MenuStrings[IDS_LAST] =', 1)[1]
    body = body.split('{', 1)[1].split('};', 1)[0]

    # 按「引号外的逗号」切分，否则含逗号的文案会被切碎
    items, cur, in_str, esc = [], '', False, False
    i = 0
    while i < len(body):
        c = body[i]
        if in_str:
            cur += c
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            cur += c
            i += 1
            continue
        if c == '/' and i + 1 < len(body) and body[i + 1] == '/':
            while i < len(body) and body[i] != '\n':
                i += 1
            continue
        if c == ',':
            items.append(cur.strip())
            cur = ''
            i += 1
            continue
        cur += c
        i += 1
    if cur.strip():
        items.append(cur.strip())

    idx, table = 0, {}
    for item in items:
        if not item:
            continue
        if item in macro:
            idx += macro[item]
        elif item.startswith('"'):
            try:
                table[idx] = item[1:item.rindex('"')]
            except ValueError:
                pass
            idx += 1

    alias = {}
    alias_sec = src.split('aliasStrings[] =', 1)[1].split('};', 1)[0]
    ids = dict(re.findall(r'#define\s+(IDS_[A-Z0-9_]+)\s+(\d+)', hdr))
    for m in re.finditer(r'\{\s*"((?:[^"\\]|\\.)*)"\s*,\s*(IDS_[A-Z0-9_]+)\s*\}', alias_sec):
        num = ids.get(m.group(2))
        if num:
            alias[int(num)] = m.group(1)

    for k, v in alias.items():
        table.setdefault(k, v)
    return table, alias

def deployed_keys():
    keys = set()
    for n in ('gameui_schinese.txt', 'valve_schinese.txt'):
        p = os.path.join(GAMEDIR, n)
        if not os.path.exists(p):
            continue
        raw = open(p, 'rb').read()
        enc = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
        for a, _ in re.findall(r'"([^"]{1,})"\s+"([^"]*)"', raw.decode(enc, 'replace')):
            keys.add(a)
    return keys

def main():
    found = scan()
    token_src = {}
    for tok, rel, ln in found:
        token_src.setdefault(tok, []).append((rel, ln))
    tokens = sorted(token_src)

    defaults, alias = menu_string_defaults()
    deployed = deployed_keys()

    excluded_gameui, entries, unregistered = [], [], []
    for tok in tokens:
        m = re.fullmatch(r'StringsList_(\d+)', tok)
        if m:
            num = int(m.group(1))
            if defaults.get(num):
                entries.append((tok, defaults[num], num in alias))
            else:
                unregistered.append((tok, num))
            continue
        if re.match(r'^(GameUI|Valve|Cstrike)_', tok) and tok in deployed:
            excluded_gameui.append(tok)
            continue
        entries.append((tok, tok, False))

    n_strl = sum(1 for t, _, _ in entries if t.startswith('StringsList_'))
    n_lit  = len(entries) - n_strl
    width  = min(72, max(len(t) for t, _, _ in entries) + 1)

    # ---------------- 1. 字典工作表 ----------------
    buf = io.StringIO()
    buf.write('// mainui_schinese.txt -- Xash3D FWGS 主菜单（mainui）中文化工作表\n')
    buf.write('//\n')
    buf.write('// 用法：左列 = 源码里的英文原文，不要改；右列 = 中文译文。\n')
    buf.write('// 右列初值与左列相同，代表「尚未翻译」；把右侧改成中文即可生效。\n')
    buf.write('// 未翻译的条目保持英文原样是安全的，随时可以部署。\n')
    buf.write('//\n')
    buf.write('// 注意：\\n 是换行符，%s / %d 是占位符，必须原样保留。\n')
    buf.write('// 部署位置：bin/a_schinese/resource/mainui_schinese.txt\n')
    buf.write('// GameUI_* / Valve_* 类词条已由 gameui_schinese.txt / valve_schinese.txt 提供，\n')
    buf.write('// 此处不再重复列出（重复列出会把已有的中文覆盖回英文）。\n')
    buf.write('//\n')
    buf.write('// 词条数：%d（英文文案 %d + StringsList_ 编号 %d）\n' % (len(entries), n_lit, n_strl))
    buf.write('\n"lang"\n{\n"Language" "schinese"\n"Tokens"\n{\n')
    for tok, val, is_alias in entries:
        pad = max(1, width - len(tok))
        if is_alias:
            buf.write('"%s"%*s"%s"   // 主菜单按钮提示文案\n' % (tok, pad, ' ', val))
        else:
            buf.write('"%s"%*s"%s"\n' % (tok, pad, ' ', val))
    buf.write('}\n}\n')

    with open(OUT_DICT, 'w', encoding='utf-16', newline='\r\n') as f:
        f.write(buf.getvalue())

    # ---------------- 2. 按菜单分组的文本清单 ----------------
    groups = {}
    for tok, rel, ln in found:
        groups.setdefault(rel, []).append((ln, tok))

    with open(OUT_LIST, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('# mainui 界面文本提取清单\n')
        f.write('# 来源：3rdparty/Mainui_Cn，与官方 dictgen.py 同源（结果一致）\n')
        f.write('# L() 调用 %d 次，去重后 %d 条\n' % (len(found), len(tokens)))
        f.write('#\n')
        f.write('#   GameUI_* / Valve_*   %3d 条  已由 gameui_schinese.txt / valve_schinese.txt 覆盖\n' % len(excluded_gameui))
        f.write('#   StringsList_* 编号   %3d 条  主菜单按钮提示等，需在 mainui_schinese.txt 里翻译\n' % (n_strl + len(unregistered)))
        f.write('#   英文文案             %3d 条  各设置菜单的静态文本\n' % n_lit)
        f.write('\n' + '=' * 78 + '\n')
        for rel in sorted(groups):
            f.write('\n### %s   (%d 条)\n' % (rel, len(groups[rel])))
            for ln, tok in groups[rel]:
                f.write('  %5d  %s\n' % (ln, tok))
        if unregistered:
            f.write('\n' + '=' * 78 + '\n')
            f.write('\n未注册的 StringsList_ 编号（源码里没有英文兜底值）：\n')
            for tok, num in unregistered:
                f.write('  %s\n' % tok)

    print('entries=%d (literal=%d, stringslist=%d)  excluded_gameui=%d  unregistered=%d'
          % (len(entries), n_lit, n_strl, len(excluded_gameui), len(unregistered)))
    print('dict ->', OUT_DICT)
    print('list ->', OUT_LIST)

main()
