import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog  # THÊM filedialog
import threading
import time
import pyautogui
import win32gui
import win32con
import sys
from datetime import datetime, timedelta
from config import *
from utils import auto_close_messagebox, focus_emulator, validate_time_input, validate_key_input
from ldconsole import get_instances, launch_instance, quit_instance
from recorder import run_record_line
from executor import run_key_press, execute_single_job, run_group_actions
from scheduler import register_job, unregister_job, pause_scheduler, resume_scheduler, shutdown_scheduler, get_queue_status
import key_sender
from job import Job, jobs, load_jobs, save_jobs
from action_groups import ACTION_GROUPS, load_action_groups, save_action_groups
from record_duration_tool import open_record_duration_window
from record_runner import open_record_runner_window
from logger import get_logger
from ui_theme import apply_theme, FONT_HEADER, FONT_SMALL
logger = get_logger()

# Biến toàn cục
var_dict = {}
record_line_var = None
schedule_time_var = None
key_input_var = None
group_var = None
group_combo = None
delay_time_var = None
subtract_time_var = None
repeat_interval_var = None  # Mới: khoảng lặp lại
schedule_list_frame = None
root = None
groups_listbox = None

# Chế độ hiển thị danh sách
display_mode_var = None

# Tính năng hành động mặc định
default_group_name = None
default_status_label = None

def set_default_group():
    global default_group_name
    group_name = group_var.get()
    if not group_name:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn một nhóm trước!")
        return
    default_group_name = group_name
    if default_status_label:
        default_status_label.config(text=f"Mặc định hiện tại: {group_name}")
    auto_close_messagebox("info", "Thành công", f"Đã đặt nhóm '{group_name}' làm hành động mặc định.\nMọi lịch trình sẽ chạy nhóm này trước.")
    print(f"[DEFAULT] Đặt nhóm mặc định: {default_group_name}")

def clear_default_group():
    global default_group_name
    default_group_name = None
    if default_status_label:
        default_status_label.config(text="Chưa có nhóm mặc định")
    auto_close_messagebox("info", "Thành công", "Đã xóa nhóm mặc định.")
    print("[DEFAULT] Đã xóa nhóm mặc định")

def update_default_label():
    if default_status_label:
        text = f"Mặc định hiện tại: {default_group_name}" if default_group_name else "Chưa có nhóm mặc định"
        default_status_label.config(text=text)

# Chế độ hiển thị: "new" = gộp theo nhóm (mặc định), "old" = từng dòng như cũ
display_mode_var = None  # tk.StringVar, được tạo trong hàm tạo UI khu vực danh sách


def toggle_display_mode():
    """Đổi chế độ hiển thị cũ/mới, rồi vẽ lại danh sách ngay."""
    global display_mode_var
    if display_mode_var is None:
        display_mode_var = tk.StringVar(value="new")
    current = display_mode_var.get()
    display_mode_var.set("old" if current == "new" else "new")
    update_jobs_list()


def update_jobs_list():
    if not schedule_list_frame or not root or not root.winfo_exists():
        return

    def safe_update():
        if not schedule_list_frame or not root.winfo_exists():
            return
        try:
            for widget in list(schedule_list_frame.winfo_children()):
                widget.destroy()

            pending_jobs = [j for j in jobs if (not j.group_name or j.is_group) and j.status == "Đã hẹn"]
            completed_jobs = [j for j in jobs if (not j.group_name or j.is_group) and j.status != "Đã hẹn"]

            global display_mode_var
            if display_mode_var is None:
                display_mode_var = tk.StringVar(value="new")

            use_new_mode = display_mode_var.get() == "new"

            mode_bar = ttk.Frame(schedule_list_frame)
            mode_bar.pack(fill="x", anchor="e", pady=(0, 4))
            mode_label = "Hiển thị: Gộp theo nhóm" if use_new_mode else "Hiển thị: Từng dòng (cũ)"
            ttk.Button(mode_bar, text=f"{mode_label}  (đổi)", width=26,
                       command=toggle_display_mode).pack(side="right")

            # ── Trạng thái hàng đợi: job nào đang chạy + còn bao nhiêu job chờ ──
            current_job, waiting_count = get_queue_status()
            if current_job is not None:
                who = current_job.group_name if (current_job.is_group and current_job.group_name) else (current_job.job_type or current_job.instance)
                status_text = f"⚡ Đang chạy: {who} - {current_job.instance}"
                if waiting_count > 0:
                    status_text += f"  (còn {waiting_count} job chờ)"
            elif waiting_count > 0:
                status_text = f"⏳ Đang xếp hàng chờ chạy... (còn {waiting_count} job chờ)"
            else:
                status_text = ""

            pending_title = "Công việc đang chờ"
            if status_text:
                pending_title += f"   —   {status_text}"

            pending_frame = ttk.LabelFrame(schedule_list_frame, text=pending_title)
            pending_frame.pack(fill="both", expand=True, pady=(0, 5))
            sorted_pending = sorted(pending_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)

            completed_frame = ttk.LabelFrame(schedule_list_frame, text="Công việc đã hoàn thành")
            completed_frame.pack(fill="both", expand=True, pady=5)
            sorted_completed = sorted(completed_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)

            if use_new_mode:
                _render_job_section_grouped(pending_frame, sorted_pending, is_pending=True)
                _render_job_section_grouped(completed_frame, sorted_completed, is_pending=False)
            else:
                _render_job_section_flat(pending_frame, sorted_pending, is_pending=True)
                _render_job_section_flat(completed_frame, sorted_completed, is_pending=False)

            global pause_button
            if pause_button and pause_button.winfo_exists():
                pause_button.config(text="Tiếp tục" if is_paused else "Tạm dừng")

        except Exception as e:
            logger.error(f"Lỗi khi update_jobs_list (safe_update): {e}")

    if root and root.winfo_exists():
        root.after(0, safe_update)


LABEL_WRAP = 480  # độ rộng (px) trước khi chữ tự xuống dòng thay vì kéo giãn hàng


def _job_icon(job):
    return ("📋" if job.is_group
            else "🎬" if job.job_type == "record"
            else "⌨️" if job.job_type == "key"
            else "🚀" if job.job_type == "launch"
            else "🛑" if job.job_type == "quit"
            else "🔔")


def _make_job_buttons(btn_frame, idx, job, is_pending):
    """Tạo bộ nút Chạy/Sửa/Xóa/Dừng... cho 1 job — dùng chung cho cả 2 chế độ hiển thị."""
    if is_pending:
        if hasattr(job, 'is_repeating') and job.is_repeating:
            ttk.Button(btn_frame, text="Dừng lặp", width=8, style="Danger.TButton",
                       command=lambda j=job: stop_repeating(j)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Chạy", width=5, style="Success.TButton",
                   command=lambda i=idx: run_job_now(i)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Sửa", width=5, style="Warning.TButton",
                   command=lambda i=idx: edit_job(i, True)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Xóa", width=5, style="Danger.TButton",
                   command=lambda i=idx: remove_job(i, True)).pack(side="left", padx=(0, 2))
    else:
        if job.is_group and job.status == "Đang chạy":
            ttk.Button(btn_frame, text="Dừng", width=5, style="Danger.TButton",
                       command=lambda j=job: stop_job(j)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Sửa", width=5, style="Warning.TButton",
                   command=lambda i=idx: edit_job(i, False)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Hẹn lại", width=6, style="Ghost.TButton",
                   command=lambda i=idx: reschedule_job(i, False)).pack(side="left", padx=(0, 2))
        ttk.Button(btn_frame, text="Xóa", width=5, style="Danger.TButton",
                   command=lambda i=idx: remove_job(i, False)).pack(side="left")


