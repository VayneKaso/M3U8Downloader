class DownloadLogcat:
    """下载合并日志输出类：作用类似 Android 里的 Logcat 封装。"""

    def log(self, message: str):
        # 统一出口：以后如果要改成写文件、加时间戳，只改这里。
        print(message)

    def print_result_group(self, title: str, results: list[tuple[str, str, str]], arrow: str):
        # 每个分类都打印数量，避免“失败/跳过为 0”时用户误以为汇总漏了。
        print(f"  {title}: {len(results):>3} 个")
        # 有明细时逐条打印，方便回头定位具体任务。
        for _, name, info in results:
            print(f"     - {name} {arrow} {info}")

    def summary(self, target_count: int, results: list[tuple[str, str, str]], free_gb: float):
        # 计算已经产生结果的任务数量。
        processed_count = len(results)
        # 按状态拆分结果，方便汇总打印。
        success = [r for r in results if r[0] == "success"]
        failed = [r for r in results if r[0] == "fail"]
        skipped = [r for r in results if r[0] == "skip"]
        warned = [r for r in results if r[0] == "warn"]
        known_statuses = {"success", "fail", "skip", "warn"}
        unknown = [r for r in results if r[0] not in known_statuses]
        # 总数减去已返回结果数量，就是因为停止或异常没有来得及执行的数量。
        cancelled_count = target_count - processed_count
        # 计算完成进度；target_count 正常大于 0，这里兜底避免除以 0。
        progress = (processed_count / target_count) * 100 if target_count else 0

        print("\n" + "═" * 50)
        print(f"📊 任务汇总报告 | 进度: {progress:.1f}%")
        print(f"  ● 总计任务: {target_count:>3} 个")
        print("  ──────────────────────────────")

        # 成功、跳过、警告、失败都统一打印，避免某个分类被遗漏。
        self.print_result_group("✅ 成功完成", success, "->")
        self.print_result_group("⏩ 自动跳过", skipped, ":")
        self.print_result_group("⚠️ 需要注意", warned, ":")
        self.print_result_group("❌ 执行失败", failed, ":")
        # 未知状态也打印出来，方便发现 process_folder 新增状态但汇总没适配的问题。
        if unknown:
            self.print_result_group("❓ 未知状态", unknown, ":")

        # 打印取消数量。
        print(f"  🚫 已取消: {cancelled_count:>3} 个\n")

        self.log(f"~~~~~ 🎉 还能下{free_gb}个G的 ~~~~~")
        print("═" * 50)


# 暴露一个全局实例，main.py 像使用 Android Logcat 工具类一样直接调用。
LOGCAT = DownloadLogcat()
