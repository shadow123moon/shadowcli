"""对比工具:测试不同 API 配置的延迟

使用方法:
1. 在 CherryStudio 里查看实际使用的 API URL 和模型名
2. 修改下面的 configs 列表,添加 CherryStudio 的配置
3. 运行对比
"""
import os
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

configs = [
    {
        "name": "当前配置 (小米)",
        "base_url": os.getenv("API_URL"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model": os.getenv("MODEL"),
    },
    # 👇 把 CherryStudio 的配置填在这里
    # {
    #     "name": "CherryStudio 配置",
    #     "base_url": "https://...",  # CherryStudio 里显示的 API URL
    #     "api_key": "sk-...",         # 你的 API key
    #     "model": "...",              # CherryStudio 里显示的模型名
    # },
]

prompt = "只回复OK"
runs = 3

for config in configs:
    print(f"\n{'='*60}")
    print(f"配置: {config['name']}")
    print(f"端点: {config['base_url']}")
    print(f"模型: {config['model']}")
    print()

    try:
        client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
        times = []

        for i in range(1, runs + 1):
            start = time.perf_counter()
            stream = client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    elapsed = time.perf_counter() - start
                    times.append(elapsed)
                    print(f"  第 {i} 次: {elapsed:.3f}s")
                    break
            time.sleep(0.3)

        avg = sum(times) / len(times)
        print(f"\n  平均: {avg:.3f}s | 最快: {min(times):.3f}s | 最慢: {max(times):.3f}s")

    except Exception as e:
        print(f"  ❌ 错误: {e}")
