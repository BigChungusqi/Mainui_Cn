# -*- coding: utf-8 -*-
"""
verify_shell_art.py -- validate generated gfx/shell art against the exact index
arithmetic mainui uses, WITHOUT running the engine.

Reimplements, faithfully:

  CBMP::LoadFile                      Utils.cpp:325
  CBtnsManager::LoadBmpButtons        Btns.cpp:37
  CMenuPicButton::Draw / DrawButton   PicButton.cpp:216,259

If a generated atlas passes here, the engine will upload the intended pixels.

bmp_t field layout, verbatim from BMPUtils.h:31-48. sizeof(bmp_t) == 54 and it
INCLUDES the magic, because CBMP::LoadFile casts the raw file straight to bmp_t*:

    2s id                I  compression
    I  fileSize          I  bitmapDataSize
    I  reserved0         I  hRes
    I  bitmapDataOffset  I  vRes
    I  bitmapHeaderSize  I  colors
    I  width             I  importantColors
    i  height
    H  planes
    H  bitsPerPixel

Do NOT narrow these to the on-disk BMP spec widths. The engine widens several
2 byte on-disk fields (bitmapDataOffset == bfOffBits, height == biHeight) to
32 bits so it can read them with plain loads. Matching the engine struct is what
makes CBMP::LoadFile's field checks land on the right bytes.
"""

import os
import struct
import sys

BMP_HDR_FMT = '<2sIIIIIiHHIIIIII'
assert struct.calcsize(BMP_HDR_FMT) == 54, \
    'sizeof(bmp_t) must be 54, got %d' % struct.calcsize(BMP_HDR_FMT)

FIELDS = ('id', 'file_size', 'reserved0', 'data_offset', 'hdr_size', 'width',
          'height', 'planes', 'bpp', 'compression', 'data_size', 'hres',
          'vres', 'colors', 'important_colors')