# ─────────────────────────────────────────────────────────────────────────
# CHẾ ĐỘ CŨ: từng dòng rời rạc, y nguyên hành vi gốc
# ─────────────────────────────────────────────────────────────────────────
def _render_job_section_flat(parent_frame, sorted_jobs, is_pending):
    for idx, job in enumerate(sorted_jobs):
        frame = ttk.Frame(parent_frame)
        frame.pack(fill="x", anchor="w", pady=1)
        frame.columnconfigure(0, weight=1)

        icon = _job_icon(job)
        label = ttk.Label(frame, text=f"{icon} {str(job)}", wraplength=LABEL_WRAP, justify="left")
        label.grid(row=0, column=0, sticky="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=1, sticky="e", padx=(8, 0))
        _make_job_buttons(btn_frame, idx, job, is_pending)


# ─────────────────────────────────────────────────────────────────────────
# CHẾ ĐỘ MỚI: gộp theo group_name, có thể thu gọn/mở rộng từng nhóm
# ─────────────────────────────────────────────────────────────────────────
def _render_job_section_grouped(parent_frame, sorted_jobs, is_pending):
    """
    idx truyền vào các nút (Chạy/Sửa/Xóa...) LUÔN là vị trí của job trong
    sorted_jobs gốc — giống 100% cách cũ — để remove_job/edit_job/
    run_job_now/reschedule_job (không bị đổi) hoạt động đúng.
    """
    groups_order = []
    groups_map = {}
    standalone = []

    for idx, job in enumerate(sorted_jobs):
        if job.group_name:
            if job.group_name not in groups_map:
                groups_map[job.group_name] = []
                groups_order.append(job.group_name)
            groups_map[job.group_name].append((idx, job))
        else:
            standalone.append((idx, job))

    for group_name in groups_order:
        entries = groups_map[group_name]

        # Mỗi nhóm có 1 container RIÊNG, cố định vị trí trong parent_frame.
        # Toggle thu gọn/mở rộng chỉ pack/unpack BÊN TRONG container này,
        # nên không bao giờ làm xáo trộn thứ tự các nhóm khác.
        group_container = ttk.Frame(parent_frame)
        group_container.pack(fill="x", anchor="w", pady=(6, 2))

        header = ttk.Frame(group_container)
        header.pack(fill="x", anchor="w")
        header.columnconfigure(0, weight=1)

        machines = sorted(set(j.instance for _, j in entries))
        times = sorted(set(
            j.scheduled_time.strftime("%H:%M") if j.scheduled_time else (j.time_str[:-3] if j.time_str else "?")
            for _, j in entries
        ))
        repeat_tags = sorted(set(
            f"{j.repeat_interval // 3600}h{(j.repeat_interval % 3600) // 60}m"
            for _, j in entries if getattr(j, 'is_repeating', False) and getattr(j, 'repeat_interval', 0) > 0
        ))
        repeat_suffix = f" (lặp: {', '.join(repeat_tags)})" if repeat_tags else ""

        summary = (f"📋 {group_name} — {len(entries)} lượt — "
                   f"Máy: {', '.join(machines)} — Giờ: {', '.join(times)}{repeat_suffix}")
        ttk.Label(header, text=summary, font=("", 9, "bold"),
                  wraplength=LABEL_WRAP, justify="left").grid(row=0, column=0, sticky="w")

        # Khung nút bên phải header — luôn sát ngay bên phải dòng tóm tắt
        header_btns = ttk.Frame(header)
        header_btns.grid(row=0, column=1, sticky="e", padx=(8, 0))

        detail_frame = ttk.Frame(group_container)
        detail_frame.pack(fill="x", anchor="w", padx=(18, 0))
        visible = {"on": True}  # dict để mutate được trong closure không cần nonlocal

        def toggle(df=detail_frame, state=visible, btn_ref=[None]):
            if state["on"]:
                df.pack_forget()
                state["on"] = False
            else:
                # pack lại NGAY SAU header, bên trong group_container của
                # chính nó — không ảnh hưởng đến các group_container khác.
                df.pack(fill="x", anchor="w", padx=(18, 0))
                state["on"] = True

        ttk.Button(header_btns, text="Thu gọn/Mở", width=11, style="Ghost.TButton",
                   command=toggle).pack(side="right", padx=(2, 0))

        if is_pending:
            ttk.Button(header_btns, text="Sửa cả nhóm", width=11, style="Warning.TButton",
                       command=lambda g=group_name: edit_group_schedule(g)).pack(side="right", padx=(2, 0))

        for idx, job in entries:
            row = ttk.Frame(detail_frame)
            row.pack(fill="x", anchor="w", pady=1)
            row.columnconfigure(0, weight=1)

            time_disp = job.scheduled_time.strftime('%d/%m %H:%M:%S') if job.scheduled_time else job.time_str
            row_text = f"   • {job.instance}  —  {time_disp}  [{job.status}]"
            ttk.Label(row, text=row_text, wraplength=LABEL_WRAP - 18,
                      justify="left").grid(row=0, column=0, sticky="w")

            btn_frame = ttk.Frame(row)
            btn_frame.grid(row=0, column=1, sticky="e", padx=(8, 0))
            _make_job_buttons(btn_frame, idx, job, is_pending)

    for idx, job in standalone:
        frame = ttk.Frame(parent_frame)
        frame.pack(fill="x", anchor="w", pady=1)
        frame.columnconfigure(0, weight=1)

        icon = _job_icon(job)
        ttk.Label(frame, text=f"{icon} {str(job)}", wraplength=LABEL_WRAP,
                  justify="left").grid(row=0, column=0, sticky="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=1, sticky="e", padx=(8, 0))
        _make_job_buttons(btn_frame, idx, job, is_pending)


# ─────────────────────────────────────────────────────────────────────────
# SỬA CẢ NHÓM: đổi giờ cho mọi job (mọi máy) thuộc 1 group_name cùng lúc
# ─────────────────────────────────────────────────────────────────────────
def edit_group_schedule(group_name):
    """
    Mở cửa sổ cho phép:
      (a) Sửa/xóa từng GIỜ hiện có của nhóm (áp dụng cho mọi máy ở giờ đó)
      (b) Nhập 1 danh sách giờ mới để THAY THẾ toàn bộ giờ hiện có của nhóm,
          áp dụng đồng loạt cho mọi máy đang có trong nhóm.
    Chỉ tác động đến các job ĐANG CHỜ (status == "Đã hẹn") của group_name này.
    """
    group_parent_jobs = [j for j in jobs if j.is_group and j.group_name == group_name and j.status == "Đã hẹn"]
    if not group_parent_jobs:
        auto_close_messagebox("warning", "Không có job", f"Nhóm '{group_name}' không có lượt nào đang chờ.")
        return

    # Gom các job theo "giờ gốc" (time_str, bỏ giây thường giống nhau theo máy
    # do lệch vài giây lúc tạo — nên gom theo giờ:phút để nhóm đúng các lượt
    # vốn được tạo cùng 1 lần đặt lịch)
    def hm_key(j):
        return j.time_str[:5] if j.time_str else "??:??"

    machines_in_group = sorted(set(j.instance for j in group_parent_jobs))
    times_map = {}  # "HH:MM" -> list of Job
    for j in group_parent_jobs:
        times_map.setdefault(hm_key(j), []).append(j)

    win = tk.Toplevel()
    win.title(f"Sửa cả nhóm: {group_name}")
    win.geometry("480x520")
    win.resizable(False, False)
    win.attributes('-topmost', True)

    main_frame = ttk.Frame(win, padding=10)
    main_frame.pack(fill="both", expand=True)

    ttk.Label(main_frame, text=f"Nhóm: {group_name}", font=("", 10, "bold")).pack(anchor="w")
    ttk.Label(main_frame, text=f"Máy đang có trong nhóm: {', '.join(machines_in_group)}",
              wraplength=440, justify="left").pack(anchor="w", pady=(0, 8))

    # ---------- Phần (a): sửa/xóa từng giờ ----------
    times_frame = ttk.LabelFrame(main_frame, text="Các giờ hiện có (áp dụng cho tất cả máy ở giờ đó)")
    times_frame.pack(fill="both", expand=True, pady=(0, 10))

    times_list_frame = ttk.Frame(times_frame)
    times_list_frame.pack(fill="both", expand=True, padx=5, pady=5)

    def refresh_times_list():
        for w in list(times_list_frame.winfo_children()):
            w.destroy()
        for hm in sorted(times_map.keys()):
            row = ttk.Frame(times_list_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{hm}  ({len(times_map[hm])} máy)").pack(side="left")
            ttk.Button(row, text="Sửa giờ này", width=11, style="Warning.TButton",
                       command=lambda h=hm: _edit_one_time(h)).pack(side="right", padx=(2, 0))
            ttk.Button(row, text="Xóa giờ này", width=11, style="Danger.TButton",
                       command=lambda h=hm: _delete_one_time(h)).pack(side="right", padx=(2, 0))

    def _edit_one_time(old_hm):
        new_time = simpledialog.askstring(
            "Sửa giờ", f"Đổi '{old_hm}' thành giờ mới (HH:MM):", initialvalue=old_hm, parent=win
        )
        if not new_time:
            return
        validated = validate_time_input(new_time.strip())
        if not validated:
            auto_close_messagebox("error", "Lỗi", "Định dạng giờ không hợp lệ (HH:MM hoặc HHMM)")
            return
        new_hm = validated[:5]
        for j in times_map[old_hm]:
            old_start = datetime.strptime(j.time_str, "%H:%M:%S")
            new_start = datetime.strptime(validated, "%H:%M:%S").replace(
                year=old_start.year, month=old_start.month, day=old_start.day
            )
            time_diff = (new_start - old_start).total_seconds()
            j.time_str = validated
            j.status = "Đã hẹn"
            j.current_child_index = 0
            j.update_scheduled_time()
            for gj in j.group_jobs:
                gj_start = datetime.strptime(gj.time_str, "%H:%M:%S")
                gj_new_str = (gj_start + timedelta(seconds=time_diff)).strftime("%H:%M:%S")
                gj.time_str = gj_new_str
                gj.status = "Đã hẹn"
                gj.update_scheduled_time()
            register_job(j, update_jobs_list, save_jobs)
        times_map[new_hm] = times_map.pop(old_hm)
        refresh_times_list()
        update_jobs_list()
        save_jobs()

    def _delete_one_time(hm):
        if not messagebox.askyesno("Xác nhận", f"Xóa tất cả lượt ở giờ {hm} (mọi máy)?"):
            return
        for j in times_map[hm]:
            unregister_job(j)
            if j in jobs:
                jobs.remove(j)
        del times_map[hm]
        refresh_times_list()
        update_jobs_list()
        save_jobs()

    refresh_times_list()

    # ---------- Phần (b): nhập nhanh nhiều giờ để thay thế toàn bộ ----------
    bulk_frame = ttk.LabelFrame(main_frame, text="Thay thế toàn bộ bằng danh sách giờ mới")
    bulk_frame.pack(fill="x", pady=(0, 10))

    ttk.Label(bulk_frame, text="Nhập các giờ, cách nhau bằng dấu phẩy (vd: 10:00, 14:00, 18:30):",
              wraplength=440, justify="left").pack(anchor="w", padx=5, pady=(5, 2))
    bulk_var = tk.StringVar(value=", ".join(sorted(times_map.keys())))
    ttk.Entry(bulk_frame, textvariable=bulk_var).pack(fill="x", padx=5, pady=(0, 5))

    note = ttk.Label(
        bulk_frame,
        text="Áp dụng cho tất cả máy đang có trong nhóm. Giữ nguyên cấu hình lặp lại hiện tại của từng máy.",
        wraplength=440, justify="left", foreground="#555"
    )
    note.pack(anchor="w", padx=5, pady=(0, 5))

    def apply_bulk():
        raw = bulk_var.get().strip()
        if not raw:
            auto_close_messagebox("error", "Lỗi", "Vui lòng nhập ít nhất 1 giờ.")
            return

        new_times = []
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            validated = validate_time_input(piece)
            if not validated:
                auto_close_messagebox("error", "Lỗi", f"Giờ không hợp lệ: '{piece}'")
                return
            new_times.append(validated)

        if not new_times:
            auto_close_messagebox("error", "Lỗi", "Không có giờ hợp lệ nào được nhập.")
            return

        if not messagebox.askyesno(
            "Xác nhận",
            f"Thay thế TOÀN BỘ {len(group_parent_jobs)} lượt hiện có của nhóm '{group_name}'\n"
            f"bằng {len(new_times)} giờ mới x {len(machines_in_group)} máy "
            f"({len(new_times) * len(machines_in_group)} lượt mới)?"
        ):
            return

        group = next((g for g in ACTION_GROUPS if g["name"] == group_name), None)
        if not group:
            auto_close_messagebox("error", "Lỗi", f"Nhóm hành động '{group_name}' không tồn tại trong action_groups!")
            return

        # Lưu lại cấu hình lặp lại cũ theo từng máy (nếu có nhiều job/máy thì
        # lấy theo job đầu tiên tìm thấy của máy đó)
        repeat_by_machine = {}
        for j in group_parent_jobs:
            if j.instance not in repeat_by_machine:
                repeat_by_machine[j.instance] = (
                    getattr(j, 'is_repeating', False),
                    getattr(j, 'repeat_interval', 0),
                )

        # Xóa hết job cũ của nhóm này (đang chờ)
        for j in group_parent_jobs:
            unregister_job(j)
            if j in jobs:
                jobs.remove(j)

        now = datetime.now()
        new_jobs = []
        for machine in machines_in_group:
            is_rep, rep_interval = repeat_by_machine.get(machine, (False, 0))
            for time_input in new_times:
                start_time = datetime.strptime(time_input, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if start_time < now:
                    start_time += timedelta(days=1)

                group_jobs_children = []
                current_time = start_time
                for action in group["actions"]:
                    time_str = current_time.strftime("%H:%M:%S")
                    if action["type"] == "group":
                        sub_job = Job(time_str, machine, "group", action["value"], group_name)
                    else:
                        sub_job = Job(time_str, machine, action["type"], action["value"], group_name)
                    group_jobs_children.append(sub_job)
                    current_time += timedelta(seconds=action.get("delay", 0))

                new_job = Job(time_input, machine, group_name=group_name,
                              is_group=True, group_jobs=group_jobs_children)
                new_job.is_repeating = is_rep
                new_job.repeat_interval = rep_interval
                new_jobs.append(new_job)

        jobs.extend(new_jobs)
        for j in new_jobs:
            register_job(j, update_jobs_list, save_jobs)

        update_jobs_list()
        save_jobs()
        auto_close_messagebox(
            "info", "Thành công",
            f"Đã thay {len(group_parent_jobs)} lượt cũ bằng {len(new_jobs)} lượt mới cho nhóm '{group_name}'."
        )
        win.destroy()

    ttk.Button(bulk_frame, text="Áp dụng (thay thế toàn bộ)", command=apply_bulk).pack(anchor="e", padx=5, pady=(0, 5))

    ttk.Button(main_frame, text="Đóng", style="Ghost.TButton", command=win.destroy).pack(anchor="e", pady=(5, 0))

    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    x = (win.winfo_screenwidth() // 2) - (w // 2)
    y = (win.winfo_screenheight() // 2) - (h // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


        
def remove_group_jobs(group_jobs):
    global jobs
    for job in group_jobs:
        if job in jobs:
            jobs.remove(job)
    update_jobs_list()
    save_jobs()
    messagebox.showinfo("Thông báo", f"Đã xóa nhóm công việc.")        
        
def update_group_combobox():
    try:
        if group_combo:
            names = [g["name"] for g in ACTION_GROUPS]
            group_combo['values'] = names
            print(f"[UPDATE_COMBO] Hiện tại có {len(names)} nhóm: {names}")
            if names and (not group_var.get() or group_var.get() not in names):
                group_var.set(names[0])
            root.update_idletasks()
    except Exception as e:
        print(f"[UPDATE_COMBO] Lỗi: {e}")

def launch_selected():
    selected = [name for name, var in var_dict.items() if var.get()]
    for name in selected:
        launch_instance(name)

def close_selected():
    selected = [name for name, var in var_dict.items() if var.get()]
    for name in selected:
        quit_instance(name)

def open_operation_recorder():
    selected = [name for name, var in var_dict.items() if var.get()]
    for name in selected:
        if focus_emulator(name):
            pyautogui.hotkey('ctrl', '8')
            time.sleep(1)
            print(f"[LOG] Đã mở Operation Recorder cho {name}")
        else:
            auto_close_messagebox("error", "Lỗi", f"Không tìm thấy cửa sổ giả lập: {name}")

def bring_to_front():
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("warning", "Chọn giả lập", "Vui lòng chọn ít nhất một giả lập để đưa lên.")
        return
    for name in selected:
        focus_emulator(name)
        print(f"[LOG] Đã đưa giả lập {name} lên trên cùng")

def calculate_time():
    delay_time = delay_time_var.get().strip()
    subtract_time = subtract_time_var.get().strip() or "00:00"
  
    delay_time = validate_time_input(delay_time)
    subtract_time = validate_time_input(subtract_time)
  
    if not delay_time:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ chờ theo định dạng HHMM hoặc HH:MM")
        return
  
    try:
        now = datetime.now()
        delay_dt = datetime.strptime(delay_time, "%H:%M:%S")
        subtract_dt = datetime.strptime(subtract_time, "%H:%M:%S")
        new_time = now + timedelta(hours=delay_dt.hour, minutes=delay_dt.minute) - timedelta(hours=subtract_dt.hour, minutes=subtract_dt.minute)
        schedule_time_var.set(new_time.strftime("%H:%M"))
        auto_close_messagebox("info", "Thành công", f"Đã tính giờ mới: {new_time.strftime('%H:%M')} (Hiện tại: {now.strftime('%H:%M')})")
    except ValueError:
        auto_close_messagebox("error", "Lỗi", "Định dạng thời gian không hợp lệ!")

def set_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ theo định dạng HHMM hoặc HH:MM")
        return
  
    line_text = record_line_var.get().strip()
    if not line_text.isdigit():
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập số dòng hợp lệ!")
        return
  
    line_num = int(line_text)
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập để hẹn giờ.")
        return
  
    all_jobs = []
   
    for name in selected:
        group_jobs = []
        current_time = datetime.strptime(time_input, "%H:%M:%S").replace(
            year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
        )
        if current_time < datetime.now():
            current_time += timedelta(days=1)
       
        
       
        time_str = current_time.strftime("%H:%M:%S")
        job = Job(time_str, name, "record", line_num)
        group_jobs.append(job)
       
        group_job = Job(time_input, name, "record", line_num, is_group=True, group_jobs=group_jobs)
        all_jobs.append(group_job)
   
    jobs.extend(all_jobs)
    for j in all_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Đặt giờ", f"Đã hẹn chạy lúc {time_input[:-3]} cho {len(selected)} giả lập (có chèn nhóm mặc định nếu có).")

def set_key_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ theo định dạng HHMM hoặc HH:MM")
        return
  
    key = key_input_var.get().strip()
    if not validate_key_input(key):
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập phím hợp lệ!")
        return
  
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập.")
        return
  
    all_jobs = []
   
    for name in selected:
        group_jobs = []
        current_time = datetime.strptime(time_input, "%H:%M:%S").replace(
            year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
        )
        if current_time < datetime.now():
            current_time += timedelta(days=1)
       
        
       
        time_str = current_time.strftime("%H:%M:%S")
        job = Job(time_str, name, "key", key)
        all_jobs.append(job)
       
        print(f"[SCHED] Thêm job gửi phím '{key}' cho {name} lúc {time_str}")
   
    jobs.extend(all_jobs)
    for j in all_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Đặt giờ", f"Đã hẹn gửi phím {key} lúc {time_input[:-3]} cho {len(selected)} giả lập (có chèn nhóm mặc định nếu có).")

def set_notification_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ hợp lệ!")
        return
  
    all_jobs = []
   
    selected = [name for name, var in var_dict.items() if var.get()]
    if selected:
        for name in selected:
            group_jobs = []
            current_time = datetime.strptime(time_input, "%H:%M:%S").replace(
                year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
            )
            if current_time < datetime.now():
                current_time += timedelta(days=1)
           
            
           
            time_str = current_time.strftime("%H:%M:%S")
            notif_job = Job(time_str, "Thông báo", "notification")
            group_jobs.append(notif_job)
           
            group_job = Job(time_input, "Thông báo", "notification", is_group=True, group_jobs=group_jobs)
            all_jobs.append(group_job)
    else:
        job = Job(time_input, "Thông báo", "notification")
        all_jobs.append(job)
   
    jobs.extend(all_jobs)
    for j in all_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Đặt thông báo", f"Đã hẹn thông báo lúc {time_input[:-3]} (có chèn nhóm mặc định nếu có).")

def set_launch_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ hợp lệ!")
        return
 
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập.")
        return
 
    all_jobs = []
  
    for name in selected:
        group_jobs = []
        current_time = datetime.strptime(time_input, "%H:%M:%S").replace(
            year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
        )
        if current_time < datetime.now():
            current_time += timedelta(days=1)
      
        # Chèn nhóm mặc định nếu có
        
      
        time_str = current_time.strftime("%H:%M:%S")
        job = Job(time_str, name, "launch")
        group_jobs.append(job)
      
        # Tạo job launch đơn giản, không gán is_group=True để tránh chạy logic nhóm
        group_job = Job(time_input, name, "launch", group_jobs=group_jobs)
        all_jobs.append(group_job)
  
    jobs.extend(all_jobs)
    for j in all_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Đặt giờ khởi động", f"Đã hẹn khởi động lúc {time_input[:-3]} cho {len(selected)} giả lập (có chèn nhóm mặc định nếu có).")
    
def set_quit_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ hợp lệ!")
        return
 
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập.")
        return
 
    all_jobs = []
  
    for name in selected:
        group_jobs = []
        current_time = datetime.strptime(time_input, "%H:%M:%S").replace(
            year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
        )
        if current_time < datetime.now():
            current_time += timedelta(days=1)
      
        
      
        time_str = current_time.strftime("%H:%M:%S")
        job = Job(time_str, name, "quit")
        group_jobs.append(job)
      
        group_job = Job(time_input, name, "quit", group_jobs=group_jobs)
        all_jobs.append(group_job)
  
    jobs.extend(all_jobs)
    for j in all_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Đặt giờ tắt", f"Đã hẹn tắt lúc {time_input[:-3]} cho {len(selected)} giả lập (có chèn nhóm mặc định nếu có).")
    
def set_group_schedule():
    time_input = schedule_time_var.get().strip()
    time_input = validate_time_input(time_input)
    if not time_input:
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giờ theo định dạng HHMM hoặc HH:MM")
        return
    group_name = group_var.get()
    if not group_name:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn một nhóm hành động!")
        return
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập để hẹn giờ nhóm.")
        return
    # Lấy khoảng lặp lại (dùng cùng logic validate_time_input như giờ chờ/giờ trừ)
    repeat_input = repeat_interval_var.get().strip()
    repeat_seconds = 0
    if repeat_input and repeat_input != "00:00" and repeat_input.lower() != "không":
        # Cho phép đặc biệt 24:00 = 24 giờ
        if repeat_input == "24:00":
            repeat_seconds = 24 * 3600
        else:
            validated = validate_time_input(repeat_input)
            if validated:
                hh_mm = validated[:-3]
                h, m = map(int, hh_mm.split(':'))
                repeat_seconds = h * 3600 + m * 60
            else:
                try:
                    total_min = int(repeat_input)
                    repeat_seconds = total_min * 60
                except ValueError:
                    auto_close_messagebox("error", "Lỗi", f"Khoảng lặp lại không hợp lệ: {repeat_input}\nVui lòng nhập HH:MM (ví dụ 01:00, 24:00) hoặc số phút (ví dụ 60)")
                    return
        
        if repeat_seconds <= 0:
            repeat_seconds = 0
            
    now = datetime.now()
    try:
        start_time = datetime.strptime(time_input, "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day
        )
        if start_time < now:
            start_time += timedelta(days=1)
    except ValueError:
        auto_close_messagebox("error", "Lỗi", "Định dạng thời gian không hợp lệ!")
        return
    group = next((g for g in ACTION_GROUPS if g["name"] == group_name), None)
    if not group:
        auto_close_messagebox("error", "Lỗi", f"Nhóm {group_name} không tồn tại!")
        return
    all_group_jobs = []
    for name in selected:
        group_jobs = []
        current_time = start_time
        
        for idx, action in enumerate(group["actions"], 1):
            action_time = current_time
            time_str = action_time.strftime("%H:%M:%S")
            if action["type"] == "group":
                sub_job = Job(time_str, name, "group", action["value"], group_name)
                group_jobs.append(sub_job)
            else:
                job = Job(time_str, name, action["type"], action["value"], group_name)
                group_jobs.append(job)
            print(f"[LOG] Thêm job con {idx} cho nhóm {group_name} trên {name}: {action['type']} - {action['value']} lúc {time_str}")
            current_time += timedelta(seconds=action["delay"])
        group_job = Job(time_input, name, group_name=group_name, is_group=True, group_jobs=group_jobs)
        # Đánh dấu job lặp lại
        if repeat_seconds > 0:
            group_job.repeat_interval = repeat_seconds
            group_job.is_repeating = True
        else:
            group_job.is_repeating = False
        all_group_jobs.append(group_job)
        print(f"[LOG] Thêm job nhóm {group_name} trên {name} lúc {time_input}")
    jobs.extend(all_group_jobs)
    for j in all_group_jobs:
        register_job(j, update_jobs_list, save_jobs)
    update_jobs_list()
    save_jobs()
    save_action_groups()
    msg = f"Đã hẹn nhóm {group_name} lúc {time_input[:-3]} cho {len(selected)} giả lập"
    if repeat_seconds > 0:
        hours = repeat_seconds // 3600
        minutes = (repeat_seconds % 3600) // 60
        msg += f". Lặp lại sau {hours} giờ {minutes} phút (tự động tạo lịch mới sau mỗi lần chạy xong)."
    else:
        msg += " (không lặp lại)."
    auto_close_messagebox("info", "Đặt giờ nhóm", msg + " (có chèn nhóm mặc định nếu có).")
    
    
def run_group_now():
    group_name = group_var.get()
    if not group_name:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn một nhóm hành động!")
        return
   
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập để chạy nhóm.")
        return
   
    group = next((g for g in ACTION_GROUPS if g["name"] == group_name), None)
    if not group:
        auto_close_messagebox("error", "Lỗi", f"Nhóm {group_name} không tồn tại!")
        return
   
    success_count = 0
    for name in selected:
        print(f"[LOG] Bắt đầu chạy nhóm {group_name} ngay lập tức trên {name}")
       
        if default_group_name:
            default_group = next((g for g in ACTION_GROUPS if g["name"] == default_group_name), None)
            if default_group:
                print(f"[DEFAULT] Chạy nhóm mặc định '{default_group_name}' trước trên {name}")
                run_group_actions(name, default_group["actions"])
                print(f"[DEFAULT] Hoàn thành nhóm mặc định '{default_group_name}' trên {name}")
                time.sleep(5)
            else:
                print(f"[DEFAULT] Nhóm mặc định '{default_group_name}' không tồn tại")
       
        run_group_actions(name, group["actions"])
        success_count += 1
   
    auto_close_messagebox("info", "Thành công", f"Đã chạy nhóm {group_name} trên {success_count}/{len(selected)} giả lập (có chạy nhóm mặc định trước nếu có).")

def run_key_now():
    key = key_input_var.get().strip()
    if not validate_key_input(key):
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập phím hợp lệ!")
        return
  
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập.")
        return
  
    for name in selected:
        try:
            success = run_key_press(name, key)
            if not success:
                raise Exception("Không thể gửi phím")
        except Exception as e:
            error_msg = f"Không thể gửi phím trên {name}: {e}"
            auto_close_messagebox("error", "Lỗi", error_msg)
            print(f"[LOG] {error_msg}")

def run_now():
    line_text = record_line_var.get().strip()
    if not line_text.isdigit():
        auto_close_messagebox("error", "Lỗi", "Vui lòng nhập số dòng hợp lệ!")
        return
  
    line_num = int(line_text)
    selected = [name for name, var in var_dict.items() if var.get()]
    if not selected:
        auto_close_messagebox("error", "Lỗi", "Vui lòng chọn ít nhất một giả lập.")
        return
  
    for name in selected:
        try:
            success = run_record_line(name, line_num)
            if not success:
                raise Exception("Không thể chạy script")
        except Exception as e:
            error_msg = f"Không thể chạy trên {name}: {e}"
            auto_close_messagebox("error", "Lỗi", error_msg)
            print(f"[LOG] {error_msg}")

def remove_job(display_index, is_pending=True):
    display_jobs = [j for j in jobs if (not j.group_name or j.is_group) and (j.status == "Đã hẹn" if is_pending else j.status != "Đã hẹn")]
    sorted_display_jobs = sorted(display_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)
  
    if 0 <= display_index < len(sorted_display_jobs):
        job_to_remove = sorted_display_jobs[display_index]
        unregister_job(job_to_remove)
        jobs.remove(job_to_remove)
        update_jobs_list()
        save_jobs()

def edit_job(display_index, is_pending=True):
    display_jobs = [j for j in jobs if (not j.group_name or j.is_group) and (j.status == "Đã hẹn" if is_pending else j.status != "Đã hẹn")]
    sorted_display_jobs = sorted(display_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)
  
    if 0 <= display_index < len(sorted_display_jobs):
        job = sorted_display_jobs[display_index]
        edit_window = tk.Toplevel()
        edit_window.title(f"Chỉnh sửa công việc - {job.instance}")
        edit_window.geometry("400x200")
        edit_window.resizable(False, False)
        edit_window.attributes('-topmost', True)
      
        main_frame = ttk.Frame(edit_window, padding=10)
        main_frame.pack(fill="both", expand=True)
      
        if job.is_group:
            info_text = f"Loại: Nhóm hành động\nNhóm: {job.group_name}\nTrạng thái: {job.status}"
        elif job.job_type == "notification":
            info_text = f"Loại: Thông báo\nTrạng thái: {job.status}"
        elif job.job_type == "launch":
            info_text = f"Loại: Khởi động giả lập\nTrạng thái: {job.status}\nNhóm: {job.group_name if job.group_name else 'Không có'}"
        elif job.job_type == "quit":
            info_text = f"Loại: Tắt giả lập\nTrạng thái: {job.status}\nNhóm: {job.group_name if job.group_name else 'Không có'}"
        else:
            info_text = f"Loại: {'Chạy dòng' if job.job_type == 'record' else 'Gửi phím'}\nGiá trị: {job.value}\nTrạng thái: {job.status}\nNhóm: {job.group_name if job.group_name else 'Không có'}"
      
        ttk.Label(main_frame, text=info_text, justify="left").pack(anchor="w", pady=(0, 10))
      
        time_frame = ttk.Frame(main_frame)
        time_frame.pack(fill="x", pady=5)
        ttk.Label(time_frame, text="Thời gian mới (HH:MM):").pack(side="left")
      
        edit_time_var = tk.StringVar(value=job.time_str[:-3])
        time_entry = ttk.Entry(time_frame, textvariable=edit_time_var, width=10)
        time_entry.pack(side="left", padx=5)
      
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=10)
      
        def save_changes():
            new_time = edit_time_var.get().strip()
            if new_time.isdigit() and len(new_time) == 4:
                new_time = f"{new_time[:2]}:{new_time[2:]}"
          
            try:
                new_start_time = datetime.strptime(new_time, "%H:%M")
                if job.is_group:
                    old_start_time = datetime.strptime(job.time_str, "%H:%M:%S")
                    new_start_time_full = datetime.strptime(new_time + ":00", "%H:%M:%S").replace(
                        year=old_start_time.year, month=old_start_time.month, day=old_start_time.day
                    )
                    if new_start_time_full < datetime.now():
                        new_start_time_full += timedelta(days=1)
                    time_diff = (new_start_time_full - old_start_time).total_seconds()
                    job.time_str = new_time + ":00"
                    job.status = "Đã hẹn"
                    job.current_child_index = 0
                    job.update_scheduled_time()
                    for gj in job.group_jobs:
                        gj_start_time = datetime.strptime(gj.time_str, "%H:%M:%S")
                        new_gj_time = (gj_start_time + timedelta(seconds=time_diff)).strftime("%H:%M:%S")
                        gj.time_str = new_gj_time
                        gj.status = "Đã hẹn"
                        gj.update_scheduled_time()
                else:
                    job.time_str = new_time + ":00"
                    job.status = "Đã hẹn"
                    job.update_scheduled_time()
                update_jobs_list()
                save_jobs()
                register_job(job, update_jobs_list, save_jobs)
                edit_window.destroy()
                auto_close_messagebox("info", "Thành công", f"Đã cập nhật thời gian thành {new_time}")
            except ValueError:
                auto_close_messagebox("error", "Lỗi", "Định dạng thời gian không hợp lệ. Vui lòng nhập theo định dạng HH:MM")
      
        ttk.Button(btn_frame, text="Lưu thay đổi", style="Success.TButton", command=save_changes).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Hủy", style="Ghost.TButton", command=edit_window.destroy).pack(side="right")
      
        time_entry.focus_set()
        time_entry.select_range(0, "end")
      
        edit_window.update_idletasks()
        width = edit_window.winfo_width()
        height = edit_window.winfo_height()
        x = (edit_window.winfo_screenwidth() // 2) - (width // 2)
        y = (edit_window.winfo_screenheight() // 2) - (height // 2)
        edit_window.geometry(f"{width}x{height}+{x}+{y}")

def reschedule_job(display_index, is_pending=True):
    display_jobs = [j for j in jobs if (not j.group_name or j.is_group) and (j.status == "Đã hẹn" if is_pending else j.status != "Đã hẹn")]
    sorted_display_jobs = sorted(display_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)
  
    if 0 <= display_index < len(sorted_display_jobs):
        job = sorted_display_jobs[display_index]
        now = datetime.now()
        job_time = datetime.strptime(job.time_str, "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day
        )
        job_time += timedelta(days=1)
        new_time_str = job_time.strftime("%H:%M:%S")
        if job.is_group:
            old_start_time = datetime.strptime(job.time_str, "%H:%M:%S")
            time_diff = (job_time - old_start_time).total_seconds()
            job.time_str = new_time_str
            job.scheduled_time = job_time
            job.status = "Đã hẹn"
            job.current_child_index = 0
            for gj in job.group_jobs:
                gj_start_time = datetime.strptime(gj.time_str, "%H:%M:%S")
                new_gj_time = (gj_start_time + timedelta(seconds=time_diff)).strftime("%H:%M:%S")
                gj.time_str = new_gj_time
                gj.scheduled_time = datetime.strptime(new_gj_time, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                ) + (timedelta(days=1) if gj_start_time < now else timedelta())
                gj.status = "Đã hẹn"
        else:
            job.time_str = new_time_str
            job.scheduled_time = job_time
            job.status = "Đã hẹn"
        update_jobs_list()
        save_jobs()
        register_job(job, update_jobs_list, save_jobs)
        auto_close_messagebox("info", "Hẹn lại", f"Đã hẹn lại {job.instance} cho {job_time.strftime('%d/%m %H:%M')}")

def reschedule_all():
    now = datetime.now()
    rescheduled_count = 0
    for job in jobs:
        if job.status != "Đã hẹn":
            rescheduled_count += 1
            if not job.is_group:
                job_time = datetime.strptime(job.time_str, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
                job_time += timedelta(days=1)
                job.time_str = job_time.strftime("%H:%M:%S")
                job.scheduled_time = job_time
                job.status = "Đã hẹn"
            else:
                old_start_time = datetime.strptime(job.time_str, "%H:%M:%S")
                job_time = old_start_time.replace(
                    year=now.year, month=now.month, day=now.day
                )
                job_time += timedelta(days=1)
                time_diff = (job_time - old_start_time).total_seconds()
                job.time_str = job_time.strftime("%H:%M:%S")
                job.scheduled_time = job_time
                job.status = "Đã hẹn"
                job.current_child_index = 0
                for gj in job.group_jobs:
                    gj_start_time = datetime.strptime(gj.time_str, "%H:%M:%S")
                    new_gj_time = (gj_start_time + timedelta(seconds=time_diff)).strftime("%H:%M:%S")
                    gj.time_str = new_gj_time
                    gj.scheduled_time = datetime.strptime(new_gj_time, "%H:%M:%S").replace(
                        year=now.year, month=now.month, day=now.day
                    ) + (timedelta(days=1) if gj_start_time < now else timedelta())
                    gj.status = "Đã hẹn"
    update_jobs_list()
    save_jobs()
    for job in jobs:
        if job.status == "Đã hẹn":
            register_job(job, update_jobs_list, save_jobs)
    auto_close_messagebox("info", "Hẹn lại tất cả", f"Đã hẹn lại {rescheduled_count} công việc đã chạy cho ngày tiếp theo")

def toggle_pause():
    global is_paused, pause_button
    is_paused = not is_paused
    if is_paused:
        pause_scheduler()
    else:
        resume_scheduler()
    if pause_button:
        pause_button.config(text="Tiếp tục" if is_paused else "Tạm dừng")
    print(f"[LOG] {'Tạm dừng' if is_paused else 'Tiếp tục'} kiểm tra lịch trình")
    
def run_job_now(display_index):
    display_jobs = [j for j in jobs if (not j.group_name or j.is_group) and j.status == "Đã hẹn"]
    sorted_display_jobs = sorted(display_jobs, key=lambda j: j.scheduled_time if j.scheduled_time else datetime.max)
  
    if 0 <= display_index < len(sorted_display_jobs):
        job = sorted_display_jobs[display_index]
        try:
            if job.is_group:
                group = next((g for g in ACTION_GROUPS if g["name"] == job.group_name), None)
                if not group:
                    raise Exception(f"Nhóm {job.group_name} không tồn tại")
                if not job.group_jobs:
                    update_group_jobs()
                for idx, action in enumerate(group["actions"]):
                    if idx >= len(job.group_jobs):
                        break
                    child_job = job.group_jobs[idx]
                    print(f"[LOG] Chạy job con {child_job.job_type} cho {child_job.instance} (Hành động {idx+1})")
                    if child_job.job_type == "record":
                        success = run_record_line(child_job.instance, int(child_job.value))
                        child_job.status = "Đã chạy" if success else "Lỗi"
                    elif child_job.job_type == "key":
                        success = run_key_press(child_job.instance, child_job.value)
                        child_job.status = "Đã gửi" if success else "Lỗi"
                    elif child_job.job_type == "launch":
                        success = launch_instance(child_job.instance)
                        child_job.status = "Đã khởi động" if success else "Lỗi"
                    elif child_job.job_type == "quit":
                        success = quit_instance(child_job.instance)
                        child_job.status = "Đã tắt" if success else "Lỗi"
                    if action["delay"] > 0:
                        print(f"[LOG] Chờ {action['delay']}s trước khi chạy hành động tiếp theo")
                        time.sleep(action["delay"])
                    if child_job.status == "Lỗi":
                        break
                job.status = "Đã chạy" if all(cj.status in ["Đã chạy", "Đã gửi", "Đã khởi động", "Đã tắt"] for cj in job.group_jobs) else "Lỗi"
                job.current_child_index = len(job.group_jobs)
            else:
                if job.job_type == "record":
                    success = run_record_line(job.instance, int(job.value))
                    job.status = "Đã chạy" if success else "Lỗi"
                elif job.job_type == "key":
                    success = run_key_press(job.instance, job.value)
                    job.status = "Đã gửi" if success else "Lỗi"
                elif job.job_type == "launch":
                    success = launch_instance(job.instance)
                    job.status = "Đã khởi động" if success else "Lỗi"
                elif job.job_type == "quit":
                    success = quit_instance(job.instance)
                    job.status = "Đã tắt" if success else "Lỗi"
                elif job.job_type == "notification":
                    auto_close_messagebox("info", "Thông báo", f"Đã đến giờ {job.time_str[:-3]}")
                    job.status = "Đã thông báo"
            update_jobs_list()
            save_jobs()
        except Exception as e:
            error_msg = f"Lỗi thực hiện công việc [{job.job_type}]: {e}"
            print(f"[LOG] {error_msg}")
            auto_close_messagebox("error", "Lỗi", error_msg)
            job.status = "Lỗi"

def stop_job(job):
    job.should_stop = True
    if job in running_threads:
        del running_threads[job]
    job.status = "Đã dừng"
    print(f"[LOG] Nhóm {job.group_name} trên {job.instance} đã bị dừng")
    update_jobs_list()
    save_jobs()

def stop_repeating(job):  # MỚI: dừng lặp lại
    job.is_repeating = False
    if hasattr(job, 'repeat_interval'):
        job.repeat_interval = 0
    update_jobs_list()
    save_jobs()
    auto_close_messagebox("info", "Thông báo", f"Đã dừng lặp lại cho nhóm {job.group_name} trên {job.instance}")

def manage_groups():
    global groups_listbox
    group_window = tk.Toplevel()
    group_window.title("Quản lý nhóm hành động")
    group_window.geometry("600x400")
    group_window.resizable(False, False)
    group_window.attributes('-topmost', True)
  
    main_frame = ttk.Frame(group_window, padding=10)
    main_frame.pack(fill="both", expand=True)
  
    groups_frame = ttk.LabelFrame(main_frame, text="Danh sách nhóm")
    groups_frame.pack(fill="both", expand=True)
  
    groups_listbox = tk.Listbox(groups_frame, height=10)
    groups_listbox.pack(fill="both", expand=True, padx=5, pady=5)
  
    def update_groups_listbox():
        groups_listbox.delete(0, tk.END)
        for group in ACTION_GROUPS:
            groups_listbox.insert(tk.END, group["name"])
        update_group_combobox()
  
    update_groups_listbox()
  
    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill="x", pady=10)
  
    def create_new_group():
        edit_group_window(None)
        update_groups_listbox()
  
    def edit_selected_group():
        try:
            selected_idx = groups_listbox.curselection()[0]
            group = ACTION_GROUPS[selected_idx]
            edit_group_window(group)
            update_groups_listbox()
        except IndexError:
            auto_close_messagebox("warning", "Chọn nhóm", "Vui lòng chọn một nhóm để chỉnh sửa.")
  
    def delete_selected_group():
        try:
            selected_idx = groups_listbox.curselection()[0]
            group_name = ACTION_GROUPS[selected_idx]["name"]
            if messagebox.askyesno("Xác nhận", f"Bạn có chắc muốn xóa nhóm '{group_name}'?"):
                ACTION_GROUPS.pop(selected_idx)
                save_action_groups()
                update_groups_listbox()
        except IndexError:
            auto_close_messagebox("warning", "Chọn nhóm", "Vui lòng chọn một nhóm để xóa.")
  
    ttk.Button(btn_frame, text="Tạo nhóm mới", command=create_new_group).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Chỉnh sửa nhóm", command=edit_selected_group).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Xóa nhóm", style="Danger.TButton", command=delete_selected_group).pack(side="left", padx=5)
  
    group_window.update_idletasks()
    width = group_window.winfo_width()
    height = group_window.winfo_height()
    x = (group_window.winfo_screenwidth() // 2) - (width // 2)
    y = (group_window.winfo_screenheight() // 2) - (height // 2)
    group_window.geometry(f"{width}x{height}+{x}+{y}")

def edit_group_window(group):
    is_new = group is None
    group_data = {"name": "", "actions": []} if is_new else group.copy()
  
    window = tk.Toplevel()
    window.title("Tạo nhóm mới" if is_new else f"Chỉnh sửa nhóm: {group_data['name']}")
    window.geometry("500x500")
    window.resizable(False, False)
    window.attributes('-topmost', True)
  
    main_frame = ttk.Frame(window, padding=10)
    main_frame.pack(fill="both", expand=True)
  
    name_frame = ttk.Frame(main_frame)
    name_frame.pack(fill="x")
    ttk.Label(name_frame, text="Tên nhóm:").pack(side="left")
    name_var = tk.StringVar(value=group_data["name"])
    ttk.Entry(name_frame, textvariable=name_var).pack(side="left", fill="x", expand=True, padx=5)
  
    actions_frame = ttk.LabelFrame(main_frame, text="Danh sách hành động")
    actions_frame.pack(fill="both", expand=True, pady=10)
  
    actions_listbox = tk.Listbox(actions_frame, height=10)
    actions_listbox.pack(fill="both", expand=True, padx=5, pady=5)
  
    dragging = False
    drag_start_index = None
    selected_action_index = None
  
    def update_actions_listbox():
        actions_listbox.delete(0, tk.END)
        for action in group_data["actions"]:
            if action["type"] == "group":
                action_str = f"Nhóm con: {action['value']} (Trễ: {action['delay']}s)"
            else:
                action_str = f"Loại: {action['type']}, Giá trị: {action['value']}, Trễ: {action['delay']}s"
            actions_listbox.insert(tk.END, action_str)
  
    update_actions_listbox()
  
    def start_drag(event):
        nonlocal dragging, drag_start_index
        index = actions_listbox.nearest(event.y)
        if 0 <= index < len(group_data["actions"]):
            dragging = True
            drag_start_index = index
            actions_listbox.selection_clear(0, tk.END)
            actions_listbox.selection_set(index)
            actions_listbox.activate(index)
  
    def drag_motion(event):
        nonlocal dragging, drag_start_index
        if not dragging:
            return
        index = actions_listbox.nearest(event.y)
        if 0 <= index < len(group_data["actions"]) and index != drag_start_index:
            action = group_data["actions"].pop(drag_start_index)
            group_data["actions"].insert(index, action)
            update_actions_listbox()
            drag_start_index = index
            actions_listbox.selection_clear(0, tk.END)
            actions_listbox.selection_set(index)
            actions_listbox.activate(index)
  
    def end_drag(event):
        nonlocal dragging, drag_start_index
        dragging = False
        drag_start_index = None
  
    actions_listbox.bind("<Button-1>", start_drag)
    actions_listbox.bind("<B1-Motion>", drag_motion)
    actions_listbox.bind("<ButtonRelease-1>", end_drag)
  
    def on_select_action(event):
        nonlocal selected_action_index
        try:
            selected_idx = actions_listbox.curselection()[0]
            if 0 <= selected_idx < len(group_data["actions"]):
                selected_action_index = selected_idx
                action = group_data["actions"][selected_idx]
                type_var.set(action["type"])
                value_var.set(str(action["value"]) if action["type"] == "record" else action["value"])
                delay_var.set(str(action["delay"]))
        except IndexError:
            pass
  
    actions_listbox.bind("<<ListboxSelect>>", on_select_action)
  
    action_edit_frame = ttk.Frame(main_frame)
    action_edit_frame.pack(fill="x", pady=5)
  
    ttk.Label(action_edit_frame, text="Loại:").pack(side="left")
    type_var = tk.StringVar(value="record")
    ttk.Combobox(action_edit_frame, textvariable=type_var, values=["record", "key", "launch", "quit", "group"], state="readonly", width=10).pack(side="left", padx=5)
  
    ttk.Label(action_edit_frame, text="Giá trị:").pack(side="left")
    value_var = tk.StringVar()
    ttk.Entry(action_edit_frame, textvariable=value_var, width=10).pack(side="left", padx=5)
  
    ttk.Label(action_edit_frame, text="Trễ (s):").pack(side="left")
    delay_var = tk.StringVar()
    ttk.Entry(action_edit_frame, textvariable=delay_var, width=10).pack(side="left", padx=5)
  
    def add_action():
        action_type = type_var.get()
        value = value_var.get().strip()
        delay = delay_var.get().strip()
       
        if not delay.isdigit():
            auto_close_messagebox("error", "Lỗi", "Vui lòng nhập thời gian trễ là số nguyên!")
            return
       
        if action_type == "group":
            if not value:
                auto_close_messagebox("error", "Lỗi", "Vui lòng nhập tên nhóm con!")
                return
            if value not in [g["name"] for g in ACTION_GROUPS]:
                auto_close_messagebox("error", "Lỗi", f"Nhóm '{value}' không tồn tại!")
                return
            action = {
                "type": "group",
                "value": value,
                "delay": int(delay)
            }
        elif action_type == "record":
            if not value.isdigit():
                auto_close_messagebox("error", "Lỗi", "Giá trị cho 'record' phải là số!")
                return
            action = {
                "type": "record",
                "value": int(value),
                "delay": int(delay)
            }
        else:
            if not value:
                auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giá trị hành động!")
                return
            action = {
                "type": action_type,
                "value": value,
                "delay": int(delay)
            }
       
        group_data["actions"].append(action)
        update_actions_listbox()
        value_var.set("")
        delay_var.set("")
  
    def edit_action():
        nonlocal selected_action_index
        if selected_action_index is None:
            auto_close_messagebox("warning", "Chọn hành động", "Vui lòng chọn một hành động để chỉnh sửa.")
            return
      
        action_type = type_var.get()
        value = value_var.get().strip()
        delay = delay_var.get().strip()
       
        if not delay.isdigit():
            auto_close_messagebox("error", "Lỗi", "Vui lòng nhập thời gian trễ là số nguyên!")
            return
       
        if action_type == "group":
            if not value:
                auto_close_messagebox("error", "Lỗi", "Vui lòng nhập tên nhóm con!")
                return
            if value not in [g["name"] for g in ACTION_GROUPS]:
                auto_close_messagebox("error", "Lỗi", f"Nhóm '{value}' không tồn tại!")
                return
            group_data["actions"][selected_action_index] = {
                "type": "group",
                "value": value,
                "delay": int(delay)
            }
        elif action_type == "record":
            if not value.isdigit():
                auto_close_messagebox("error", "Lỗi", "Giá trị cho 'record' phải là số!")
                return
            group_data["actions"][selected_action_index] = {
                "type": "record",
                "value": int(value),
                "delay": int(delay)
            }
        else:
            if not value:
                auto_close_messagebox("error", "Lỗi", "Vui lòng nhập giá trị hành động!")
                return
            group_data["actions"][selected_action_index] = {
                "type": action_type,
                "value": value,
                "delay": int(delay)
            }
        update_actions_listbox()
        selected_action_index = None
        value_var.set("")
        delay_var.set("")
  
    def delete_action():
        try:
            selected_idx = actions_listbox.curselection()[0]
            group_data["actions"].pop(selected_idx)
            update_actions_listbox()
            selected_action_index = None
        except IndexError:
            auto_close_messagebox("warning", "Chọn hành động", "Vui lòng chọn một hành động để xóa.")
  
    action_btn_frame = ttk.Frame(main_frame)
    action_btn_frame.pack(fill="x", pady=5)
    ttk.Button(action_btn_frame, text="Thêm hành động", command=add_action).pack(side="left", padx=5)
    ttk.Button(action_btn_frame, text="Chỉnh sửa hành động", command=edit_action).pack(side="left", padx=5)
    ttk.Button(action_btn_frame, text="Xóa hành động", style="Danger.TButton", command=delete_action).pack(side="left", padx=5)
  
    def save_group():
        new_name = name_var.get().strip()
        if not new_name:
            auto_close_messagebox("error", "Lỗi", "Vui lòng nhập tên nhóm!")
            return
        if not group_data["actions"]:
            auto_close_messagebox("error", "Lỗi", "Nhóm phải có ít nhất một hành động!")
            return
        if any(g["name"] == new_name for g in ACTION_GROUPS if g != group):
            auto_close_messagebox("error", "Lỗi", f"Nhóm '{new_name}' đã tồn tại!")
            return
      
        group_data["name"] = new_name
        if is_new:
            ACTION_GROUPS.append(group_data)
            print(f"[SAVE_GROUP] Đã append nhóm mới: {new_name}, tổng ACTION_GROUPS: {len(ACTION_GROUPS)}")
        else:
            group.update(group_data)
            print(f"[SAVE_GROUP] Đã update nhóm cũ: {new_name}")
        save_action_groups()
        update_groups_listbox()
        update_group_combobox()
        window.destroy()
        auto_close_messagebox("info", "Thành công", f"Nhóm '{new_name}' đã được {'tạo' if is_new else 'cập nhật'}.")
  
    ttk.Button(main_frame, text="Lưu nhóm", style="Success.TButton", command=save_group).pack(side="right", padx=5, pady=10)
    ttk.Button(main_frame, text="Hủy", style="Ghost.TButton", command=window.destroy).pack(side="right", padx=5, pady=10)
  
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

def update_groups_listbox():
    if groups_listbox:
        groups_listbox.delete(0, tk.END)
        for group in ACTION_GROUPS:
            groups_listbox.insert(tk.END, group["name"])
        update_group_combobox()
        
def clear_all_completed():
    """Xóa tất cả job đã chạy xong (không lặp lại lẫn lặp lại)"""
    global jobs
    try:
        # Lấy mọi job không còn ở trạng thái "Đã hẹn" (tức đã chạy xong/đã hủy...)
        to_remove = [
            j for j in jobs
            if j.status != "Đã hẹn"
        ]

        if not to_remove:
            messagebox.showinfo("Thông báo", "Không có job nào đã chạy xong để xóa.")
            return

        removed_count = 0
        for job in to_remove:
            if job in jobs:
                try:
                    unregister_job(job)
                    jobs.remove(job)
                    removed_count += 1
                    logger.info(f"[CLEAR] Đã xóa job: {job}")
                except Exception as e:
                    logger.error(f"Lỗi khi xóa job: {e}")

        # Cập nhật lại GUI và lưu file
        update_jobs_list()
        save_jobs()

        logger.info(f"[CLEAR] Tổng cộng đã xóa {removed_count} job đã chạy xong.")
        messagebox.showinfo(
            "Thành công",
            f"Đã xóa {removed_count} job đã hoàn thành.\n"
            f"Đã lưu thay đổi vào scheduled_jobs.json."
        )

    except Exception as e:
        logger.error(f"Lỗi trong clear_all_completed: {e}")
        messagebox.showerror("Lỗi", f"Không thể xóa job đã chạy xong:\n{str(e)}")

def create_gui():
    global var_dict, record_line_var, schedule_time_var, key_input_var, group_var, group_combo
    global delay_time_var, subtract_time_var, repeat_interval_var, schedule_list_frame, root, default_status_label
    global pause_button
    global canvas, scrollable_frame
    
    load_action_groups()
    load_jobs()
    
  
    root = tk.Tk()
    filename = os.path.basename(sys.argv[0]) if sys.argv else "unknown.py"
    root.title(f"LDPlayer Multi-Launcher + Script Clicker ({filename})")
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    root.minsize(720, 520)
    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Áp theme dùng chung cho cả cửa sổ chính lẫn mọi cửa sổ con mở sau này
    apply_theme(root)
    try:
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
    except Exception:
        pass  # bỏ qua nếu hệ điều hành không hỗ trợ .ico (vd: Linux/macOS)

    outer_frame = ttk.Frame(root)
    outer_frame.pack(fill="both", expand=True)

    header = ttk.Frame(outer_frame, padding=(14, 12, 14, 8))
    header.pack(fill="x")
    ttk.Label(header, text="🎮 LDPlayer Multi-Launcher", font=FONT_HEADER).pack(anchor="w")
    ttk.Label(header, text="Điều khiển & lên lịch cho nhiều giả lập LDPlayer",
              font=FONT_SMALL, foreground="#6B7280").pack(anchor="w")
    ttk.Separator(outer_frame, orient="horizontal").pack(fill="x")

    main_frame = ttk.Frame(outer_frame, padding=10)
    main_frame.pack(fill="both", expand=True)

    # Ô tuỳ chỉnh kích thước cửa sổ
    size_frame = ttk.LabelFrame(main_frame, text="Kích thước cửa sổ")
    size_frame.pack(fill="x", pady=5)
    win_width_var = tk.IntVar(value=WINDOW_WIDTH)
    win_height_var = tk.IntVar(value=WINDOW_HEIGHT)
    size_row = ttk.Frame(size_frame)
    size_row.pack(fill="x", padx=5, pady=4)
    ttk.Label(size_row, text="Rộng:").pack(side="left")
    ttk.Entry(size_row, textvariable=win_width_var, width=7).pack(side="left", padx=4)
    ttk.Label(size_row, text="Cao:").pack(side="left")
    ttk.Entry(size_row, textvariable=win_height_var, width=7).pack(side="left", padx=4)

    def apply_window_size():
        w = max(400, win_width_var.get())
        h = max(300, win_height_var.get())
        root.geometry(f"{w}x{h}")

    def save_window_size():
        w = max(400, win_width_var.get())
        h = max(300, win_height_var.get())
        root.geometry(f"{w}x{h}")
        config_data = {}
        if os.path.exists("config.json"):
            try:
                with open("config.json", 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                print(f"[CONFIG] Lỗi đọc config.json cũ: {e}. Tạo mới.")
                config_data = {}
        config_data['WINDOW_WIDTH'] = w
        config_data['WINDOW_HEIGHT'] = h
        try:
            with open("config.json", 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            messagebox.showinfo("Thông báo", f"Đã lưu kích thước cửa sổ mặc định: {w}x{h}")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không lưu được config.json: {e}")

    ttk.Button(size_row, text="Áp dụng", command=apply_window_size).pack(side="left", padx=8)
    ttk.Button(size_row, text="Lưu làm mặc định", command=save_window_size).pack(side="left")
    
        # Ô chọn và lưu đường dẫn ldconsole.exe
    path_frame = ttk.LabelFrame(main_frame, text="Đường dẫn ldconsole.exe (lưu rồi reset để update)")
    path_frame.pack(fill="x", pady=5)
    
    ld_path_var = tk.StringVar(value=LD_CONSOLE_PATH or "Chưa chọn")
    
    ttk.Label(path_frame, text="Đường dẫn hiện tại:").pack(side="left", padx=5)
    ttk.Entry(path_frame, textvariable=ld_path_var, width=30).pack(side="left", padx=5, fill="x", expand=True)
    
    def browse_ld_path():
        file_path = filedialog.askopenfilename(
            title="Chọn ldconsole.exe",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
            initialdir=os.path.dirname(LD_CONSOLE_PATH) if LD_CONSOLE_PATH else os.getcwd()
        )
        if file_path:
            ld_path_var.set(file_path)
    
    ttk.Button(path_frame, text="Chọn file", command=browse_ld_path).pack(side="left", padx=5)
    
    def save_ld_path():
        new_path = ld_path_var.get().strip()
        if new_path:
            # Đọc file config.json cũ (nếu có)
            config_data = {}
            if os.path.exists("config.json"):
                try:
                    with open("config.json", 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                except Exception as e:
                    print(f"[CONFIG] Lỗi đọc config.json cũ: {e}. Tạo mới.")
                    config_data = {}
            
            # Cập nhật chỉ LD_CONSOLE_PATH, giữ nguyên các biến khác
            config_data['LD_CONSOLE_PATH'] = new_path
            
            # Lưu lại toàn bộ
            try:
                with open("config.json", 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=4)
                messagebox.showinfo("Thông báo", f"Đã lưu đường dẫn '{new_path}' vào config.json.\nCác biến offset giữ nguyên.\nReset chương trình để update danh sách giả lập.")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không lưu được config.json: {e}")
        else:
            messagebox.showwarning("Lỗi", "Đường dẫn không được để trống!")   
    
    ttk.Button(path_frame, text="Lưu", command=save_ld_path).pack(side="right", padx=5)

    # Hàng riêng: 2 nút mở tool record (tách khỏi path_frame để dễ bấm)
    record_tools_frame = ttk.Frame(main_frame)
    record_tools_frame.pack(fill="x", pady=(0, 5))
    ttk.Button(record_tools_frame, text="Chạy record",
               command=lambda: open_record_runner_window(root, list(var_dict.keys()))
               ).pack(side="left", expand=True, fill="x", padx=(0, 5))
    ttk.Button(record_tools_frame, text="Tính h recoder",
               command=lambda: open_record_duration_window(root)
               ).pack(side="left", expand=True, fill="x", padx=(5, 0))

    emulator_frame = ttk.LabelFrame(main_frame, text="Chọn các giả lập")
    emulator_frame.pack(fill="x", pady=5)

    instances = get_instances()
    var_dict = {}

    inst_row = ttk.Frame(emulator_frame)
    inst_row.pack(fill="x", pady=(4, 2))
    for name in instances:
        var = tk.BooleanVar()
        ttk.Checkbutton(inst_row, text=name, variable=var).pack(side="left", padx=5)
        var_dict[name] = var

    inst_btn_frame = ttk.Frame(emulator_frame)
    inst_btn_frame.pack(fill="x", pady=(2, 4))
    ttk.Button(inst_btn_frame, text="Khởi", width=5, command=launch_selected).pack(side="left", padx=2)
    ttk.Button(inst_btn_frame, text="Đóng", width=5, style="Danger.TButton", command=close_selected).pack(side="left", padx=2)
    ttk.Button(inst_btn_frame, text="OpRec", width=5, command=open_operation_recorder).pack(side="left", padx=2)
    ttk.Button(inst_btn_frame, text="Lên", width=5, command=bring_to_front).pack(side="left", padx=2)
  
    record_frame = ttk.Frame(main_frame)
    record_frame.pack(fill="x", pady=10)
    ttk.Label(record_frame, text="Chạy dòng số (VD: 1, 2, 3...):").pack(anchor="w")
    record_line_var = tk.StringVar()
    tk.Entry(record_frame, textvariable=record_line_var).pack(fill="x")
  
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill="x", pady=5)
    ttk.Button(button_frame, text="Đặt giờ chạy", command=set_schedule).pack(side="left", expand=True, fill="x", padx=(0, 5))
    ttk.Button(button_frame, text="Chạy ngay", style="Success.TButton", command=run_now).pack(side="right", expand=True, fill="x", padx=(5, 0))
  
    schedule_time_frame = ttk.Frame(main_frame)
    schedule_time_frame.pack(fill="x", pady=10)
    ttk.Label(schedule_time_frame, text="Giờ chạy (HHMM hoặc HH:MM):").pack(anchor="w")
    schedule_time_var = tk.StringVar()
    tk.Entry(schedule_time_frame, textvariable=schedule_time_var).pack(fill="x")
  
    calc_frame = ttk.Frame(schedule_time_frame)
    calc_frame.pack(fill="x", pady=(5, 0))
    ttk.Label(calc_frame, text="Giờ chờ (HH:MM):").pack(side="left")
    delay_time_var = tk.StringVar()
    ttk.Entry(calc_frame, textvariable=delay_time_var, width=10).pack(side="left", padx=5)
    ttk.Label(calc_frame, text="Giờ trừ (HH:MM):").pack(side="left")
    subtract_time_var = tk.StringVar()
    ttk.Entry(calc_frame, textvariable=subtract_time_var, width=10).pack(side="left", padx=5)
    ttk.Button(calc_frame, text="Tính giờ", command=calculate_time).pack(side="left")
  
    schedule_button_frame = ttk.Frame(schedule_time_frame)
    schedule_button_frame.pack(fill="x", pady=(5, 0))
    ttk.Button(schedule_button_frame, text="Hẹn thông báo", command=set_notification_schedule).pack(side="left", expand=True, fill="x", padx=(0, 5))
    ttk.Button(schedule_button_frame, text="Hẹn khởi động", command=set_launch_schedule).pack(side="left", expand=True, fill="x", padx=(0, 5))
    ttk.Button(schedule_button_frame, text="Hẹn tắt", command=set_quit_schedule).pack(side="left", expand=True, fill="x", padx=(0, 5))
  
    group_frame = ttk.Frame(main_frame)
    group_frame.pack(fill="x", pady=10)
    ttk.Label(group_frame, text="Chọn nhóm hành động:").pack(anchor="w")
    group_var = tk.StringVar()
    group_combo = ttk.Combobox(group_frame, textvariable=group_var, values=[g["name"] for g in ACTION_GROUPS], state="readonly")
  
    update_group_combobox()
    group_combo.pack(fill="x")
  
    # MỚI: Ô nhập khoảng lặp lại
    repeat_frame = ttk.Frame(group_frame)
    repeat_frame.pack(fill="x", pady=5)
    ttk.Label(repeat_frame, text="Tự động lặp lại sau (HH:MM):").pack(side="left")
    repeat_interval_var = tk.StringVar(value="00:00")  # mặc định không lặp
    ttk.Entry(repeat_frame, textvariable=repeat_interval_var, width=10).pack(side="left", padx=5)
    ttk.Label(repeat_frame, text="(để trống hoặc 00:00 để không lặp)").pack(side="left")
  
    button_container = ttk.Frame(group_frame)
    button_container.pack(fill="x", pady=5)
   
    ttk.Button(button_container, text="Chạy ngay", style="Success.TButton", command=run_group_now).pack(side="left", expand=True, fill="x", padx=5)
    ttk.Button(button_container, text="Đặt giờ nhóm", command=set_group_schedule).pack(side="left", expand=True, fill="x", padx=5)
    ttk.Button(button_container, text="Quản lý nhóm", command=manage_groups).pack(side="left", expand=True, fill="x", padx=5)
    ttk.Button(button_container, text="Đặt làm mặc định", command=set_default_group).pack(side="left", expand=True, fill="x", padx=5)
    ttk.Button(button_container, text="Xóa mặc định", style="Danger.TButton", command=clear_default_group).pack(side="left", expand=True, fill="x", padx=5)
   
    default_status_label = ttk.Label(group_frame, text="Chưa có nhóm mặc định")
    default_status_label.pack(anchor="w", pady=(5, 0))
    update_default_label()
  
    key_frame = ttk.Frame(main_frame)
    key_frame.pack(fill="x", pady=10)
    ttk.Label(key_frame, text="Phím cần gửi (VD: a, ctrl+8, alt+ctrl+9):").pack(anchor="w")
    key_input_var = tk.StringVar()
    tk.Entry(key_frame, textvariable=key_input_var).pack(fill="x")
  
    key_button_frame = ttk.Frame(key_frame)
    key_button_frame.pack(fill="x", pady=(5, 0))
    ttk.Button(key_button_frame, text="Đặt giờ gửi phím", command=set_key_schedule).pack(side="left", expand=True, fill="x", padx=(0, 5))
    ttk.Button(key_button_frame, text="Gửi phím ngay", style="Success.TButton", command=run_key_now).pack(side="right", expand=True, fill="x", padx=(5, 0))
  
        # ==================== DANH SÁCH CÔNG VIỆC HẸN GIỜ ====================
    jobs_list_frame = ttk.LabelFrame(main_frame, text="Danh sách công việc hẹn giờ")
    jobs_list_frame.pack(fill="both", expand=True, pady=10)

    # === PHẦN 1: Khu vực có thể cuộn ===
    scroll_frame = ttk.Frame(jobs_list_frame)
    scroll_frame.pack(fill="both", expand=True, padx=5, pady=(5, 0))

    canvas = tk.Canvas(scroll_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
    
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Ép scrollable_frame luôn rộng bằng canvas, để các nút căn phải (sticky="e")
    # dính sát mép phải cửa sổ và tự chạy theo khi kéo giãn/thu nhỏ cửa sổ.
    _canvas_window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

    def _on_canvas_configure(event, canvas=canvas, win_id=_canvas_window_id):
        canvas.itemconfig(win_id, width=event.width)

    canvas.bind("<Configure>", _on_canvas_configure)

    # Gán biến toàn cục để update_jobs_list() dùng
    global schedule_list_frame
    schedule_list_frame = scrollable_frame

    # Cuộn bằng chuột
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    # === PHẦN 2: 3 NÚT CỐ ĐỊNH Ở DƯỚI (KHÔNG BỊ CUỘN) ===
    button_frame = ttk.Frame(jobs_list_frame, padding=(0, 8, 0, 5))
    button_frame.pack(fill="x", padx=5)

    ttk.Button(button_frame, text="Hẹn lại tất cả", 
               command=reschedule_all).pack(side="left", expand=True, fill="x", padx=(0, 5))
    
    global pause_button
    pause_button = ttk.Button(button_frame, text="Tạm dừng", command=toggle_pause)
    pause_button.pack(side="left", expand=True, fill="x", padx=5)
    
    ttk.Button(button_frame, text="Xoá tất cả đã chạy xong",
               command=clear_all_completed).pack(side="left", expand=True, fill="x", padx=(5, 0))

    # Bind chuột cuộn cho canvas
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    

    
    key_sender.start()  # Khởi động worker gửi phím tuần tự
    # Đăng ký tất cả job đã load vào APScheduler (thay thế scheduled_checker thread)
    for job in jobs:
        if job.status == "Đã hẹn":
            register_job(job, update_jobs_list, save_jobs)
    update_jobs_list()
    root.mainloop()

def on_closing():
    global is_running, root
    is_running = False
    shutdown_scheduler()
    key_sender.stop()
    try:
        if root and root.winfo_exists():
            root.quit()
            root.destroy()
    except:
        pass
    save_jobs()
    save_action_groups()
    print("[LOG] Chương trình đã dừng hoàn toàn")

if __name__ == "__main__":
    create_gui()