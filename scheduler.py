# scheduler.py - Dùng APScheduler thay polling loop
# pip install apscheduler

import threading
import traceback
import queue
import itertools
import time as _time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from config import running_threads
from job import Job, jobs, save_jobs
from action_groups import ACTION_GROUPS
from executor import execute_single_job, run_group_actions
from logger import get_logger

logger = get_logger()

# ─────────────────────────────────────────────
# Khởi tạo APScheduler (1 instance dùng chung)
# ─────────────────────────────────────────────
_aps = BackgroundScheduler(
    executors={'default': ThreadPoolExecutor(20)},
    job_defaults={
        'misfire_grace_time': 60,   # bỏ qua nếu trễ quá 60s (vd: máy vừa wake)
        'coalesce': True,           # gộp lại nếu fire nhiều lần cùng lúc
    }
)
_aps.start()
logger.info("[SCHED] APScheduler đã khởi động")

# Theo dõi (instance, group_name) đang xếp hàng/đang chạy để chặn chồng lượt lặp
_running_group_keys: set = set()

# ─────────────────────────────────────────────
# HÀNG ĐỢI THỰC THI TOÀN CỤC (fix lỗi chồng chéo)
# ─────────────────────────────────────────────
# Vấn đề cũ: mỗi job đến giờ được chạy trong 1 thread riêng (qua
# ThreadPoolExecutor của APScheduler), nên 2 nhóm khác nhau hẹn giờ gần
# nhau (vd 11:00 và 11:01) sẽ CHẠY SONG SONG. Vì các thao tác thực tế
# (di chuột, click, focus cửa sổ Operation Recorder...) dùng chung 1 con
# trỏ chuột / 1 cửa sổ foreground của Windows, chạy song song sẽ giẫm
# chân nhau → sai thao tác, lỗi.
#
# Cách sửa: mọi job (đơn lẫn nhóm) khi đến giờ KHÔNG chạy ngay trong
# thread riêng nữa, mà chỉ được XẾP VÀO HÀNG ĐỢI (_exec_queue), sắp xếp
# theo scheduled_time. MỘT worker thread duy nhất (_executor_worker) lấy
# lần lượt từng job ra chạy — job nào tới giờ trước chạy trước và phải
# chạy XONG HẲN mới đến job tiếp theo, dù nhóm nào có tới giờ chen giữa.
_exec_queue = queue.PriorityQueue()
_seq_counter = itertools.count()
_current_job = None   # job đang thực sự chạy trong worker (None nếu đang rảnh)
_pause_event = threading.Event()
_pause_event.set()  # set() = KHÔNG tạm dừng (mặc định chạy bình thường)


def get_queue_status():
    """Trả về (job đang chạy hoặc None, số job còn đang xếp hàng chờ).
    Dùng để hiển thị trạng thái 'Đang chạy - ... (còn N job chờ)' trên GUI."""
    return _current_job, _exec_queue.qsize()


def _enqueue(scheduled_time, job, kind, update_ui_callback, save_jobs_callback):
    """Đưa 1 job vào hàng đợi thực thi, sắp theo scheduled_time (tới giờ trước chạy trước)."""
    when = scheduled_time or datetime.now()
    _exec_queue.put((when, next(_seq_counter), job, kind, update_ui_callback, save_jobs_callback))


def _executor_worker():
    """Worker DUY NHẤT chạy suốt vòng đời app — đảm bảo tại một thời điểm
    chỉ có đúng 1 job (đơn hoặc nhóm) đang thao tác lên máy ảo."""
    global _current_job
    while True:
        when, _, job, kind, update_ui_callback, save_jobs_callback = _exec_queue.get()

        # ── Cổng tạm dừng: nếu đang "Tạm dừng", đứng chờ ở đây, KHÔNG bắt
        # đầu job tiếp theo cho tới khi bấm "Tiếp tục". Job đang xếp hàng
        # vẫn nằm nguyên trong queue, không bị mất, chỉ là chưa tới lượt.
        if not _pause_event.is_set():
            job.status = "Tạm dừng - Đang chờ tiếp tục"
            if update_ui_callback:
                update_ui_callback()
            _pause_event.wait()

        _current_job = job
        try:
            if kind == 'group':
                _run_group_thread(job, update_ui_callback, save_jobs_callback)
            else:
                _run_single_job_body(job, update_ui_callback, save_jobs_callback)
        except Exception as e:
            logger.error(f"[SCHED] Lỗi trong worker thực thi hàng đợi: {e}\n{traceback.format_exc()}")
        finally:
            _current_job = None
            _exec_queue.task_done()
            if update_ui_callback:
                update_ui_callback()


