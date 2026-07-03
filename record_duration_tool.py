"""
Record Duration Tool
---------------------
Quét 1 thư mục chứa nhiều file .record của LDPlayer, hiển thị bảng:
    Tên file | Phím tắt | Lặp lại | Thời gian (mm:ss)

Cách chạy:
    python record_duration_tool.py

Không cần cài thêm thư viện gì (chỉ dùng tkinter có sẵn trong Python).
"""

import json
import math
import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# Các nơi có thể tìm thấy config.json (ưu tiên từ trên xuống)
_CONFIG_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
    os.path.join(os.getcwd(), "config.json"),
]

CONFIG_KEY_RECORDS_DIR = "RECORDS_FOLDER_PATH"


# ──────────────────────────────────────────────────────────────────
# Đọc / ghi config.json
# ──────────────────────────────────────────────────────────────────

def _find_config_path() -> str:
    """Trả về đường dẫn config.json thực sự đang dùng (để lưu ghi đè đúng chỗ)."""
    for cfg_path in _CONFIG_CANDIDATES:
        if os.path.isfile(cfg_path):
            return cfg_path
    # Nếu chưa có file nào, mặc định lưu cạnh script này
    return _CONFIG_CANDIDATES[0]


def _load_config() -> dict:
    cfg_path = _find_config_path()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_default_records_dir() -> str:
    """
    Ưu tiên 1: đọc key RECORDS_FOLDER_PATH đã lưu (do người dùng tự chọn qua nút
               "Chọn thư mục" + "Lưu làm mặc định") -> đáng tin cậy nhất vì
               vms/operationRecords của LDPlayer có thể bị người dùng dời sang
               ổ đĩa khác, không nhất thiết nằm cạnh ldconsole.exe.
    Ưu tiên 2 (dự phòng, có thể sai): suy ra từ LD_CONSOLE_PATH -> <thư mục đó>/vms/operationRecords.
    """
    cfg = _load_config()

    explicit = cfg.get(CONFIG_KEY_RECORDS_DIR, "")
    if explicit:
        return os.path.normpath(explicit)

    ld_console_path = cfg.get("LD_CONSOLE_PATH", "")
    if ld_console_path:
        ld_dir = os.path.dirname(ld_console_path)
        return os.path.normpath(os.path.join(ld_dir, "vms", "operationRecords"))

    return ""


def save_default_records_dir(path: str):
    """Lưu RECORDS_FOLDER_PATH vào config.json, giữ nguyên các key khác (giống cách gui.py lưu LD_CONSOLE_PATH)."""
    cfg_path = _find_config_path()
    cfg = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    cfg[CONFIG_KEY_RECORDS_DIR] = path
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    return cfg_path


# ──────────────────────────────────────────────────────────────────
# Giải mã phím tắt (shortkey + modifyKey)
# ──────────────────────────────────────────────────────────────────

# Bitmask chuẩn kiểu Win32 RegisterHotKey: MOD_ALT=1, MOD_CONTROL=2, MOD_SHIFT=4, MOD_WIN=8
# LƯU Ý: đây là suy đoán dựa theo quy ước phổ biến nhất + khớp với ví dụ modifyKey=1 -> Alt.
# Nếu thực tế LDPlayer dùng bảng mã khác, chỉnh lại dict/hàm bên dưới cho đúng.
_MODIFIER_BITS = [
    (2, "Ctrl"),
    (1, "Alt"),
    (4, "Shift"),
    (8, "Win"),
]

# Vài phím đặc biệt hay dùng làm hotkey, ngoài chữ cái A-Z và số 0-9
_VK_MAP = {
    112: "F1", 113: "F2", 114: "F3", 115: "F4", 116: "F5", 117: "F6",
    118: "F7", 119: "F8", 120: "F9", 121: "F10", 122: "F11", 123: "F12",
    37: "Left", 38: "Up", 39: "Right", 40: "Down",
    9: "Tab", 13: "Enter", 27: "Esc", 32: "Space",
}


def _modify_key_to_str(modify_key: int) -> str:
    parts = [name for bit, name in _MODIFIER_BITS if modify_key & bit]
    return "+".join(parts)


def _shortkey_to_str(shortkey: int) -> str:
    if not shortkey:
        return ""
    if 48 <= shortkey <= 57 or 65 <= shortkey <= 90:
        return chr(shortkey)
    return _VK_MAP.get(shortkey, f"Key({shortkey})")


