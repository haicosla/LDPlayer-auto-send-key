# recorder.py
import pyautogui
import time
import win32gui
import win32con
from config import OPR_WINDOW_X, OPR_WINDOW_Y, OFFSET_X, OFFSET_Y, Y_STEP
from utils import focus_emulator, move_operation_recorder_window, close_operation_recorder, auto_close_messagebox
from ldconsole import launch_instance
from logger import get_logger

logger = get_logger()

def open_operation_recorder_for_instance(instance_name):
    """Mở Operation Recorder cho một instance"""
    if not focus_emulator(instance_name):
        logger.info(f"[REC] Không focus được {instance_name}, thử launch...")
        launch_instance(instance_name)
        time.sleep(12)  # đợi giả lập khởi động
        if not focus_emulator(instance_name):
            auto_close_messagebox("error", "Lỗi", f"Không thể focus giả lập: {instance_name}")
            return False
    
    pyautogui.hotkey('ctrl', '8')
    time.sleep(1.2)
    logger.info(f"[REC] Đã mở Operation Recorder cho {instance_name}")
    return True

def run_record_line(instance_name, line_number):
    """
    Chạy một dòng script từ Operation Recorder
    
    Args:
        instance_name: Tên giả lập
        line_number: Số dòng cần chạy (1-based)
    
    Returns:
        True nếu thành công, False nếu thất bại
    """
    logger.info(f"[REC] Bắt đầu chạy dòng {line_number} trên {instance_name}")
    
    try:
        # Đảm bảo giả lập đang chạy và focus
        if not focus_emulator(instance_name):
            logger.warning(f"[REC] Instance không focus, thử launch...")
            launch_instance(instance_name)
            time.sleep(12)
            if not focus_emulator(instance_name):
                logger.error(f"[REC] Không thể focus {instance_name} sau khi launch")
                auto_close_messagebox("error", "Lỗi", f"Không thể focus {instance_name}")
                return False
        
        # Mở recorder
        if not open_operation_recorder_for_instance(instance_name):
            logger.error(f"[REC] Không thể mở Operation Recorder cho {instance_name}")
            return False
        
        time.sleep(0.5)  # Đợi Recorder mở xong
        
        # Di chuyển cửa sổ Recorder
        if not move_operation_recorder_window():
            logger.error(f"[REC] Không tìm thấy cửa sổ Operation Recorder")
            close_operation_recorder()
            time.sleep(0.5)
            return False
        
        time.sleep(0.5)  # Đợi cửa sổ di chuyển xong
        
        # Tính tọa độ click
        click_x = OPR_WINDOW_X + OFFSET_X
        click_y = OPR_WINDOW_Y + OFFSET_Y + (line_number - 1) * Y_STEP
        
        logger.debug(f"[REC] Click tại ({click_x}, {click_y}) cho dòng {line_number}")
        
        # Click vào dòng
        pyautogui.moveTo(click_x, click_y, duration=0.3)
        time.sleep(0.2)
        pyautogui.click()
        time.sleep(1.0)  # Đợi script chạy xong
        
        logger.info(f"[REC] Script dòng {line_number} đã chạy xong")
        
        # Đóng recorder
        close_operation_recorder()
        time.sleep(1.0)
        
        # Focus lại giả lập để tiếp tục các hành động khác
        if not focus_emulator(instance_name):
            logger.warning(f"[REC] Cảnh báo: Không focus lại được {instance_name} sau khi chạy script")
        
        logger.info(f"[REC] Hoàn thành chạy dòng {line_number} trên {instance_name}")
        return True
        
    except Exception as e:
        logger.error(f"[REC] Lỗi khi chạy dòng {line_number} trên {instance_name}: {e}")
        try:
            close_operation_recorder()
        except:
            pass
        return False