_worker_thread = threading.Thread(target=_executor_worker, daemon=True, name="GlobalJobQueueWorker")
_worker_thread.start()
logger.info("[SCHED] Worker hàng đợi thực thi toàn cục đã khởi động")


# ─────────────────────────────────────────────
# API công khai
# ─────────────────────────────────────────────

def register_job(job, update_ui_callback=None, save_jobs_callback=None):
    """Đăng ký 1 Job vào APScheduler."""
    if job.scheduled_time is None:
        job.update_scheduled_time()
    if job.scheduled_time is None:
        logger.warning(f"[SCHED] Không đăng ký được job (scheduled_time is None): {job}")
        return

    job_id = f"job_{id(job)}"
    func   = _fire_group_job if job.is_group else _fire_single_job

    _aps.add_job(
        func=func,
        trigger='date',
        run_date=job.scheduled_time,
        args=[job, update_ui_callback, save_jobs_callback],
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        f"[SCHED] Đã đăng ký job '{job_id}' "
        f"lúc {job.scheduled_time.strftime('%d/%m %H:%M:%S')}: {job}"
    )


def unregister_job(job):
    """Hủy job khỏi APScheduler."""
    try:
        _aps.remove_job(f"job_{id(job)}")
        logger.info(f"[SCHED] Đã hủy job 'job_{id(job)}'")
    except Exception:
        pass


def pause_scheduler():
    _aps.pause()
    _pause_event.clear()
    logger.info("[SCHED] Tạm dừng APScheduler + hàng đợi thực thi")


def resume_scheduler():
    _aps.resume()
    _pause_event.set()
    logger.info("[SCHED] Tiếp tục APScheduler + hàng đợi thực thi")


def shutdown_scheduler():
    _aps.shutdown(wait=False)
    logger.info("[SCHED] Đã tắt APScheduler")


# ─────────────────────────────────────────────
# Internal: fire job đơn
# ─────────────────────────────────────────────

def _fire_single_job(job, update_ui_callback, save_jobs_callback):
    """APScheduler gọi đúng giờ → chỉ XẾP HÀNG, không chạy ngay (tránh chồng
    chéo với job khác đang/sắp chạy)."""
    logger.info(f"[SCHED] Job đơn đến giờ, xếp vào hàng đợi: {job}")
    job.status = "Đang chờ đến lượt"
    running_threads[job] = True
    _enqueue(job.scheduled_time, job, 'single', update_ui_callback, save_jobs_callback)
    if update_ui_callback:
        update_ui_callback()


def _run_single_job_body(job, update_ui_callback, save_jobs_callback):
    """Được worker gọi khi đến lượt job đơn này — thực thi thật sự."""
    logger.info(f"[SCHED] Đến lượt, chạy job đơn: {job}")
    job.status = "Đang chạy"
    if update_ui_callback:
        update_ui_callback()
    try:
        execute_single_job(job)
        job.status = "Đã chạy" if job.status != "Lỗi" else "Lỗi"
    except Exception as e:
        logger.error(f"[SCHED] Lỗi chạy job đơn: {e}\n{traceback.format_exc()}")
        job.status = "Lỗi"
    finally:
        running_threads.pop(job, None)
        _after_job(job, update_ui_callback, save_jobs_callback)


# ─────────────────────────────────────────────
# Internal: fire job nhóm
# ─────────────────────────────────────────────

