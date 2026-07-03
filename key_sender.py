# key_sender.py
# Worker thread duy nhất xử lý tuần tự việc gửi phím.
# Trước mỗi lần gửi: Ctrl+8 mở Operation Recorder → chờ 1s → đóng → focus lại.
# Cơ chế này đảm bảo LDPlayer luôn nhận được foreground trước khi nhận phím.

import queue
import threading
import time
import ctypes

import pyautogui
import win32api
import win32con
import win32gui
import win32process

from logger import get_logger

logger = get_logger()

# ─────────────────────────────────────────────────────────────
# Cấu hình — chỉnh tại đây nếu cần
# ─────────────────────────────────────────────────────────────

# Vị trí cửa sổ Operation Recorder (từ config.py)
try:
    from config import OPR_WINDOW_X, OPR_WINDOW_Y
except Exception:
    OPR_WINDOW_X, OPR_WINDOW_Y = 0, 0

# Thời gian chờ sau khi mở Ctrl+8 để Operation Recorder xuất hiện
OPR_OPEN_WAIT   = 1.0   # giây

# Thời gian chờ sau khi đóng Operation Recorder trước khi focus lại
OPR_CLOSE_WAIT  = 0.5   # giây

# Thời gian chờ sau focus trước khi gửi phím
FOCUS_SETTLE    = 0.15  # giây

# Delay sau khi gửi xong 1 phím, trước khi worker lấy task tiếp theo
POST_SEND_DELAY = 1.0   # giây

# ─────────────────────────────────────────────────────────────
# Queue + worker
# ─────────────────────────────────────────────────────────────

_queue: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None
_started = False
_lock = threading.Lock()
_STOP = object()


def start():
    """Khởi động worker. Gọi 1 lần khi app start."""
    global _worker, _started
    with _lock:
        if _started:
            return
        _worker = threading.Thread(
            target=_worker_loop,
            daemon=True,
            name="KeySenderWorker",
        )
        _worker.start()
        _started = True
        logger.info(f"[KEYSEND] Worker khởi động")


def stop():
    """Dừng worker sạch. Gọi khi app đóng."""
    global _started
    _queue.put(_STOP)
    _started = False
    logger.info("[KEYSEND] Worker đã dừng")


def send_key(instance_name: str, hwnd: int, key: str,
             timeout: float = 15.0, retries: int = 3) -> bool:
    """
    Gửi phím vào hwnd qua worker duy nhất — không tranh foreground.
    Trước khi gửi: mở/đóng Ctrl+8 để đảm bảo LDPlayer nhận foreground.
    Block cho đến khi worker xử lý xong hoặc timeout.

    timeout=15s vì OPR_OPEN_WAIT(1) + OPR_CLOSE_WAIT(0.5) + POST_SEND_DELAY(1)
    cộng thêm buffer cho retry.
    """
    if not _started:
        logger.warning("[KEYSEND] Worker chưa start, tự khởi động...")
        start()

    for attempt in range(1, retries + 1):
        result_box = [None]
        done_event = threading.Event()

        _queue.put({
            'instance': instance_name,
            'hwnd':     hwnd,
            'key':      key,
            'result':   result_box,
            'event':    done_event,
            'attempt':  attempt,
        })

        fired = done_event.wait(timeout=timeout)

        if not fired:
            logger.warning(
                f"[KEYSEND] Timeout '{key}' → '{instance_name}' "
                f"(lần {attempt}/{retries})"
            )
            continue

        if result_box[0]:
            return True

        if attempt < retries:
            logger.warning(
                f"[KEYSEND] Retry '{key}' → '{instance_name}' "
                f"(lần {attempt + 1}/{retries})"
            )
            time.sleep(0.5 * attempt)

    logger.error(
        f"[KEYSEND] Không gửi được '{key}' → '{instance_name}' "
        f"sau {retries} lần"
    )
    return False


# ─────────────────────────────────────────────────────────────
# Worker loop — tuần tự, 1 task tại 1 thời điểm
# ─────────────────────────────────────────────────────────────