def format_hotkey(shortkey, modify_key) -> str:
    shortkey = shortkey or 0
    modify_key = modify_key or 0
    key = _shortkey_to_str(shortkey)
    if not key:
        return "(không có)"
    mod = _modify_key_to_str(modify_key)
    return f"{mod}+{key}" if mod else key


# ──────────────────────────────────────────────────────────────────
# Đọc nội dung file .record
# ──────────────────────────────────────────────────────────────────

def ms_to_mmss(ms: float) -> str:
    """
    Làm tròn LÊN tới giây gần nhất (ceiling), rồi định dạng:
    - Dưới 1 phút: "Ss"      (VD: 29.1s -> "30s")
    - Từ 1 phút trở lên: "M:SS"  (VD: 91.3s -> "1:32")
    (Giữ lại hàm này để tương thích ngược, bảng hiện dùng 2 cột riêng bên dưới.)
    """
    total_seconds_rounded = math.ceil(ms / 1000.0)
    m, s = divmod(total_seconds_rounded, 60)
    if m == 0:
        return f"{s}s"
    return f"{m}:{s:02d}"


def ms_to_seconds_str(ms: float) -> str:
    """VD: 90000ms -> '90s'"""
    total_seconds_rounded = math.ceil(ms / 1000.0)
    return f"{total_seconds_rounded}s"


def ms_to_minutes_str(ms: float) -> str:
    """VD: 90000ms -> '1p30' (1 phút 30 giây)"""
    total_seconds_rounded = math.ceil(ms / 1000.0)
    m, s = divmod(total_seconds_rounded, 60)
    return f"{m}p{s:02d}"


