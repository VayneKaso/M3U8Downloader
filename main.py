import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ffmpeg_utils import get_ffmpeg_stderr
from handlers import pick_handler
from logcat import LOGCAT
from mp4_validator import get_validator
from output_namer import build_unique_output_paths, get_clean_name
from task_scanner import (
    find_best_ts_dir,
    find_target_folders,
    get_dir_size_gb,
    natural_sort_key,
)
from ts_analyzer import TSAnalyzer

# ===== 配置 =====
BASE_DIR = Path("/Users/jiangliqun/Downloads/output/3")
OUTPUT_DIR = Path("/Users/jiangliqun/Downloads/output/merge_output")
MAX_WORKERS = 4
DISK_THRESHOLD_GB = 1.0  # 剩余空间阈值 (GB)
CHECK_INTERVAL = 2.0  # 磁盘检测间隔 (秒)
DISK_SAFE_SPACE_GB = 3.0  # 磁盘剩余安全容量 (GB)

# 全局停止信号
STOP_EVENT = threading.Event()
SOFT_STOP_FLAG = threading.Event()


def is_disk_space_sufficient(min_gb: float) -> bool:

    try:
        # 写死获取根目录的磁盘情况
        free_gb = getFreeGB()
        return free_gb >= min_gb
    except Exception:  # 其他意外错误
        return False


def getFreeGB():
    usage = shutil.disk_usage(str(OUTPUT_DIR))
    free_gb = usage.free / (1024**3)
    return round(free_gb, 1)


def disk_monitor():
    """后台监控守护线程：检查全盘剩余空间"""
    LOGCAT.log(f"🔍 磁盘全局监控已启动 (阈值: {DISK_THRESHOLD_GB}GB)")

    while not STOP_EVENT.is_set():
        # 软限制检查 (3GB)
        if not is_disk_space_sufficient(DISK_SAFE_SPACE_GB):
            if not SOFT_STOP_FLAG.is_set():
                LOGCAT.log(f"\n⚠️ 提示：磁盘空间低于 {DISK_SAFE_SPACE_GB}GB，将不再启动新任务。")
                SOFT_STOP_FLAG.set()
        else:
            SOFT_STOP_FLAG.clear()

        # 硬限制检查 (1GB)
        if not is_disk_space_sufficient(DISK_THRESHOLD_GB):
            # 获取当前精确数值用于打印提示
            LOGCAT.log("\n🚨 紧急刹车：磁盘全局剩余空间不足")
            STOP_EVENT.set()
            break

        # 每隔指定时间检查一次
        time.sleep(CHECK_INTERVAL)


