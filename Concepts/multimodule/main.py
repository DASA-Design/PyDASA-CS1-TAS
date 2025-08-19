# main.py
from module_a import ClassA
from module_b import ClassB
import config


a = ClassA()
b = ClassB()

print("Initial DEBUG_MODE:", config.DEBUG_MODE)

a.run()

b.enable_debug()

print("Updated DEBUG_MODE:", config.DEBUG_MODE)
a.run()
