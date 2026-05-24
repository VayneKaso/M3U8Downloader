from pathlib import Path

from handlers.base import BaseSiteHandler
from handlers.chigua51 import Chigua51Handler
from handlers.hsck import HsckHandler


# 注册表：类似 Java 里 List<SiteHandler>，顺序越靠前，优先级越高。
HANDLERS: list[BaseSiteHandler] = [
    Chigua51Handler(),
    HsckHandler(),
]


def pick_handler(folder: Path, ts_dir: Path) -> BaseSiteHandler:
    # 依次询问每个处理器是否能处理当前任务目录。
    for handler in HANDLERS:
        if handler.match(folder, ts_dir):
            return handler

    # 理论上不会走到这里，因为 HsckHandler 是兜底处理器。
    raise ValueError("找不到可用的网站处理器")