def process_folder(folder: Path):
    # 合并前、运行中、合并后都通过 STOP_EVENT 判断
    # 1. 基础状态检查
    if STOP_EVENT.is_set():
        return ("skip", folder.name, "紧急停止")
    if SOFT_STOP_FLAG.is_set():
        return ("skip", folder.name, "触发软停止限制（空间不足）")

    folder_name = folder.name
    output_file = None

    try:
        # 1. 扫描 TS 文件
        ts_dir = find_best_ts_dir(folder)
        ts_files = sorted(
            list(ts_dir.glob("*.ts")), key=lambda x: natural_sort_key(x.name)
        )

        if not ts_files:
            return ("warn", folder_name, "找不到 TS 文件")

        # 2. 基础信息生成
        clean_name = get_clean_name(folder_name)
        output_name = f"{clean_name}.mp4"
        output_file = OUTPUT_DIR / output_name
        error_log = OUTPUT_DIR / f"{clean_name}.txt"

        LOGCAT.log(f"{output_name} 扫描完毕，准备校验")
        # 检查ts是否合格。tag是一个标签，区分ts合成的种类，如果不合格，会抛出异常，这个任务算失败了。
        tag = TSAnalyzer.analyze(ts_files)
        # 根据当前任务目录选择具体网站处理器，类似 Java 里从 List<SiteHandler> 里挑一个实现类。
        handler = pick_handler(folder, ts_dir)
        # 处理器可以按自己的网站特征调整输出标签，例如 AES 任务会追加 aes。
        tag = handler.build_tag(tag)
        # 拼出带 6 位内容指纹的输出路径，避免两个同名视频因为文件名相同而被误判为已存在。
        output_name, output_file, error_log = build_unique_output_paths(
            OUTPUT_DIR, folder, clean_name, tag, ts_files
        )

        LOGCAT.log(f"{output_name} 校验合格，准备合并")

        # 3. 跳过本地已有的
        if output_file.exists():
            is_ok, _ = get_validator().verify(output_file)
            if is_ok:
                return ("skip", folder_name, f"已存在且完整 ({output_name})")
            else:
                output_file.unlink()

        # 二次检查停止信号
        if STOP_EVENT.is_set():
            return ("skip", folder_name, "任务已取消")

        # 计算真实需要的空间大小，看看磁盘剩余是否符合
        ts_total_size = get_dir_size_gb(ts_dir)
        if not is_disk_space_sufficient(ts_total_size * 1.2):
            # 这里不设置硬退出，因为可能是某个文件特别大，让其他小文件试试。
            return (
                "fail",
                folder_name,
                "预估空间不足",
            )

        # 合并细节交给具体处理器，main.py 只负责主流程编排。
        LOGCAT.log(handler.get_start_message(output_name))
        result = handler.merge(folder, ts_dir, ts_files, output_file)

        result_stderr = get_ffmpeg_stderr(result.stderr)
        if result.returncode == 0:
            if error_log.exists():
                error_log.unlink(missing_ok=True)
            return ("success", folder_name, output_name)
        else:
            # 失败处理：清理半成品
            if output_file.exists():
                output_file.unlink()
            # FFmpeg层级的报错，空间不足
            if "No space left on device" in result.stderr:
                STOP_EVENT.set()
                return ("fail", folder_name, "❌ 磁盘爆满")
            with open(error_log, "w", encoding="utf-8") as f:
                f.write(result_stderr)
            return ("fail", folder_name, "FFmpeg 报错")

    except Exception as e:
        if isinstance(e, OSError) and e.errno == 28:  # 磁盘空间不足的系统错误码
            STOP_EVENT.set()
            return ("fail", folder_name, "❌ 磁盘空间已满 (写入清单失败)")
        if output_file is not None and output_file.exists():
            output_file.unlink()

        return ("fail", folder_name, f"异常: {e}")
    finally:
        checkDiskSpace()


def checkDiskSpace():
    if not is_disk_space_sufficient(DISK_SAFE_SPACE_GB):
        SOFT_STOP_FLAG.set()
    else:
        SOFT_STOP_FLAG.clear()


def main():

    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGCAT.log(f"~~~~~ 🎉 还能下{getFreeGB()}个G的 ~~~~~")
    target_folders = find_target_folders(BASE_DIR)
    LOGCAT.log(f"🎬 发现任务: {len(target_folders)} 个\n")

    if len(target_folders) <= 0:
        LOGCAT.log("👋🏻 👋🏻  没有可执行的任务，程序退出")
        return

    # if len(target_folders) >= 0:
    #     LOGCAT.log("👋🏻 👋🏻  没有可执行的任务，程序退出")
    #     return

    # 启动监控
    monitor_thread = threading.Thread(target=disk_monitor, daemon=True)
    monitor_thread.start()

    results = []
    # 使用 ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务，注意仅仅是提交到等待队列，process_folder不会执行。
        future_to_folder = {
            executor.submit(process_folder, folder): folder for folder in target_folders
        }

        try:
            # 关键：使用 as_completed 实时获取结果
            for future in as_completed(future_to_folder):
                res = future.result()
                results.append(res)
                # 实时结果直接在这里拼文案，输出动作统一走 LOGCAT。
                status, name, info = res
                tag = (
                    "✅ 成功"
                    if status == "success"
                    else "⏩ 跳过"
                    if status == "skip"
                    else "❌ 失败"
                )
                LOGCAT.log(f"{tag}  name: {name}  info: {info}")

        except KeyboardInterrupt:
            LOGCAT.log("\n🛑 用户手动停止，正在等待当前线程收尾...")
            STOP_EVENT.set()

    # 汇总打印交给 Logcat 类，后续改展示样式不用动 main.py。
    LOGCAT.summary(len(target_folders), results, getFreeGB())


if __name__ == "__main__":
    main()