class BMP:
    def __init__(self, path):
        raw = open(path, 'rb').read()
        self.raw = raw

        # --- CBMP::LoadFile header read, verbatim (Utils.cpp:328-340) ---
        # The engine casts the RAW FILE to bmp_t*, so id[2] is part of the
        # header and the pixel data starts at sizeof(bmp_t) == 54.
        if len(raw) < 54:
            raise ValueError('too small for bmp_t')
        vals = struct.unpack(BMP_HDR_FMT, raw[:54])
        for name, v in zip(FIELDS, vals):
            setattr(self, name, v)

        if self.id != b'BM':
            raise ValueError('%s: not a BMP (magic %r)' % (path, self.id))

        # --- CBMP::LoadFile validation, verbatim (Utils.cpp:346-356) ---
        if not self.width or not self.height:
            raise ValueError('bogus width/height')
        checks = [
            ('length < fileSize',         len(raw) < self.file_size),
            ('length < bitmapDataSize',   len(raw) < self.data_size),
            ('length < bitmapDataOffset', len(raw) < self.data_offset),
            ('length < bitmapHeaderSize', len(raw) < self.hdr_size),
            ('length < off+dataSize',
             len(raw) < self.data_offset + self.data_size),
            ('length < hdrSize+dataSize',
             len(raw) < self.hdr_size + self.data_size),
        ]
        for name, bad in checks:
            if bad:
                raise ValueError('CBMP::LoadFile would REJECT: ' + name)

        if self.bpp != 32:
            raise ValueError('expected 32bpp, got %d' % self.bpp)
        if self.compression != 0:
            raise ValueError('expected BI_RGB, got %d' % self.compression)

        self.stride = ((self.width * (self.bpp // 8)) + 3) & ~3
        self.tex = raw[self.data_offset:]
        expected = self.stride * self.height
        if len(self.tex) != expected:
            raise ValueError('pixel data is %d, expected %d'
                             % (len(self.tex), expected))

    def bgra(self, x, y):
        """Read a pixel as stored on disk (B,G,R,A)."""
        o = y * self.stride + x * 4
        return self.tex[o:o + 4]


def check_btns(path, num_btns=67):
    print('== %s' % os.path.basename(path))
    bmp = BMP(path)

    bpp = bmp.bpp // 8
    button_w = bmp.width
    button_tex_h = 26                       # Btns.cpp:42, hardcoded
    src_cell_h = button_tex_h * 3
    src_height = bmp.height

    print('   %dx%d %dbpp stride=%d' % (bmp.width, bmp.height, bmp.bpp, bmp.stride))

    # Btns.cpp:43
    pic_count = min(src_height // button_tex_h // 3, num_btns)
    print('   src_cell_h=%d  pic_count=%d' % (src_cell_h, pic_count))
    if pic_count <= 0:
        raise SystemExit('   FAIL: pic_count <= 0 -> LoadBmpButtons bails')
    if pic_count < num_btns:
        print('   WARN: only %d of %d buttons present' % (pic_count, num_btns))

    if bpp == 0 or button_w == 0:
        raise SystemExit('   FAIL: bpp/button_w zero -> would bail')

    src_stride = ((bmp.width * bpp) + 3) & ~3
    if src_stride != bmp.stride:
        raise SystemExit('   FAIL: src_stride %d != data stride %d'
                         % (src_stride, bmp.stride))
    print('   src_stride=%d == data stride  OK' % src_stride)

    # width must be 4-aligned or the row advance desyncs (see gen_shell_art doc)
    if bmp.width % 4:
        raise SystemExit('   FAIL: width %d not a multiple of 4' % bmp.width)
    print('   width %% 4 == 0  OK')

    # ---- atlas placement (Btns.cpp:74-116) ----
    state_step = button_tex_h + 2
    cell_w = button_w + 2
    cell_h = state_step * 3
    pot = [256, 512, 1024]
    best = None
    for w in pot:
        for h in pot:
            c, r = w // cell_w, h // cell_h
            if c > 0 and r > 0 and c * r >= pic_count:
                if best is None or w * h < best[0]:
                    best = (w * h, w, h, c, r)
    if best:
        _, atlas_w, atlas_h, cols, rows = best
    else:
        atlas_w = atlas_h = 1024
        cols, rows = atlas_w // cell_w, atlas_h // cell_h
    print('   atlas %dx%d  cells %dx%d  per_page=%d'
          % (atlas_w, atlas_h, cols, rows, cols * rows))

    # ---- every button/state must read real pixel data ----
    ok, bad = 0, []
    for btn in range(pic_count):
        for state in range(3):
            ps = (btn * src_cell_h + state * button_tex_h) * src_stride
            pe = ps + button_w * bpp
            if pe > len(bmp.tex):
                bad.append((btn, state, 'read past end'))
                continue
            if not any(bmp.tex[ps:pe]):
                bad.append((btn, state, 'all-zero row band'))
            else:
                ok += 1
    if bad:
        print('   FAIL: %d malformed cells' % len(bad))
        for b in bad[:10]:
            print('     ', b)
        return False
    print('   %d cells carry pixel data  OK' % ok)

    # ---- geometry readout for button 0 ----
    print('   button 0 (PC_NEW_GAME) opacity profile per state:')
    for state, nm in enumerate(('nofocus', 'focus', 'pressed')):
        ps = state * button_tex_h * src_stride
        prof = []
        for line in range(button_tex_h):
            off = ps + line * src_stride
            nz = sum(1 for i in range(button_w) if bmp.tex[off + i * 4 + 3])
            prof.append(nz)
        print('     %-8s rows[0]=%3d  rows[%d]=%3d  rows[last]=%3d  widest=%3d'
              % (nm, prof[0], button_tex_h // 2, prof[button_tex_h // 2],
                 prof[-1], max(prof)))
        if prof[0] == 0 or prof[-1] == 0:
            print('       WARN: top/bottom row fully transparent')
    return True


def check_sprite(path, expect_w=None, expect_h=None):
    try:
        bmp = BMP(path)
    except ValueError as e:
        print('   %-26s FAIL %s' % (os.path.basename(path), e))
        return False

    nz = 0
    total = bmp.width * bmp.height
    for y in range(bmp.height):
        for x in range(bmp.width):
            b, g, r, a = bmp.bgra(x, y)
            if a and (r or g or b):
                nz += 1

    problems = []
    if expect_w and bmp.width != expect_w:
        problems.append('width %d != %d' % (bmp.width, expect_w))
    if expect_h and bmp.height != expect_h:
        problems.append('height %d != %d' % (bmp.height, expect_h))
    if nz == 0:
        problems.append('EMPTY')

    print('   %-26s %2dx%-3d painted=%4d/%-4d %s'
          % (os.path.basename(path), bmp.width, bmp.height, nz, total,
             'FAIL ' + '; '.join(problems) if problems else 'OK'))
    return not problems


# --------------------------------------------------------------- orientation
# BMP on disk is bottom-up and the engine uploads it straight to GL (no row
# flip -- see gen_shell_art.write_bmp_bottom_up). So the row the FILE stores
# first is the row the player sees at the BOTTOM of the sprite. Every writer
# here emits bottom-up; getting it wrong mirrors the sprite vertically and is
# exactly what made the tick look upside down and the up-arrow point down.
#
# These sprites have a known visual orientation, so we can assert on them.
# `top_heavy` / `bottom_heavy` record where the ink should concentrate on
# screen, in screen coordinates (screen row 0 = top).

def _ink_rows_screen(bmp):
    """Return the list of screen row indices that contain any inked pixel.

    Screen row 0 is the TOP. The file's first stored row is screen row
    height-1, i.e. `screen_y = height - 1 - file_y`.
    """
    rows = []
    for fy in range(bmp.height):
        sy = bmp.height - 1 - fy
        for x in range(bmp.width):
            b, g, r, a = bmp.bgra(x, fy)
            if a and (r or g or b):
                rows.append(sy)
                break
    return rows


def _ink_width_per_screen_row(bmp):
    """Map screen row -> count of inked pixels in that row."""
    out = {}
    for fy in range(bmp.height):
        sy = bmp.height - 1 - fy
        n = 0
        for x in range(bmp.width):
            b, g, r, a = bmp.bgra(x, fy)
            if a and (r or g or b):
                n += 1
        out[sy] = n
    return out


def _ink_left_margin_per_screen_row(bmp):
    """Map screen row -> x of the leftmost inked pixel (None when blank)."""
    out = {}
    for fy in range(bmp.height):
        sy = bmp.height - 1 - fy
        left = None
        for x in range(bmp.width):
            b, g, r, a = bmp.bgra(x, fy)
            if a and (r or g or b):
                left = x
                break
        out[sy] = left
    return out


def _ink_cols_screen(bmp):
    cols = []
    for x in range(bmp.width):
        for fy in range(bmp.height):
            b, g, r, a = bmp.bgra(x, fy)
            if a and (r or g or b):
                cols.append(x)
                break
    return cols


def check_orientation(directory):
    """Assert sprite orientation using sprites with a known visual shape.

    Returns True when every probe agrees. This is the regression guard for the
    row-order contract -- if the flip is dropped again, these fail loudly
    instead of silently shipping mirrored art.

    Note we probe SHAPE, not ink centroid. A chevron's centroid sits on its
    wide side, so a centroid test would wrongly flag a correct up-arrow.
    """
    ok = True

    def load(name):
        p = os.path.join(directory, name + '.bmp')
        if not os.path.exists(p):
            print('   %-20s SKIP (missing)' % name)
            return None
        return BMP(p)

    # uparrowd: apex is a single narrow tip; the arrow must get WIDER as we go
    # DOWN the screen. Compare the topmost inked row against the bottommost.
    b = load('uparrowd')
    if b is not None:
        widths = _ink_width_per_screen_row(b)
        inked = [sy for sy, n in widths.items() if n > 0]
        if not inked:
            print('   uparrowd   FAIL (no ink)')
            ok = False
        else:
            top_w = widths[min(inked)]
            bot_w = widths[max(inked)]
            good = top_w < bot_w
            print('   uparrowd   top row ink=%d, bottom row ink=%d  '
                  '(want top < bottom) %s'
                  % (top_w, bot_w, 'OK' if good else 'FAIL -> mirrored'))
            ok &= good

    # larrowdefault: a triangle whose APEX is on the LEFT. The apex row is a
    # short run hugging x=0; the base row is the longest run. Assert the apex
    # (leftmost ink) is on the left and the sprite widens to the right.
    b = load('larrowdefault')
    if b is not None:
        runs = {}
        for fy in range(b.height):
            sy = b.height - 1 - fy
            xs = [x for x in range(b.width)
                  if (lambda p: p[3] and (p[0] or p[1] or p[2]))(b.bgra(x, fy))]
            if xs:
                runs[sy] = (min(xs), max(xs), len(xs))
        if not runs:
            print('   larrowdefault FAIL (no ink)')
            ok = False
        else:
            thinnest = min(runs.items(), key=lambda kv: kv[1][2])
            widest = max(runs.items(), key=lambda kv: kv[1][2])
            # the thin end must sit further left than the wide end
            good = thinnest[1][0] <= widest[1][0] and thinnest[1][2] < widest[1][2]
            print('   larrowdefault thin row(ink=%d,left=%d) wide row(ink=%d,left=%d)'
                  '  (want apex on the LEFT) %s'
                  % (thinnest[1][2], thinnest[1][0], widest[1][2], widest[1][0],
                     'OK' if good else 'FAIL -> mirrored'))
            ok &= good

    # min_n: a horizontal bar. The 1px frame is deliberately much darker than
    # the glyph, so select by luminance and require one short run of rows near
    # the vertical centre.
    b = load('min_n')
    if b is not None:
        def bright(x, fy):
            p = b.bgra(x, fy)
            return p[3] and ((p[0] * 3 + p[1] * 6 + p[2]) / 10.0) > 140

        rows_with_ink = []
        for fy in range(b.height):
            sy = b.height - 1 - fy
            if any(bright(x, fy) for x in range(b.width)):
                rows_with_ink.append(sy)
        if not rows_with_ink:
            print('   min_n      FAIL (no bright glyph ink)')
            ok = False
        else:
            span = max(rows_with_ink) - min(rows_with_ink) + 1
            centre = (max(rows_with_ink) + min(rows_with_ink)) / 2.0
            good = 1 <= span <= 4 and abs(centre - (b.height - 1) / 2.0) <= 2.5
            print('   min_n      bar spans %d rows, centre %.1f of %d '
                  '(want a short, centred bar) %s'
                  % (span, centre, b.height, 'OK' if good else 'FAIL -> wrong shape'))
            ok &= good

    return ok


# Arrow stems, verbatim from BaseMenu.h:41-52. Note the asymmetry: Left/Right
# spell the state out, Up/Down use a single letter. Getting this wrong silently
# falls back to defaultTexture (magenta checkerboard), so it is asserted below.
ARROW_STEMS = [
    'larrowdefault', 'larrowflyover', 'larrowpressed',
    'rarrowdefault', 'rarrowflyover', 'rarrowpressed',
    'uparrowd', 'uparrowf', 'uparrowp',
    'dnarrowd', 'dnarrowf', 'dnarrowp',
]

SPRITES = [
    # extension-less in CImage/BaseMenu.h; Image_ProbeLoad appends .bmp
    ('cb_empty', 16, 16),
    ('cb_over', 16, 16),
    ('cb_down', 16, 16),
    ('cb_checked', 16, 16),
    ('cb_checked_over', 16, 16),
    ('cb_disabled', 16, 16),
    ('slider', 40, 18),
    ('larrowdefault', 24, 14),
    ('larrowflyover', 24, 14),
    ('larrowpressed', 24, 14),
    ('rarrowdefault', 24, 14),
    ('rarrowflyover', 24, 14),
    ('rarrowpressed', 24, 14),
    ('uparrowd', 24, 14),
    ('uparrowf', 24, 14),
    ('uparrowp', 24, 14),
    ('dnarrowd', 24, 14),
    ('dnarrowf', 24, 14),
    ('dnarrowp', 24, 14),
    # window-control glyphs (Main.cpp:34-39)
    ('cls_n', 16, 16), ('cls_f', 16, 16), ('cls_d', 16, 16),
    ('min_n', 16, 16), ('min_f', 16, 16), ('min_d', 16, 16),
    # BackgroundBitmap fallback
    ('splash', 64, 64),
    # NOTE: the btn_* standalone PicButton sprites (Btns.h:99-109 PC_*) are
    # intentionally not generated -- button art is out of scope, see
    # OUT_OF_SCOPE_STEMS below.
    # list scroll arrows (BaseMenu.h:39-40)
    ('up', 24, 24), ('down', 24, 24),
    # badges
    ('lock', 24, 24), ('favorite', 24, 24), ('gamma', 24, 24),
]

# gfx/shell/<name> that are DATA FILES, not images -- loaded via COM_LoadFile,
# so they must NOT be generated as BMPs and must not be reported as missing art.
NON_IMAGE_STEMS = {
    'colors',    # gfx/shell/colors.lst   (BaseMenu.cpp:915)
    'kb_act',    # gfx/shell/kb_act.lst   (KbActListModel.h:56)
    'kb_def',    # gfx/shell/kb_def.lst   (Controls.cpp:114)
    'kb_keys',   # gfx/shell/kb_keys.lst
    'strings',   # gfx/shell/strings.lst  (MenuStrings.cpp:523)
}

# Button art is intentionally NOT produced by this generator. The button plates
# (btns_main.bmp atlas + the btn_* PicButton sprites) were explicitly out of
# scope, so they must not be reported as "not covered".
OUT_OF_SCOPE_STEMS = {
    'btns_main',       # the atlas itself
    'btn_gamepad',     # PC_* standalone sprites, Btns.h:99-109
    'btn_touch',
    'btn_touch_options',
    'btn_touch_buttons',
    'btn_touch_save',
    'btn_touch_editor',
    'btn_touch_select',
    'btn_touch_reset',
    'btn_favorite',
    'btn_unfavorite',
    'btn_gyro',
}


def discover_shell_stems(repo_root):
    """Scrape every gfx/shell/<name> literal out of the mainui sources.

    This is the guard that catches invented AND forgotten filenames: whatever
    the code asks for must exist, and nothing we ship should be dead weight.
    btns_main is excluded because it is an atlas, not a flat sprite.
    """
    import re
    pat = re.compile(r'gfx/shell/([A-Za-z0-9_]+)')
    stems = set()
    for root, _dirs, files in os.walk(repo_root):
        if 'translations' in root or '.git' in root:
            continue
        for fn in files:
            if not fn.endswith(('.cpp', '.h')):
                continue
            try:
                txt = open(os.path.join(root, fn), encoding='utf-8',
                           errors='ignore').read()
            except OSError:
                continue
            stems.update(pat.findall(txt))
    stems -= OUT_OF_SCOPE_STEMS
    return sorted(stems)


def discover_banner_stems(repo_root):
    """Scrape every gfx/shell/head_* literal straight out of the sources.

    This is the guard that would have caught the invented-name bug: instead of
    hand-copying the list, ask the code that actually requests the files.
    """
    import re
    pat = re.compile(r'gfx/shell/(head_[A-Za-z0-9_]+)')
    stems = set()
    for root, _dirs, files in os.walk(repo_root):
        if 'translations' in root or '.git' in root:
            continue
        for fn in files:
            if not fn.endswith(('.cpp', '.h')):
                continue
            try:
                txt = open(os.path.join(root, fn), encoding='utf-8',
                           errors='ignore').read()
            except OSError:
                continue
            stems.update(pat.findall(txt))
    return sorted(stems)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else '.'
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    all_ok = True

    # btns_main.bmp (the WON button atlas) is OUT OF SCOPE for this generator:
    # the button plates are not part of the standalone-widget restoration, so
    # the file is optional. Validate it only when present, e.g. when a real
    # WON asset was dropped in by hand.
    atlas = os.path.join(d, 'btns_main.bmp')
    if os.path.exists(atlas):
        all_ok &= check_btns(atlas)
    else:
        print('== btns_main.bmp        SKIPPED (button atlas, out of scope)')
    print()

    print('== standalone sprites')
    for stem, w, h in SPRITES:
        p = os.path.join(d, stem + '.bmp')
        if not os.path.exists(p):
            print('   %-26s MISSING' % stem)
            all_ok = False
            continue
        all_ok &= check_sprite(p, w, h)

    print()
    print('== arrows present for every stem BaseMenu.h asks for')
    for stem in ARROW_STEMS:
        ok = os.path.exists(os.path.join(d, stem + '.bmp'))
        print('   %-20s %s' % (stem, 'OK' if ok else 'MISSING'))
        all_ok &= ok

    print()
    banners = discover_banner_stems(repo)
    print('== banners (%d stems requested by menus/*.cpp)' % len(banners))
    for stem in banners:
        p = os.path.join(d, stem + '.bmp')
        if not os.path.exists(p):
            print('   %-26s MISSING' % stem)
            all_ok = False
            continue
        all_ok &= check_sprite(p, 240, 48)

    print()
    print('== orientation (row-order regression guard)')
    all_ok &= check_orientation(d)

    # --- completeness: every gfx/shell/<name> the code asks for must exist ---
    print()
    known = {s for s, _w, _h in SPRITES} | set(banners)
    wanted = [s for s in discover_shell_stems(repo) if s not in NON_IMAGE_STEMS]
    missing = [s for s in wanted if s not in known]
    print('== completeness: %d gfx/shell/ image stems referenced by the code'
          % len(wanted))
    print('   (%d data-file stems excluded: %s)'
          % (len(NON_IMAGE_STEMS), ', '.join(sorted(NON_IMAGE_STEMS))))
    if missing:
        for s in missing:
            print('   %-26s NOT COVERED by generator' % s)
        all_ok = False
    else:
        print('   all covered by the generator OK')

    print()
    print('RESULT:', 'PASS' if all_ok else 'FAIL')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
