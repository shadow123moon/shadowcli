"""对比不同 API 端点和模型的首 token 延迟"""
import os
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

configs = [
    {
        "name": "当前配置 (DeepSeek V4)",
        "base_url": os.getenv("API_URL"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model": os.getenv("MODEL"),
    },
    # 如果你知道 CherryStudio 的配置,可以添加在这里
    # {
    #     "name": "CherryStudio 配置",
    #     "base_url": "https://...",
    #     "api_key": "...",
    #     "model": "...",
    # },
]

prompt = "只回复 OK"

for config in configs:
    print(f"\n{'='*60}")
    print(f"测试: {config['name']}")
    print(f"模型: {config['model']}")
    print(f"端点: {config['base_url']}")

    try:
        client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

        # 测试 3 次取平均
        times = []
        for i in range(3):
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
                    break

        avg = sum(times) / len(times)
        print(f"首 token 延迟: {avg:.3f}s (平均), {min(times):.3f}s (最快), {max(times):.3f}s (最慢)")
    except Exception as e:
        print(f"错误: {e}")
