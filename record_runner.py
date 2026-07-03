"""
record_runner.py
─────────────────
Chạy file .record của LDPlayer trên nhiều giả lập tuần tự:
  1. Copy file → operationRecords/00000.record (ghi đè, luôn ở đầu danh sách)
  2. Ctrl+8 mở Operation Recorder → di chuyển cửa sổ ra góc
  3. Click vào dòng đầu tiên → file tự chạy
  4. Sleep đúng duration_ms (đọc từ nội dung file .record)
  5. Đóng Operation Recorder

Tích hợp vào gui.py:
    from record_runner import open_record_runner_window
    tk.Button(..., command=lambda: open_record_runner_window(root))
"""

import json
import math
import os
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

import pyautogui
import win32api
import win32con
import win32gui
import win32process
import ctypes

# Tái sử dụng load_record() + scan_records_folder() từ tool đo thời gian
from record_duration_tool import load_record, scan_records_folder, ms_to_mmss

# ─────────────────────────────────────────────────────────────
# Đọc / ghi config
# ─────────────────────────────────────────────────────────────

def _load_config() -> dict:
    for p in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        os.path.join(os.getcwd(), "config.json"),
    ]:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    return json.load(f), p
            except Exception:
                pass
    return {}, os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _save_config(cfg: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)


# ─────────────────────────────────────────────────────────────
# Nhóm record (lưu riêng, không đụng config.json)
# ─────────────────────────────────────────────────────────────

_GROUPS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record_groups.json")


def load_groups() -> dict:
    """Trả về {"Tên nhóm": ["file1.record", "file2.record", ...]}"""
    if os.path.isfile(_GROUPS_PATH):
        try:
            with open(_GROUPS_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return data.get("groups", {})
        except Exception:
            pass
    return {}


def save_groups(groups: dict):
    with open(_GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump({"groups": groups}, f, ensure_ascii=False, indent=4)


def display_name(filename: str) -> str:
    """Ẩn đuôi .record để hiển thị cho dễ nhìn."""
    if filename.lower().endswith(".record"):
        return filename[:-len(".record")]
    return filename


# ─────────────────────────────────────────────────────────────
# Helpers LDPlayer window
# ─────────────────────────────────────────────────────────────

def _find_hwnd(instance_name: str) -> int | None:
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if instance_name.lower() in t.lower():
                found.append((hwnd, t))
    win32gui.EnumWindows(_cb, None)
    if not found:
        return None
    for hwnd, t in found:
        if t.strip() == instance_name.strip():
            return hwnd
    return found[0][0]


def _silent_focus(hwnd: int):
    _SFW = ctypes.windll.user32.SetForegroundWindow
    _BTT = ctypes.windll.user32.BringWindowToTop
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.15)
        cur, (tgt, pid) = win32api.GetCurrentThreadId(), win32process.GetWindowThreadProcessId(hwnd)
        attached = False
        if cur != tgt:
            try:
                win32process.AttachThreadInput(cur, tgt, True)
                attached = True
            except Exception:
                pass
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            _BTT(hwnd)
            _SFW(hwnd)
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(cur, tgt, False)
                except Exception:
                    pass
        if win32gui.GetForegroundWindow() != hwnd:
            ctypes.windll.user32.AllowSetForegroundWindow(pid)
            _SFW(hwnd)
    except Exception:
        pass


def _move_opr(opr_x: int, opr_y: int):
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP,
                                  opr_x, opr_y, 0, 0, win32con.SWP_NOSIZE)
    except Exception:
        pass


def _close_opr():
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Core: chạy 1 file record trên 1 instance
# ─────────────────────────────────────────────────────────────

