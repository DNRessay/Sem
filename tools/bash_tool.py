import asyncio
import re

# ─── 23 Security Checks ──────────────────────────────────────────────────────

def _check_no_rm_rf(cmd):                return not re.search(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f|rm\s+-[a-zA-Z]*f[a-zA-Z]*r", cmd)
def _check_no_fork_bomb(cmd):            return ":(){" not in cmd and ":(){ :|:& };" not in cmd
def _check_no_curl_pipe_sh(cmd):         return not re.search(r"curl.+\|\s*(ba)?sh", cmd)
def _check_no_sudo(cmd):                 return not re.search(r"\bsudo\b", cmd)
def _check_no_passwd_access(cmd):        return "/etc/passwd" not in cmd and "/etc/shadow" not in cmd
def _check_no_env_exfil(cmd):            return not re.search(r"env\s*>\s*/dev/tcp|nc\s+-e|bash\s+-i\s+>&", cmd)
def _check_no_network_bypass(cmd):       return not re.search(r"iptables\s+-F|ufw\s+disable|firewall-cmd.*--flush", cmd)
def _check_no_write_outside_workspace(cmd): return not re.search(r">\s*/etc/|>\s*/bin/|>\s*/usr/|>\s*/root/", cmd)
def _check_no_kill_signals(cmd):         return not re.search(r"kill\s+-9\s+1|killall\s+-9|pkill\s+-9\s+-f\s+(python|uvicorn|semblance)", cmd)
def _check_no_cron_edit(cmd):            return "crontab" not in cmd and "/etc/cron" not in cmd
def _check_no_dd_wipe(cmd):              return not re.search(r"dd\s+if=/dev/zero|dd\s+if=/dev/random.*of=/dev", cmd)
def _check_no_history_clear(cmd):        return "history -c" not in cmd and "> ~/.bash_history" not in cmd
def _check_no_ssh_key_tampering(cmd):    return "authorized_keys" not in cmd and not re.search(r">\s*~/.ssh/", cmd)
def _check_no_chmod_777_root(cmd):       return not re.search(r"chmod\s+777\s+/", cmd)
def _check_no_python_exec_eval(cmd):     return not re.search(r"python[23]?\s+-c\s+[\"'].*exec\(|eval\(", cmd)
def _check_no_wget_pipe_sh(cmd):         return not re.search(r"wget.+\|\s*(ba)?sh", cmd)
def _check_no_base64_decode_exec(cmd):   return not re.search(r"base64\s+-d.*\|\s*(ba)?sh", cmd)
def _check_no_mount_ops(cmd):            return not re.search(r"\bmount\b|\bumount\b", cmd)
def _check_no_disk_format(cmd):          return not re.search(r"\bmkfs\b|\bfdisk\b|\bparted\b", cmd)
def _check_no_suid_bit(cmd):             return not re.search(r"chmod\s+[ugoa]*s", cmd)
def _check_no_raw_socket(cmd):           return not re.search(r"python.*socket\.SOCK_RAW|nc\s+-u\s+-l", cmd)
def _check_no_coredump_exploit(cmd):     return "ulimit -c unlimited" not in cmd and "/proc/sysrq-trigger" not in cmd
def _check_no_kernel_module(cmd):        return not re.search(r"\binsmod\b|\bmodprobe\b|\brmmod\b", cmd)


SECURITY_CHECKS = [
    ("no_rm_rf",               _check_no_rm_rf),
    ("no_fork_bomb",           _check_no_fork_bomb),
    ("no_curl_pipe_sh",        _check_no_curl_pipe_sh),
    ("no_sudo",                _check_no_sudo),
    ("no_passwd_access",       _check_no_passwd_access),
    ("no_env_exfil",           _check_no_env_exfil),
    ("no_network_bypass",      _check_no_network_bypass),
    ("no_write_outside_workspace", _check_no_write_outside_workspace),
    ("no_kill_signals",        _check_no_kill_signals),
    ("no_cron_edit",           _check_no_cron_edit),
    ("no_dd_wipe",             _check_no_dd_wipe),
    ("no_history_clear",       _check_no_history_clear),
    ("no_ssh_key_tampering",   _check_no_ssh_key_tampering),
    ("no_chmod_777_root",      _check_no_chmod_777_root),
    ("no_python_exec_eval",    _check_no_python_exec_eval),
    ("no_wget_pipe_sh",        _check_no_wget_pipe_sh),
    ("no_base64_decode_exec",  _check_no_base64_decode_exec),
    ("no_mount_ops",           _check_no_mount_ops),
    ("no_disk_format",         _check_no_disk_format),
    ("no_suid_bit",            _check_no_suid_bit),
    ("no_raw_socket",          _check_no_raw_socket),
    ("no_coredump_exploit",    _check_no_coredump_exploit),
    ("no_kernel_module",       _check_no_kernel_module),
]

assert len(SECURITY_CHECKS) == 23, f"Expected 23 security checks, got {len(SECURITY_CHECKS)}"


class BashTool:
    """
    Shell command executor.
    Every command passes through 23 security checks before execution.
    """

    async def execute(self, command: str, trust_mode: str = "AUTO", timeout: int = 30) -> dict:
        failures = self._run_security_checks(command)
        if failures:
            return {
                "blocked": True,
                "failed_checks": failures,
                "command": command,
                "error": f"Command blocked by security gate: {', '.join(failures)}",
            }

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "blocked": False,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "exit_code": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"blocked": False, "error": f"Command timed out after {timeout}s", "exit_code": -1}
        except Exception as e:
            return {"blocked": False, "error": str(e), "exit_code": -1}

    def _run_security_checks(self, command: str) -> list[str]:
        """Run all 23 checks. Return names of failed checks (empty = all passed)."""
        failed = []
        for name, check_fn in SECURITY_CHECKS:
            try:
                if not check_fn(command):
                    failed.append(name)
            except Exception:
                failed.append(f"{name}_error")
        return failed
