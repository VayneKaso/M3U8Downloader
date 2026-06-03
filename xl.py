#!/usr/bin/env python3
"""迅雷任务脚本的根目录入口。"""

import sys

import pyperclip

from thunder_tools.thunder_task import main

#################################################################################################################################
# 在 VS Code 里点“运行 Python 文件”时，可以把网页 URL 填在这里。
# 默认留空，避免提交后误触发固定网页地址。
# URL = "https://91porny.com/video/view/679967df6ba4fc760a1c"
URL = pyperclip.paste()
#################################################################################################################################

if __name__ == "__main__":
    # 命令行参数优先，避免 URL 写死后影响临时手敲的新地址。
    if len(sys.argv) > 1:
        # 有命令行参数时保持 CLI 模式，继续支持 uv run xl.py "网页URL"。
        main()
    # 如果 URL 有值，就像命令行传参一样交给底层逻辑处理。
    elif URL.strip():
        # 这里用列表传参，类似 Java 里手动构造 String[] args。
        main([URL.strip()])
    else:
        # URL 为空且没有命令行参数时，让 argparse 打印标准用法提示。
        main()