def _worker_loop():
    logger.info("[KEYSEND] Worker bắt đầu lắng nghe queue")
    while True:
        task = _queue.get()

        if task is _STOP:
            logger.info("[KEYSEND] Worker nhận lệnh dừng")
            _queue.task_done()
            break

        instance = task['instance']
        hwnd     = task['hwnd']
        key      = task['key']
        result   = task['result']
        event    = task['event']
        attempt  = task['attempt']

        try:
            logger.debug(f"[KEYSEND] Xử lý: '{key}' → '{instance}' (lần {attempt})")

            _wake_focus_send(hwnd, key, instance)
            result[0] = True
            logger.info(f"[KEYSEND] ✓ '{key}' → '{instance}'")

        except Exception as e:
            result[0] = False
            logger.error(f"[KEYSEND] Lỗi '{key}' → '{instance}': {e}")

        finally:
            event.set()         # Unblock caller ngay
            _queue.task_done()

        # Delay sau gửi — chạy SAU event.set() để không block caller
        if POST_SEND_DELAY > 0:
            time.sleep(POST_SEND_DELAY)


# ─────────────────────────────────────────────────────────────
# Wake → Focus → Send
# ─────────────────────────────────────────────────────────────

def _wake_focus_send(hwnd: int, key: str, instance_name: str):
    """
    Quy trình chuẩn trước khi gửi phím (học từ file 57.py):
      1. Focus LDPlayer
      2. Ctrl+8 → mở Operation Recorder (đánh thức LDPlayer, lấy foreground chắc chắn)
      3. Di chuyển cửa sổ OPR ra góc cố định (không che game)
      4. Chờ 1s
      5. Đóng Operation Recorder
      6. Chờ 0.5s
      7. Focus lại LDPlayer
      8. Chờ settle
      9. Gửi phím
    """
    # ── Bước 1: Focus lần đầu ────────────────────────────────
    _silent_focus(hwnd)
    time.sleep(0.1)

    # ── Bước 2: Mở Operation Recorder ────────────────────────
    logger.debug(f"[KEYSEND] Ctrl+8 wake-up cho '{instance_name}'")
    pyautogui.hotkey('ctrl', '8')
    time.sleep(OPR_OPEN_WAIT)

    # ── Bước 3: Di chuyển cửa sổ OPR (nếu xuất hiện) ────────
    _move_opr_window()

    # ── Bước 4: Đóng OPR ─────────────────────────────────────
    _close_opr_window()
    time.sleep(OPR_CLOSE_WAIT)

    # ── Bước 5: Focus lại LDPlayer sau khi OPR đóng ──────────
    _silent_focus(hwnd)
    time.sleep(FOCUS_SETTLE)

    # ── Bước 6: Verify foreground ────────────────────────────
    fg = win32gui.GetForegroundWindow()
    if fg != hwnd:
        logger.debug(
            f"[KEYSEND] Chưa foreground sau wake-up "
            f"(fg={fg} hwnd={hwnd}), thử focus lần 2"
        )
        _silent_focus(hwnd)
        time.sleep(FOCUS_SETTLE)

    # ── Bước 7: Gửi phím ─────────────────────────────────────
    keys = [k.strip() for k in key.split('+')]
    if len(keys) > 1:
        pyautogui.hotkey(*keys)
    else:
        pyautogui.press(keys[0])


def _move_opr_window():
    """Di chuyển Operation Recorder ra vị trí cố định nếu đang mở."""
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd and hwnd != 0:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOP,
                OPR_WINDOW_X, OPR_WINDOW_Y,
                0, 0, win32con.SWP_NOSIZE
            )
    except Exception as e:
        logger.debug(f"[KEYSEND] _move_opr_window: {e}")


def _close_opr_window():
    """Đóng Operation Recorder."""
    try:
        hwnd = win32gui.FindWindow("LDOperationRecorderWindow", None)
        if hwnd and hwnd != 0:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception as e:
        logger.debug(f"[KEYSEND] _close_opr_window: {e}")


def _silent_focus(hwnd: int):
    """SetForegroundWindow qua ctypes (không raise exception) + AttachThreadInput."""
    _SFW = ctypes.windll.user32.SetForegroundWindow
    _BTT = ctypes.windll.user32.BringWindowToTop

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.15)

        cur_tid = win32api.GetCurrentThreadId()
        tgt_tid, tgt_pid = win32process.GetWindowThreadProcessId(hwnd)

        attached = False
        if cur_tid != tgt_tid:
            try:
                win32process.AttachThreadInput(cur_tid, tgt_tid, True)
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
                    win32process.AttachThreadInput(cur_tid, tgt_tid, False)
                except Exception:
                    pass

        if win32gui.GetForegroundWindow() != hwnd:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(tgt_pid)
                _SFW(hwnd)
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"[KEYSEND] _silent_focus lỗi nhỏ: {e}")
