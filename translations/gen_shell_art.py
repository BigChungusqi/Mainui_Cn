# -*- coding: utf-8 -*-
"""
gen_shell_art.py -- generate the missing gfx/shell/ menu artwork.

Why this exists
---------------
Xash3D FWGS deliberately does NOT ship the WON-style menu art. It is expected
to come from a legal Half-Life installation (or the FWGS/xash-extras repo).
Without it:

  * CBtnsManager::LoadBmpButtons() bails out (CBMP::LoadFile returns NULL)
    -> PicButton::Draw takes the *text* branch (letters only, no button plate)
  * CMenuCheckBox::Draw has NO fallback -> UI_DrawPic(0) -> engine binds
    tr.defaultTexture -> 16x16 magenta/black checkerboard
  * CMenuSlider::Draw draws the groove with UI_DrawRectangleExt (vector, fine)
    but the knob uses UI_DrawPic -> missing

Layout contract -- MUST NOT BREAK
----------------------------------
Btns.cpp:41      const int button_tex_h = height; // 26
Btns.cpp:42      const int src_cell_h   = button_tex_h * 3
Btns.cpp:43      const int pic_count    = Q_min( hdr->height / button_tex_h / 3, PC_BUTTONCOUNT )

So the atlas is a *vertical* strip of 26*pic_count*3 px, and button #n occupies
source rows [ n*78 , (n+1)*78 ). Within those 78 px:
    state 0 = BUTTON_NOFOCUS -> visual rows [0,26)
    state 1 = BUTTON_FOCUS   -> visual rows [26,52)
    state 2 = BUTTON_PRESSED -> visual rows [52,78)

Passing BUTTON_FOCUS to DrawButton() additionally sets PIC_Set alpha to 255
inside DrawButton() (PicButton.cpp:218), so at runtime the engine synthesises
its own focus/decay animation. That means state 1 and state 2 do NOT have to be
pre-baked -- they only need to be non-empty so the copy loop has something to
read. We bake them as slightly brighter / slightly sunken plates anyway, which
looks better when the engine's additive pass lands on top.

Row order contract
------------------
BMP files on disk are BOTTOM-UP: the first row in the file is the bottom row of
the image. Every writer in this file therefore emits y = height-1 first and
walks down to y = 0 (see write_bmp_bottom_up / write_raw_bmp).

Both consumers want that:
* Standalone sprites (cb_*, slider, arrows, min_*/cls_*, scroll arrows, badges,
  splash) are uploaded via PIC_Load -> ref_gl's GL_UploadTexture, which hands
  the buffer straight to pglTexImage2D (gl_image.c:908) with NO row flip. GL
  takes row 0 as t=0 (texture bottom), so a bottom-up file renders upright.
* Btns.cpp:135 (and :180) additionally flip with
    int src_row = src_height - 1 - src_visual_y;
  and equally expect a bottom-up file.

Getting this backwards mirrors every sprite vertically -- it is exactly what
made the checkbox tick render upside down and the up-arrow point down. Do NOT
"simplify" the flip away.

Format constraints
------------------
* 32bpp BI_RGB. The file starts with sizeof(bmp_t) == 54 bytes of header (magic
  "BM" included -- the engine casts the raw file to bmp_t*), then pixel data.
  CBMP::LoadFile validates fileSize, bitmapDataSize, bitmapDataOffset and
  bitmapHeaderSize against the real file length, so all of them must be exact.
* BI_RGB stores channels as B,G,R,A -- byte order in file is B,G,R,A, which is
  exactly the RF_BGRA layout the engine expects. No swap needed.
* WIDTH MUST BE A MULTIPLE OF 4. Btns.cpp:53 computes
      src_stride = ((hdr->width * bpp) + 3) & ~3
  which for bpp=4 is always width*4 (already aligned), yet the copy loop walks
  `memcpy(d, s, button_w * bpp)` and then advances the *row pointer* by
  src_stride. With width a multiple of 4 the two agree. hlslib's real atlas was
  a multiple of 4 and thus never exposed this. Keep it that way.
"""

import os
import struct
import math

# A tiny 5x7 bitmap font so the generated banners carry a real label.
FONT5X7 = {
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'B': ["11110", "10001", "11110", "10001", "10001", "10001", "11110"],
    'C': ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "11110", "10000", "10000", "10000", "11111"],
    'F': ["11111", "10000", "11110", "10000", "10000", "10000", "10000"],
    'G': ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    'H': ["10001", "10001", "11111", "10001", "10001", "10001", "10001"],
    'I': ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    'J': ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'N': ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    'Z': ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    '0': ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '2': ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    '3': ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    '9': ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '.': ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    '/': ["00001", "00001", "00010", "00100", "01000", "10000", "10000"],
    ' ': ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}

# labels, indexed by EDefaultBtns (Btns.h). Text is short on purpose: it is a
# placeholder identifier, the real localisation lives in the dictionary.


# ------------------------------------------------------------------- BMP write

