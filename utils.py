# utils.py

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
import time
import threading
import win32gui
import win32con
import win32api
import win32process
import ctypes
from datetime import datetime
from config import OPR_WINDOW_X, OPR_WINDOW_Y
from logger import get_logger

logger = get_logger()


# ─────────────────────────────────────────────────────────────
# Lấy hwnd
# ─────────────────────────────────────────────────────────────

def get_ldplayer_hwnd(instance_name: str) -> int | None:
    """Lấy window handle của LDPlayer instance (exact title match)."""
    hwnd = win32gui.FindWindow(None, instance_name)
    if hwnd == 0:
        logger.warning(f"[HWND] Không tìm thấy cửa sổ '{instance_name}'")
        return None
    return hwnd


# ─────────────────────────────────────────────────────────────
# Messagebox tự đóng
# ─────────────────────────────────────────────────────────────

def auto_close_messagebox(msg_type: str, title: str, message: str, auto_close_sec: int = 2):
    """Hiển thị messagebox tự động đóng sau thời gian chỉ định."""
    def show_and_close():
        win = tk.Toplevel()
        win.title(title)
        win.geometry("400x180")
        win.resizable(False, False)
        win.attributes('-topmost', True)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=message, wraplength=360, justify="left").pack(anchor="w", pady=(0, 12))
        ttk.Button(frm, text="Đóng", command=win.destroy).pack(side="right")

        win.after(auto_close_sec * 1000, win.destroy)
        win.grab_set()
        win.wait_window()

    threading.Thread(target=show_and_close, daemon=True).start()


# ─────────────────────────────────────────────────────────────
# Focus emulator — 2 phiên bản
# ─────────────────────────────────────────────────────────────

def focus_emulator(name: str) -> bool:
    """
    Focus cơ bản (giữ tương thích ngược).
    Dùng EnumWindows + SetForegroundWindow với retry đơn giản.
    """
    hwnds = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if name.lower() in title:
                hwnds.append(hwnd)

    try:
        win32gui.EnumWindows(callback, None)
    except Exception as e:
        logger.error(f"[FOCUS] EnumWindows lỗi: {e}")
        return False

    if not hwnds:
        logger.warning(f"[FOCUS] Không tìm thấy cửa sổ: '{name}'")
        return False

    hwnd = hwnds[0]
    for attempt in range(3):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            logger.info(f"[FOCUS] Đã focus '{name}' (lần {attempt + 1})")
            return True
        except Exception as e:
            logger.warning(f"[FOCUS] Lần {attempt + 1} lỗi: {e}")
            time.sleep(0.5)

    logger.error(f"[FOCUS] Không focus được '{name}' sau 3 lần")
    return False


def focus_emulator_reliable(instance_name: str, retries: int = 3) -> bool:
    """
    Focus đáng tin cậy hơn — dùng AttachThreadInput để bypass giới hạn
    SetForegroundWindow của Windows (Windows không cho phép app nền tự đưa
    cửa sổ khác lên foreground nếu không attach vào thread của nó).

    Dùng cho gui.py (nút "Lên") và executor.py.
    """
    # Tìm hwnd qua partial title match
    found = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if instance_name.lower() in title.lower():
                found.append(hwnd)

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as e:
        logger.error(f"[FOCUS_R] EnumWindows lỗi: {e}")
        return False

    if not found:
        logger.warning(f"[FOCUS_R] Không tìm thấy cửa sổ: '{instance_name}'")
        return False

    # Ưu tiên exact match
    hwnd = next(
        (h for h in found if win32gui.GetWindowText(h).strip() == instance_name.strip()),
        found[0]
    )

    for attempt in range(retries):
        try:
            # Restore nếu đang minimize
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.15)

            cur_tid = win32api.GetCurrentThreadId()
            tgt_tid, tgt_pid = win32process.GetWindowThreadProcessId(hwnd)

            # AttachThreadInput: buộc Windows cho phép ta set foreground
            attached = False
            if cur_tid != tgt_tid:
                try:
                    win32process.AttachThreadInput(cur_tid, tgt_tid, True)
                    attached = True
                except Exception:
                    pass

            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    try:
                        win32process.AttachThreadInput(cur_tid, tgt_tid, False)
                    except Exception:
                        pass

            # Verify foreground
            deadline = time.time() + 0.5
            while time.time() < deadline:
                if win32gui.GetForegroundWindow() == hwnd:
                    logger.info(f"[FOCUS_R] Focus thành công '{instance_name}' (lần {attempt + 1})")
                    return True
                time.sleep(0.05)

            # Fallback: AllowSetForegroundWindow
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(tgt_pid)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)
                if win32gui.GetForegroundWindow() == hwnd:
                    logger.info(f"[FOCUS_R] Focus fallback thành công '{instance_name}'")
                    return True
            except Exception:
                pass

            logger.warning(f"[FOCUS_R] Lần {attempt + 1} chưa verify được foreground '{instance_name}'")
            time.sleep(0.3 * (attempt + 1))

        except Exception as e:
            logger.warning(f"[FOCUS_R] Lần {attempt + 1} lỗi: {e}")
            time.sleep(0.3 * (attempt + 1))

    logger.error(f"[FOCUS_R] Không focus được '{instance_name}' sau {retries} lần")
    return False


