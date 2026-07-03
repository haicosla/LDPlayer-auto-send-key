# job.py - Quản lý Job (công việc hẹn giờ, hỗ trợ nhóm lồng nhau)
from datetime import datetime, timedelta
import json
import os
from config import JOBS_FILE
from utils import auto_close_messagebox

jobs = []  # Danh sách toàn cục các job

class Job:
    def __init__(self, time_str, instance, job_type=None, value=None, group_name=None,
                 is_group=False, group_jobs=None, status="Đã hẹn", scheduled_time=None):
        self.time_str = time_str
        self.instance = instance
        self.job_type = job_type
        self.value = value
        self.group_name = group_name
        self.is_group = is_group
        self.group_jobs = group_jobs or []
        self.status = status
        self.current_child_index = 0 if is_group else None
        self.should_stop = False
        self.is_repeating = False
        self.repeat_interval = 0
        self.origin_time = None  # Giờ gốc tuyệt đối, truyền xuyên suốt chuỗi lặp

        if scheduled_time is not None:
            # Caller đã tính sẵn scheduled_time (vd: child job trong nhóm,
            # job lặp từ scheduler) → dùng luôn, không gọi update_scheduled_time()
            # để tránh bị nhảy sang ngày mai khi giờ đó đã qua.
            self.scheduled_time = scheduled_time
        else:
            self.scheduled_time = None
            self.update_scheduled_time()

    def update_scheduled_time(self):
        """Cập nhật thời gian thực thi dự kiến từ time_str"""
        if not self.time_str:
            self.scheduled_time = None
            return
        try:
            now = datetime.now()
            job_time = datetime.strptime(self.time_str, "%H:%M:%S").replace(
                year=now.year, month=now.month, day=now.day
            )
            if job_time < now:
                job_time += timedelta(days=1)
            self.scheduled_time = job_time
            print(f"[JOB] Cập nhật scheduled_time cho job {self.time_str} - {self.instance}: {self.scheduled_time}")
        except ValueError as e:
            print(f"[JOB] Lỗi parse time_str '{self.time_str}' cho {self.instance}: {e}")
            self.scheduled_time = None

    def to_dict(self):
        return {
            'time_str': self.time_str,
            'instance': self.instance,
            'job_type': self.job_type,
            'value': self.value,
            'group_name': self.group_name,
            'is_group': self.is_group,
            'group_jobs': [job.to_dict() for job in self.group_jobs] if self.group_jobs else [],
            'status': self.status,
            'current_child_index': self.current_child_index,
            'is_repeating': getattr(self, 'is_repeating', False),
            'repeat_interval': getattr(self, 'repeat_interval', 0),
            'origin_time': self.origin_time.isoformat() if getattr(self, 'origin_time', None) else None,
        }

    @classmethod
    def from_dict(cls, data):
        job = cls(
            time_str=data['time_str'],
            instance=data['instance'],
            job_type=data.get('job_type'),
            value=data.get('value'),
            group_name=data.get('group_name'),
            is_group=data.get('is_group', False),
            group_jobs=[cls.from_dict(j) for j in data.get('group_jobs', [])],
            status=data.get('status', 'Đã hẹn')
        )
        job.current_child_index = data.get('current_child_index', 0)
        job.is_repeating = data.get('is_repeating', False)
        job.repeat_interval = data.get('repeat_interval', 0)
        # Restore origin_time nếu có (tránh drift sau nhiều ngày lặp)
        origin_raw = data.get('origin_time')
        job.origin_time = datetime.fromisoformat(origin_raw) if origin_raw else None
        job.update_scheduled_time()
        return job

    def __str__(self):
        display_time = self.time_str[:-3] if self.time_str else self.time_str
        job_date = self.scheduled_time.strftime('%d/%m') if self.scheduled_time else datetime.now().strftime('%d/%m')
        
        repeat_info = ""
        if hasattr(self, 'is_repeating') and self.is_repeating:
            hours = self.repeat_interval // 3600
            mins = (self.repeat_interval % 3600) // 60
            repeat_info = f" (Lặp mỗi {hours}h {mins}m)"
        
        if self.is_group:
            return f"[{self.status}] {display_time} - {job_date} - {self.instance} - Nhóm: {self.group_name}{repeat_info}"
        if self.job_type == "record":
            group_info = f" (Nhóm: {self.group_name})" if self.group_name else ""
            return f"[{self.status}] {display_time} - {job_date} - {self.instance} - dòng {self.value}{group_info}{repeat_info}"
        elif self.job_type == "key":
            group_info = f" (Nhóm: {self.group_name})" if self.group_name else ""
            return f"[{self.status}] {display_time} - {job_date} - {self.instance} - phím: {self.value}{group_info}{repeat_info}"
        elif self.job_type == "launch":
            group_info = f" (Nhóm: {self.group_name})" if self.group_name else ""
            return f"[{self.status}] {display_time} - {job_date} - {self.instance} - Khởi động giả lập{group_info}{repeat_info}"
        elif self.job_type == "quit":
            group_info = f" (Nhóm: {self.group_name})" if self.group_name else ""
            return f"[{self.status}] {display_time} - {job_date} - {self.instance} - Tắt giả lập{group_info}{repeat_info}"
        else:
            return f"[{self.status}] {display_time} - {job_date} - Thông báo{repeat_info}"
            
