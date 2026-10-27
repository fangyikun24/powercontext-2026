"""pytest 路径配置：确保 tests 能导入 sample_project 下的模块。"""
import os
import sys

# 将 sample_project 目录加入 sys.path，使 `from discount import ...` 可解析
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
