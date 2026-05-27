#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
简单计算器程序
支持加减乘除四则运算
"""


def calculator():
    """主计算器函数"""
    print("=" * 40)
    print("        简单计算器")
    print("=" * 40)
    print("支持运算: +  -  *  /")
    print("输入 'q' 退出程序")
    print("=" * 40)
    
    while True:
        print()
        # 获取第一个数字
        num1 = input("请输入第一个数字 (或输入 q 退出): ")
        if num1.lower() == 'q':
            print("感谢使用，再见！")
            break
        
        try:
            num1 = float(num1)
        except ValueError:
            print("❌ 输入无效，请输入有效的数字！")
            continue
        
        # 获取运算符
        operator = input("请输入运算符 (+, -, *, /): ")
        if operator not in ['+', '-', '*', '/']:
            print("❌ 无效的运算符！")
            continue
        
        # 获取第二个数字
        num2 = input("请输入第二个数字: ")
        try:
            num2 = float(num2)
        except ValueError:
            print("❌ 输入无效，请输入有效的数字！")
            continue
        
        # 执行计算
        if operator == '+':
            result = num1 + num2
        elif operator == '-':
            result = num1 - num2
        elif operator == '*':
            result = num1 * num2
        elif operator == '/':
            if num2 == 0:
                print("❌ 错误：除数不能为零！")
                continue
            result = num1 / num2
        
        # 显示结果（整数结果不显示小数点）
        if result == int(result):
            result = int(result)
        
        print(f"✅ 计算结果: {num1} {operator} {num2} = {result}")


if __name__ == "__main__":
    calculator()
