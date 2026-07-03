import logging
import os
from datetime import datetime

# Tạo thư mục logs nếu chưa có
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("LDLauncher")
logger.setLevel(logging.DEBUG)

# Handler ghi file (mỗi ngày một file)
file_handler = logging.FileHandler(
    f"logs/ldlauncher_{datetime.now().strftime('%Y-%m-%d')}.log",
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)

# Handler in console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(threadName)s | %(message)s'
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

def get_logger():
    return logger