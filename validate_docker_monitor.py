import os
import sys

# Ensure project root is on the path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from tools.monitoring_tools import check_port, get_disk_usage, prune_docker_system

def main():
    print("=========================================")
    print("   Testing Docker Monitor Tools          ")
    print("=========================================")
    
    print("\n[1] Testing check_port()...")
    try:
        # Check a commonly used port and a random one
        print(" -> check_port(80)")
        res1 = check_port(80)
        print(f"    Result: {res1}")
        
        print(" -> check_port(5432) on 127.0.0.1")
        res2 = check_port(5432, "127.0.0.1")
        print(f"    Result: {res2}")
        print(" [SUCCESS] check_port test complete.")
    except Exception as e:
        print(f" [ERROR] Error testing check_port: {e}")

    print("\n[2] Testing get_disk_usage()...")
    try:
        res = get_disk_usage()
        # Just print the first 5 lines to avoid huge output if there's a lot
        lines = res.splitlines()
        print(f"    Output (first 8 lines):")
        for line in lines[:8]:
            print(f"      {line}")
        print(" [SUCCESS] get_disk_usage test complete.")
    except Exception as e:
        print(f" [ERROR] Error testing get_disk_usage: {e}")

    print("\n[3] Testing prune_docker_system(dry_run=True)...")
    try:
        res = prune_docker_system(dry_run=True, prune_volumes=False)
        lines = res.splitlines()
        print(f"    Output (first 8 lines):")
        for line in lines[:8]:
            print(f"      {line}")
        print(" [SUCCESS] prune_docker_system test complete.")
    except Exception as e:
        print(f" [ERROR] Error testing prune_docker_system: {e}")

    print("\n=========================================")
    print("   All monitor tests executed.           ")
    print("=========================================")

if __name__ == "__main__":
    main()
