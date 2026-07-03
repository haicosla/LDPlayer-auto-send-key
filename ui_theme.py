# -*- coding: utf-8 -*-
"""
ui_theme.py
============
Bảng màu + font + style dùng chung cho TOÀN BỘ chương trình.

Chỉ cần gọi apply_theme(root) MỘT LẦN duy nhất, ngay sau khi tạo cửa sổ
gốc (root = tk.Tk()), trước khi tạo bất kỳ widget nào khác. Vì ttk.Style
áp dụng cho cả trình thông dịch Tk (không phải riêng từng cửa sổ), nên
mọi cửa sổ con (tk.Toplevel) mở ra sau đó — kể cả cửa sổ "Chạy record",
"Tính giờ recoder", "Quản lý nhóm", "Sửa job"... — sẽ TỰ ĐỘNG đồng bộ
giao diện mà không cần sửa gì thêm ở các file đó.

File này KHÔNG đổi bất kỳ logic/tính năng nào, chỉ định nghĩa màu sắc,
font chữ và style hiển thị.
"""

import tkinter as tk
from tkinter import ttk
import sys

# ──────────────────────────────────────────────────────────────────────
# BẢNG MÀU
# ──────────────────────────────────────────────────────────────────────
BG = "#F3F5F9"              # nền cửa sổ / khung
SURFACE = "#FFFFFF"         # nền ô nhập, bảng, danh sách
SURFACE_ALT = "#EDF1F8"     # nền phụ (hàng chẵn, khu vực nhấn nhẹ)
BORDER = "#DCE2ED"          # viền nhạt
BORDER_STRONG = "#C3CCDD"

TEXT = "#1F2937"            # chữ chính
TEXT_MUTED = "#6B7280"      # chữ phụ / ghi chú
TEXT_ON_ACCENT = "#FFFFFF"

ACCENT = "#2F6FED"          # xanh dương chủ đạo (nút chính)
ACCENT_HOVER = "#255ACB"
ACCENT_PRESSED = "#1E4AA8"
ACCENT_SOFT = "#E4ECFE"     # nền xanh nhạt (tiêu đề khung, chọn dòng)

SUCCESS = "#1E9E5A"         # nút "Chạy ngay", hành động tích cực
SUCCESS_HOVER = "#178048"

DANGER = "#E1483F"          # nút "Xóa", "Dừng"
DANGER_HOVER = "#C93A32"

WARNING = "#D98324"         # nút "Sửa", cảnh báo nhẹ
WARNING_HOVER = "#B96A16"

NEUTRAL = "#5B6472"         # nút phụ / thứ cấp
NEUTRAL_HOVER = "#454C58"

# ──────────────────────────────────────────────────────────────────────
# FONT
# ──────────────────────────────────────────────────────────────────────
_FONT_FAMILY = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"

FONT_BASE = (_FONT_FAMILY, 9)
FONT_BOLD = (_FONT_FAMILY, 4, "bold")
FONT_SMALL = (_FONT_FAMILY, 7)
FONT_SMALL_BOLD = (_FONT_FAMILY, 8, "bold")
FONT_HEADER = (_FONT_FAMILY, 5, "bold")
FONT_SUBHEADER = (_FONT_FAMILY, 6, "bold")
FONT_MONO = ("Consolas" if sys.platform.startswith("win") else "Courier New", 7)


def _style_button_variant(style, name, base, hover, pressed, fg=TEXT_ON_ACCENT):
    """Tạo 1 biến thể ttk.Button (màu nền riêng) dùng chung layout TButton."""
    style.configure(
        name,
        background=base,
        foreground=fg,
        bordercolor=base,
        lightcolor=base,
        darkcolor=base,
        focusthickness=0,
        focuscolor=base,
        padding=(8, 3),
        font=FONT_BASE,
        borderwidth=0,
        relief="flat",
    )
    style.map(
        name,
        background=[("disabled", "#B9C0CC"), ("pressed", pressed), ("active", hover)],
        foreground=[("disabled", "#E7EAF0")],
    )