def run_record_file(
    instance_name: str,
    record_path: str,
    records_dir: str,
    opr_x: int,
    opr_y: int,
    play_x: int,
    play_y: int,
    log_fn=None,
):
    """
    Chạy file .record trên instance_name.

    Args:
        instance_name : Tên giả lập (để focus đúng cửa sổ)
        record_path   : Đường dẫn đầy đủ đến file .record cần chạy
        records_dir   : Thư mục operationRecords của LDPlayer
        opr_x/opr_y   : Vị trí đặt cửa sổ Operation Recorder
        play_x/play_y : Tọa độ màn hình để click vào dòng đầu tiên trong OPR
        log_fn        : Hàm(str) để ghi log ra UI
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        # ── 1. Đọc thời gian từ file trước khi copy ──────────
        _, duration_ms = load_record(record_path)
        duration_s = math.ceil(duration_ms / 1000.0)
        log(f"[{instance_name}] File: {os.path.basename(record_path)} | Thời gian: {ms_to_mmss(duration_ms)}")

        # ── 2. Copy → 00000.record ────────────────────────────
        dest = os.path.join(records_dir, "00000.record")
        shutil.copy2(record_path, dest)
        log(f"[{instance_name}] Đã copy → 00000.record")

        # ── 3. Focus LDPlayer ─────────────────────────────────
        hwnd = _find_hwnd(instance_name)
        if not hwnd:
            log(f"[{instance_name}] ⚠ Không tìm thấy cửa sổ '{instance_name}'")
            return False
        _silent_focus(hwnd)
        time.sleep(0.1)

        # ── 4. Ctrl+8 mở OPR ─────────────────────────────────
        pyautogui.hotkey('ctrl', '8')
        time.sleep(1.0)   # Chờ OPR xuất hiện

        # ── 5. Di chuyển cửa sổ OPR ra góc ───────────────────
        _move_opr(opr_x, opr_y)
        time.sleep(0.3)

        # ── 6. Click vào dòng đầu tiên (00000.record) ─────────
        pyautogui.click(play_x, play_y)
        log(f"[{instance_name}] Đã click play tại ({play_x}, {play_y})")

        # ── 7. Chờ đủ thời gian chạy + buffer 1s ─────────────
        #log(f"[{instance_name}] Đang chờ {duration_s}s...")
        #time.sleep(duration_s + 1.0)

        # ── 8. Đóng OPR ───────────────────────────────────────
        _close_opr()
        log(f"[{instance_name}] ✓ Hoàn thành")
        return True

    except Exception as e:
        log(f"[{instance_name}] ✗ Lỗi: {e}")
        return False


class GroupManagerWindow(tk.Toplevel):
    """
    Quản lý nhóm record:
      - Cột trái: danh sách nhóm (thêm / xóa)
      - Cột phải: chọn nhiều file (Ctrl/Shift+click) thuộc nhóm đang chọn, bấm Lưu
    """

    def __init__(self, parent, groups: dict, all_filenames: list, on_change):
        super().__init__(parent)
        self.title("Quản lý nhóm record")
        self.geometry("560x420")
        self.groups = dict(groups)  # copy để sửa, chỉ ghi thật khi bấm Lưu
        self.all_filenames = sorted(all_filenames, key=str.lower)
        self.on_change = on_change

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        # ── Cột trái: danh sách nhóm ──
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 10))
        ttk.Label(left, text="Nhóm").pack(anchor="w")
        self.group_listbox = tk.Listbox(left, width=20, height=16, exportselection=False)
        self.group_listbox.pack(fill="y", expand=True)
        self.group_listbox.bind("<<ListboxSelect>>", lambda e: self._load_group_members())

        new_row = ttk.Frame(left)
        new_row.pack(fill="x", pady=4)
        self.new_group_var = tk.StringVar()
        ttk.Entry(new_row, textvariable=self.new_group_var, width=13).pack(side="left")
        ttk.Button(new_row, text="+", width=2, command=self._add_group).pack(side="left", padx=2)
        ttk.Button(left, text="Xóa nhóm đang chọn", command=self._delete_group).pack(fill="x", pady=(2, 0))

        # ── Cột phải: file thuộc nhóm ──
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Chọn các file thuộc nhóm (giữ Ctrl/Shift để chọn nhiều)").pack(anchor="w")
        self.file_listbox = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.file_listbox.pack(fill="both", expand=True)
        for fname in self.all_filenames:
            self.file_listbox.insert("end", display_name(fname))

        ttk.Button(right, text="Lưu thành viên nhóm này", command=self._save_members).pack(fill="x", pady=(6, 0))

        # nút đóng
        ttk.Button(self, text="Đóng", command=self.destroy).pack(pady=(0, 10))

        self._refresh_group_listbox()

    def _refresh_group_listbox(self, select_name: str = None):
        self.group_listbox.delete(0, "end")
        for name in sorted(self.groups.keys(), key=str.lower):
            self.group_listbox.insert("end", name)
        if select_name and select_name in self.groups:
            idx = sorted(self.groups.keys(), key=str.lower).index(select_name)
            self.group_listbox.selection_set(idx)
            self._load_group_members()

    def _selected_group(self):
        sel = self.group_listbox.curselection()
        if not sel:
            return None
        return self.group_listbox.get(sel[0])

    def _add_group(self):
        name = self.new_group_var.get().strip()
        if not name:
            return
        if name in self.groups:
            messagebox.showwarning("Trùng tên", "Nhóm này đã tồn tại.")
            return
        self.groups[name] = []
        self.new_group_var.set("")
        self._refresh_group_listbox(select_name=name)
        save_groups(self.groups)
        self.on_change(self.groups)

    def _delete_group(self):
        name = self._selected_group()
        if not name:
            messagebox.showwarning("Chưa chọn nhóm", "Chọn 1 nhóm để xóa.")
            return
        if messagebox.askyesno("Xác nhận", f"Xóa nhóm '{name}'?"):
            self.groups.pop(name, None)
            self._refresh_group_listbox()
            self.file_listbox.selection_clear(0, "end")
            save_groups(self.groups)
            self.on_change(self.groups)

    def _load_group_members(self):
        name = self._selected_group()
        self.file_listbox.selection_clear(0, "end")
        if not name:
            return
        members = set(self.groups.get(name, []))
        for i, fname in enumerate(self.all_filenames):
            if fname in members:
                self.file_listbox.selection_set(i)

    def _save_members(self):
        name = self._selected_group()
        if not name:
            messagebox.showwarning("Chưa chọn nhóm", "Chọn 1 nhóm bên trái trước.")
            return
        sel = self.file_listbox.curselection()
        self.groups[name] = [self.all_filenames[i] for i in sel]
        save_groups(self.groups)
        self.on_change(self.groups)
        messagebox.showinfo("Đã lưu", f"Nhóm '{name}': {len(sel)} file.")


# ─────────────────────────────────────────────────────────────
# Calibrate: lấy tọa độ click bằng cách hỏi người dùng click
# ─────────────────────────────────────────────────────────────

class CalibrateWindow(tk.Toplevel):
    """
    Tự động hoá lấy tọa độ:
      1. Tự focus giả lập đã chọn, gửi Ctrl+8 mở Operation Recorder
      2. Tự di chuyển cửa sổ OPR tới vị trí mặc định (opr_x, opr_y)
      3. Đếm ngược 3s để người dùng di chuột tới đúng vị trí cần lấy tọa độ
      4. Ghi lại tọa độ chuột → tự đóng cửa sổ Operation Recorder
    Trả về (x, y) qua callback on_done.
    """

    def __init__(self, parent, title: str, instance_name: str, opr_x: int, opr_y: int, on_done):
        super().__init__(parent)
        self.title(title)
        self.geometry("640x360")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.instance_name = instance_name
        self.opr_x = opr_x
        self.opr_y = opr_y
        self.on_done = on_done
        self._result = None

        tk.Label(self, text=title, font=("", 11, "bold")).pack(pady=(14, 4))
        tk.Label(self,
                 text=f"Giả lập dùng để calibrate: {instance_name}\n"
                      "Đang tự động mở Ctrl+8 và di chuyển cửa sổ Operation Recorder...",
                 justify="left").pack(padx=16)

        self.btn = tk.Button(self, text="Bắt đầu chọn (3s đếm ngược)",
                             command=self._start_countdown, state="disabled")
        self.btn.pack(pady=10)
        self.status = tk.Label(self, text="Đang mở Ctrl+8...", fg="blue")
        self.status.pack()

        threading.Thread(target=self._auto_open, daemon=True).start()

    def _auto_open(self):
        hwnd = _find_hwnd(self.instance_name)
        if not hwnd:
            self.after(0, lambda: self.status.config(
                text=f"⚠ Không tìm thấy cửa sổ '{self.instance_name}'", fg="red"))
            return
        _silent_focus(hwnd)
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', '8')
        time.sleep(1.0)
        _move_opr(self.opr_x, self.opr_y)
        time.sleep(0.3)
        self.after(0, self._ready_for_countdown)

    def _ready_for_countdown(self):
        self.status.config(
            text="Đã mở Operation Recorder. Bấm nút bên dưới rồi di chuột\n"
                 "tới vị trí dòng đầu tiên trong danh sách trong 3s.", fg="blue")
        self.btn.config(state="normal")

    def _start_countdown(self):
        self.btn.config(state="disabled")
        self._countdown(3)

    def _countdown(self, n):
        if n > 0:
            self.status.config(text=f"Di chuột đến vị trí... {n}s")
            self.after(1000, lambda: self._countdown(n - 1))
        else:
            x, y = pyautogui.position()
            self.status.config(text=f"Đã lấy tọa độ: ({x}, {y}) — đang đóng Operation Recorder...")
            self._result = (x, y)
            self.after(300, self._finish)

    def _finish(self):
        _close_opr()
        if self.on_done and self._result:
            self.on_done(*self._result)
        self.destroy()


# ─────────────────────────────────────────────────────────────
# Giao diện chính
# ─────────────────────────────────────────────────────────────

class RecordRunnerWindow(tk.Toplevel):
    def __init__(self, parent, instances: list[str]):
        super().__init__(parent)
        self.title("Chạy file Record")

        # Đọc config
        cfg, self._cfg_path = _load_config()
        self._cfg = cfg
        self._groups = load_groups()

        win_w = cfg.get("RUNNER_WINDOW_WIDTH", 1700)
        win_h = cfg.get("RUNNER_WINDOW_HEIGHT", 1620)
        self.geometry(f"{win_w}x{win_h}")
        self.resizable(True, True)
        self.attributes("-topmost", False)

        self._instances = instances
        self._running   = False
        self._thread    = None

        records_dir_default = cfg.get("RECORDS_FOLDER_PATH", "")
        if not records_dir_default:
            ld = cfg.get("LD_CONSOLE_PATH", "")
            if ld:
                records_dir_default = os.path.join(os.path.dirname(ld), "vms", "operationRecords")

        opr_x = cfg.get("OPR_WINDOW_X", 0)
        opr_y = cfg.get("OPR_WINDOW_Y", 0)
        play_x = cfg.get("RECORD_PLAY_X", opr_x + 100)
        play_y = cfg.get("RECORD_PLAY_Y", opr_y + 80)

        # ── Kích thước cửa sổ ──────────────────────────────────
        frm_size = ttk.LabelFrame(self, text="Kích thước cửa sổ")
        frm_size.pack(fill="x", padx=10, pady=(10, 6))
        self.win_width_var = tk.IntVar(value=win_w)
        self.win_height_var = tk.IntVar(value=win_h)
        size_row = ttk.Frame(frm_size)
        size_row.pack(fill="x", padx=5, pady=4)
        ttk.Label(size_row, text="Rộng:").pack(side="left")
        ttk.Entry(size_row, textvariable=self.win_width_var, width=7).pack(side="left", padx=4)
        ttk.Label(size_row, text="Cao:").pack(side="left")
        ttk.Entry(size_row, textvariable=self.win_height_var, width=7).pack(side="left", padx=4)
        ttk.Button(size_row, text="Áp dụng", command=self._apply_window_size).pack(side="left", padx=8)
        ttk.Button(size_row, text="Lưu làm mặc định", command=self._save_window_size).pack(side="left")

        # ── Thư mục records ───────────────────────────────────
        frm_dir = ttk.LabelFrame(self, text="Thư mục operationRecords")
        frm_dir.pack(fill="x", padx=10, pady=6)
        self.dir_var = tk.StringVar(value=records_dir_default)
        ttk.Entry(frm_dir, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=5, pady=4)
        ttk.Button(frm_dir, text="Chọn...", command=self._browse_dir).pack(side="left", padx=2)
        ttk.Button(frm_dir, text="Lưu", command=self._save_dir).pack(side="left", padx=2)

        # ── Tọa độ play ───────────────────────────────────────
        frm_coord = ttk.LabelFrame(self, text="Tọa độ click dòng đầu trong Operation Recorder")
        frm_coord.pack(fill="x", padx=10, pady=4)
        self.play_x_var = tk.IntVar(value=play_x)
        self.play_y_var = tk.IntVar(value=play_y)
        coord_row = ttk.Frame(frm_coord)
        coord_row.pack(fill="x", padx=5, pady=4)
        ttk.Label(coord_row, text="X:").pack(side="left")
        ttk.Entry(coord_row, textvariable=self.play_x_var, width=7).pack(side="left", padx=4)
        ttk.Label(coord_row, text="Y:").pack(side="left")
        ttk.Entry(coord_row, textvariable=self.play_y_var, width=7).pack(side="left", padx=4)
        ttk.Button(coord_row, text="Calibrate (tự lấy tọa độ)",
                   command=self._calibrate).pack(side="left", padx=8)
        ttk.Button(coord_row, text="Lưu tọa độ", command=self._save_coords).pack(side="left")

        # ── Chọn giả lập ─────────────────────────────────────
        frm_inst = ttk.LabelFrame(self, text="Chọn giả lập")
        frm_inst.pack(fill="x", padx=10, pady=4)
        inst_scroll = ttk.Frame(frm_inst)
        inst_scroll.pack(fill="x", padx=5, pady=4)
        self._inst_vars = {}
        for name in instances:
            v = tk.BooleanVar(value=True)
            self._inst_vars[name] = v
            ttk.Checkbutton(inst_scroll, text=name, variable=v).pack(side="left", padx=6)

        # ── Chọn file record ─────────────────────────────────
        frm_rec = ttk.LabelFrame(self, text="Chọn file record để chạy")
        frm_rec.pack(fill="both", expand=True, padx=10, pady=4)

        filter_row = ttk.Frame(frm_rec)
        filter_row.pack(fill="x", padx=5, pady=(4, 0))
        ttk.Label(filter_row, text="Lọc theo nhóm:").pack(side="left")
        self.group_filter_var = tk.StringVar(value="Tất cả")
        self.group_filter_combo = ttk.Combobox(filter_row, textvariable=self.group_filter_var,
                                               state="readonly", width=22)
        self.group_filter_combo.pack(side="left", padx=5)
        self.group_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_records())
        ttk.Button(filter_row, text="Quản lý nhóm...", command=self._open_group_manager).pack(side="left", padx=10)

        # ── Dòng nút nhóm nhanh (bấm để chuyển sang xem dạng button to) ──
        quick_row = ttk.Frame(frm_rec)
        quick_row.pack(fill="x", padx=5, pady=(4, 0))
        self.group_btns_frame = ttk.Frame(quick_row)
        self.group_btns_frame.pack(side="left", fill="x", expand=True)
        self.back_to_table_btn = ttk.Button(quick_row, text="◀ Xem dạng bảng",
                                            command=self._switch_to_table_view)
        # ẩn sẵn, chỉ hiện khi đang ở chế độ button

        self._view_mode = "table"  # "table" hoặc "buttons"

        self.tree = ttk.Treeview(frm_rec,
                                  columns=("name", "group", "hotkey", "loop", "duration"),
                                  show="headings", selectmode="browse", height=6)
        self.tree.heading("name", text="Tên file")
        self.tree.heading("group", text="Nhóm")
        self.tree.heading("hotkey", text="Phím tắt")
        self.tree.heading("loop", text="Lặp lại")
        self.tree.heading("duration", text="Thời gian")
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("group", width=140, anchor="w")
        self.tree.column("hotkey", width=90, anchor="center")
        self.tree.column("loop", width=80, anchor="center")
        self.tree.column("duration", width=90, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=5, pady=4)

        # Khung chứa button lớn cho từng record (chế độ "buttons"), chưa pack vội
        self.record_btns_canvas = tk.Canvas(frm_rec, highlightthickness=0)
        self.record_btns_scroll = ttk.Scrollbar(frm_rec, orient="vertical",
                                                command=self.record_btns_canvas.yview)
        self.record_btns_frame = ttk.Frame(self.record_btns_canvas)
        self.record_btns_frame.bind(
            "<Configure>",
            lambda e: self.record_btns_canvas.configure(scrollregion=self.record_btns_canvas.bbox("all"))
        )
        self.record_btns_canvas.create_window((0, 0), window=self.record_btns_frame, anchor="nw")
        self.record_btns_canvas.configure(yscrollcommand=self.record_btns_scroll.set)
        # cuộn bằng chuột CHỈ khi con trỏ đang ở trên canvas này (không dùng bind_all
        # để tránh cuộn lan sang cửa sổ/danh sách khác đang mở cùng lúc)
        self.record_btns_canvas.bind(
            "<Enter>",
            lambda e: self.record_btns_canvas.bind_all(
                "<MouseWheel>",
                lambda ev: self.record_btns_canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")
            )
        )
        self.record_btns_canvas.bind("<Leave>", lambda e: self.record_btns_canvas.unbind_all("<MouseWheel>"))

        self._record_data = []      # toàn bộ record quét được (không lọc)
        self._visible_records = []  # record đang hiển thị (đã lọc theo nhóm), cùng thứ tự với các dòng/button


        ttk.Button(frm_rec, text="Tải lại danh sách",
                   command=self._refresh_records).pack(anchor="e", padx=5, pady=(0, 4))

        # ── Nút chạy / log ────────────────────────────────────
        frm_run = ttk.Frame(self)
        frm_run.pack(fill="x", padx=10, pady=6)
        self.run_btn = ttk.Button(frm_run, text="▶ Chạy trên giả lập đã chọn",
                                   command=self._start_run)
        self.run_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        ttk.Button(frm_run, text="✕ Dừng", command=self._stop_run).pack(side="left")

        # Log
        frm_log = ttk.LabelFrame(self, text="Log")
        frm_log.pack(fill="x", padx=10, pady=(0, 8))
        self.log_text = tk.Text(frm_log, height=5, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self._refresh_records()

    # ── Helpers ───────────────────────────────────────────────

    def _log(self, msg: str):
        def _do():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _do)

    def _apply_window_size(self):
        w = max(400, self.win_width_var.get())
        h = max(300, self.win_height_var.get())
        self.geometry(f"{w}x{h}")

    def _save_window_size(self):
        w = max(400, self.win_width_var.get())
        h = max(300, self.win_height_var.get())
        cfg, path = _load_config()
        cfg["RUNNER_WINDOW_WIDTH"] = w
        cfg["RUNNER_WINDOW_HEIGHT"] = h
        _save_config(cfg, path)
        self._log(f"Đã lưu kích thước cửa sổ mặc định: {w}x{h}")

    def _browse_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục operationRecords",
                                    initialdir=self.dir_var.get() or os.getcwd())
        if d:
            self.dir_var.set(d)
            self._refresh_records()

    def _save_dir(self):
        d = self.dir_var.get().strip()
        if not d:
            messagebox.showwarning("Lỗi", "Chưa chọn thư mục")
            return
        cfg, path = _load_config()
        cfg["RECORDS_FOLDER_PATH"] = d
        _save_config(cfg, path)
        self._log(f"Đã lưu RECORDS_FOLDER_PATH = {d}")

    def _save_coords(self):
        cfg, path = _load_config()
        cfg["RECORD_PLAY_X"] = self.play_x_var.get()
        cfg["RECORD_PLAY_Y"] = self.play_y_var.get()
        _save_config(cfg, path)
        self._log(f"Đã lưu tọa độ play ({self.play_x_var.get()}, {self.play_y_var.get()})")

    def _calibrate(self):
        instances = self._get_selected_instances()
        if not instances:
            messagebox.showwarning("Chưa chọn giả lập",
                                   "Vui lòng chọn ít nhất 1 giả lập (dùng để tự mở Ctrl+8 khi calibrate).")
            return
        instance_name = instances[0]
        opr_x = self._cfg.get("OPR_WINDOW_X", 0)
        opr_y = self._cfg.get("OPR_WINDOW_Y", 0)

        def on_done(x, y):
            self.play_x_var.set(x)
            self.play_y_var.set(y)
            self._log(f"Calibrate: tọa độ ({x}, {y}) — nhớ bấm 'Lưu tọa độ'")

        CalibrateWindow(self, "Lấy tọa độ dòng đầu tiên trong OPR",
                        instance_name, opr_x, opr_y, on_done)

    def _refresh_records(self):
        folder = self.dir_var.get().strip()
        self.tree.delete(*self.tree.get_children())
        self._record_data = []
        self._visible_records = []
        if not folder or not os.path.isdir(folder):
            self._build_group_quick_buttons()
            self._build_record_buttons()
            return
        records = scan_records_folder(folder)
        self._record_data = records

        # cập nhật danh sách nhóm trong combobox lọc (giữ lựa chọn hiện tại nếu còn hợp lệ)
        group_names = sorted(self._groups.keys(), key=str.lower)
        current_filter = self.group_filter_var.get()
        self.group_filter_combo["values"] = ["Tất cả"] + group_names
        if current_filter not in (["Tất cả"] + group_names):
            self.group_filter_var.set("Tất cả")
            current_filter = "Tất cả"

        def groups_of(fname):
            return [g for g, files in self._groups.items() if fname in files]

        self.tree.tag_configure("error", foreground="red")
        for r in records:
            file_groups = groups_of(r["name"])
            if current_filter != "Tất cả" and current_filter not in file_groups:
                continue
            group_str = ", ".join(file_groups)
            self._visible_records.append(r)
            if r["error"]:
                self.tree.insert("", "end", values=(display_name(r["name"]), group_str, "LỖI", "-", "-"),
                                 tags=("error",))
            else:
                self.tree.insert("", "end",
                                  values=(display_name(r["name"]), group_str, r["hotkey"],
                                          r["loop_text"], r["duration_sec_text"]))
        if self._visible_records:
            self.tree.selection_set(self.tree.get_children()[0])

        self._build_group_quick_buttons()
        self._build_record_buttons()

    # ── Dòng nút nhóm nhanh + chế độ xem record dạng button to ──

    def _build_group_quick_buttons(self):
        for w in self.group_btns_frame.winfo_children():
            w.destroy()
        names = ["Tất cả"] + sorted(self._groups.keys(), key=str.lower)
        current = self.group_filter_var.get()
        for name in names:
            is_selected = (name == current)
            b = tk.Button(
                self.group_btns_frame, text=name,
                relief="sunken" if is_selected else "raised",
                bg="#cfe8ff" if is_selected else None,
                command=lambda n=name: self._select_group_quick(n)
            )
            b.pack(side="left", padx=3, pady=2)

    def _select_group_quick(self, name):
        self.group_filter_var.set(name)
        self._view_mode = "buttons"
        self._refresh_records()
        self._apply_view_mode()

    def _switch_to_table_view(self):
        self._view_mode = "table"
        self._apply_view_mode()

    def _apply_view_mode(self):
        if self._view_mode == "buttons":
            self.tree.pack_forget()
            self.record_btns_canvas.pack(fill="both", expand=True, padx=5, pady=4, side="left")
            self.record_btns_scroll.pack(fill="y", pady=4, side="left")
            self.back_to_table_btn.pack(side="right", padx=5)
        else:
            self.record_btns_canvas.pack_forget()
            self.record_btns_scroll.pack_forget()
            self.back_to_table_btn.pack_forget()
            self.tree.pack(fill="both", expand=True, padx=5, pady=4)

    def _build_record_buttons(self):
        for w in self.record_btns_frame.winfo_children():
            w.destroy()
        cols = 4
        for i, r in enumerate(self._visible_records):
            text = display_name(r["name"])
            is_error = bool(r["error"])
            btn = tk.Button(
                self.record_btns_frame,
                text=("⚠ " + text) if is_error else text,
                width=22, height=2, wraplength=170, justify="center",
                fg="red" if is_error else "black",
                command=lambda rec=r: self._select_record_button(rec)
            )
            btn.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nsew")

    def _select_record_button(self, rec):
        # Tìm dòng tương ứng trong tree (nguồn dữ liệu chọn dùng chung cho lúc Chạy)
        try:
            idx = self._visible_records.index(rec)
        except ValueError:
            return
        children = self.tree.get_children()
        if idx >= len(children):
            return
        iid = children[idx]
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self._log(f"Đã chọn: {display_name(rec['name'])}")

    def _open_group_manager(self):
        all_filenames = [r["name"] for r in self._record_data]

        def on_change(new_groups):
            self._groups = new_groups
            self._refresh_records()

        GroupManagerWindow(self, self._groups, all_filenames, on_change)

    def _get_selected_record(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn 1 file record trong danh sách.")
            return None
        idx = self.tree.index(sel[0])
        r = self._visible_records[idx]
        if r["error"]:
            messagebox.showerror("File lỗi", f"File này không đọc được:\n{r['error']}")
            return None
        return r

    def _get_selected_instances(self):
        return [n for n, v in self._inst_vars.items() if v.get()]

    # ── Run ───────────────────────────────────────────────────

    def _start_run(self):
        if self._running:
            messagebox.showinfo("Đang chạy", "Đang có tiến trình chạy, vui lòng đợi.")
            return
        r = self._get_selected_record()
        if not r:
            return
        instances = self._get_selected_instances()
        if not instances:
            messagebox.showwarning("Chưa chọn giả lập", "Vui lòng chọn ít nhất 1 giả lập.")
            return
        folder = self.dir_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Lỗi", "Thư mục operationRecords không hợp lệ.")
            return

        opr_x = self._cfg.get("OPR_WINDOW_X", 0)
        opr_y = self._cfg.get("OPR_WINDOW_Y", 0)
        play_x = self.play_x_var.get()
        play_y = self.play_y_var.get()

        self._running = True
        self.run_btn.config(state="disabled")
        self._log(f"─── Bắt đầu: {display_name(r['name'])} trên {instances} ───")

        def worker():
            for inst in instances:
                if not self._running:
                    self._log("⛔ Đã dừng")
                    break
                run_record_file(
                    instance_name=inst,
                    record_path=r["path"],
                    records_dir=folder,
                    opr_x=opr_x, opr_y=opr_y,
                    play_x=play_x, play_y=play_y,
                    log_fn=self._log,
                )
            self._running = False
            self.after(0, lambda: self.run_btn.config(state="normal"))
            self._log("─── Xong ───")

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def _stop_run(self):
        self._running = False
        self._log("⛔ Yêu cầu dừng...")


# ─────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────

def open_record_runner_window(parent, instances: list[str]):
    """
    Gọi từ gui.py:
        from record_runner import open_record_runner_window
        tk.Button(..., command=lambda: open_record_runner_window(root, list(var_dict.keys())))
    """
    win = RecordRunnerWindow(parent, instances)
    win.grab_set()
    return win


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    win = RecordRunnerWindow(root, ["LDPlayer-0", "LDPlayer-1"])
    root.mainloop()
