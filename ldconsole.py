# ldconsole.py
import subprocess
import os
import time
from config import LD_CONSOLE_PATH
from utils import auto_close_messagebox
from logger import get_logger

logger = get_logger()

def get_instances():
    """Lấy danh sách tất cả LDPlayer instances"""
    if not os.path.exists(LD_CONSOLE_PATH):
        logger.error(f"Không tìm thấy ldconsole.exe: {LD_CONSOLE_PATH}")
        auto_close_messagebox("error", "Lỗi", f"Không tìm thấy ldconsole.exe\n{LD_CONSOLE_PATH}")
        return []
    try:
        out = subprocess.check_output([LD_CONSOLE_PATH, "list2"], stderr=subprocess.STDOUT, timeout=10)
        lines = out.decode('utf-8', errors='ignore').splitlines()
        names = [p.split(',')[1].strip() for p in lines if len(p.split(',')) >= 2 and p.split(',')[1].strip()]
        logger.info(f"[LD] Lấy danh sách instances thành công: {names}")
        return names
    except subprocess.TimeoutExpired:
        logger.error("[LD] Timeout khi lấy danh sách instances")
        auto_close_messagebox("error", "Lỗi", "Timeout khi lấy danh sách giả lập")
        return []
    except Exception as e:
        logger.error(f"[LD] Lỗi lấy danh sách instances: {e}")
        auto_close_messagebox("error", "Lỗi", f"Không lấy được danh sách giả lập:\n{e}")
        return []

def launch_instance(name):
    """Khởi động một LDPlayer instance"""
    try:
        logger.info(f"[LD] Khởi động instance: {name}")
        subprocess.Popen([LD_CONSOLE_PATH, "launch", "--name", name], 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        logger.info(f"[LD] Lệnh khởi động '{name}' đã gửi thành công")
        return True
    except Exception as e:
        logger.error(f"[LD] Lỗi khởi động instance '{name}': {e}")
        return False

def quit_instance(name):
    """Tắt một LDPlayer instance"""
    try:
        logger.info(f"[LD] Tắt instance: {name}")
        subprocess.Popen([LD_CONSOLE_PATH, "quit", "--name", name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        logger.info(f"[LD] Lệnh tắt '{name}' đã gửi thành công")
        return True
    except Exception as e:
        logger.error(f"[LD] Lỗi tắt instance '{name}': {e}")
        return False