def _fire_group_job(job, update_ui_callback, save_jobs_callback):
    """Được APScheduler gọi đúng giờ → chỉ XẾP HÀNG (không tự spawn thread
    chạy song song nữa), để đảm bảo nhóm nào tới giờ trước chạy xong hẳn
    rồi mới tới nhóm kế tiếp, dù 2 nhóm khác nhau hẹn giờ sát nhau."""
    logger.info(f"[SCHED] Nhóm đến giờ, xếp vào hàng đợi: {job}")

    key = (job.instance, job.group_name)
    if key in _running_group_keys:
        logger.warning(
            f"[SCHED] Nhóm '{job.group_name}' trên '{job.instance}' "
            f"đang chạy/đang chờ (lượt trước chưa xong) → bỏ qua, vẫn lên lịch lặp tiếp."
        )
        job.status = "Bỏ qua - Trùng lượt"
        _after_job(job, update_ui_callback, save_jobs_callback)
        if getattr(job, 'is_repeating', False) and not getattr(job, 'should_stop', False):
            _schedule_next_repeat(job, update_ui_callback, save_jobs_callback)
        return

    if job in running_threads:
        logger.warning(f"[SCHED] Job nhóm đã được xếp hàng/đang chạy, bỏ qua: {job}")
        return

    _running_group_keys.add(key)
    job.status = "Đang chờ đến lượt"
    running_threads[job] = True
    _enqueue(job.scheduled_time, job, 'group', update_ui_callback, save_jobs_callback)
    if update_ui_callback:
        update_ui_callback()


def run_job_now_via_queue(job, update_ui_callback=None, save_jobs_callback=None):
    """Dùng cho nút "Chạy" (chạy ngay) trên GUI.

    Trước đây nút này chạy trực tiếp trên luồng giao diện (kể cả
    time.sleep(delay) giữa các action) → job có delay dài sẽ TREO CỨNG cả
    cửa sổ, và có thể chạy đồng thời với 1 job khác đang được worker xử lý
    (chồng chéo thao tác chuột/bàn phím).

    Hàm này đưa job vào đúng hàng đợi thực thi chung (_exec_queue) thay vì
    chạy ngay tại chỗ: không treo giao diện, và luôn tôn trọng đúng 1 job
    chạy tại 1 thời điểm + tôn trọng trạng thái Tạm dừng.

    Trả về True nếu đã xếp hàng thành công, False nếu nhóm này đang
    chạy/đang chờ sẵn trong hàng đợi rồi (không thêm trùng).
    """
    if job.is_group:
        key = (job.instance, job.group_name)
        if key in _running_group_keys or job in running_threads:
            logger.warning(f"[SCHED] 'Chạy ngay' bỏ qua vì nhóm đang chạy/đang chờ: {job}")
            return False
        _running_group_keys.add(key)
        kind = 'group'
    else:
        if job in running_threads:
            logger.warning(f"[SCHED] 'Chạy ngay' bỏ qua vì job đang chạy/đang chờ: {job}")
            return False
        kind = 'single'

    logger.info(f"[SCHED] 'Chạy ngay' → xếp vào hàng đợi: {job}")
    # Ép mốc giờ về NGAY BÂY GIỜ — nếu không, với job nhóm còn hẹn ở tương
    # lai, logic tính giờ action con (max(job.scheduled_time, now())) sẽ
    # chờ tới đúng giờ hẹn gốc thay vì chạy ngay như người dùng bấm.
    job.scheduled_time = datetime.now()
    job.status = "Đang chờ đến lượt"
    running_threads[job] = True
    _enqueue(datetime.now(), job, kind, update_ui_callback, save_jobs_callback)
    if update_ui_callback:
        update_ui_callback()
    return True


# ─────────────────────────────────────────────
# Internal: thread chạy các action trong nhóm
# ─────────────────────────────────────────────

