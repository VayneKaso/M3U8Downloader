import re
from pathlib import Path

# 在文件顶部
DEBUG = __name__ == "__main__"


class TSAnalyzer:
    @staticmethod
    def analyze(ts_files):
        """
        分析 ts 文件序列完整性

        返回:
        - full_x_y
        - sub

        可能抛异常:
        - ValueError: 文件结构异常

        info:
        目的是: 当前目录下的ts可能会是0.ts 1.ts 2.ts 也可能是seg-1-part.ts.... 这个就是根据ts集合，粗略的判断一下ts文件是否合法
        怎么算合法？只要连续就算合法。比如0.ts-100.ts 2.ts - 102.ts count 都等于 101,能对的上就算合法。
        反之如果不全的，则认为是sub，也能通过但是会在名字上做出区分，有些sub可能是我人为造成的，删除中间的广告，有些则是可能没下载全。
        所以出现sub 的信息需要让人看到，以便分析具体原因
        """
        if not ts_files:
            return "sub"

        number_matrix = []

        for f in ts_files:
            nums = re.findall(r"\d+", f.stem)
            if not nums:
                raise ValueError(f"文件无法解析数字: {f.name}")

            number_matrix.append([int(n) for n in nums])

        # 1️⃣ 检查结构一致性
        lengths = [len(row) for row in number_matrix]
        if len(set(lengths)) != 1:
            raise ValueError("TS 文件数字结构不一致")

        col_count = lengths[0]
        # 🚀 如果只有1列，直接使用这一列
        if col_count == 1:
            indexes = sorted(row[0] for row in number_matrix)
            if DEBUG:
                print("===== 🚀 fast path =====")
        else:
            if DEBUG:
                print("===== 📚 analyze path =====")
            # 2️⃣ 计算每列变化幅度
            col_ranges = []
            for col in range(col_count):
                col_values = [row[col] for row in number_matrix]
                min_v = min(col_values)
                max_v = max(col_values)
                diff = max_v - min_v

                if diff > 0:
                    col_ranges.append((col, diff))

            if not col_ranges:
                return "sub"

            # 3️⃣ 选变化幅度最大的列
            # target_col = max(col_ranges, key=lambda x: x[1])[0]
            # 多列diff相同，选最后一个 例如v1_001.ts v2_002.ts... 选择002作为主列。
            target_col = max(col_ranges, key=lambda x: (x[1], x[0]))[0]

            indexes = sorted(row[target_col] for row in number_matrix)

        # 4️⃣ 去重校验
        if len(indexes) != len(set(indexes)):
            return "sub"

        min_idx = indexes[0]
        max_idx = indexes[-1]
        count = len(indexes)

        # 5️⃣ 连续性判断（核心规则）
        if count == (max_idx - min_idx + 1):
            return f"full_{min_idx}_{max_idx}"
        # 只要是连续的，我就认为是完整的
        return "sub"


# --- 这里是 Main 函数入口 ---
if __name__ == "__main__":
    # 模拟一些文件名（实际使用时可以用 Path("your_dir").glob("*.ts")）
    test_cases = ["video_001.ts", "video_002.ts", "video_003.ts"]

    # 将字符串转换为 Path 对象，因为 analyze 方法里用了 f.stem 和 f.name
    file_paths = [Path(f) for f in test_cases]

    try:
        result = TSAnalyzer.analyze(file_paths)
        print(f"分析结果: {result}")
    except Exception as e:
        print(f"发生错误: {e}")