def load_jobs():
    """Tải danh sách job từ file JSON"""
    global jobs
    jobs.clear()
    if not os.path.exists(JOBS_FILE):
        print(f"[LOAD] File {JOBS_FILE} chưa tồn tại, khởi tạo danh sách rỗng")
        return
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
            for item in saved_data:
                job = Job.from_dict(item)
                jobs.append(job)
        print(f"[LOAD] Đã tải {len(jobs)} job từ file {JOBS_FILE}")
    except json.JSONDecodeError as e:
        print(f"[LOAD] File {JOBS_FILE} bị hỏng (JSON lỗi): {e}")
        auto_close_messagebox("error", "Lỗi", f"File scheduled_jobs.json bị hỏng: {e}")
    except Exception as e:
        print(f"[LOAD] Lỗi tải file {JOBS_FILE}: {e}")
        auto_close_messagebox("error", "Lỗi", f"Không thể tải danh sách hẹn giờ: {e}")

def save_jobs():
    """Lưu danh sách job vào file JSON"""
    try:
        saved_data = [job.to_dict() for job in jobs]
        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(saved_data, f, ensure_ascii=False, indent=4)
        print(f"[SAVE] Đã lưu {len(jobs)} job vào file {JOBS_FILE}")
    except Exception as e:
        print(f"[SAVE] Lỗi khi lưu file {JOBS_FILE}: {e}")
        auto_close_messagebox("error", "Lỗi", f"Không thể lưu danh sách hẹn giờ: {e}")

def update_group_jobs():
    """Cập nhật lại job con cho các nhóm khi cần (ví dụ khi load hoặc chỉnh sửa nhóm)"""
    from action_groups import ACTION_GROUPS  # import muộn để tránh circular
    now = datetime.now()
    updated_count = 0
    for job in jobs:
        if job.is_group and job.status == "Đã hẹn":
            group = next((g for g in ACTION_GROUPS if g["name"] == job.group_name), None)
            if group:
                start_time = datetime.strptime(job.time_str, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if start_time < now:
                    start_time += timedelta(days=1)
                group_jobs = []
                current_time = start_time
                for idx, action in enumerate(group["actions"], 1):
                    action_time = current_time
                    time_str = action_time.strftime("%H:%M:%S")
                    child_job = Job(time_str, job.instance, action["type"], action["value"], job.group_name)
                    group_jobs.append(child_job)
                    print(f"[JOB] Cập nhật job con {idx} cho nhóm {job.group_name} trên {job.instance}: {action['type']} - {action['value']} lúc {time_str}")
                    current_time += timedelta(seconds=action["delay"])
                job.group_jobs = group_jobs
                job.current_child_index = 0
                job.update_scheduled_time()
                updated_count += 1
    if updated_count > 0:
        save_jobs()
        print(f"[JOB] Đã cập nhật {updated_count} nhóm job con")