def _run_group_thread(job, update_ui_callback, save_jobs_callback):
    key = (job.instance, job.group_name)
    _running_group_keys.add(key)
    job.status = "Đang chạy"
    if update_ui_callback:
        update_ui_callback()
    try:
        logger.info(f"[SCHED] Đến lượt, bắt đầu chạy nhóm '{job.group_name}' trên {job.instance}")

        group = next((g for g in ACTION_GROUPS if g["name"] == job.group_name), None)
        if not group:
            job.status = "Lỗi - Nhóm không tồn tại"
            logger.error(f"Nhóm '{job.group_name}' không tồn tại")
            return

        job.group_jobs = []
        job.current_child_index = 0

        # ── Chạy nhóm mặc định TRƯỚC (blocking) ─────────────────────────
        # Đo thời gian để biết nhóm mặc định tốn bao lâu, dùng tính mốc delay.
        default_elapsed = 0.0
        default_start = datetime.now()
        try:
            from gui import default_group_name
        except Exception:
            default_group_name = None

        if default_group_name:
            try:
                from utils import run_default_group_if_exists
                run_default_group_if_exists(job.instance, default_group_name)
            except Exception as e:
                logger.warning(f"Không chạy được nhóm mặc định cho {job.instance}: {e}")
            default_elapsed = (datetime.now() - default_start).total_seconds()
            if default_elapsed > 1:
                logger.info(
                    f"[GROUP] Nhóm mặc định '{default_group_name}' tốn "
                    f"{default_elapsed:.1f}s trên '{job.instance}'"
                )

        # ── Tính mốc thời gian cho các action con ────────────────────────
        #
        # Nguyên tắc:
        #   - Nếu nhóm mặc định xong TRƯỚC giờ gốc → neo theo giờ gốc (lịch đều đặn).
        #   - Nếu nhóm mặc định chạy LÂU, vượt qua giờ gốc → neo theo now(),
        #     để delay giữa các action con vẫn được tôn trọng đầy đủ từ lúc này.
        #
        current_time = max(job.scheduled_time, datetime.now())

        for action in group["actions"]:
            child = Job(
                time_str=current_time.strftime("%H:%M:%S"),
                instance=job.instance,
                job_type=action["type"],
                value=action.get("value"),
                group_name=job.group_name,
                scheduled_time=current_time,  # truyền thẳng → không gọi update_scheduled_time()
            )
            job.group_jobs.append(child)
            current_time += timedelta(seconds=action.get("delay", 0))

        # ── Thực thi từng action con, đợi đúng giờ ───────────────────────
        while job.current_child_index < len(job.group_jobs):
            if getattr(job, 'should_stop', False):
                break

            child = job.group_jobs[job.current_child_index]

            # Chờ đến scheduled_time của action con
            if child.scheduled_time:
                while True:
                    if getattr(job, 'should_stop', False):
                        break
                    if not _pause_event.is_set():
                        # Đang tạm dừng: giữ nguyên tại đây (giữa 2 action, an
                        # toàn), không thao tác gì thêm cho tới khi tiếp tục.
                        job.status = "Tạm dừng - Đang chờ tiếp tục"
                        if update_ui_callback:
                            update_ui_callback()
                        _pause_event.wait(timeout=0.5)
                        continue
                    diff = (child.scheduled_time - datetime.now()).total_seconds()
                    if diff <= 0:
                        break
                    _time.sleep(min(diff, 0.5))

            if getattr(job, 'should_stop', False):
                break

            if job.status != "Đang chạy":
                job.status = "Đang chạy"
                if update_ui_callback:
                    update_ui_callback()

            logger.info(
                f"[GROUP] Thực thi {job.current_child_index + 1}/{len(job.group_jobs)}: "
                f"{child.job_type} - {child.value}"
            )

            if child.job_type == "group":
                sub_group = next((g for g in ACTION_GROUPS if g["name"] == child.value), None)
                if sub_group:
                    run_group_actions(child.instance, sub_group["actions"])
                child.status = "Đã chạy"
            else:
                success = execute_single_job(child)
                child.status = "Đã chạy" if success else "Lỗi"

            job.current_child_index += 1

        # ── Cập nhật trạng thái cuối ──────────────────────────────────────
        if getattr(job, 'should_stop', False):
            job.status = "Đã dừng"
        else:
            job.status = "Đã chạy"

        logger.info(f"[SCHED] Hoàn thành nhóm '{job.group_name}' trên {job.instance} → {job.status}")

        # ── Lên lịch lặp tiếp theo ────────────────────────────────────────
        if getattr(job, 'is_repeating', False) and not getattr(job, 'should_stop', False):
            _schedule_next_repeat(job, update_ui_callback, save_jobs_callback)

    except Exception as e:
        logger.error(
            f"[SCHED] Lỗi nghiêm trọng thread nhóm {job.group_name}: "
            f"{e}\n{traceback.format_exc()}"
        )
        job.status = "Lỗi"
    finally:
        _running_group_keys.discard(key)
        running_threads.pop(job, None)
        _after_job(job, update_ui_callback, save_jobs_callback)


