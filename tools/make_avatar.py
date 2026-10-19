#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 PlanWeaver 市场头像（512×512 PNG），仅用 Python 标准库。

设计意图：三条不同长度的"目标带"（学习/工作/生活）被一条竖向"时间轴"编织在一起，
右端圆点是里程碑。深色底 + 三色带在小尺寸下仍可辨认。

用法:
    python tools/make_avatar.py
    python tools/make_avatar.py --size 512 --out release

输出:
    release/avatar-512.png        深色底（默认，推荐）
    release/avatar-512-light.png  浅色底（备用，适合浅色列表）

纯数学绘制（圆角矩形 SDF + 1px 抗锯齿），不依赖 Pillow / numpy。
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import zlib

# 调色
DARK_BG = (0x22, 0x2A, 0x45)      # 深靛
LIGHT_BG = (0xF6, 0xF3, 0xEC)     # 暖白
IVORY = (0xF4, 0xEF, 0xE4)
AMBER = (0xE9, 0xA6, 0x3F)
TEAL = (0x67, 0xAF, 0xA4)
INK = (0x22, 0x2A, 0x45)
AXIS = (0x9A, 0xA3, 0xC4)         # 时间轴：淡紫灰，与三条带区分开


def sd_round_rect(px, py, cx, cy, hw, hh, r):
    """圆角矩形的有符号距离（负值在内部）。"""
    dx = abs(px - cx) - (hw - r)
    dy = abs(py - cy) - (hh - r)
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    return math.hypot(ax, ay) + min(max(dx, dy), 0.0) - r


def coverage(distance):
    """把有符号距离转成 0–1 覆盖率，得到 1px 抗锯齿。"""
    return min(1.0, max(0.0, 0.5 - distance))


class Canvas:
    def __init__(self, size):
        self.size = size
        # 预乘前的 RGBA 浮点缓冲
        self.px = [[0.0, 0.0, 0.0, 0.0] for _ in range(size * size)]

    def blend(self, x, y, color, alpha):
        if alpha <= 0:
            return
        index = y * self.size + x
        dst = self.px[index]
        a = alpha + dst[3] * (1 - alpha)
        if a <= 0:
            return
        for channel in range(3):
            src = color[channel] / 255.0          # 调色板用 0–255，缓冲用 0–1
            dst[channel] = (src * alpha + dst[channel] * dst[3] * (1 - alpha)) / a
        dst[3] = a

    def fill_round_rect(self, cx, cy, hw, hh, r, color, alpha=1.0):
        for y in range(self.size):
            for x in range(self.size):
                d = sd_round_rect(x + 0.5, y + 0.5, cx, cy, hw, hh, r)
                if d < 1.0:
                    self.blend(x, y, color, coverage(d) * alpha)

    def fill_circle(self, cx, cy, radius, color, alpha=1.0):
        for y in range(self.size):
            for x in range(self.size):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy) - radius
                if d < 1.0:
                    self.blend(x, y, color, coverage(d) * alpha)

    def to_rgba_bytes(self):
        out = bytearray()
        for y in range(self.size):
            out.append(0)  # filter type 0
            row = self.px[y * self.size:(y + 1) * self.size]
            for r, g, b, a in row:
                out.extend((
                    int(round(min(1.0, max(0.0, r)) * 255)),
                    int(round(min(1.0, max(0.0, g)) * 255)),
                    int(round(min(1.0, max(0.0, b)) * 255)),
                    int(round(min(1.0, max(0.0, a)) * 255)),
                ))
        return bytes(out)


def write_png(path, width, height, rgba):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", header)
               + chunk(b"IDAT", zlib.compress(rgba, 9))
               + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(payload)


def render(size, dark=True):
    """按 512 的设计坐标绘制，再按 size/512 等比缩放。"""
    scale = size / 512.0
    canvas = Canvas(size)

    def s(value):
        return value * scale

    bg = DARK_BG if dark else LIGHT_BG
    canvas.fill_round_rect(s(256), s(256), s(256), s(256), s(112), bg, 1.0)

    band_colors = [IVORY if dark else INK, AMBER, TEAL]
    band_y = [172, 256, 340]
    band_end = [372, 404, 344]          # 不同长度 = 不同进度
    band_half = s(15)
    left = s(118)

    # 竖向时间轴（先画，作为"经线"）
    axis_x = s(150)
    axis_color = AXIS if dark else (0x7A, 0x82, 0x9E)
    canvas.fill_round_rect(axis_x, s(256), s(8), s(126), s(8), axis_color, 1.0)

    # 三条横向目标带（"纬线"），中间那条覆盖时间轴 → 形成"上下穿插"的编织感
    for index, (y, end) in enumerate(zip(band_y, band_end)):
        color = band_colors[index]
        canvas.fill_round_rect((left + s(end)) / 2, s(y),
                               (s(end) - left) / 2, band_half, band_half, color, 1.0)

    # 第 1、3 条带之后重画时间轴，让轴从它们上方压过；第 2 条保持被覆盖
    for y in (band_y[0], band_y[2]):
        canvas.fill_round_rect(axis_x, s(y), s(8), s(19), s(8), axis_color, 1.0)

    # 里程碑节点：先挖一圈底色，再放实心点，避免看起来像"孔"
    for index, (y, end) in enumerate(zip(band_y, band_end)):
        canvas.fill_circle(s(end), s(y), s(21), bg, 1.0)
        canvas.fill_circle(s(end), s(y), s(16), band_colors[index], 1.0)

    return canvas.to_rgba_bytes()


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成 PlanWeaver 头像 PNG")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--out", default=os.path.join("release"))
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    for dark, name in ((True, f"avatar-{args.size}.png"),
                       (False, f"avatar-{args.size}-light.png")):
        path = os.path.join(args.out, name)
        write_png(path, args.size, args.size, render(args.size, dark=dark))
        print(f"已生成 {path}（{os.path.getsize(path):,} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
