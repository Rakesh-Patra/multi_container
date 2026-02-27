import os
import sys

# Ensure project root is on the path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from container_agent import create_agent

def main():
    print("=========================================")
    print("   Testing Basic Agent Initialization    ")
    print("=========================================")
    try:
        print("[1] Creating the Docker DevOps Agent...")
        agent = create_agent()
        print(" [SUCCESS] Agent created successfully.")
        
        print("\n[2] Testing a simple instruction...")
        prompt = "Hi, reply with 'Hello from Strands' and your tool count."
        print(f" -> Prompt: {prompt}")
        
        response = agent(prompt)
        print("\n[3] Agent Response:")
        print("-" * 40)
        print(response)
        print("-" * 40)
        print(" [SUCCESS] Basic Agent test passed.")
        
    except Exception as e:
        print(f"\n [ERROR] Error during agent test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
