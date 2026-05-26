# Python 编程教程

欢迎来到 Python 编程教程！本教程将带你从零开始学习 Python 编程语言，涵盖从基础语法到实战项目的完整内容。

---

## 目录

1. [Python 基础语法](#1-python-基础语法)
2. [控制流](#2-控制流)
3. [函数和模块](#3-函数和模块)
4. [面向对象编程](#4-面向对象编程)
5. [异常处理](#5-异常处理)
6. [文件操作](#6-文件操作)
7. [常用标准库](#7-常用标准库)
8. [实战项目示例](#8-实战项目示例)

---

## 1. Python 基础语法

### 1.1 变量

变量是存储数据的容器。Python 是动态类型语言，不需要声明变量类型。

```python
# 变量赋值
name = "Alice"           # 字符串
age = 25                 # 整数
height = 1.75            # 浮点数
is_student = True        # 布尔值

# 多重赋值
x, y, z = 1, 2, 3

# 链式赋值
a = b = c = 100

# 变量命名规则
my_name = "Bob"          # 下划线命名法（推荐）
myName = "Bob"           # 驼峰命名法
_private = "隐藏变量"     # 下划线开头表示私有
# 2name = "错误"         # 不能以数字开头
# class = "错误"         # 不能使用保留字
```

### 1.2 数据类型

#### 数字类型

```python
# 整数 (int)
integer_num = 42
negative_num = -10
big_num = 1_000_000      # 可以用下划线分隔提高可读性
hex_num = 0xFF           # 十六进制
oct_num = 0o77           # 八进制
bin_num = 0b1010         # 二进制

# 浮点数 (float)
float_num = 3.14
scientific = 2.5e10      # 科学计数法

# 复数 (complex)
complex_num = 3 + 4j
print(complex_num.real)  # 实部: 3.0
print(complex_num.imag)  # 虚部: 4.0
```

#### 字符串 (str)

```python
# 字符串创建
single_quote = 'Hello'
double_quote = "World"
triple_quote = '''这是
多行字符串'''

# 字符串操作
name = "Python"
print(len(name))         # 长度: 6
print(name[0])           # 索引: P
print(name[-1])          # 负索引: n
print(name[0:3])         # 切片: Pyt
print(name * 2)          # 重复: PythonPython
print("Py" in name)      # 包含: True

# 字符串方法
text = "  Hello, World!  "
print(text.strip())      # 去除空白: "Hello, World!"
print(text.lower())      # 小写
print(text.upper())      # 大写
print(text.replace("World", "Python"))  # 替换
print(text.split(","))   # 分割: ['  Hello', ' World!  ']
print("-".join(["a", "b", "c"]))  # 连接: "a-b-c"

# 字符串格式化
name = "Alice"
age = 25
# f-string (推荐)
print(f"我叫{name}，今年{age}岁")
# format方法
print("我叫{}，今年{}岁".format(name, age))
# % 操作符
print("我叫%s，今年%d岁" % (name, age))
```

#### 列表 (list)

```python
# 列表创建
fruits = ["苹果", "香蕉", "橙子"]
mixed = [1, "hello", 3.14, True]
nested = [[1, 2], [3, 4], [5, 6]]

# 列表操作
fruits.append("葡萄")       # 添加元素
fruits.insert(1, "草莓")    # 插入元素
fruits.remove("香蕉")       # 删除元素
popped = fruits.pop()       # 弹出最后一个
fruits.sort()               # 排序
fruits.reverse()            # 反转

# 列表推导式
squares = [x**2 for x in range(10)]
even_squares = [x**2 for x in range(10) if x % 2 == 0]
```

#### 元组 (tuple)

```python
# 元组创建（不可变）
point = (3, 4)
single = (1,)              # 单元素元组需要逗号
empty = ()

# 元组解包
x, y = point
print(f"x={x}, y={y}")
```

#### 字典 (dict)

```python
# 字典创建
person = {
    "name": "Alice",
    "age": 25,
    "city": "北京"
}

# 字典操作
print(person["name"])           # 访问
person["email"] = "alice@example.com"  # 添加
person["age"] = 26              # 修改
del person["city"]              # 删除
print(person.get("phone", "未提供"))  # 安全访问

# 字典方法
print(person.keys())            # 所有键
print(person.values())          # 所有值
print(person.items())           # 所有键值对

# 字典推导式
squares = {x: x**2 for x in range(6)}
```

#### 集合 (set)

```python
# 集合创建（无序、不重复）
fruits = {"苹果", "香蕉", "橙子"}
numbers = set([1, 2, 2, 3, 3])  # {1, 2, 3}

# 集合操作
fruits.add("葡萄")
fruits.discard("香蕉")

# 集合运算
set1 = {1, 2, 3, 4}
set2 = {3, 4, 5, 6}
print(set1 & set2)    # 交集: {3, 4}
print(set1 | set2)    # 并集: {1, 2, 3, 4, 5, 6}
print(set1 - set2)    # 差集: {1, 2}
print(set1 ^ set2)    # 对称差集: {1, 2, 5, 6}
```

### 1.3 运算符

```python
# 算术运算符
print(10 + 3)     # 加法: 13
print(10 - 3)     # 减法: 7
print(10 * 3)     # 乘法: 30
print(10 / 3)     # 除法: 3.333...
print(10 // 3)    # 整除: 3
print(10 % 3)     # 取余: 1
print(10 ** 3)    # 幂运算: 1000

# 比较运算符
print(5 == 5)     # 等于: True
print(5 != 3)     # 不等于: True
print(5 > 3)      # 大于: True
print(5 < 3)      # 小于: False
print(5 >= 5)     # 大于等于: True
print(5 <= 3)     # 小于等于: False

# 逻辑运算符
print(True and False)   # 与: False
print(True or False)    # 或: True
print(not True)         # 非: False

# 赋值运算符
x = 10
x += 5     # x = x + 5
x -= 3     # x = x - 3
x *= 2     # x = x * 2
x /= 4     # x = x / 4

# 身份运算符
a = [1, 2, 3]
b = a
c = [1, 2, 3]
print(a is b)      # True (同一对象)
print(a is c)      # False (不同对象)
print(a == c)      # True (值相等)

# 成员运算符
fruits = ["苹果", "香蕉", "橙子"]
print("苹果" in fruits)        # True
print("葡萄" not in fruits)    # True
```

### 练习题 1.1

```python
# 练习 1: 创建一个包含你个人信息的字典，包括姓名、年龄、爱好
# 练习 2: 使用字符串格式化输出你的个人信息
# 练习 3: 创建两个列表，使用集合操作找出它们的交集和并集
# 练习 4: 写一个表达式判断一个年份是否为闰年
#       （能被4整除但不能被100整除，或者能被400整除）
```

---

## 2. 控制流

### 2.1 条件语句 (if/elif/else)

```python
# 基本 if 语句
age = 18
if age >= 18:
    print("你是成年人")

# if-else
score = 85
if score >= 60:
    print("及格")
else:
    print("不及格")

# if-elif-else
score = 85
if score >= 90:
    grade = "A"
elif score >= 80:
    grade = "B"
elif score >= 70:
    grade = "C"
elif score >= 60:
    grade = "D"
else:
    grade = "F"
print(f"成绩等级: {grade}")

# 三元表达式
age = 20
status = "成年" if age >= 18 else "未成年"
print(status)

# 嵌套条件
num = 15
if num > 0:
    if num % 2 == 0:
        print("正偶数")
    else:
        print("正奇数")
else:
    print("非正数")
```

### 2.2 for 循环

```python
# 基本 for 循环
fruits = ["苹果", "香蕉", "橙子"]
for fruit in fruits:
    print(fruit)

# range() 函数
for i in range(5):          # 0, 1, 2, 3, 4
    print(i)

for i in range(2, 8):       # 2, 3, 4, 5, 6, 7
    print(i)

for i in range(0, 10, 2):   # 0, 2, 4, 6, 8
    print(i)

# enumerate() 带索引遍历
fruits = ["苹果", "香蕉", "橙子"]
for index, fruit in enumerate(fruits):
    print(f"{index}: {fruit}")

# 遍历字典
person = {"name": "Alice", "age": 25, "city": "北京"}
for key, value in person.items():
    print(f"{key}: {value}")

# 列表推导式
squares = [x**2 for x in range(10)]
even_squares = [x**2 for x in range(10) if x % 2 == 0]

# 嵌套循环 - 九九乘法表
for i in range(1, 10):
    for j in range(1, i + 1):
        print(f"{j}×{i}={i*j}", end="\t")
    print()
```

### 2.3 while 循环

```python
# 基本 while 循环
count = 0
while count < 5:
    print(count)
    count += 1

# 用户输入循环
while True:
    user_input = input("请输入命令 (输入 'quit' 退出): ")
    if user_input.lower() == 'quit':
        print("程序退出")
        break
    print(f"你输入了: {user_input}")

# while-else
count = 0
while count < 5:
    print(count)
    count += 1
else:
    print("循环正常结束")
```

### 2.4 break 和 continue

```python
# break - 跳出循环
for i in range(10):
    if i == 5:
        break
    print(i)  # 输出: 0, 1, 2, 3, 4

# continue - 跳过当前迭代
for i in range(10):
    if i % 2 == 0:
        continue
    print(i)  # 输出: 1, 3, 5, 7, 9

# 循环中的 else
for i in range(5):
    if i == 10:  # 不会执行
        break
else:
    print("循环正常完成，没有遇到 break")
```

### 练习题 2.1

```python
# 练习 1: 写一个程序判断一个数字是正数、负数还是零
# 练习 2: 使用 for 循环计算 1 到 100 的和
# 练习 3: 写一个猜数字游戏，随机生成 1-100 的数字，让用户猜测
# 练习 4: 打印一个三角形图案:
#     *
#    ***
#   *****
#  *******
# *********
# 练习 5: 找出 100 以内的所有质数
```

---

## 3. 函数和模块

### 3.1 函数定义和调用

```python
# 基本函数定义
def greet(name):
    """向用户打招呼"""
    return f"你好，{name}！"

# 调用函数
message = greet("Alice")
print(message)

# 多个返回值
def get_min_max(numbers):
    """返回列表的最小值和最大值"""
    return min(numbers), max(numbers)

minimum, maximum = get_min_max([3, 1, 4, 1, 5, 9])
print(f"最小值: {minimum}, 最大值: {maximum}")

# 默认参数
def power(base, exponent=2):
    """计算幂"""
    return base ** exponent

print(power(3))      # 9 (3^2)
print(power(3, 3))   # 27 (3^3)

# 可变参数 *args
def sum_all(*args):
    """计算所有参数的和"""
    return sum(args)

print(sum_all(1, 2, 3, 4, 5))  # 15

# 关键字可变参数 **kwargs
def print_info(**kwargs):
    """打印所有关键字参数"""
    for key, value in kwargs.items():
        print(f"{key}: {value}")

print_info(name="Alice", age=25, city="北京")

# 混合使用
def func(a, b, *args, **kwargs):
    print(f"a={a}, b={b}")
    print(f"args={args}")
    print(f"kwargs={kwargs}")

func(1, 2, 3, 4, x=5, y=6)
```

### 3.2 Lambda 表达式

```python
# Lambda 函数
square = lambda x: x ** 2
print(square(5))  # 25

add = lambda x, y: x + y
print(add(3, 4))  # 7

# 在高阶函数中使用
numbers = [3, 1, 4, 1, 5, 9, 2, 6]
sorted_numbers = sorted(numbers, key=lambda x: -x)
print(sorted_numbers)  # [9, 6, 5, 4, 3, 2, 1, 1]

# map 函数
numbers = [1, 2, 3, 4, 5]
squared = list(map(lambda x: x**2, numbers))
print(squared)  # [1, 4, 9, 16, 25]

# filter 函数
numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
even_numbers = list(filter(lambda x: x % 2 == 0, numbers))
print(even_numbers)  # [2, 4, 6, 8, 10]
```

### 3.3 作用域和闭包

```python
# 全局变量和局部变量
x = 10  # 全局变量

def func():
    x = 20  # 局部变量
    print(f"函数内 x = {x}")

func()
print(f"函数外 x = {x}")

# global 关键字
x = 10

def func():
    global x
    x = 20
    print(f"函数内 x = {x}")

func()
print(f"函数外 x = {x}")

# 闭包
def outer_function(message):
    def inner_function():
        print(f"消息: {message}")
    return inner_function

my_func = outer_function("Hello")
my_func()  # 消息: Hello
```

### 3.4 模块和包

```python
# 导入整个模块
import math
print(math.pi)
print(math.sqrt(16))

# 导入特定函数
from math import pi, sqrt
print(pi)
print(sqrt(16))

# 导入并重命名
import numpy as np

# 导入所有（不推荐）
from math import *

# 创建自己的模块
# mymodule.py
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

PI = 3.14159

# 使用自己的模块
import mymodule
print(mymodule.add(5, 3))
print(mymodule.PI)

# 包的结构
# mypackage/
#     __init__.py
#     module1.py
#     module2.py
#     subpackage/
#         __init__.py
#         module3.py
```

### 3.5 装饰器

```python
# 简单装饰器
def my_decorator(func):
    def wrapper():
        print("函数执行前")
        func()
        print("函数执行后")
    return wrapper

@my_decorator
def say_hello():
    print("Hello!")

say_hello()

# 带参数的装饰器
def repeat(times):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for _ in range(times):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator

@repeat(times=3)
def greet(name):
    print(f"Hello, {name}!")

greet("Alice")

# 常用装饰器示例
import time

def timer(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} 执行时间: {end - start:.4f}秒")
        return result
    return wrapper

@timer
def slow_function():
    time.sleep(1)
    return "完成"

result = slow_function()
```

### 练习题 3.1

```python
# 练习 1: 写一个函数计算斐波那契数列的第 n 项
# 练习 2: 写一个装饰器，记录函数被调用的次数
# 练习 3: 写一个函数，接受任意数量的数字，返回它们的平均值
# 练习 4: 创建一个模块 calculator.py，包含加减乘除四个函数
# 练习 5: 写一个闭包，实现一个计数器，每次调用返回递增的数字
```

---

## 4. 面向对象编程

### 4.1 类和对象

```python
# 定义类
class Dog:
    # 类变量（所有实例共享）
    species = "犬科"
    
    # 构造方法
    def __init__(self, name, age):
        # 实例变量
        self.name = name
        self.age = age
    
    # 实例方法
    def bark(self):
        return f"{self.name} 说: 汪汪！"
    
    def get_info(self):
        return f"{self.name}，{self.age}岁"

# 创建对象
dog1 = Dog("旺财", 3)
dog2 = Dog("小白", 2)

print(dog1.bark())        # 旺财 说: 汪汪！
print(dog2.get_info())    # 小白，2岁
print(dog1.species)       # 犬科
```

### 4.2 继承

```python
# 父类
class Animal:
    def __init__(self, name, species):
        self.name = name
        self.species = species
    
    def make_sound(self):
        pass
    
    def __str__(self):
        return f"{self.name} 是一只 {self.species}"

# 子类继承
class Dog(Animal):
    def __init__(self, name, breed):
        super().__init__(name, "狗")  # 调用父类构造方法
        self.breed = breed
    
    def make_sound(self):
        return "汪汪！"
    
    def fetch(self, item):
        return f"{self.name} 捡回了 {item}"

class Cat(Animal):
    def __init__(self, name, color):
        super().__init__(name, "猫")
        self.color = color
    
    def make_sound(self):
        return "喵喵！"

# 使用
dog = Dog("旺财", "金毛")
cat = Cat("咪咪", "橘色")

print(dog)              # 旺财 是一只 狗
print(dog.make_sound()) # 汪汪！
print(dog.fetch("球"))  # 旺财 捡回了 球
print(cat.make_sound()) # 喵喵！

# 多重继承
class Flyable:
    def fly(self):
        return f"{self.name} 可以飞"

class Swimmable:
    def swim(self):
        return f"{self.name} 可以游泳"

class Duck(Animal, Flyable, Swimmable):
    def __init__(self, name):
        super().__init__(name, "鸭子")
    
    def make_sound(self):
        return "嘎嘎！"

duck = Duck("唐老鸭")
print(duck.fly())    # 唐老鸭 可以飞
print(duck.swim())   # 唐老鸭 可以游泳
```

### 4.3 封装

```python
class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner          # 公有属性
        self.__balance = balance    # 私有属性（名称改编）
        self._type = "储蓄账户"     # 保护属性（约定）
    
    # Getter 方法
    @property
    def balance(self):
        return self.__balance
    
    # Setter 方法
    @balance.setter
    def balance(self, amount):
        if amount < 0:
            raise ValueError("余额不能为负数")
        self.__balance = amount
    
    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("存款金额必须大于0")
        self.__balance += amount
        return self.__balance
    
    def withdraw(self, amount):
        if amount > self.__balance:
            raise ValueError("余额不足")
        self.__balance -= amount
        return self.__balance
    
    def __str__(self):
        return f"账户所有者: {self.owner}, 余额: {self.__balance}"

# 使用
account = BankAccount("Alice", 1000)
print(account)          # 账户所有者: Alice, 余额: 1000
account.deposit(500)
print(account.balance)  # 1500
account.withdraw(200)
print(account.balance)  # 1300
```

### 4.4 魔术方法

```python
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    
    # 字符串表示
    def __str__(self):
        return f"Vector({self.x}, {self.y})"
    
    def __repr__(self):
        return f"Vector({self.x}, {self.y})"
    
    # 加法
    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)
    
    # 减法
    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y)
    
    # 乘法（标量）
    def __mul__(self, scalar):
        return Vector(self.x * scalar, self.y * scalar)
    
    # 等于比较
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    
    # 长度
    def __abs__(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5
    
    # 布尔值
    def __bool__(self):
        return self.x != 0 or self.y != 0
    
    # 索引访问
    def __getitem__(self, index):
        if index == 0:
            return self.x
        elif index == 1:
            return self.y
        raise IndexError("索引超出范围")

# 使用
v1 = Vector(3, 4)
v2 = Vector(1, 2)

print(v1 + v2)        # Vector(4, 6)
print(v1 - v2)        # Vector(2, 2)
print(v1 * 3)         # Vector(9, 12)
print(abs(v1))        # 5.0
print(v1 == v2)       # False
print(v1[0])          # 3
print(bool(v1))       # True
```

### 4.5 类方法和静态方法

```python
class Date:
    def __init__(self, year, month, day):
        self.year = year
        self.month = month
        self.day = day
    
    # 实例方法
    def display(self):
        return f"{self.year}-{self.month:02d}-{self.day:02d}"
    
    # 类方法 - 可以访问类本身
    @classmethod
    def from_string(cls, date_string):
        year, month, day = map(int, date_string.split('-'))
        return cls(year, month, day)
    
    # 静态方法 - 不访问实例或类
    @staticmethod
    def is_valid_date(year, month, day):
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        return True

# 使用
date1 = Date(2023, 12, 25)
print(date1.display())  # 2023-12-25

date2 = Date.from_string("2024-01-15")
print(date2.display())  # 2024-01-15

print(Date.is_valid_date(2023, 13, 1))  # False
```

### 练习题 4.1

```python
# 练习 1: 创建一个 Rectangle 类，包含计算面积和周长的方法
# 练习 2: 创建一个 Shape 父类，派生出 Circle、Triangle、Rectangle 子类
# 练习 3: 创建一个 Student 类，使用属性装饰器保护年龄在 0-150 之间
# 练习 4: 创建一个 Stack 类，实现 push、pop、peek、is_empty 方法
# 练习 5: 实现一个简单的银行账户系统，支持存款、取款、转账功能
```

---

## 5. 异常处理

### 5.1 try/except

```python
# 基本异常处理
try:
    result = 10 / 0
except ZeroDivisionError:
    print("错误：除以零！")

# 捕获多种异常
try:
    num = int(input("请输入一个数字: "))
    result = 10 / num
except ValueError:
    print("错误：输入的不是有效数字！")
except ZeroDivisionError:
    print("错误：不能除以零！")

# 捕获异常信息
try:
    result = 10 / 0
except ZeroDivisionError as e:
    print(f"发生错误: {e}")

# 捕获所有异常（不推荐）
try:
    # 可能出错的代码
    pass
except Exception as e:
    print(f"发生错误: {e}")
```

### 5.2 try/except/else/finally

```python
# 完整的异常处理结构
def divide(a, b):
    try:
        result = a / b
    except ZeroDivisionError:
        print("错误：除以零！")
        return None
    except TypeError:
        print("错误：参数类型错误！")
        return None
    else:
        print("计算成功！")
        return result
    finally:
        print("计算结束")

# 使用
print(divide(10, 2))   # 计算成功！5.0
print(divide(10, 0))   # 错误：除以零！None
print(divide(10, "a")) # 错误：参数类型错误！None
```

### 5.3 抛出异常

```python
# raise 语句
def set_age(age):
    if age < 0:
        raise ValueError("年龄不能为负数")
    if age > 150:
        raise ValueError("年龄不能超过150岁")
    return age

try:
    set_age(-5)
except ValueError as e:
    print(f"错误: {e}")

# 重新抛出异常
def process_data(data):
    try:
        result = int(data)
    except ValueError:
        print("记录日志：数据转换失败")
        raise  # 重新抛出当前异常

try:
    process_data("abc")
except ValueError:
    print("捕获到重新抛出的异常")
```

### 5.4 自定义异常

```python
# 自定义异常类
class InsufficientFundsError(Exception):
    """余额不足异常"""
    def __init__(self, balance, amount):
        self.balance = balance
        self.amount = amount
        super().__init__(f"余额不足：当前余额 {balance}，尝试取款 {amount}")

class BankAccount:
    def __init__(self, balance=0):
        self.balance = balance
    
    def withdraw(self, amount):
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount)
        self.balance -= amount
        return self.balance

# 使用自定义异常
account = BankAccount(100)
try:
    account.withdraw(150)
except InsufficientFundsError as e:
    print(f"错误: {e}")
    print(f"差额: {e.amount - e.balance}")
```

### 5.5 异常处理最佳实践

```python
# 1. 只捕获你知道如何处理的异常
try:
    value = int(user_input)
except ValueError:
    print("请输入有效的数字")

# 2. 不要捕获所有异常
# 不推荐
try:
    pass
except:
    pass

# 推荐
try:
    pass
except (ValueError, TypeError) as e:
    pass

# 3. 使用上下文管理器处理资源
with open("file.txt", "r") as f:
    content = f.read()
# 文件会自动关闭，即使发生异常

# 4. 提供有用的错误信息
def connect_to_database(host, port):
    if not host:
        raise ValueError("数据库主机地址不能为空")
    if not (0 <= port <= 65535):
        raise ValueError(f"端口号必须在 0-65535 之间，收到: {port}")
    # 连接代码...

# 5. 记录异常
import logging

logging.basicConfig(level=logging.ERROR)

try:
    result = 10 / 0
except ZeroDivisionError:
    logging.error("发生除以零错误", exc_info=True)
```

### 练习题 5.1

```python
# 练习 1: 写一个函数，安全地将字符串转换为整数，失败时返回默认值
# 练习 2: 创建一个自定义异常 InvalidEmailError，用于验证邮箱格式
# 练习 3: 写一个文件读取函数，处理文件不存在、权限不足等异常
# 练习 4: 创建一个输入验证器，验证用户名（3-20字符，只含字母数字）
# 练习 5: 实现一个重试装饰器，在函数失败时自动重试指定次数
```

---

## 6. 文件操作

### 6.1 读写文本文件

```python
# 写入文件
with open("example.txt", "w", encoding="utf-8") as f:
    f.write("第一行\n")
    f.write("第二行\n")
    f.write("第三行\n")

# 读取整个文件
with open("example.txt", "r", encoding="utf-8") as f:
    content = f.read()
    print(content)

# 逐行读取
with open("example.txt", "r", encoding="utf-8") as f:
    for line in f:
        print(line.strip())

# 读取所有行到列表
with open("example.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()
    print(lines)

# 追加写入
with open("example.txt", "a", encoding="utf-8") as f:
    f.write("第四行\n")

# 写入多行
lines = ["行1\n", "行2\n", "行3\n"]
with open("example.txt", "w", encoding="utf-8") as f:
    f.writelines(lines)
```

### 6.2 读写二进制文件

```python
# 写入二进制文件
data = b'\x00\x01\x02\x03\x04'
with open("binary.bin", "wb") as f:
    f.write(data)

# 读取二进制文件
with open("binary.bin", "rb") as f:
    data = f.read()
    print(data)

# 复制文件
def copy_file(source, destination):
    with open(source, "rb") as src, open(destination, "wb") as dst:
        while True:
            chunk = src.read(4096)  # 每次读取 4KB
            if not chunk:
                break
            dst.write(chunk)

copy_file("source.txt", "destination.txt")
```

### 6.3 文件和目录操作

```python
import os
import shutil

# 获取当前工作目录
current_dir = os.getcwd()
print(f"当前目录: {current_dir}")

# 列出目录内容
files = os.listdir(".")
print(f"文件列表: {files}")

# 创建目录
os.mkdir("new_directory")
os.makedirs("path/to/nested/dir", exist_ok=True)  # 递归创建

# 删除目录
os.rmdir("new_directory")
shutil.rmtree("path/to/nested/dir")  # 递归删除

# 重命名文件
os.rename("old_name.txt", "new_name.txt")

# 删除文件
os.remove("file_to_delete.txt")

# 检查文件/目录是否存在
print(os.path.exists("file.txt"))
print(os.path.isfile("file.txt"))
print(os.path.isdir("directory"))

# 获取文件信息
file_path = "example.txt"
print(f"文件名: {os.path.basename(file_path)}")
print(f"目录名: {os.path.dirname(file_path)}")
print(f"绝对路径: {os.path.abspath(file_path)}")
print(f"文件扩展名: {os.path.splitext(file_path)[1]}")
print(f"文件大小: {os.path.getsize(file_path)} 字节")

# 路径拼接
base_dir = "/home/user"
file_name = "document.txt"
full_path = os.path.join(base_dir, file_name)
print(f"完整路径: {full_path}")

# 遍历目录
for root, dirs, files in os.walk("."):
    for file in files:
        print(os.path.join(root, file))
```

### 6.4 pathlib 模块（现代路径处理）

```python
from pathlib import Path

# 创建路径对象
p = Path(".")
home = Path.home()
print(f"当前目录: {p.absolute()}")
print(f"主目录: {home}")

# 路径操作
file_path = Path("documents") / "file.txt"
print(f"文件路径: {file_path}")
print(f"文件名: {file_path.name}")
print(f"文件名（无扩展名）: {file_path.stem}")
print(f"扩展名: {file_path.suffix}")
print(f"父目录: {file_path.parent}")

# 创建目录
Path("new_dir").mkdir(exist_ok=True)
Path("nested/dir").mkdir(parents=True, exist_ok=True)

# 创建文件并写入
file_path = Path("example.txt")
file_path.write_text("Hello, World!", encoding="utf-8")

# 读取文件
content = file_path.read_text(encoding="utf-8")
print(content)

# 遍历目录
for item in Path(".").iterdir():
    if item.is_file():
        print(f"文件: {item}")
    elif item.is_dir():
        print(f"目录: {item}")

# 通配符匹配
python_files = list(Path(".").glob("*.py"))
print(f"Python 文件: {python_files}")

# 递归匹配
all_python_files = list(Path(".").rglob("*.py"))
print(f"所有 Python 文件: {all_python_files}")
```

### 6.5 CSV 和 JSON 文件

```python
import csv
import json

# ===== CSV 文件 =====

# 写入 CSV
data = [
    ["姓名", "年龄", "城市"],
    ["Alice", 25, "北京"],
    ["Bob", 30, "上海"],
    ["Charlie", 35, "广州"]
]

with open("people.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerows(data)

# 读取 CSV
with open("people.csv", "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    for row in reader:
        print(row)

# 使用字典方式读写 CSV
with open("people.csv", "w", newline="", encoding="utf-8") as f:
    fieldnames = ["姓名", "年龄", "城市"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow({"姓名": "Alice", "年龄": 25, "城市": "北京"})
    writer.writerow({"姓名": "Bob", "年龄": 30, "城市": "上海"})

with open("people.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        print(dict(row))

# ===== JSON 文件 =====

# 写入 JSON
data = {
    "name": "Alice",
    "age": 25,
    "hobbies": ["reading", "coding", "hiking"],
    "address": {
        "city": "北京",
        "district": "朝阳区"
    }
}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

# 读取 JSON
with open("data.json", "r", encoding="utf-8") as f:
    loaded_data = json.load(f)
    print(loaded_data)

# JSON 字符串转换
json_string = json.dumps(data, ensure_ascii=False)
print(json_string)

parsed_data = json.loads(json_string)
print(parsed_data)
```

### 练习题 6.1

```python
# 练习 1: 写一个程序，统计一个文本文件中每个单词出现的次数
# 练习 2: 写一个函数，将 CSV 文件转换为 JSON 文件
# 练习 3: 写一个日志记录器，将日志信息追加写入文件，包含时间戳
# 练习 4: 写一个程序，递归搜索目录下所有 .txt 文件，并统计总行数
# 练习 5: 实现一个简单的配置文件读写器，支持 JSON 格式
```

---

## 7. 常用标准库

### 7.1 os 和 sys 模块

```python
import os
import sys

# os 模块 - 操作系统接口
print(f"当前工作目录: {os.getcwd()}")
print(f"环境变量 PATH: {os.environ.get('PATH')}")
print(f"操作系统类型: {os.name}")

# 执行系统命令
os.system("ls -la")  # Linux/Mac
os.system("dir")      # Windows

# sys 模块 - Python 解释器接口
print(f"Python 版本: {sys.version}")
print(f"平台: {sys.platform}")
print(f"命令行参数: {sys.argv}")
print(f"模块搜索路径: {sys.path}")

# 标准输入输出
sys.stdout.write("标准输出\n")
sys.stderr.write("标准错误\n")

# 退出程序
# sys.exit(0)  # 正常退出
# sys.exit(1)  # 异常退出
```

### 7.2 math 和 random 模块

```python
import math
import random

# math 模块 - 数学函数
print(f"圆周率: {math.pi}")
print(f"自然常数: {math.e}")
print(f"向上取整: {math.ceil(3.2)}")   # 4
print(f"向下取整: {math.floor(3.8)}")  # 3
print(f"绝对值: {math.fabs(-5.5)}")    # 5.5
print(f"幂运算: {math.pow(2, 10)}")    # 1024.0
print(f"平方根: {math.sqrt(16)}")      # 4.0
print(f"对数: {math.log(100, 10)}")    # 2.0
print(f"三角函数: {math.sin(math.pi/2)}")  # 1.0

# random 模块 - 随机数
print(f"随机整数: {random.randint(1, 100)}")
print(f"随机浮点数: {random.random()}")
print(f"范围随机: {random.uniform(1.0, 10.0)}")

# 从序列中随机选择
fruits = ["苹果", "香蕉", "橙子", "葡萄"]
print(f"随机选择: {random.choice(fruits)}")
print(f"多个随机: {random.choices(fruits, k=3)}")
print(f"随机抽样: {random.sample(fruits, 2)}")

# 打乱列表
numbers = [1, 2, 3, 4, 5]
random.shuffle(numbers)
print(f"打乱后: {numbers}")

# 设置随机种子（可复现）
random.seed(42)
print(random.randint(1, 100))  # 总是返回相同的值
```

### 7.3 datetime 模块

```python
from datetime import datetime, date, time, timedelta

# 获取当前时间
now = datetime.now()
print(f"当前时间: {now}")
print(f"当前日期: {now.date()}")
print(f"当前时间: {now.time()}")
print(f"时间戳: {now.timestamp()}")

# 创建特定日期时间
dt = datetime(2023, 12, 25, 10, 30, 0)
print(f"特定时间: {dt}")

# 格式化时间
print(f"格式化: {now.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"中文格式: {now.strftime('%Y年%m月%d日 %H时%M分%S秒')}")

# 解析时间字符串
dt_str = "2023-12-25 10:30:00"
dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
print(f"解析后: {dt}")

# 时间运算
tomorrow = now + timedelta(days=1)
yesterday = now - timedelta(days=1)
next_week = now + timedelta(weeks=1)
print(f"明天: {tomorrow}")
print(f"昨天: {yesterday}")

# 计算时间差
birthday = datetime(2000, 6, 15)
age = now - birthday
print(f"年龄天数: {age.days}")
print(f"年龄: {age.days // 365} 岁")

# 常用格式化符号
"""
%Y - 四位年份
%m - 月份（01-12）
%d - 日期（01-31）
%H - 小时（00-23）
%M - 分钟（00-59）
%S - 秒（00-59）
%w - 星期几（0-6，0是星期一）
%A - 星期几全称
%B - 月份全称
"""
```

### 7.4 collections 模块

```python
from collections import Counter, defaultdict, OrderedDict, namedtuple, deque

# Counter - 计数器
words = ["apple", "banana", "apple", "cherry", "banana", "apple"]
word_count = Counter(words)
print(f"计数: {word_count}")
print(f"最常见: {word_count.most_common(2)}")

# 统计字符出现次数
text = "hello world"
char_count = Counter(text)
print(f"字符计数: {char_count}")

# defaultdict - 默认字典
dd = defaultdict(list)
dd["fruits"].append("apple")
dd["fruits"].append("banana")
dd["vegetables"].append("carrot")
print(f"默认字典: {dict(dd)}")

# 按首字母分组
words = ["apple", "banana", "avocado", "blueberry", "cherry"]
grouped = defaultdict(list)
for word in words:
    grouped[word[0]].append(word)
print(f"分组: {dict(grouped)}")

# OrderedDict - 有序字典（Python 3.7+ 普通字典也有序）
od = OrderedDict()
od["first"] = 1
od["second"] = 2
od["third"] = 3
print(f"有序字典: {od}")

# namedtuple - 命名元组
Point = namedtuple("Point", ["x", "y"])
p = Point(3, 4)
print(f"点: {p}")
print(f"x 坐标: {p.x}")
print(f"y 坐标: {p.y}")

# deque - 双端队列
dq = deque([1, 2, 3])
dq.append(4)        # 右端添加
dq.appendleft(0)    # 左端添加
print(f"双端队列: {dq}")
dq.pop()             # 右端删除
dq.popleft()         # 左端删除
print(f"操作后: {dq}")

# 限制长度的 deque
limited = deque(maxlen=3)
limited.extend([1, 2, 3])
print(f"限制长度: {limited}")
limited.append(4)  # 自动移除最左边的元素
print(f"添加后: {limited}")
```

### 7.5 itertools 模块

```python
import itertools

# 无限迭代器
# count - 无限计数
counter = itertools.count(start=1, step=2)
for _ in range(5):
    print(next(counter), end=" ")  # 1 3 5 7 9

print()

# cycle - 无限循环
colors = itertools.cycle(["red", "green", "blue"])
for _ in range(6):
    print(next(colors), end=" ")  # red green blue red green blue

print()

# repeat - 重复
repeater = itertools.repeat("hello", 3)
print(list(repeater))  # ['hello', 'hello', 'hello']

# 组合迭代器
# chain - 连接多个迭代器
result = list(itertools.chain([1, 2], [3, 4], [5, 6]))
print(f"chain: {result}")

# product - 笛卡尔积
colors = ["红", "蓝"]
sizes = ["大", "小"]
result = list(itertools.product(colors, sizes))
print(f"product: {result}")

# permutations - 排列
items = ["A", "B", "C"]
result = list(itertools.permutations(items, 2))
print(f"permutations: {result}")

# combinations - 组合
result = list(itertools.combinations(items, 2))
print(f"combinations: {result}")

# groupby - 分组
data = [("A", 1), ("A", 2), ("B", 3), ("B", 4), ("A", 5)]
data.sort(key=lambda x: x[0])  # 需要先排序
for key, group in itertools.groupby(data, key=lambda x: x[0]):
    print(f"{key}: {list(group)}")
```

### 7.6 functools 模块

```python
import functools

# reduce - 累积计算
numbers = [1, 2, 3, 4, 5]
sum_result = functools.reduce(lambda x, y: x + y, numbers)
product_result = functools.reduce(lambda x, y: x * y, numbers)
print(f"求和: {sum_result}")      # 15
print(f"求积: {product_result}")  # 120

# lru_cache - 缓存装饰器
@functools.lru_cache(maxsize=128)
def fibonacci(n):
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

print(f"斐波那契数列第10项: {fibonacci(10)}")  # 55
print(f"缓存信息: {fibonacci.cache_info()}")

# partial - 偏函数
def power(base, exponent):
    return base ** exponent

square = functools.partial(power, exponent=2)
cube = functools.partial(power, exponent=3)

print(f"平方: {square(5)}")  # 25
print(f"立方: {cube(3)}")    # 27

# cmp_to_key - 比较函数转换
def compare(a, b):
    return (a > b) - (a < b)

numbers = [3, 1, 4, 1, 5, 9, 2, 6]
sorted_numbers = sorted(numbers, key=functools.cmp_to_key(compare))
print(f"排序: {sorted_numbers}")

# wraps - 保留原函数信息
def my_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@my_decorator
def example():
    """示例函数"""
    pass

print(f"函数名: {example.__name__}")  # example
print(f"文档字符串: {example.__doc__}")  # 示例函数
```

### 练习题 7.1

```python
# 练习 1: 使用 datetime 模块计算两个日期之间的天数
# 练习 2: 使用 Counter 统计一段文本中出现频率最高的 5 个单词
# 练习 3: 使用 collections 模块实现一个简单的 LRU 缓存
# 练习 4: 使用 itertools 生成所有可能的扑克牌组合（4花色 × 13点数）
# 练习 5: 使用 functools.lru_cache 优化递归算法
```

---

## 8. 实战项目示例

### 8.1 计算器程序

```python
"""
简单计算器程序
支持基本的四则运算和括号
"""

def calculator():
    """计算器主函数"""
    print("=" * 40)
    print("欢迎使用 Python 计算器")
    print("=" * 40)
    print("支持的操作:")
    print("  +  加法")
    print("  -  减法")
    print("  *  乘法")
    print("  /  除法")
    print("  ** 幂运算")
    print("  %  取余")
    print("  quit 退出")
    print("=" * 40)
    
    history = []  # 计算历史
    
    while True:
        try:
            # 获取用户输入
            expression = input("\n请输入表达式 (或 'quit' 退出): ").strip()
            
            if expression.lower() == 'quit':
                print("\n计算历史:")
                for i, record in enumerate(history, 1):
                    print(f"  {i}. {record}")
                print("感谢使用，再见！")
                break
            
            if expression.lower() == 'history':
                print("\n计算历史:")
                for i, record in enumerate(history, 1):
                    print(f"  {i}. {record}")
                continue
            
            # 安全检查
            allowed_chars = set('0123456789+-*/.%() ')
            if not all(c in allowed_chars for c in expression):
                print("错误：表达式包含不允许的字符")
                continue
            
            # 计算结果
            result = eval(expression)
            
            # 记录历史
            history.append(f"{expression} = {result}")
            
            # 显示结果
            print(f"结果: {result}")
            
        except ZeroDivisionError:
            print("错误：不能除以零")
        except SyntaxError:
            print("错误：表达式语法错误")
        except Exception as e:
            print(f"错误：{e}")

# 运行计算器
if __name__ == "__main__":
    calculator()
```

### 8.2 学生成绩管理系统

```python
"""
学生成绩管理系统
功能：添加、查询、删除、统计学生成绩
"""

import json
from datetime import datetime

class Student:
    """学生类"""
    def __init__(self, student_id, name, scores=None):
        self.student_id = student_id
        self.name = name
        self.scores = scores or {}
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def add_score(self, subject, score):
        """添加成绩"""
        if not 0 <= score <= 100:
            raise ValueError("成绩必须在 0-100 之间")
        self.scores[subject] = score
    
    def get_average(self):
        """计算平均分"""
        if not self.scores:
            return 0
        return sum(self.scores.values()) / len(self.scores)
    
    def to_dict(self):
        """转换为字典"""
        return {
            "student_id": self.student_id,
            "name": self.name,
            "scores": self.scores,
            "created_at": self.created_at
        }
    
    def __str__(self):
        avg = self.get_average()
        return f"学号: {self.student_id}, 姓名: {self.name}, 平均分: {avg:.1f}"

class StudentManager:
    """学生管理器"""
    def __init__(self, data_file="students.json"):
        self.data_file = data_file
        self.students = {}
        self.load_data()
    
    def load_data(self):
        """从文件加载数据"""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for student_data in data:
                    student = Student(
                        student_data['student_id'],
                        student_data['name'],
                        student_data.get('scores', {})
                    )
                    self.students[student.student_id] = student
            print(f"已加载 {len(self.students)} 个学生记录")
        except FileNotFoundError:
            print("数据文件不存在，将创建新文件")
        except json.JSONDecodeError:
            print("数据文件格式错误")
    
    def save_data(self):
        """保存数据到文件"""
        data = [student.to_dict() for student in self.students.values()]
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("数据已保存")
    
    def add_student(self):
        """添加学生"""
        student_id = input("请输入学号: ").strip()
        if student_id in self.students:
            print("错误：该学号已存在")
            return
        
        name = input("请输入姓名: ").strip()
        student = Student(student_id, name)
        
        # 添加成绩
        while True:
            subject = input("请输入科目名称 (输入 'done' 完成): ").strip()
            if subject.lower() == 'done':
                break
            
            try:
                score = float(input(f"请输入 {subject} 成绩: "))
                student.add_score(subject, score)
            except ValueError as e:
                print(f"错误：{e}")
        
        self.students[student_id] = student
        self.save_data()
        print(f"学生 {name} 添加成功")
    
    def query_student(self):
        """查询学生"""
        student_id = input("请输入要查询的学号: ").strip()
        student = self.students.get(student_id)
        
        if not student:
            print("未找到该学生")
            return
        
        print(f"\n{'='*40}")
        print(f"学号: {student.student_id}")
        print(f"姓名: {student.name}")
        print(f"成绩:")
        for subject, score in student.scores.items():
            print(f"  {subject}: {score}")
        print(f"平均分: {student.get_average():.1f}")
        print(f"{'='*40}")
    
    def delete_student(self):
        """删除学生"""
        student_id = input("请输入要删除的学号: ").strip()
        if student_id in self.students:
            name = self.students[student_id].name
            confirm = input(f"确定要删除学生 {name} 吗？(y/n): ").strip()
            if confirm.lower() == 'y':
                del self.students[student_id]
                self.save_data()
                print(f"学生 {name} 已删除")
        else:
            print("未找到该学生")
    
    def show_statistics(self):
        """显示统计信息"""
        if not self.students:
            print("没有学生数据")
            return
        
        averages = [s.get_average() for s in self.students.values()]
        print(f"\n{'='*40}")
        print(f"学生总数: {len(self.students)}")
        print(f"最高平均分: {max(averages):.1f}")
        print(f"最低平均分: {min(averages):.1f}")
        print(f"班级平均分: {sum(averages)/len(averages):.1f}")
        print(f"{'='*40}")
    
    def run(self):
        """运行主程序"""
        while True:
            print("\n" + "="*40)
            print("学生成绩管理系统")
            print("="*40)
            print("1. 添加学生")
            print("2. 查询学生")
            print("3. 删除学生")
            print("4. 统计信息")
            print("5. 显示所有学生")
            print("0. 退出")
            print("="*40)
            
            choice = input("请选择操作: ").strip()
            
            if choice == '1':
                self.add_student()
            elif choice == '2':
                self.query_student()
            elif choice == '3':
                self.delete_student()
            elif choice == '4':
                self.show_statistics()
            elif choice == '5':
                if not self.students:
                    print("没有学生数据")
                else:
                    for student in self.students.values():
                        print(student)
            elif choice == '0':
                print("感谢使用，再见！")
                break
            else:
                print("无效的选择，请重新输入")

# 运行程序
if __name__ == "__main__":
    manager = StudentManager()
    manager.run()
```

### 8.3 Web 爬虫示例

```python
"""
简单的网页爬虫
使用 requests 和 BeautifulSoup
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import random

class SimpleWebCrawler:
    """简单网页爬虫"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_page(self, url):
        """获取网页内容"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return response.text
        except requests.RequestException as e:
            print(f"获取页面失败: {e}")
            return None
    
    def parse_html(self, html):
        """解析 HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # 提取标题
        title = soup.title.string if soup.title else "无标题"
        
        # 提取所有链接
        links = []
        for link in soup.find_all('a', href=True):
            links.append({
                'text': link.get_text(strip=True),
                'href': link['href']
            })
        
        # 提取所有段落文本
        paragraphs = [p.get_text(strip=True) for p in soup.find_all('p')]
        
        return {
            'title': title,
            'links': links[:10],  # 只取前10个
            'paragraphs': paragraphs[:5]  # 只取前5个
        }
    
    def save_to_csv(self, data, filename):
        """保存到 CSV 文件"""
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['类型', '内容'])
            writer.writerow(['标题', data['title']])
            for link in data['links']:
                writer.writerow(['链接', f"{link['text']}: {link['href']}"])
            for para in data['paragraphs']:
                writer.writerow(['段落', para[:100]])  # 只取前100字符
        print(f"数据已保存到 {filename}")
    
    def crawl(self, url):
        """爬取网页"""
        print(f"正在爬取: {url}")
        
        html = self.fetch_page(url)
        if not html:
            return None
        
        data = self.parse_html(html)
        
        print(f"标题: {data['title']}")
        print(f"找到 {len(data['links'])} 个链接")
        print(f"找到 {len(data['paragraphs'])} 个段落")
        
        return data

# 使用示例
def main():
    crawler = SimpleWebCrawler()
    
    # 爬取示例网站
    url = "https://example.com"
    data = crawler.crawl(url)
    
    if data:
        # 显示结果
        print("\n爬取结果:")
        print(f"标题: {data['title']}")
        
        print("\n链接:")
        for link in data['links']:
            print(f"  {link['text']}: {link['href']}")
        
        print("\n段落:")
        for para in data['paragraphs']:
            print(f"  {para[:100]}...")
        
        # 保存到文件
        crawler.save_to_csv(data, "crawl_result.csv")

if __name__ == "__main__":
    main()
```

### 8.4 数据分析示例

```python
"""
简单的数据分析工具
使用标准库处理 CSV 数据
"""

import csv
import statistics
from collections import Counter

class DataAnalyzer:
    """数据分析器"""
    
    def __init__(self, filename):
        self.filename = filename
        self.data = []
        self.headers = []
        self.load_data()
    
    def load_data(self):
        """加载 CSV 数据"""
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.headers = reader.fieldnames
                self.data = list(reader)
            print(f"成功加载 {len(self.data)} 条记录")
        except FileNotFoundError:
            print(f"文件 {self.filename} 不存在")
        except Exception as e:
            print(f"加载数据失败: {e}")
    
    def get_column(self, column_name):
        """获取指定列的数据"""
        if column_name not in self.headers:
            print(f"列 '{column_name}' 不存在")
            return []
        
        values = []
        for row in self.data:
            try:
                values.append(float(row[column_name]))
            except (ValueError, TypeError):
                continue
        return values
    
    def basic_statistics(self, column_name):
        """基本统计信息"""
        values = self.get_column(column_name)
        if not values:
            return None
        
        stats = {
            'count': len(values),
            'sum': sum(values),
            'mean': statistics.mean(values),
            'median': statistics.median(values),
            'mode': statistics.mode(values) if len(set(values)) < len(values) else '无众数',
            'std_dev': statistics.stdev(values) if len(values) > 1 else 0,
            'min': min(values),
            'max': max(values)
        }
        
        return stats
    
    def frequency_distribution(self, column_name):
        """频率分布"""
        if column_name not in self.headers:
            return None
        
        values = [row[column_name] for row in self.data if row[column_name]]
        counter = Counter(values)
        return counter.most_common()
    
    def filter_data(self, column_name, condition, value):
        """筛选数据"""
        filtered = []
        for row in self.data:
            try:
                cell_value = float(row[column_name])
                if condition == '>' and cell_value > value:
                    filtered.append(row)
                elif condition == '<' and cell_value < value:
                    filtered.append(row)
                elif condition == '==' and cell_value == value:
                    filtered.append(row)
                elif condition == '>=' and cell_value >= value:
                    filtered.append(row)
                elif condition == '<=' and cell_value <= value:
                    filtered.append(row)
            except (ValueError, TypeError):
                if condition == '==' and row[column_name] == value:
                    filtered.append(row)
        
        return filtered
    
    def generate_report(self):
        """生成报告"""
        print("\n" + "="*60)
        print(f"数据分析报告 - {self.filename}")
        print("="*60)
        
        print(f"\n数据概览:")
        print(f"  记录数: {len(self.data)}")
        print(f"  字段数: {len(self.headers)}")
        print(f"  字段名: {', '.join(self.headers)}")
        
        # 对数值列进行统计分析
        print(f"\n数值列统计:")
        for header in self.headers:
            values = self.get_column(header)
            if values:
                print(f"\n  {header}:")
                print(f"    数量: {len(values)}")
                print(f"    平均值: {statistics.mean(values):.2f}")
                print(f"    中位数: {statistics.median(values):.2f}")
                if len(values) > 1:
                    print(f"    标准差: {statistics.stdev(values):.2f}")
                print(f"    最小值: {min(values):.2f}")
                print(f"    最大值: {max(values):.2f}")

# 使用示例
def create_sample_data():
    """创建示例数据"""
    data = [
        ['姓名', '年龄', '成绩', '城市'],
        ['Alice', '20', '85', '北京'],
        ['Bob', '22', '92', '上海'],
        ['Charlie', '21', '78', '广州'],
        ['David', '23', '95', '北京'],
        ['Eve', '20', '88', '上海'],
        ['Frank', '22', '72', '广州'],
        ['Grace', '21', '91', '北京'],
        ['Henry', '23', '83', '上海'],
        ['Ivy', '20', '96', '广州'],
        ['Jack', '22', '79', '北京']
    ]
    
    with open('students_data.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(data)
    print("示例数据已创建: students_data.csv")

def main():
    # 创建示例数据
    create_sample_data()
    
    # 创建分析器
    analyzer = DataAnalyzer('students_data.csv')
    
    # 生成报告
    analyzer.generate_report()
    
    # 筛选数据
    print("\n筛选成绩大于 90 的学生:")
    excellent = analyzer.filter_data('成绩', '>', 90)
    for student in excellent:
        print(f"  {student['姓名']}: {student['成绩']}")
    
    # 频率分布
    print("\n城市分布:")
    city_dist = analyzer.frequency_distribution('城市')
    for city, count in city_dist:
        print(f"  {city}: {count} 人")

if __name__ == "__main__":
    main()
```

### 练习题 8.1

```python
# 练习 1: 扩展计算器程序，支持更多数学函数（如三角函数、对数等）
# 练习 2: 为学生成绩管理系统添加导出为 CSV 和导入 CSV 的功能
# 练习 3: 改进 Web 爬虫，支持爬取多个页面并限制爬取速度
# 练习 4: 创建一个待办事项管理程序，支持增删改查和持久化存储
# 练习 5: 实现一个简单的密码管理器，支持加密存储和生成随机密码
```

---

## 总结

恭喜你完成 Python 编程教程的学习！让我们回顾一下本教程涵盖的内容：

1. **基础语法** - 变量、数据类型、运算符
2. **控制流** - 条件语句、循环结构
3. **函数和模块** - 函数定义、装饰器、模块导入
4. **面向对象编程** - 类、继承、封装、魔术方法
5. **异常处理** - try/except、自定义异常
6. **文件操作** - 读写文件、CSV、JSON
7. **常用标准库** - datetime、collections、itertools 等
8. **实战项目** - 计算器、管理系统、爬虫、数据分析

### 下一步学习建议

1. **深入学习**：学习更高级的主题，如并发编程、网络编程、数据库操作
2. **框架学习**：Web 开发（Django、Flask）、数据分析（Pandas、NumPy）、机器学习（Scikit-learn、TensorFlow）
3. **项目实践**：尝试完成更多实际项目，积累经验
4. **参与开源**：在 GitHub 上参与开源项目，学习优秀代码
5. **持续学习**：关注 Python 社区，阅读官方文档和优秀博客

### 推荐资源

- [Python 官方文档](https://docs.python.org/3/)
- [Python 标准库文档](https://docs.python.org/3/library/index.html)
- [Real Python](https://realpython.com/)
- [Python 教程 - 廖雪峰](https://www.liaoxuefeng.com/wiki/1016959663602400)

---

**祝你编程愉快！🐍**