# ─────────────────────────────────────────────
# Internal: tính và đăng ký lượt lặp kế tiếp
# ─────────────────────────────────────────────

def _schedule_next_repeat(job, update_ui_callback, save_jobs_callback):
    """
    Tính giờ lặp kế tiếp từ ORIGIN GỐC tuyệt đối, không phải scheduled_time
    của job hiện tại — tránh drift giây lẻ sau nhiều ngày lặp.

    Origin gốc được lưu trong job.origin_time (set lần đầu khi tạo job lặp).
    Nếu chưa có (job cũ, tương thích ngược) thì dùng job.scheduled_time làm origin.

    Ví dụ: origin 11:00:00, interval 3600s
      → lần 2: 12:00:00, lần 3: 13:00:00  (không bao giờ thành 12:00:01)
    """
    now      = datetime.now()
    interval = timedelta(seconds=job.repeat_interval)

    # origin_time: giờ gốc tuyệt đối, xuyên suốt chuỗi lặp
    origin = getattr(job, 'origin_time', None) or job.scheduled_time

    # Bước nhảy tối thiểu để next_time > now
    steps     = int((now - origin).total_seconds() / job.repeat_interval) + 1
    next_time = origin + interval * steps
    while next_time <= now:          # phòng rounding
        steps    += 1
        next_time = origin + interval * steps

    next_time_str = next_time.strftime("%H:%M:%S")

    new_job = Job(
        time_str=next_time_str,
        instance=job.instance,
        group_name=job.group_name,
        is_group=True,
        group_jobs=[],
        status="Đã hẹn",
        scheduled_time=next_time,   # truyền thẳng → không gọi update_scheduled_time()
    )
    new_job.is_repeating    = True
    new_job.repeat_interval = job.repeat_interval
    new_job.origin_time     = origin   # truyền origin gốc tuyệt đối xuyên suốt chuỗi lặp

    jobs.append(new_job)
    register_job(new_job, update_ui_callback, save_jobs_callback)

    logger.info(
        f"[SCHED] Job lặp tiếp theo: {new_job.group_name} @ {next_time_str} "
        f"(interval {job.repeat_interval}s, "
        f"origin gốc {origin.strftime('%d/%m %H:%M:%S')})"
    )

    if save_jobs_callback:
        save_jobs_callback()
    if update_ui_callback:
        update_ui_callback()


# ─────────────────────────────────────────────
# Internal: callback chung sau khi job xong
# ─────────────────────────────────────────────

def _after_job(job, update_ui_callback, save_jobs_callback):
    if update_ui_callback:
        update_ui_callback()
    if save_jobs_callback:
        save_jobs_callback()


# ─────────────────────────────────────────────
# Tương thích ngược
# ─────────────────────────────────────────────

def scheduled_checker(*args, **kwargs):
    """Deprecated — giữ để tránh ImportError."""
    logger.warning("[SCHED] scheduled_checker() đã deprecated. Dùng register_job().")


run_group_in_thread = _run_group_thread   # alias cũ