def apply_theme(root: tk.Misc) -> None:
    """Áp style hiện đại, đồng bộ cho root và mọi cửa sổ con sau này."""

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(background=BG)

    # ---- Nền / khung chung -------------------------------------------------
    style.configure(".", background=BG, foreground=TEXT, font=FONT_BASE)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)

    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_BASE)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("Header.TLabel", background=BG, foreground=TEXT, font=FONT_HEADER)
    style.configure("SubHeader.TLabel", background=BG, foreground=ACCENT_PRESSED, font=FONT_SUBHEADER)
    style.configure("Success.TLabel", background=BG, foreground=SUCCESS, font=FONT_SMALL_BOLD)
    style.configure("Danger.TLabel", background=BG, foreground=DANGER, font=FONT_SMALL_BOLD)

    # ---- Khung nhóm (LabelFrame) -------------------------------------------
    style.configure(
        "TLabelframe",
        background=BG,
        bordercolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        borderwidth=1,
        relief="solid",
        padding=6,
    )
    style.configure(
        "TLabelframe.Label",
        background=BG,
        foreground=ACCENT_PRESSED,
        font=FONT_SUBHEADER,
        padding=(4, 2),
    )

    # ---- Nút bấm -------------------------------------------------------------
    # Mặc định TButton = màu accent (nút chính)
    _style_button_variant(style, "TButton", ACCENT, ACCENT_HOVER, ACCENT_PRESSED)
    _style_button_variant(style, "Accent.TButton", ACCENT, ACCENT_HOVER, ACCENT_PRESSED)
    _style_button_variant(style, "Success.TButton", SUCCESS, SUCCESS_HOVER, SUCCESS_HOVER)
    _style_button_variant(style, "Danger.TButton", DANGER, DANGER_HOVER, DANGER_HOVER)
    _style_button_variant(style, "Warning.TButton", WARNING, WARNING_HOVER, WARNING_HOVER)
    _style_button_variant(style, "Secondary.TButton", NEUTRAL, NEUTRAL_HOVER, NEUTRAL_HOVER)
    # Nút viền mảnh, nền trắng - dùng cho hành động phụ ít quan trọng
    style.configure(
        "Ghost.TButton",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        borderwidth=1,
        relief="solid",
        padding=(8, 3),
        font=FONT_BASE,
    )
    style.map(
        "Ghost.TButton",
        background=[("active", SURFACE_ALT), ("pressed", SURFACE_ALT)],
        bordercolor=[("active", ACCENT)],
    )

    # ---- Ô nhập liệu ----------------------------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        padding=4,
        insertcolor=TEXT,
        relief="flat",
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        arrowcolor=ACCENT_PRESSED,
        padding=4,
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE), ("disabled", SURFACE_ALT)],
        foreground=[("disabled", TEXT_MUTED)],
        bordercolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT_ON_ACCENT)
    root.option_add("*TCombobox*Listbox.font", FONT_BASE)

    style.configure("TCheckbutton", background=BG, foreground=TEXT, font=FONT_BASE)
    style.map("TCheckbutton", background=[("active", BG)])

    # ---- Notebook (tab), nếu có dùng sau này ----------------------------------
    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    style.configure(
        "TNotebook.Tab",
        background=SURFACE_ALT,
        foreground=TEXT_MUTED,
        padding=(10, 5),
        font=FONT_BASE,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE)],
        foreground=[("selected", ACCENT_PRESSED)],
        expand=[("selected", (1, 1, 1, 0))],
    )

    # ---- Bảng (Treeview) --------------------------------------------------------
    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        borderwidth=1,
        rowheight=22,
        font=FONT_BASE,
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_ALT,
        foreground=TEXT,
        font=FONT_SMALL_BOLD,
        relief="flat",
        padding=(6, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", TEXT)],
    )
    style.map("Treeview.Heading", background=[("active", SURFACE_ALT)])

    # ---- Thanh cuộn --------------------------------------------------------------
    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_ALT,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=TEXT_MUTED,
        relief="flat",
        arrowsize=14,
    )
    style.map("Vertical.TScrollbar", background=[("active", BORDER_STRONG)])
    style.configure(
        "Horizontal.TScrollbar",
        background=SURFACE_ALT,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=TEXT_MUTED,
        relief="flat",
        arrowsize=14,
    )
    style.map("Horizontal.TScrollbar", background=[("active", BORDER_STRONG)])

    style.configure("TSeparator", background=BORDER_STRONG)
    style.configure("TPanedwindow", background=BG)

    # ────────────────────────────────────────────────────────────────────
    # Widget tk "cổ điển" (không phải ttk) — dùng option database để mọi
    # tk.Label / tk.Frame / tk.Entry / tk.Listbox / tk.Text / tk.Canvas
    # được tạo SAU lệnh này (kể cả trong các cửa sổ con mở sau) tự động
    # nhận đúng màu + font, không cần sửa từng dòng code tạo widget.
    # ────────────────────────────────────────────────────────────────────
    root.option_add("*Font", FONT_BASE)
    root.option_add("*Background", BG)
    root.option_add("*Foreground", TEXT)

    root.option_add("*Frame.Background", BG)
    root.option_add("*Label.Background", BG)
    root.option_add("*Label.Foreground", TEXT)

    root.option_add("*Entry.Background", SURFACE)
    root.option_add("*Entry.Foreground", TEXT)
    root.option_add("*Entry.insertBackground", TEXT)
    root.option_add("*Entry.relief", "flat")
    root.option_add("*Entry.highlightThickness", 1)
    root.option_add("*Entry.highlightBackground", BORDER_STRONG)
    root.option_add("*Entry.highlightColor", ACCENT)

    root.option_add("*Listbox.Background", SURFACE)
    root.option_add("*Listbox.Foreground", TEXT)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", TEXT_ON_ACCENT)
    root.option_add("*Listbox.relief", "flat")
    root.option_add("*Listbox.highlightThickness", 1)
    root.option_add("*Listbox.highlightBackground", BORDER_STRONG)
    root.option_add("*Listbox.highlightColor", ACCENT)

    root.option_add("*Text.Background", SURFACE)
    root.option_add("*Text.Foreground", TEXT)
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", BORDER_STRONG)
    root.option_add("*Text.font", FONT_MONO)

    root.option_add("*Canvas.Background", BG)
    root.option_add("*Canvas.highlightThickness", 0)

    root.option_add("*Menu.Background", SURFACE)
    root.option_add("*Menu.Foreground", TEXT)
    root.option_add("*Menu.activeBackground", ACCENT_SOFT)
    root.option_add("*Menu.activeForeground", TEXT)

    # Toplevel con (cửa sổ "Chạy record", "Quản lý nhóm", "Sửa job"...) cũng
    # cần được set nền ngay khi tạo — bọc lại tk.Toplevel để tự động
    # configure(background=BG) mà KHÔNG cần sửa từng file mở cửa sổ con.
    _patch_toplevel_background(root)


def _patch_toplevel_background(root):
    """Khiến MỌI tk.Toplevel tạo sau thời điểm này tự nhận nền đồng bộ."""
    if getattr(tk.Toplevel, "_ui_theme_patched", False):
        return
    _orig_init = tk.Toplevel.__init__

    def _patched_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            self.configure(background=BG)
        except tk.TclError:
            pass

    tk.Toplevel.__init__ = _patched_init
    tk.Toplevel._ui_theme_patched = True
