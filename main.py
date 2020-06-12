import subprocess
import socket as s
import logging
import os
import time

logger = logging.getLogger()
logging.basicConfig(format='%(asctime)-15s pid=%(process)d %(side)s: %(message)s', level=logging.INFO)

if __name__ == '__main__':
    sp = subprocess.Popen(["python3", "children.py"])
    time.sleep(3)
    sp = subprocess.Popen(["python3", "parent.py"])

    time.sleep(99999)