# The BMP header is 14 (file header) + 40 (BITMAPINFOHEADER) = 54 bytes, which
# is exactly bmp_t in BMPUtils.h:
#   char id[2]; uint fileSize; uint reserved0; uint bitmapDataOffset;
#   uint bitmapHeaderSize; uint width; int height; word planes;
#   word bitsPerPixel; uint compression; uint bitmapDataSize;
#   uint hRes; uint vRes; uint colors; uint importantColors;
#
# THE HEADER IS sizeof(bmp_t) == 54 BYTES, AND THE MAGIC "BM" IS INSIDE IT.
# CBMP::LoadFile does:
#     bmp_t *bmp = (bmp_t*)COM_LoadFile( filename, &length );
#     if( (size_t)length < sizeof( bmp_t )) return NULL;
#     if( bmp->id[0] != 'B' || bmp->id[1] != 'M' ) return NULL;
# i.e. it casts the RAW FILE to bmp_t*. There is no separate 14 byte
# BITMAPFILEHEADER that we prepend and that bmp_t then skips -- bmp_t *is* the
# file header, id[2] included. So the pixel data starts at offset 54 and
# bitmapDataOffset (which LoadFile only checks as `length >= bitmapDataOffset`)
# is conventionally set to that same 54.
#
# Authoritative field types, read verbatim from BMPUtils.h:31-48:
#   char[2] id; uint fileSize; uint reserved0; uint bitmapDataOffset;
#   uint bitmapHeaderSize; uint width; int height; word planes;
#   word bitsPerPixel; uint compression; uint bitmapDataSize;
#   uint hRes; uint vRes; uint colors; uint importantColors;
#
# Do NOT "simplify" any of these to the on-disk BMP spec widths. The engine's
# struct widens several fields that are 2 bytes on disk (bitmapDataOffset is
# bfOffBits, height is biHeight as a signed dword) so that it can read them with
# plain 32 bit loads. Matching the engine struct, not the BMP spec, is what
# makes LoadFile's field checks land on the right bytes.
BMP_HDR_FMT = '<2sIIIIIiHHIIIIII'
_BMP_HDR_SIZE = struct.calcsize(BMP_HDR_FMT)
assert _BMP_HDR_SIZE == 54, 'sizeof(bmp_t) must be 54, got %d' % _BMP_HDR_SIZE


def _bmp_header(width, height, img_size, data_offset):
    """Build a sizeof(bmp_t) == 54 byte BMP header.

    This is the *whole* file header, magic included -- see BMP_HDR_FMT above.
    We emit a plain positive height. bmp_t does declare height as `int`, so a
    negative "top-down" biHeight would fit, but we deliberately do not use it:
    Btns.cpp:135 computes `src_row = src_height - 1 - src_visual_y` regardless,
    so a negative height would be double-flipped and mirror every button.
    """
    file_size = data_offset + img_size
    assert data_offset == _BMP_HDR_SIZE, \
        'data_offset must equal sizeof(bmp_t) (54), got %d' % data_offset
    assert file_size <= 0xFFFFFFFF, 'file too large for bmp_t.fileSize'
    assert 0 <= width <= 0xFFFFFFFF
    assert 0 <= height <= 0x7FFFFFFF, \
        'height %d must stay positive (see docstring)' % height

    return struct.pack(
        BMP_HDR_FMT,
        b'BM',          # id[2]        -- magic lives INSIDE bmp_t
        file_size,      # fileSize
        0,              # reserved0
        data_offset,    # bitmapDataOffset (54)
        40,             # bitmapHeaderSize (BITMAPINFOHEADER)
        width,          # width
        height,         # height (positive; row flip is done by Btns.cpp)
        1,              # planes
        32,             # bitsPerPixel
        0,              # compression = BI_RGB
        img_size,       # bitmapDataSize
        0,              # hRes
        0,              # vRes
        0,              # colors
        0,              # importantColors
    )


# ---------------------------------------------------------------- BMP writing

def _check_stride_rule(width, is_atlas):
    """The width % 4 rule is an *atlas-only* constraint.

    Btns.cpp:62 computes
        src_stride = ((hdr->width * bpp) + 3) & ~3
    and then advances the source row pointer by that stride while memcpy'ing
    `button_w * bpp` per row. For bpp=4 the two agree only when `width` is a
    multiple of 4 -- otherwise the row advance desyncs from the copy width and
    every row shears sideways.

    Standalone sprites (cb_*, slider, head_*, larrow*, ...) never touch that
    loop: they are uploaded through the ordinary GL_UploadTexture path, which
    reads bitmapDataSize and walks the buffer row by row with no separate
    stride assumption. So 22x22 and 24x24 are fine for them.
    """
    if is_atlas:
        assert width % 4 == 0, \
            'atlas width must be a multiple of 4 (Btns.cpp:62), got %d' % width


def write_bmp_bottom_up(path, width, height, get_pixel, is_atlas=False):
    """Write a 32bpp BI_RGB BMP with TRUE bottom-up rows on disk.

    BMP on disk is bottom-up: the first row in the file is the BOTTOM row of
    the image. `get_pixel(x, y)` is called with the logical top-down
    coordinates, so we must emit y = height-1 first and walk down to y = 0.

    Both consumers agree on this:
      * standalone sprites (cb_*, slider, arrows, min_*/cls_*, scroll arrows,
        badges, splash) go through PIC_Load -> GL_UploadTexture ->
        pglTexImage2D (gl_image.c:908), which passes the buffer straight to GL
        with no row flip. GL treats row 0 as t=0 (the bottom of the texture),
        so a bottom-up file lands the right way up on screen.
      * the atlas path in Btns.cpp:135 also flips with
        src_row = src_height - 1 - src_visual_y, and it too expects a bottom-up
        file. (We no longer generate the atlas here, but the rule is unchanged.)
    """
    _check_stride_rule(width, is_atlas)

    data_offset = _BMP_HDR_SIZE
    stride = width * 4
    img_size = stride * height

    with open(path, 'wb') as f:
        f.write(_bmp_header(width, height, img_size, data_offset))

        # emit bottom row first -> bottom-up file, as BMP requires
        for y in range(height - 1, -1, -1):
            row = bytearray()
            for x in range(width):
                r, g, b, a = get_pixel(x, y)
                row += bytes((b, g, r, a))   # BGRA on disk
            assert len(row) == stride
            f.write(row)

    return img_size