def load_record(path: str):
    """
    Đọc 1 file .record, trả về:
        outer_info: dict recordInfo ở cấp ngoài cùng (chứa shortkey, modifyKey, loopTimes...)
        total_duration_ms: tổng thời gian chạy 1 lần (cộng hết các đoạn nếu là file gộp)
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    outer_info = data.get("recordInfo", {})
    total_ms = 0.0

    if "mergedRecords" in data and isinstance(data["mergedRecords"], list):
        for rec in data["mergedRecords"]:
            ri = rec.get("recordInfo", {})
            circle = ri.get("circleDuration", 0) or 0
            loop_times = ri.get("loopTimes", 1) or 1
            loop_interval = ri.get("loopInterval", 0) or 0
            total_ms += circle * loop_times + loop_interval * max(loop_times - 1, 0)
    else:
        circle = outer_info.get("circleDuration", 0) or 0
        loop_times = outer_info.get("loopTimes", 1) or 1
        loop_interval = outer_info.get("loopInterval", 0) or 0
        total_ms = circle * loop_times + loop_interval * max(loop_times - 1, 0)

    return outer_info, total_ms


def scan_records_folder(folder: str):
    """
    Quét các file .record nằm trực tiếp trong `folder` (KHÔNG quét thư mục con).
    Trả về list[dict]: name, hotkey, loop_text, duration_text, path, error (nếu có).
    """
    results = []
    if not folder or not os.path.isdir(folder):
        return results

    for fname in os.listdir(folder):
        if not fname.lower().endswith(".record"):
            continue
        full_path = os.path.join(folder, fname)
        if not os.path.isfile(full_path):
            continue
        try:
            outer_info, total_ms = load_record(full_path)
            shortkey = outer_info.get("shortkey", 0)
            modify_key = outer_info.get("modifyKey", 0)
            loop_times = outer_info.get("loopTimes", 1) or 1

            results.append({
                "name": fname,
                "hotkey": format_hotkey(shortkey, modify_key),
                "loop_text": "Không lặp" if loop_times <= 1 else f"{loop_times} lần",
                "duration_sec_text": ms_to_seconds_str(total_ms),
                "duration_min_text": ms_to_minutes_str(total_ms),
                "duration_ms": total_ms,
                "path": full_path,
                "error": None,
            })
        except Exception as e:
            results.append({
                "name": fname, "hotkey": "-", "loop_text": "-",
                "duration_sec_text": "-", "duration_min_text": "-", "duration_ms": 0,
                "path": full_path, "error": str(e),
            })

    results.sort(key=lambda r: r["name"].lower())
    return results


# ──────────────────────────────────────────────────────────────────
# Giao diện
# ──────────────────────────────────────────────────────────────────

class RecordDurationApp(tk.Toplevel):
    """
    Cửa sổ quét thư mục record. Có thể mở như cửa sổ con (truyền parent = cửa sổ
    Tk chính đang chạy) hoặc chạy độc lập (parent=None, tool tự tạo root ẩn).
    """

    def __init__(self, parent=None):
        self._owns_root = parent is None
        if parent is None:
            parent = tk.Tk()
            parent.withdraw()
        super().__init__(parent)
        self._parent_root = parent
        self.title("Danh sách file record - phím tắt - lặp lại - thời gian")
        self.geometry("820x520")
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.folder_var = tk.StringVar(value=get_default_records_dir())

        # ── Thanh chọn thư mục ──
        top = tk.Frame(self, padx=10, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="Thư mục record:").pack(side="left")
        tk.Entry(top, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(top, text="Chọn thư mục...", command=self.choose_folder).pack(side="left", padx=2)
        tk.Button(top, text="Lưu làm mặc định", command=self.save_default).pack(side="left", padx=2)
        tk.Button(top, text="Tải lại", command=self.refresh).pack(side="left", padx=2)

        # ── Bảng kết quả ──
        columns = ("name", "hotkey", "loop", "duration_sec", "duration_min")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("name", text="Tên file")
        self.tree.heading("hotkey", text="Phím tắt")
        self.tree.heading("loop", text="Lặp lại")
        self.tree.heading("duration_sec", text="Thời gian (giây)")
        self.tree.heading("duration_min", text="Thời gian (phút)")
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("hotkey", width=120, anchor="center")
        self.tree.column("loop", width=100, anchor="center")
        self.tree.column("duration_sec", width=130, anchor="e")
        self.tree.column("duration_min", width=130, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        # ── Thanh trạng thái ──
        self.status_label = tk.Label(self, text="", anchor="w", fg="#555555")
        self.status_label.pack(fill="x", padx=10, pady=(0, 10))

        self.after(50, self.refresh)

    def _on_close(self):
        self.destroy()
        if self._owns_root:
            self._parent_root.destroy()

    def choose_folder(self):
        initial = self.folder_var.get() or os.getcwd()
        folder = filedialog.askdirectory(title="Chọn thư mục chứa file .record", initialdir=initial)
        if folder:
            self.folder_var.set(folder)
            self.refresh()

    def save_default(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Lỗi", "Chưa chọn thư mục nào để lưu.")
            return
        try:
            cfg_path = save_default_records_dir(folder)
            messagebox.showinfo(
                "Đã lưu",
                f"Đã lưu thư mục mặc định vào:\n{cfg_path}\n\n{folder}"
            )
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không lưu được config.json:\n{e}")

    def refresh(self):
        folder = self.folder_var.get().strip()
        for row in self.tree.get_children():
            self.tree.delete(row)

        if not folder:
            self.status_label.config(text="Chưa có thư mục nào (chọn thư mục hoặc lưu mặc định).")
            return
        if not os.path.isdir(folder):
            self.status_label.config(text=f"Không tìm thấy thư mục: {folder}")
            return

        records = scan_records_folder(folder)
        error_count = 0
        for r in records:
            if r["error"]:
                error_count += 1
                self.tree.insert("", "end", values=(r["name"], "LỖI ĐỌC FILE", "-", "-", "-"))
            else:
                self.tree.insert("", "end", values=(
                    r["name"], r["hotkey"], r["loop_text"],
                    r["duration_sec_text"], r["duration_min_text"]
                ))

        total = len(records)
        msg = f"Tìm thấy {total} file .record trong: {folder}"
        if error_count:
            msg += f"  (⚠ {error_count} file đọc lỗi)"
        self.status_label.config(text=msg)


def open_record_duration_window(parent=None):
    """
    Gọi từ chương trình chính (gui.py):
        from record_duration_tool import open_record_duration_window
        tk.Button(path_frame, text="Tính h recoder",
                  command=lambda: open_record_duration_window(root)).pack(...)
    """
    win = RecordDurationApp(parent)
    return win


if __name__ == "__main__":
    app = RecordDurationApp(parent=None)
    app.mainloop()
