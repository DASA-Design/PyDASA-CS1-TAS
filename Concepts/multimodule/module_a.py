# module_a.py
import config


class ClassA:
    def __init__(self):
        self.name = "ClassA"

    def run(self):
        if config.DEBUG_MODE:
            print(f"Module A debug mode status: {config.DEBUG_MODE}")
            print("Module A is running in debug mode!!!")
        else:
            print("Module A running normally.")