# ---------------------------------------------------------------- drawing bits

def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def rounded_mask(x, y, w, h, radius):
    """Rounded-rect coverage for a point, using the classic corner-circle test."""
    rx = min(x, w - 1 - x)
    ry = min(y, h - 1 - y)
    if rx < 0 or ry < 0:
        return False
    if rx >= radius or ry >= radius:
        return True
    dx = radius - rx
    dy = radius - ry
    return dx * dx + dy * dy <= radius * radius


def glyph_pixel(ch, gx, gy, scale):
    """Return True if (gx,gy) inside the scaled 5x7 glyph for ch."""
    rows = FONT5X7.get(ch)
    if rows is None:
        return False
    cw = 5 * scale
    chh = 7 * scale
    if gx < 0 or gy < 0 or gx >= cw or gy >= chh:
        return False
    return rows[gy // scale][gx // scale] == '1'


def text_width(s, scale, spacing):
    if not s:
        return 0
    return len(s) * 6 * scale - scale + (len(s) - 1) * spacing


def draw_text(buf, w, h, cx, cy, s, scale, spacing, color, shadow=None):
    """Blit a centred label into an RGBA bytearray (top-down rows)."""
    total = text_width(s, scale, spacing)
    x0 = int(cx - total / 2)
    y0 = int(cy - 7 * scale / 2)

    if shadow is not None:
        for i, ch in enumerate(s):
            gx0 = x0 + i * (6 * scale + spacing)
            for gy in range(7 * scale):
                for gx in range(5 * scale):
                    if not glyph_pixel(ch, gx, gy, scale):
                        continue
                    px, py = gx0 + gx + scale, y0 + gy + scale
                    if 0 <= px < w and 0 <= py < h:
                        o = (py * w + px) * 4
                        buf[o], buf[o + 1], buf[o + 2] = shadow[0], shadow[1], shadow[2]

    for i, ch in enumerate(s):
        gx0 = x0 + i * (6 * scale + spacing)
        for gy in range(7 * scale):
            for gx in range(5 * scale):
                if not glyph_pixel(ch, gx, gy, scale):
                    continue
                px, py = gx0 + gx, y0 + gy
                if 0 <= px < w and 0 <= py < h:
                    o = (py * w + px) * 4
                    buf[o], buf[o + 1], buf[o + 2] = color[0], color[1], color[2]


# ------------------------------------------------------- standalone UI sprites

def build_plain(path, w, h, draw_fn):
    """Emit a small standalone sprite. draw_fn(x,y,w,h) -> (r,g,b,a)."""
    return write_bmp_bottom_up(path, w, h, draw_fn)


def winbtn_art(kind, state):
    """Window-control glyphs the main menu overlays in its top-right corner.

    Main.cpp:34-39 asks for min_{n,f,d} and cls_{n,f,d}; Main.cpp:236,240 wires
    them as CMenuPicButtons (QMF_MOUSEONLY, QM_HIGHLIGHTIFFOCUS). 16x16 keeps
    them a sane click target regardless of buttons_draw_size.
      n = normal, f = flyover (hover), d = down (pressed)
    """
    size = 16
    hot = (238, 196, 92)
    cold = (176, 182, 196)
    down = (150, 120, 52)
    ink = hot if state == 'f' else down if state == 'd' else cold
    plate = (30, 32, 40) if state != 'f' else (46, 40, 26)

    def fn(x, y, w=size, h=size):
        if not rounded_mask(x, y, w, h, 2):
            return (0, 0, 0, 0)
        if x in (0, w - 1) or y in (0, h - 1):
            # Frame must stay DARKER than the glyph. A bright 1px frame reads
            # as a second bar inside a 16px box and makes the minimise glyph
            # look doubled. Keep it just above the plate value instead.
            frame = (58, 62, 74, 235) if state != 'f' else (74, 64, 42, 235)
            return frame
        if kind == 'cls':
            # X made of two diagonals, inside a 3px margin
            for dx in (-1, 0, 1):
                if abs((x - 3) - (y - 3)) == dx and 3 <= x <= 12 and 3 <= y <= 12:
                    return ink + (255,)
                if abs((12 - x) - (y - 3)) == dx and 3 <= x <= 12 and 3 <= y <= 12:
                    return ink + (255,)
        else:  # 'min' -- a single horizontal bar centred in the box
            if y in (7, 8) and 4 <= x <= 11:
                return ink + (255,)
        return plate + (240,)

    return fn


# Standalone button sprites named by the PC_* string defines in Btns.h:99-109.
# These are NOT atlas slots -- they are passed to SetPicture( const char* ) as
# literal filenames, so each needs its own file. 22x22 matches the plate feel.
def scroll_arrow_art(direction):
    """gfx/shell/up and gfx/shell/down -- the list scroll arrows (BaseMenu.h:39-40).

    Distinct from the larrow/rarrow family: these are 24x24 and used by
    CMenuScrollListBox, not by the number paddles.
    """
    w = h = 24
    ink = (198, 204, 218)

    def fn(x, y):
        cx = (w - 1) / 2.0
        half = abs(x - cx)
        if direction == 'up':
            # apex at top, widening downward
            if abs(half - (y - 3) * 0.62) <= 1.1 and 3 <= y <= 15:
                return ink + (255,)
            if y in (15, 16) and half <= 7.5:
                return ink + (255,)
        else:
            if abs(half - (18 - y) * 0.62) <= 1.1 and 8 <= y <= 20:
                return ink + (255,)
            if y in (7, 8) and half <= 7.5:
                return ink + (255,)
        return (0, 0, 0, 0)

    return fn


def badge_art(kind):
    """gfx/shell/lock, gfx/shell/favorite, gfx/shell/gamma -- 24x24 badges."""
    w = h = 24
    ink = (216, 222, 236)
    gold = (238, 196, 92)

    def fn(x, y):
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        dx, dy = x - cx, y - cy

        if kind == 'lock':
            # shackle arc above a solid body
            rr = (dx * dx + (dy + 5.0) ** 2) ** 0.5
            if 3.4 <= rr <= 5.2 and dy + 5.0 <= 0.5:
                return ink + (255,)
            if abs(dx) <= 6.0 and 0 <= dy <= 6.5:
                return ink + (255,)
            return (0, 0, 0, 0)

        if kind == 'favorite':
            # proper 5-point star via the classic radius-alternating test:
            # a point is inside if its radius is below the outline radius at
            # that angle. 10 sectors alternate outer/inner.
            import math
            ang = math.atan2(dy, dx)
            rr = (dx * dx + dy * dy) ** 0.5
            # fold to 0..2pi/5, then interpolate between inner and outer radius
            sector = (ang % (2 * math.pi / 5)) / (2 * math.pi / 5)
            # triangle wave: 0 at point, 1 at valley
            tri = abs(sector * 2 - 1)
            r_out = 9.0
            r_in = 3.6
            limit = r_out - (r_out - r_in) * tri
            # rotate so a point is up
            if rr <= limit:
                return gold + (255,)
            return (0, 0, 0, 0)

        # 'gamma' -- a brightness/sun badge: an 8-spoke wheel with a bright hub.
        # Kept as explicit spokes (not a filled disc) so it reads as 'brightness'
        # and not as the multiply/close X.
        rr = (dx * dx + dy * dy) ** 0.5
        if rr <= 5.2:
            # hub with a soft dot in the middle
            if rr <= 1.8:
                return (255, 250, 232, 255)
            return ink + (255,)
        if 7.0 <= rr <= 9.6:
            # 8 spokes at 0/45/90/... degrees; test the folded angle
            import math
            ang = math.atan2(dy, dx)
            # distance to the nearest multiple of 45 degrees, in radians
            step = math.pi / 4
            off = abs(((ang + step / 2) % step) - step / 2)
            # convert angular offset to a perpendicular pixel distance
            if rr * math.sin(off) <= 1.3:
                return ink + (255,)
        return (0, 0, 0, 0)

    return fn


def splash_art():
    """BackgroundBitmap fallback. Only seen if no steam/HL background exists.

    BackgroundBitmap.cpp stretches this to the full screen, so a plain vertical
    gradient with a vignette reads fine and costs nothing to generate.
    """
    w, h = 64, 64
    top, bot = (38, 44, 58), (12, 14, 20)

    def fn(x, y):
        t = y / max(1, h - 1)
        r, g, b = lerp(top, bot, t)
        # vignette: darken toward the frame edges
        cx, cy = (x - w / 2.0) / (w / 2.0), (y - h / 2.0) / (h / 2.0)
        d = (cx * cx + cy * cy) ** 0.5
        if d > 0.6:
            f = min(1.0, (d - 0.6) / 0.7)
            r, g, b = lerp((r, g, b), (4, 5, 8), f)
        return (r, g, b, 255)

    return fn


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from (px,py) to the segment (ax,ay)-(bx,by)."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    dx, dy = wx - t * vx, wy - t * vy
    return (dx * dx + dy * dy) ** 0.5


def _checkmark_coverage(x, y):
    """Anti-aliased coverage (0.0 .. 1.0) of a 16x16 checkmark at pixel (x,y).

    A tick is two strokes, not an X:
      * short leg: starts low-left, rises to the elbow
      * long  leg: elbow continues steeply up to the top-right

    Being a signed-distance test, this yields partial coverage on the stroke
    edges, which is what keeps the tick from looking like a jagged staircase --
    the old hard-edge version was the main reason the box read as 'wrong'.
    Sample the pixel centre and feather over ~1px. The stroke is nudged +0.5px
    in y so the tick lands optically centred inside the box (ink rows 4..12,
    centre 8.0 of a 16px box) instead of hugging the top edge.
    """
    cx, cy = x + 0.5, y + 0.5 + 0.5
    d = min(_seg_dist(cx, cy, 3.5, 9.5, 6.5, 12.5),    # short leg
            _seg_dist(cx, cy, 6.5, 12.5, 12.0, 4.5))    # long leg
    half = 1.05                                          # stroke half-width
    if d <= half - 0.5:
        return 1.0
    if d >= half + 0.5:
        return 0.0
    return (half + 0.5 - d)


def _checkmark(x, y):
    """Back-compat wrapper: True when the tick covers this pixel's centre."""
    return _checkmark_coverage(x, y) >= 0.5


def cb_art(kind):
    """Checkbox sprite generator: 16x16, one visual variant per `kind`.

    Visual model (logical top-down coords, y == 0 is the top row):
      * 1px outer frame, lit on the top/left and dark on the bottom/right, so
        it reads as a bevel
      * 1px inner well line, also darker toward the bottom-right
      * interior fill is near-black so the tick carries all the contrast
    The recessed bevel is what makes a checkbox read as an input control
    instead of a flat outlined square. The tick is anti-aliased; see
    _checkmark_coverage.
    """
    size = 16
    # bevel pair: light comes from above-left
    frame_hi = (178, 184, 198)
    frame_lo = (56, 58, 66)
    well = (18, 19, 24)
    fill = (11, 12, 16)
    # focus / pressed accents live in the HL orange family
    acc_hi = (244, 200, 96)
    acc_lo = (118, 92, 38)

    def fn(x, y, w=size, h=size):
        on_top, on_bottom = (y == 0), (y == h - 1)
        on_left, on_right = (x == 0), (x == w - 1)
        edge = on_top or on_bottom or on_left or on_right
        inner = (x == 1) or (y == 1) or (x == w - 2) or (y == h - 2)

        if kind == 'empty':
            if edge:
                return (frame_hi if (on_top or on_left) else frame_lo) + (255,)
            if inner:
                return well + (235,)
            return fill + (200,)

        if kind == 'disabled':
            if edge:
                return ((94, 96, 104) if (on_top or on_left) else (44, 45, 52)) + (225,)
            if inner:
                return (26, 27, 32) + (205,)
            return (13, 14, 17) + (175,)

        if kind == 'over':
            if edge:
                return (acc_hi if (on_top or on_left) else acc_lo) + (255,)
            if inner:
                return (52, 44, 26) + (240,)
            return (20, 18, 12) + (215,)

        if kind == 'down':
            # inverted bevel: pressed in, so the shadow moves to the top/left
            if edge:
                return (acc_lo if (on_top or on_left) else acc_hi) + (255,)
            if inner:
                return (36, 30, 17) + (245,)
            return (16, 14, 10) + (222,)

        if kind in ('checked', 'checked_over'):
            hot = (kind == 'checked_over')
            if edge:
                if hot:
                    return (acc_hi if (on_top or on_left) else acc_lo) + (255,)
                return (frame_hi if (on_top or on_left) else frame_lo) + (255,)
            if inner:
                return ((52, 44, 26) if hot else well) + (240,)
            base = (20, 18, 12) if hot else fill
            cov = _checkmark_coverage(x, y)
            if cov > 0.0:
                tick = (255, 246, 214) if hot else (246, 240, 220)
                return lerp(base, tick, cov) + (255,)
            return base + (215,)

        raise ValueError(kind)

    return fn


def slider_art():
    """Slider knob: 40x18 with two grip notches, matches m_scCenterBox aspect."""
    w, h = 40, 18
    top, bot = (96, 100, 114), (44, 46, 56)

    def fn(x, y):
        if not rounded_mask(x, y, w, h, 2):
            return (0, 0, 0, 0)
        r, g, b = lerp(top, bot, y / max(1, h - 1))
        if y == 0:
            r, g, b = (168, 174, 190)
        elif y == h - 1:
            r, g, b = (22, 23, 28)
        elif x == 0:
            r, g, b = lerp((r, g, b), (168, 174, 190), 0.5)
        elif x == w - 1:
            r, g, b = lerp((r, g, b), (22, 23, 28), 0.5)
        elif y == 2:
            r, g, b = lerp((r, g, b), (255, 255, 255), 0.10)
        # grip notches
        if x in (w // 2 - 5, w // 2, w // 2 + 5) and 5 <= y <= h - 6:
            r, g, b = (24, 25, 30)
        return (r, g, b, 255)

    return fn


def arrow_art(direction, variant):
    """Directional arrow sprite (24x14). `variant` is default / flyover / pressed.

    Coordinates are LOGICAL top-down: y == 0 is the top row of the sprite.
    write_bmp_bottom_up handles the on-disk flip, so anything computed here can
    reason in plain screen space.

    The paddles are drawn as solid triangles, not thin chevrons:
      * left / right -> a triangle whose APEX points left / right and whose base
        is the opposite edge. Because the sprite is 24 wide but only 14 tall, a
        left/right arrow is the natural filling shape.
      * up / down -> a triangle whose apex points up / down, spanning the full
        height. The apex sits at the very top (up) or very bottom (down) row.

    An earlier version derived all four directions from one chevron by swapping
    the (ux, uy) axes. In a non-square sprite that collapses `up` and `down`
    onto the same shape and mirrors left/right, which is why the paddles were
    drawn pointing the wrong way.
    """
    w, h = 24, 14
    if variant == 'default':
        fg, bg_a = (198, 200, 208), 0
    elif variant == 'flyover':
        fg, bg_a = (246, 208, 108), 0
    else:  # pressed
        fg, bg_a = (166, 138, 62), 0

    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0

    def fn(x, y):
        px, py = x + 0.5, y + 0.5

        if direction in ('left', 'right'):
            # triangle spanning the full height; apex on the given side.
            # half-height at the base, tapering to 0 at the apex.
            t = (px - 0.0) / (w - 1.0)          # 0 at left edge .. 1 at right
            if direction == 'right':
                t = 1.0 - t                     # apex now on the right
            half = (1.0 - t) * ((h - 2) / 2.0)  # widest at the base
            if abs(py - (cy + 0.5)) <= half:
                return fg + (255,)
            return (0, 0, 0, bg_a)

        # up / down: triangle spanning the full width; apex on top or bottom.
        t = (py - 0.0) / (h - 1.0)              # 0 at top .. 1 at bottom
        if direction == 'down':
            t = 1.0 - t                         # apex now at the bottom
        half = t * ((w - 2) / 2.0)              # widest at the base
        if abs(px - (cx + 0.5)) <= half:
            return fg + (255,)
        return (0, 0, 0, bg_a)

    return fn


_FONT_CACHE = {}


def _banner_font(size):
    """Return a CJK-capable TrueType face at `size`, or None if unavailable.

    The 5x7 FONT5X7 table below only covers ASCII, so Chinese captions need a
    real font. Prefer SimSun (宋体, simsun.ttc face 0): its serif strokes and
    embedded bitmap strikes suit the hard-edged banner style. Fall back to
    YaHei Bold / SimHei / serif CJK faces if SimSun is missing.
    """
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    windir = os.environ.get('WINDIR', 'C:/Windows')
    # (file, TTC face index). simsun.ttc face 0 is SimSun; face 1 is NSimSun
    # (monospaced), which is NOT the face we want here.
    candidates = [
        (os.path.join(windir, 'Fonts', 'simsun.ttc'), 0),
        (os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 0),
        (os.path.join(windir, 'Fonts', 'simhei.ttf'), 0),
        ('/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', 0),
        ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', 0),
    ]
    result = None
    for path, face in candidates:
        if not os.path.exists(path):
            continue
        try:
            result = ImageFont.truetype(path, size, index=face)
            break
        except OSError:
            continue
    _FONT_CACHE[size] = result
    return result


def banner_art(text, w=240, h=48):
    """Page banner (head_*): hard-edged caption with outline + drop shadow.

    CMenuFramework::CMenuBannerBitmap::Draw() (controls/Framework.cpp:236)
    draws this sprite with QM_DRAWADDITIVE, i.e. it is ADDED to the menu
    background. Two consequences:

      * every background pixel must stay (0,0,0,0) or it lights up as a plate;
      * nothing can be DARKER than the background, so a true black outline /
        shadow is impossible in this blend mode. Instead we use a hard,
        saturated amber-brown rim and a much dimmer offset copy: over a
        (26,24,22) menu background they land near (122,78,34) / (56,44,30),
        still far below the (255,204,46) glyph. Being crisp 2px / 4px-offset
        shapes (not a soft falloff) they read as relief, not bloom.

    Captions use a real TrueType face (FONT5X7 is ASCII-only) but are HARD
    THRESHOLDED -- no anti-aliasing, no smooth edges, every pixel is either a
    solid colour or fully transparent. Three binary masks are composited back
    to front: offset shadow, 2px dilated outline, solid glyph.

    Channel order is B,G,R,A (see write_raw_bmp / verify_shell_art.BMP.bgra).
    Every painted pixel is A=255 with an exact solid colour: no coverage
    pre-multiplication, no blur, no halo, no warm-white core.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageChops
    except ImportError:
        raise RuntimeError('gen_shell_art.py needs Pillow to rasterise CJK banners')

    glyph_rgb   = (240, 180, 24)   # uiPromptTextColor, BaseMenu.cpp:64
    outline_rgb = (96, 54, 12)     # hard 2px amber-brown rim
    shadow_rgb  = (30, 20, 8)      # dim drop, offset +4/+4
    SHADOW_DX, SHADOW_DY = 4, 4
    OUTLINE_PX = 2

    max_w, min_size, size = w - 16, 12, 30
    font = None
    while size >= min_size:
        f = _banner_font(size)
        if f is None:
            break
        font = f
        box = f.getbbox(text)
        if (box[2] - box[0]) <= max_w:
            break
        size -= 1
    if font is None:
        raise RuntimeError('no CJK TrueType font found '
                           '(tried WINDIR/Fonts/simsun.ttc, msyhbd.ttc, simhei.ttf)')

    box = font.getbbox(text)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (w - tw) / 2.0 - box[0]
    y = (h - th) / 2.0 - box[1]

    aa = Image.new('L', (w, h), 0)
    ImageDraw.Draw(aa).text((x, y), text, font=font, fill=255)
    glyph = aa.point(lambda v: 255 if v >= 128 else 0)   # kill AA entirely
    outline = ImageChops.subtract(
        glyph.filter(ImageFilter.MaxFilter(2 * OUTLINE_PX + 1)), glyph)
    shadow = Image.new('L', (w, h), 0)
    shadow.paste(glyph.crop((0, 0, w - SHADOW_DX, h - SHADOW_DY)),
                 (SHADOW_DX, SHADOW_DY))

    g_px, o_px, s_px = glyph.load(), outline.load(), shadow.load()

    def bgra(rgb):
        r, g, b = rgb
        return (b, g, r, 255)

    shadow_q, outline_q, glyph_q = (bgra(c) for c in
                                    (shadow_rgb, outline_rgb, glyph_rgb))
    buf = bytearray(w * h * 4)
    for yy in range(h):
        row = yy * w
        for xx in range(w):
            # priority: glyph > outline > shadow > transparent
            if g_px[xx, yy]:
                q = glyph_q
            elif o_px[xx, yy]:
                q = outline_q
            elif s_px[xx, yy]:
                q = shadow_q
            else:
                continue
            o = (row + xx) * 4
            buf[o], buf[o + 1], buf[o + 2], buf[o + 3] = q
    return bytes(buf)


# (English caption, Chinese caption, stem). Stems are harvested verbatim from
# the ART_BANNER defines in menus/*.cpp (plus the Zoo.cpp showcase list). Do
# not guess these -- they are the literal strings FS_LoadImage is asked for
# (extension resolved by Image_ProbeLoad).
#
# Chinese labels reuse the translations already shipped in
# bin/a_schinese/resource/mainui_schinese.txt where one exists
# ("Adv. Options"->高级选项, "Game options"->游戏选项, "Touch buttons"->触摸按钮,
# "Video modes"->视频模式, ...). The rest use the same vocabulary as the rest
# of that dictionary. Both languages are rasterised into the BMP; --lang picks
# which one gets baked, so the artwork itself stays L10N-free at runtime.
BANNERS = [
    ('OPTIONS',       '选项',         'head_config'),
    ('AUDIO',         '音频',         'head_audio'),
    ('VIDEO',         '视频',         'head_video'),
    ('VIDEO MODES',   '视频模式',     'head_vidmodes'),
    ('VIDEO OPTIONS', '视频选项',     'head_vidoptions'),
    ('CONTROLS',      '控制',         'head_controls'),
    ('ADVANCED',      '高级',         'head_advanced'),
    ('ADV OPTIONS',   '高级选项',     'head_advoptions'),
    ('GAMEPAD',       '手柄',         'head_gamepad'),
    ('GYRO',          '陀螺仪',       'head_gyro'),
    ('KEYBOARD',      '键盘',         'head_keyboard'),
    ('NEW GAME',      '新游戏',       'head_newgame'),
    ('SINGLE PLAYER', '单人游戏',     'head_single'),
    ('MULTIPLAYER',   '多人游戏',     'head_multi'),
    ('CREATE GAME',   '创建游戏',     'head_creategame'),
    ('CUSTOM GAME',   '自定义游戏',   'head_custom'),
    ('CUSTOMIZE',     '自定义',       'head_customize'),
    ('GAME OPTIONS',  '游戏选项',     'head_gameopts'),
    ('LOAD GAME',     '载入游戏',     'head_load'),
    ('SAVE GAME',     '保存游戏',     'head_save'),
    ('SAVE/LOAD',     '保存/加载',    'head_saveload'),
    ('INTERNET',      '互联网游戏',   'head_inetgames'),
    ('LAN GAMES',     '局域网游戏',   'head_lan'),
    ('SERVER FILTER', '服务器筛选',   'head_filter'),
    ('SPECTATE',      '观战',         'head_specgames'),
    ('GORE',          '血腥效果',     'head_gore'),
    ('READ ME',       '自述文件',     'head_readme'),
    ('TOUCH',         '触摸',         'head_touch'),
    ('TOUCH BUTTONS', '触摸按钮',     'head_touch_buttons'),
    ('TOUCH OPTIONS', '触摸选项',     'head_touchoptions'),
    ('TOUCH OPT',     '触摸选项',     'head_touch_options'),
    ('PLAY',          '播放',         'head_play'),
    ('RECORD',        '录制',         'head_record'),
    ('PLAY RECORD',   '播放录像',     'head_playrec'),
    ('ROOM',          '房间',         'head_room'),
    ('ROOMS',         '房间列表',     'head_rooms'),
    ('CREATE ROOM',   '创建房间',     'head_createroom'),
]


def banner_labels(lang):
    """Yield (caption, stem) for the requested baked-in language."""
    if lang not in ('cn', 'en'):
        raise SystemExit('--lang must be cn or en (got %r)' % lang)
    for en, cn, stem in BANNERS:
        yield (cn if lang == 'cn' else en), stem


def write_raw_bmp(path, w, h, rgba):
    """Write a pre-rendered RGBA buffer (top-down rows) as a 32bpp BMP.

    The buffer arrives top-down (row 0 = top of the image) but BMP on disk is
    bottom-up, so we flip the row order here -- same contract as
    write_bmp_bottom_up. Without the flip every banner comes out vertically
    mirrored (see banner_art for the visual proof).
    """
    _check_stride_rule(w, is_atlas=False)
    data_offset, stride = _BMP_HDR_SIZE, w * 4
    img_size = stride * h
    assert len(rgba) == img_size, 'buffer is %d, expected %d' % (len(rgba), img_size)

    with open(path, 'wb') as f:
        f.write(_bmp_header(w, h, img_size, data_offset))
        for y in range(h - 1, -1, -1):
            f.write(rgba[y * stride:(y + 1) * stride])
    return img_size


# --------------------------------------------------------------------- driver

def main():
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out = args[0] if args else '.'
    banners_only = '--banners-only' in sys.argv[1:]
    lang = 'cn'
    for a in sys.argv[1:]:
        if a.startswith('--lang='):
            lang = a.split('=', 1)[1]
    if lang not in ('cn', 'en'):
        raise SystemExit('--lang must be cn or en (got %r)' % lang)

    os.makedirs(out, exist_ok=True)
    made = []

    # Regenerate only the 37 page banners. Useful when deploying a caption
    # restyle without touching any of the standalone widget sprites.
    if banners_only:
        for text, stem in banner_labels(lang):
            p = os.path.join(out, stem + '.bmp')
            made.append((p, write_raw_bmp(p, 240, 48, banner_art(text))))
        for path, size in made:
            print('%-28s %8d bytes' % (os.path.basename(path), os.path.getsize(path)))
        print('\n%d banners (lang=%s) -> %s' % (len(made), lang, out))
        return

    # NOTE: btns_main.bmp and the btn_* PicButton sprites are deliberately NOT
    # generated. Those belong to the button plates, which the user did not ask
    # us to restore -- only the standalone widgets (checkbox, slider, arrows,
    # window controls, scroll arrows, badges, banners, splash) are in scope.

    # checkbox variants. cb_checked_over is an extra the stock code never asks
    # for, but CMenuCheckBox writes szPressPic over szFocusPic additively, so a
    # combined sprite is what actually reads well.
    for kind, name in [('empty', 'cb_empty.bmp'),
                       ('over', 'cb_over.bmp'),
                       ('down', 'cb_down.bmp'),
                       ('checked', 'cb_checked.bmp'),
                       ('checked_over', 'cb_checked_over.bmp'),
                       ('disabled', 'cb_disabled.bmp')]:
        p = os.path.join(out, name)
        made.append((p, build_plain(p, 16, 16, cb_art(kind))))

    p = os.path.join(out, 'slider.bmp')
    made.append((p, build_plain(p, 40, 18, slider_art())))

    # Arrow names are NOT uniform -- Left/Right spell the state out, Up/Down use
    # a single letter suffix. Verbatim from BaseMenu.h:41-52:
    #   gfx/shell/larrowdefault  larrowflyover  larrowpressed
    #   gfx/shell/rarrowdefault  rarrowflyover  rarrowpressed
    #   gfx/shell/uparrowd       uparrowf       uparrowp
    #   gfx/shell/dnarrowd       dnarrowf       dnarrowp
    ARROW_NAMES = {
        ('left',  'default'): 'larrowdefault.bmp',
        ('left',  'flyover'): 'larrowflyover.bmp',
        ('left',  'pressed'): 'larrowpressed.bmp',
        ('right', 'default'): 'rarrowdefault.bmp',
        ('right', 'flyover'): 'rarrowflyover.bmp',
        ('right', 'pressed'): 'rarrowpressed.bmp',
        ('up',    'default'): 'uparrowd.bmp',
        ('up',    'flyover'): 'uparrowf.bmp',
        ('up',    'pressed'): 'uparrowp.bmp',
        ('down',  'default'): 'dnarrowd.bmp',
        ('down',  'flyover'): 'dnarrowf.bmp',
        ('down',  'pressed'): 'dnarrowp.bmp',
    }
    for (d, variant), name in sorted(ARROW_NAMES.items()):
        p = os.path.join(out, name)
        made.append((p, build_plain(p, 24, 14, arrow_art(d, variant))))

    # Page banners: transparent plate + flat non-glowing caption in the
    # runtime button colour. BANNERS / banner_labels live at module scope.
    for text, stem in banner_labels(lang):
        p = os.path.join(out, stem + '.bmp')
        made.append((p, write_raw_bmp(p, 240, 48, banner_art(text))))

    for stem, kind in [('cls', 'cls'), ('min', 'min')]:
        for state, suffix in (('n', 'n'), ('f', 'f'), ('d', 'd')):
            p = os.path.join(out, '%s_%s.bmp' % (stem, suffix))
            made.append((p, build_plain(p, 16, 16, winbtn_art(kind, state))))

    p = os.path.join(out, 'splash.bmp')
    made.append((p, build_plain(p, 64, 64, splash_art())))

    # list scroll arrows (BaseMenu.h:39-40)
    for stem, direction in (('up', 'up'), ('down', 'down')):
        p = os.path.join(out, stem + '.bmp')
        made.append((p, build_plain(p, 24, 24, scroll_arrow_art(direction))))

    # server-browser / video badges
    for stem, kind in (('lock', 'lock'), ('favorite', 'favorite'),
                       ('gamma', 'gamma')):
        p = os.path.join(out, stem + '.bmp')
        made.append((p, build_plain(p, 24, 24, badge_art(kind))))

    for path, size in made:
        print('%-28s %8d bytes' % (os.path.basename(path), os.path.getsize(path)))
    print('\n%d files -> %s' % (len(made), out))


if __name__ == '__main__':
    main()
