# -*- coding: utf-8 -*-
"""font_cjk_report.py -- 检查 TTF 的 cmap 覆盖情况（是否内含 CJK 字形）

用法: python font_cjk_report.py <font.ttf> [...]
输出每个字体的 cmap 子表、总码位数、以及关键区段覆盖统计。
"""
import struct
import sys
import unicodedata


def read_tables(buf):
    if len(buf) < 12:
        raise ValueError('not a TTF')
    num = struct.unpack('>H', buf[4:6])[0]
    tables = {}
    for i in range(num):
        off = 12 + 16 * i
        tag = buf[off:off + 4].decode('latin-1')
        toff, tlen = struct.unpack('>II', buf[off + 8:off + 16])
        tables[tag] = (toff, tlen)
    return tables


def parse_cmap(buf, tables):
    if 'cmap' not in tables:
        return {}
    base = tables['cmap'][0]
    n = struct.unpack('>H', buf[base + 2:base + 4])[0]
    out = {}
    for i in range(n):
        off = base + 4 + 8 * i
        pid, eid, sub = struct.unpack('>HHI', buf[off:off + 8])
        sub += base
        fmt = struct.unpack('>H', buf[sub:sub + 2])[0]
        cps = set()
        if fmt == 4:
            segx2 = struct.unpack('>H', buf[sub + 6:sub + 8])[0]
            seg = segx2 // 2
            end = struct.unpack('>%dH' % seg, buf[sub + 14:sub + 14 + segx2])
            p = sub + 16 + segx2
            start = struct.unpack('>%dH' % seg, buf[p:p + segx2])
            p += segx2
            delta = struct.unpack('>%dh' % seg, buf[p:p + segx2])
            p += segx2
            robase = p
            ro = struct.unpack('>%dH' % seg, buf[p:p + segx2])
            for s in range(seg):
                if start[s] == 0xFFFF:
                    continue
                for c in range(start[s], end[s] + 1):
                    if ro[s] == 0:
                        g = (c + delta[s]) & 0xFFFF
                    else:
                        gidx = robase + 2 * ro[s] + 2 * (c - start[s])
                        if gidx + 2 > len(buf):
                            continue
                        g = struct.unpack('>H', buf[gidx:gidx + 2])[0]
                        if g:
                            g = (g + delta[s]) & 0xFFFF
                    if g:
                        cps.add(c)
        elif fmt == 12:
            ngroups = struct.unpack('>I', buf[sub + 12:sub + 16])[0]
            p = sub + 16
            for _ in range(ngroups):
                s, e, g = struct.unpack('>III', buf[p:p + 12])
                p += 12
                if g:
                    for c in range(s, min(e, s + 0x2000) + 1):
                        cps.add(c)
        elif fmt == 6:
            first, count = struct.unpack('>HH', buf[sub + 6:sub + 10])
            for k in range(count):
                g = struct.unpack('>H', buf[sub + 10 + 2 * k:sub + 12 + 2 * k])[0]
                if g:
                    cps.add(first + k)
        elif fmt == 0:
            for c in range(256):
                if buf[sub + 6 + c]:
                    cps.add(c)
        out[(pid, eid, fmt)] = cps
    return out


RANGES = [
    ('ASCII 0x20-0x7E', 0x20, 0x7E),
    ('Latin-1 0xA0-0xFF', 0xA0, 0xFF),
    ('Cyrillic 0x400-0x4FF', 0x400, 0x4FF),
    ('CJK 符号 0x3000-0x303F', 0x3000, 0x303F),
    ('CJK 标点 0xFF00-0xFFEF', 0xFF00, 0xFFEF),
    ('CJK 统一表意 0x4E00-0x9FFF', 0x4E00, 0x9FFF),
    ('CJK 扩展A 0x3400-0x4DBF', 0x3400, 0x4DBF),
]


def main(argv):
    for path in argv[1:]:
        buf = open(path, 'rb').read()
        try:
            tables = read_tables(buf)
            cmaps = parse_cmap(buf, tables)
        except Exception as e:
            print('== %s: 解析失败 %s' % (path, e))
            continue
        best = set()
        for k, v in cmaps.items():
            if len(v) > len(best):
                best = v
        print('== %s' % path)
        print('   cmap 子表: %s' % (', '.join('(%d,%d,格式%d) 码位%d' % (p, e, f, len(c)) for (p, e, f), c in cmaps.items()) or '无'))
        print('   最大子表覆盖码位总数: %d' % len(best))
        for label, lo, hi in RANGES:
            n = sum(1 for c in best if lo <= c <= hi)
            total = hi - lo + 1
            print('     %-28s %5d / %d  (%.1f%%)' % (label, n, total, 100.0 * n / total))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