# ─────────────────────────────────────────────────────────────
# Operation Recorder helpers
# ─────────────────────────────────────────────────────────────

def move_operation_recorder_window() -> bool:
    """Di chuyển Operation Recorder window đến vị trí định sẵn trong config."""
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd == 0:
            logger.warning("[OPR] Không tìm thấy Operation Recorder window")
            return False
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP,
            OPR_WINDOW_X, OPR_WINDOW_Y,
            0, 0,
            win32con.SWP_NOSIZE
        )
        logger.debug(f"[OPR] Di chuyển Recorder đến ({OPR_WINDOW_X}, {OPR_WINDOW_Y})")
        return True
    except Exception as e:
        logger.error(f"[OPR] Lỗi di chuyển: {e}")
        return False


def close_operation_recorder() -> bool:
    """Đóng Operation Recorder."""
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            logger.debug("[OPR] Gửi WM_CLOSE đến Recorder")
            time.sleep(0.2)
            return True
        return False
    except Exception as e:
        logger.error(f"[OPR] Lỗi đóng: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Validate helpers
# ─────────────────────────────────────────────────────────────

def validate_time_input(t_str: str) -> str | None:
    """
    Validate chuỗi thời gian (HH:MM hoặc HHMM).
    Trả về HH:MM:SS nếu hợp lệ, None nếu không.
    """
    t_str = t_str.strip()
    if t_str.isdigit() and len(t_str) == 4:
        t_str = f"{t_str[:2]}:{t_str[2:]}"
    if len(t_str) != 5 or ":" not in t_str:
        logger.warning(f"[VALIDATE] Định dạng thời gian không hợp lệ: '{t_str}'")
        return None
    try:
        datetime.strptime(t_str, "%H:%M")
        return t_str + ":00"
    except ValueError:
        logger.warning(f"[VALIDATE] Giá trị thời gian không hợp lệ: '{t_str}'")
        return None


def validate_key_input(key_str: str) -> bool:
    """Validate chuỗi phím (đơn hoặc tổ hợp dùng +)."""
    if not key_str:
        return False
    keys = key_str.lower().split('+')
    valid = set(pyautogui.KEYBOARD_KEYS)
    is_valid = all(k.strip() in valid for k in keys)
    if not is_valid:
        logger.warning(f"[VALIDATE] Phím không hợp lệ: '{key_str}'")
    return is_valid


# ─────────────────────────────────────────────────────────────
# Nhóm mặc định
# ─────────────────────────────────────────────────────────────

def run_default_group_if_exists(instance_name: str, default_group: str = None) -> bool:
    """Chạy nhóm mặc định trước khi thực hiện job chính (nếu có)."""
    if not default_group:
        logger.debug("[DEFAULT] Không có nhóm mặc định")
        return True

    try:
        from action_groups import ACTION_GROUPS
        from executor import run_group_actions
    except ImportError as e:
        logger.error(f"[DEFAULT] Import lỗi: {e}")
        return False

    group = next((g for g in ACTION_GROUPS if g["name"] == default_group), None)
    if not group:
        logger.warning(f"[DEFAULT] Nhóm mặc định '{default_group}' không tồn tại")
        return True  # Không crash, tiếp tục job chính

    logger.info(f"[DEFAULT] Chạy nhóm mặc định '{default_group}' cho '{instance_name}'")
    try:
        success = run_group_actions(instance_name, group["actions"], group_name=default_group)
        if success:
            logger.info(f"[DEFAULT] Hoàn thành '{default_group}' ✓")
        else:
            logger.warning(f"[DEFAULT] '{default_group}' gặp lỗi nhỏ, vẫn tiếp tục job chính")
        return True
    except Exception as e:
        logger.error(f"[DEFAULT] Lỗi chạy nhóm mặc định '{default_group}': {e}")
        return False
