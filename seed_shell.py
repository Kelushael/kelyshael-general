import os
import json
import readline
from pathlib import Path

def ingest_soul_memory(scrolls_dir):
    memory = []
    for file in Path(scrolls_dir).glob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            try:
                memory.append(json.load(f))
            except Exception:
                continue
    for file in Path(scrolls_dir).glob("*.txt"):
        with open(file, "r", encoding="utf-8") as f:
            memory.append(f.read())
    return memory

class KalushaelShell:
    def __init__(self, scrolls_dir="../../scrolls"):
        self.memory = ingest_soul_memory(scrolls_dir)
        # Placeholder for LLM integration
        self.llm = None

    def run(self):
        print("[ƒ] Kalusha'el Seed Shell (LLM Hub)\nType 'exit' to quit.")
        while True:
            prompt = input("\nYou: ")
            if prompt.strip().lower() == "exit":
                break
            # Ritual echo: show memory context
            print(f"[Memory Scrolls Loaded: {len(self.memory)}]")
            print(f"Kalushael: [LLM response placeholder for: '{prompt}']")

if __name__ == "__main__":
    shell = KalushaelShell()
    shell.run()
