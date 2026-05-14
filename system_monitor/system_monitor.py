#!/usr/bin/env python3
"""
macOS System Monitor & Diagnostic Tool
Optimized for Early 2015 MacBook Air running macOS Monterey.
Requires no external dependencies. Use 'sudo' for thermal data.
"""

import subprocess
import os
import re
import sys

class Colors:
    """ANSI color codes for terminal formatting."""
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class MacMonitor:
    def __init__(self):
        self.is_root = os.geteuid() == 0

    def _run_cmd(self, cmd, silent=True):
        """Helper to run shell commands safely and return decoded output."""
        try:
            stderr = subprocess.DEVNULL if silent else None
            return subprocess.check_output(cmd, shell=True, stderr=stderr).decode('utf-8').strip()
        except Exception:
            return ""

    def _draw_bar(self, percent, width=30):
        """Draws a visual progress bar based on percentage."""
        try:
            percent = float(percent)
            filled = int((percent / 100) * width)
            color = Colors.GREEN if percent < 60 else (Colors.YELLOW if percent < 85 else Colors.RED)
            return f"{color}{'█' * filled}{Colors.RESET}{'░' * (width - filled)}"
        except ValueError:
            return f"{Colors.YELLOW}[Bar Error]{Colors.RESET}"

    # --- Basic Metrics ---

    def get_cpu_load(self):
        """Fetches active CPU usage."""
        out = self._run_cmd("top -l 2 -n 0 -F | grep 'CPU usage' | tail -1")
        if out:
            try:
                idle = float(out.split(',')[2].split('%')[0].strip())
                return 100.0 - idle
            except IndexError:
                pass
        return 0.0

    def get_memory_stats(self):
        """Fetches physical memory usage."""
        out = self._run_cmd("top -l 1 -n 0 | grep 'PhysMem'")
        if out:
            try:
                used = int(re.search(r'(\d+)M used', out).group(1))
                unused = int(re.search(r'(\d+)M unused', out).group(1))
                total = used + unused
                return (used / total) * 100, used / 1024, total / 1024
            except (AttributeError, ZeroDivisionError):
                pass
        return 0.0, 0.0, 0.0

    def get_battery_stats(self):
        """Fetches battery charge, status, and cycle count."""
        batt_out = self._run_cmd("pmset -g batt")
        pct, status, cycles = 0, "Unknown", 0
        
        if batt_out:
            match = re.search(r'(\d+)%', batt_out)
            if match:
                pct = int(match.group(1))
            
            if "charging" in batt_out and "discharging" not in batt_out:
                status = f"{Colors.GREEN}Charging{Colors.RESET}"
            elif "discharging" in batt_out:
                status = f"{Colors.YELLOW}Discharging{Colors.RESET}"
            elif "charged" in batt_out:
                status = f"{Colors.GREEN}Fully Charged{Colors.RESET}"

        sp_out = self._run_cmd("system_profiler SPPowerDataType | grep 'Cycle Count'")
        if sp_out:
            try:
                cycles = int(sp_out.split(':')[1].strip())
            except IndexError:
                pass
                
        return pct, status, cycles

    def get_temperature(self):
        """Fetches SMC thermal data via powermetrics."""
        if not self.is_root:
            return f"{Colors.YELLOW}[Requires sudo]{Colors.RESET}"
            
        out = self._run_cmd("powermetrics --samplers smc -n 1")
        temp_line = [line for line in out.split('\n') if 'CPU die temperature' in line]
        
        if temp_line:
            temp_str = temp_line[0].split(':')[1].strip()
            try:
                num_temp = float(re.search(r'(\d+\.\d+)', temp_str).group(1))
                color = Colors.GREEN if num_temp < 60 else (Colors.YELLOW if num_temp < 85 else Colors.RED)
                return f"{color}{temp_str}{Colors.RESET}"
            except AttributeError:
                return temp_str
        return "N/A"

    # --- Deep Dive Metrics ---

    def get_swap_usage(self):
        out = self._run_cmd("sysctl vm.swapusage")
        match = re.search(r'used = (\d+\.\d+[A-Z])', out)
        return f"{Colors.YELLOW}{match.group(1)}{Colors.RESET}" if match else "Error"

    def get_load_average(self):
        out = self._run_cmd("sysctl vm.loadavg")
        if out:
            return out.split('{')[1].split('}')[0].strip()
        return "Error"

    def get_ssd_health(self):
        out = self._run_cmd("diskutil info disk0 | grep 'SMART Status'")
        if out:
            status = out.split(':')[1].strip()
            color = Colors.GREEN if status == "Verified" else Colors.RED
            return f"{color}{status}{Colors.RESET}"
        return f"{Colors.YELLOW}Not Available{Colors.RESET}"

    # --- Process Culprits ---

    def get_process_hogs(self, sort_by="cpu", limit=5):
        """Fetches top processes by CPU or Memory and parses exact script/app names."""
        # Switched 'comm' to 'command' to grab full execution arguments
        if sort_by == "cpu":
            cmd = "ps -eo pcpu,pid,command | sort -k 1 -nr"
        else:
            cmd = "ps -eo rss,pid,command | sort -k 1 -nr"
            
        out = self._run_cmd(cmd)
        lines = out.split('\n')
        
        # Filter valid lines starting with numbers
        valid_lines = [line for line in lines if line.strip() and line.strip()[0].isdigit()]
        
        results = []
        for line in valid_lines[:limit]:
            # Split into max 3 parts: Value, PID, Full Command String
            parts = line.split(maxsplit=2)
            if len(parts) == 3:
                val, pid, cmd_str = parts
                
                # --- INTELLIGENT PARSING ---
                if ".app/" in cmd_str:
                    # Clean up GUI Mac Apps (e.g., TradingView)
                    match = re.search(r'([^\/]+)\.app', cmd_str)
                    clean_name = match.group(1) if match else "App"
                    if "Helper" in cmd_str:
                        clean_name += " Helper"
                else:
                    # Clean up Terminal Commands (Python, Bash)
                    cmd_parts = cmd_str.split()
                    exec_name = cmd_parts[0].split('/')[-1] # Gets 'python3.13' or 'bash'
                    
                    if 'python' in exec_name.lower() or 'bash' in exec_name.lower():
                        # Grab the next argument as the script name
                        if len(cmd_parts) > 1 and not cmd_parts[1].startswith('-'):
                            script_name = cmd_parts[1].split('/')[-1]
                            clean_name = f"{exec_name} [{script_name}]"
                        else:
                            clean_name = exec_name
                    else:
                        clean_name = exec_name
                
                # --- FORMATTING OUTPUT ---
                if sort_by == "cpu":
                    try:
                        cpu = float(val)
                        color = Colors.RED if cpu > 50 else (Colors.YELLOW if cpu > 20 else Colors.GREEN)
                        results.append(f"  {color}{cpu:>7.1f} %{Colors.RESET}  PID: {pid:<5} {clean_name}")
                    except ValueError:
                        pass
                else:
                    try:
                        mb = float(val) / 1024
                        color = Colors.RED if mb > 1000 else (Colors.YELLOW if mb > 500 else Colors.GREEN)
                        results.append(f"  {color}{mb:>7.1f} MB{Colors.RESET}  PID: {pid:<5} {clean_name}")
                    except ValueError:
                        pass
        return results

    # --- Display / Report Generation ---

    def print_report(self):
        print(f"\n{Colors.BOLD}{Colors.CYAN}=== macOS System Monitor & Diagnostics ==={Colors.RESET}\n")
        print("Gathering metrics... (takes ~1 second for CPU sampling)\n")

        # 1. Basic Status
        cpu_pct = self.get_cpu_load()
        mem_pct, mem_used, mem_total = self.get_memory_stats()
        batt_pct, batt_status, batt_cycles = self.get_battery_stats()
        temp = self.get_temperature()

        print(f"{Colors.BOLD}--- Core Hardware ---{Colors.RESET}")
        print(f"CPU Load:    {self._draw_bar(cpu_pct)}  {cpu_pct:>5.1f}%")
        print(f"RAM Usage:   {self._draw_bar(mem_pct)}  {mem_pct:>5.1f}% ({mem_used:.1f}GB / {mem_total:.1f}GB)")
        
        batt_color = Colors.GREEN if batt_pct > 50 else (Colors.YELLOW if batt_pct > 20 else Colors.RED)
        print(f"Battery:     {self._draw_bar(batt_pct)}  {batt_color}{batt_pct}%{Colors.RESET} [{batt_status}]")
        print(f"Cycles:      {batt_cycles}")
        print(f"CPU Heat:    {temp}\n")

        # 2. Deep Dive
        print(f"{Colors.BOLD}--- System Bottlenecks ---{Colors.RESET}")
        print(f"Swap Used:   {self.get_swap_usage()} (High swap = heavy SSD reliance)")
        print(f"Load Avg:    {self.get_load_average()} (1m, 5m, 15m queue)")
        print(f"SSD Health:  {self.get_ssd_health()}\n")

        # 3. Process Hogs
        print(f"{Colors.BOLD}--- Top 5 CPU Culprits ---{Colors.RESET}")
        for proc in self.get_process_hogs(sort_by="cpu", limit=5):
            print(proc)
            
        print(f"\n{Colors.BOLD}--- Top 5 RAM Culprits (Physical) ---{Colors.RESET}")
        for proc in self.get_process_hogs(sort_by="mem", limit=5):
            print(proc)
            
        print("\n")


if __name__ == "__main__":
    monitor = MacMonitor()
    monitor.print_report()