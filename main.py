# main.py
import sys
import traceback
from gui import create_gui

if __name__ == "__main__":
    try:
        print("[MAIN] Khởi động chương trình...")
        create_gui()
        print("[MAIN] Chương trình kết thúc bình thường")
    except Exception as e:
        print(f"[MAIN] LỖI KHỞI ĐỘNG: {e}")
        traceback.print_exc()