# executor.py

import traceback
import threading
import time

import win32gui
import win32con

import key_sender
from ldconsole import launch_instance, quit_instance
from recorder import run_record_line
from action_groups import ACTION_GROUPS
from utils import auto_close_messagebox, move_operation_recorder_window, close_operation_recorder
from utils import run_default_group_if_exists
from logger import get_logger

logger = get_logger()


# ─────────────────────────────────────────────────────────────
# Tìm hwnd
# ─────────────────────────────────────────────────────────────

def _find_hwnd(instance_name: str) -> int | None:
    """Tìm hwnd LDPlayer theo tên instance, ưu tiên exact match."""
    found = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if instance_name.lower() in title.lower():
                found.append((hwnd, title))

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as e:
        logger.error(f"[HWND] EnumWindows lỗi: {e}")

    if not found:
        logger.warning(f"[HWND] Không tìm thấy cửa sổ cho '{instance_name}'")
        return None

    # Exact match trước
    for hwnd, title in found:
        if title.strip() == instance_name.strip():
            return hwnd
    return found[0][0]


# ─────────────────────────────────────────────────────────────
# Gửi phím — qua key_sender worker (tuần tự, không tranh nhau)
# ─────────────────────────────────────────────────────────────

def send_key_to_ldplayer(instance_name: str, key: str,
                         retries: int = 3) -> bool:
    """
    Gửi phím đến LDPlayer qua key_sender worker.
    Tuần tự — không bao giờ 2 giả lập tranh foreground cùng lúc.
    """
    hwnd = _find_hwnd(instance_name)
    if not hwnd:
        logger.error(f"[KEY] Không tìm thấy cửa sổ '{instance_name}'")
        return False

    return key_sender.send_key(
        instance_name=instance_name,
        hwnd=hwnd,
        key=key,
        timeout=5.0,
        retries=retries,
    )


def run_key_press(instance_name: str, key: str) -> bool:
    """Wrapper tương thích ngược."""
    return send_key_to_ldplayer(instance_name, key)


# ─────────────────────────────────────────────────────────────
# Wrapper an toàn
# ─────────────────────────────────────────────────────────────

def safe_execute(func, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
        return result if result is not None else True
    except Exception as e:
        logger.error(f"[SAFE] Lỗi trong {func.__name__}: {e}\n{traceback.format_exc()}")
        return False


# ─────────────────────────────────────────────────────────────
# Thực thi job đơn
# ─────────────────────────────────────────────────────────────

def execute_single_job(job) -> bool:
    try:
        logger.info(f"[EXEC] Bắt đầu: {job}")

        if job.job_type == "record":
            success = safe_execute(run_record_line, job.instance, int(job.value))

        elif job.job_type == "key":
            success = send_key_to_ldplayer(job.instance, job.value, retries=3)

        elif job.job_type == "launch":
            success = safe_execute(launch_instance, job.instance)

        elif job.job_type == "quit":
            success = safe_execute(quit_instance, job.instance)

        elif job.job_type == "notification":
            auto_close_messagebox("info", "Thông báo", f"Đã đến giờ {job.time_str[:-3]}")
            success = True

        else:
            logger.warning(f"[EXEC] Loại job không hỗ trợ: {job.job_type}")
            success = False

        job.status = "Đã chạy" if success else "Lỗi"
        logger.info(f"[EXEC] Kết thúc {job.job_type} trên '{job.instance}' → {job.status}")
        return success

    except Exception as e:
        logger.error(f"[EXEC] Lỗi nghiêm trọng job {job}: {e}\n{traceback.format_exc()}")
        job.status = "Lỗi"
        return False


# ─────────────────────────────────────────────────────────────
# Chạy danh sách action của 1 nhóm
# ─────────────────────────────────────────────────────────────

def run_group_actions(instance: str, actions: list,
                      visited: set = None, group_name: str = "",
                      parent_instance: str = "") -> bool:
    if visited is None:
        visited = set()

    logger.info(
        f"[GROUP] Bắt đầu nhóm '{group_name}' trên '{instance}' "
        f"({len(actions)} hành động)"
    )
    had_error = False

    for idx, action in enumerate(actions, 1):
        if not isinstance(action, dict):
            logger.error(f"[GROUP] Action {idx} không phải dict: {action}")
            continue

        action_type = action.get("type")
        value       = action.get("value")
        delay       = action.get("delay", 0)

        logger.debug(
            f"[GROUP] Action {idx}/{len(actions)}: "
            f"{action_type} = {value!r} (delay {delay}s)"
        )

        try:
            if action_type == "group":
                if value in visited:
                    logger.warning(f"[GROUP] Vòng lặp nhóm, bỏ qua: {value}")
                    continue
                sub = next((g for g in ACTION_GROUPS if g["name"] == value), None)
                if not sub:
                    logger.warning(f"[GROUP] Sub-group '{value}' không tồn tại")
                    had_error = True
                else:
                    visited.add(value)
                    run_group_actions(instance, sub["actions"], visited, value, instance)
                    visited.discard(value)

            elif action_type == "record":
                if not safe_execute(run_record_line, instance, int(value)):
                    had_error = True

            elif action_type == "key":
                # Gửi qua worker — tuần tự, không tranh foreground
                if not send_key_to_ldplayer(instance, value, retries=3):
                    had_error = True

            elif action_type == "launch":
                if not safe_execute(launch_instance, instance):
                    had_error = True

            elif action_type == "quit":
                if not safe_execute(quit_instance, instance):
                    had_error = True

            else:
                logger.warning(f"[GROUP] Loại action không hỗ trợ: {action_type}")

        except Exception as e:
            logger.error(
                f"[GROUP] Lỗi action {idx} ('{action_type}') "
                f"trong '{group_name}': {e}"
            )
            had_error = True

        # Delay giữa các action — chỉ cần sleep vì delay đã được neo
        # vào scheduled_time từ scheduler, không bị ảnh hưởng bởi
        # thời gian xử lý trong worker.
        if delay > 0:
            time.sleep(delay)

    status = "có lỗi nhỏ" if had_error else "✓"
    logger.info(f"[GROUP] Hoàn thành '{group_name}' trên '{instance}' ({status})")
    return not had_error
