class DownloadLogcat:
    """下载合并日志输出类：作用类似 Android 里的 Logcat 封装。"""

    def log(self, message: str):
        # 统一出口：以后如果要改成写文件、加时间戳，只改这里。
        print(message)

    def summary(self, target_count: int, results: list[tuple[str, str, str]], free_gb: float):
        # 计算已经产生结果的任务数量。
        processed_count = len(results)
        # 按状态拆分结果，方便汇总打印。
        success = [r for r in results if r[0] == "success"]
        failed = [r for r in results if r[0] == "fail"]
        skipped = [r for r in results if r[0] == "skip"]
        # 总数减去已返回结果数量，就是因为停止或异常没有来得及执行的数量。
        cancelled_count = target_count - processed_count
        # 计算完成进度；target_count 正常大于 0，这里兜底避免除以 0。
        progress = (processed_count / target_count) * 100 if target_count else 0

        print("\n" + "═" * 50)
        print(f"📊 任务汇总报告 | 进度: {progress:.1f}%")
        print(f"  ● 总计任务: {target_count:>3} 个")
        print("  ──────────────────────────────")

        # 打印成功列表。
        if success:
            print(f"  ✅ 成功完成: {len(success):>3} 个")
            for _, name, info in success:
                print(f"     - {name} -> {info}")

        # 打印跳过列表。
        if skipped:
            print(f"  ⏩ 自动跳过: {len(skipped):>3} 个")
            for _, name, info in skipped:
                print(f"     - {name}: {info}")

        # 打印失败列表。
        if failed:
            print(f"  ❌ 执行失败: {len(failed):>3} 个")
            for _, name, info in failed:
                print(f"     - {name}: {info}")

        # 打印取消数量。
        if cancelled_count > 0:
            print(f"  🚫 已取消: {cancelled_count:>3} 个\n")

        self.log(f"~~~~~ 🎉 还能下{free_gb}个G的 ~~~~~")
        print("═" * 50)


# 暴露一个全局实例，main.py 像使用 Android Logcat 工具类一样直接调用。
LOGCAT = DownloadLogcat()
