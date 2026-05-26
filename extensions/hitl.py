from extensions import approval_policy as policy


def register(runtime):
    runtime.on_before_execute(hitl_handler)


def hitl_handler(tool_name, arguments, tool):
    if not policy.requires_approval_for_tool(tool, arguments):
        return None

    print(f"\n⚠️ {policy.danger_level_for_tool(tool)} {tool_name}")
    print(f"   风险: {policy.risk_description_for_tool(tool)}")
    print(f"   参数: {arguments}")

    choice = input("允许执行？[y/n/c]: ").strip().lower()
    if choice == "y":
        return None
    if choice == "c":
        advice = input("补充说明: ").strip()
        return {
            "block": True,
            "hard_stop": False,
            "reason": (
                "用户拒绝本次工具调用，并补充要求："
                f"{advice or '未提供补充说明'}。"
                "请根据该要求调整后续步骤，不要重复执行被拒绝的调用。"
            ),
        }
    return {
        "block": True,
        "hard_stop": True,
        "reason": (
            "用户拒绝执行本次工具调用。"
            "不要用其他等价工具或命令绕过该拒绝；"
            "如需继续，请说明原因并等待用户新指示。"
        ),
    }
