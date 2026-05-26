#!/usr/bin/env python3
"""
简单计算器程序
支持加减乘除四则运算
"""

def add(x, y):
    """加法"""
    return x + y

def subtract(x, y):
    """减法"""
    return x - y

def multiply(x, y):
    """乘法"""
    return x * y

def divide(x, y):
    """除法"""
    if y == 0:
        raise ValueError("错误：除数不能为零！")
    return x / y

def get_number(prompt):
    """获取用户输入的数字"""
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("输入无效，请输入一个数字！")

def get_operator():
    """获取用户输入的运算符"""
    valid_operators = ['+', '-', '*', '/']
    while True:
        operator = input("请输入运算符 (+, -, *, /): ").strip()
        if operator in valid_operators:
            return operator
        print("运算符无效，请重新输入！")

def calculate(num1, num2, operator):
    """执行计算"""
    operations = {
        '+': add,
        '-': subtract,
        '*': multiply,
        '/': divide
    }
    
    try:
        result = operations[operator](num1, num2)
        return result
    except ValueError as e:
        print(e)
        return None

def main():
    """主函数"""
    print("=" * 40)
    print("简单计算器程序")
    print("=" * 40)
    print("支持的运算: +, -, *, /")
    print("输入 'q' 或 'quit' 退出程序")
    print("=" * 40)
    
    while True:
        print("\n--- 新的计算 ---")
        
        # 获取第一个数字
        try:
            input1 = input("请输入第一个数字 (或输入'q'退出): ").strip()
            if input1.lower() in ['q', 'quit']:
                break
            num1 = float(input1)
        except ValueError:
            print("输入无效，请输入一个数字！")
            continue
        
        # 获取运算符
        operator = get_operator()
        
        # 获取第二个数字
        try:
            num2 = float(input("请输入第二个数字: ").strip())
        except ValueError:
            print("输入无效，请输入一个数字！")
            continue
        
        # 执行计算
        result = calculate(num1, num2, operator)
        
        # 显示结果
        if result is not None:
            # 如果结果是整数，则显示为整数形式
            if result == int(result):
                print(f"\n结果: {num1} {operator} {num2} = {int(result)}")
            else:
                print(f"\n结果: {num1} {operator} {num2} = {result}")
    
    print("\n感谢使用计算器程序，再见！")

if __name__ == "__main__":
    main()
