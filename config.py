import os
import json

# File cấu hình
CONFIG_FILE = "config.json"

# Mặc định nếu json không có hoặc thiếu key
LD_CONSOLE_PATH = r"c:/LDPlayer/LDPlayer9/ldconsole.exe"
OPR_WINDOW_X = 0
OPR_WINDOW_Y = 0
OFFSET_X = 940
OFFSET_Y = 250
Y_STEP = 76

# Kích thước cửa sổ mặc định
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 1600

# Load từ config.json nếu tồn tại
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
           
            # Load LD_CONSOLE_PATH nếu có
            saved_path = data.get('LD_CONSOLE_PATH', '')
            if saved_path and os.path.isfile(saved_path):
                LD_CONSOLE_PATH = saved_path
                print(f"[CONFIG] Load LD_CONSOLE_PATH thành công từ config.json: {LD_CONSOLE_PATH}")
            else:
                print("[CONFIG] LD_CONSOLE_PATH trong config.json không hợp lệ. Dùng mặc định.")
           
            # Load các biến vị trí cửa sổ nếu có
            if 'OPR_WINDOW_X' in data:
                OPR_WINDOW_X = data['OPR_WINDOW_X']
            if 'OPR_WINDOW_Y' in data:
                OPR_WINDOW_Y = data['OPR_WINDOW_Y']
            if 'OFFSET_X' in data:
                OFFSET_X = data['OFFSET_X']
            if 'OFFSET_Y' in data:
                OFFSET_Y = data['OFFSET_Y']
            if 'Y_STEP' in data:
                Y_STEP = data['Y_STEP']
            print("[CONFIG] Load các biến vị trí cửa sổ thành công từ config.json (nếu có key)")
           
            # Load kích thước cửa sổ nếu có (mặc định 900x1600 nếu thiếu)
            if 'WINDOW_WIDTH' in data and isinstance(data['WINDOW_WIDTH'], int) and data['WINDOW_WIDTH'] > 400:
                WINDOW_WIDTH = data['WINDOW_WIDTH']
            if 'WINDOW_HEIGHT' in data and isinstance(data['WINDOW_HEIGHT'], int) and data['WINDOW_HEIGHT'] > 600:
                WINDOW_HEIGHT = data['WINDOW_HEIGHT']
            print(f"[CONFIG] Load kích thước cửa sổ từ config.json: {WINDOW_WIDTH}x{WINDOW_HEIGHT}")
           
    except json.JSONDecodeError as e:
        print(f"[CONFIG] Lỗi định dạng JSON trong config.json: {e}. Dùng mặc định.")
    except Exception as e:
        print(f"[CONFIG] Lỗi load config.json: {e}. Dùng mặc định.")
else:
    print("[CONFIG] Không có config.json. Dùng mặc định.")

GROUPS_FILE = "action_groups.json"
JOBS_FILE = "scheduled_jobs.json"

running_threads = {}
is_running = True
is_paused = False