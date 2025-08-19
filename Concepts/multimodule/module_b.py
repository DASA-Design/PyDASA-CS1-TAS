# module_b.py
import config


class ClassB:
    def __init__(self):
        self.name = "ClassA"

    def enable_debug(self):
        print("Enabling debug mode from Module B.")
        config.DEBUG_MODE = True
