"""LisiOS Game Mode: общая часть (настройки, обнаружение игр, демон, командная строка). Работает от обычного пользователя."""
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = "/usr/lib/lisios/gamemode/helper.py"
MAX_GAMES = 3
CONF = os.path.join(os.path.expanduser("~"), ".config/lisios/gamemode.json")
RUN = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
STATUS = os.path.join(RUN, "lisios-gamemode-%d.json" % os.getuid()) if RUN == "/tmp" else os.path.join(RUN, "lisios-gamemode.json")
LOCK = STATUS + ".lock"
DEFAULT = {"enabled": False, "auto": False, "games": [],
           "protect": ["discord", "vesktop", "mumble", "teamspeak", "obs"]}
GENERIC = {"sh", "bash", "zsh", "python", "python3", "java", "wine", "wine64", "steam", "env", "flatpak", "kitty",
           "firefox", "hyprland", "quickshell", "systemd", "dbus", "node", "electron"}
TICK_IDLE = 1.0
TICK_ACTIVE = 2.0
REAPPLY = 6.0
GRACE = 5.0
HI, LO, LO_HOLD = 65.0, 40.0, 6.0   # гистерезис нагрузки: включать приоритеты фону при >=65 %, снимать при <=40 % дольше 6 с


# ------------------------------------------------------------------ настройки
def load_conf():
    c = dict(DEFAULT)
    try:
        c.update(json.load(open(CONF)))
    except (OSError, ValueError):
        pass
    games = []
    for g in c.get("games") or []:
        if isinstance(g, dict) and g.get("name") and (g.get("exec") or g.get("match")):
            games.append({"name": str(g["name"]), "exec": str(g.get("exec") or ""),
                          "match": [str(m) for m in (g.get("match") or [])]})
    c["games"] = games[:MAX_GAMES]
    c["enabled"], c["auto"] = bool(c.get("enabled")), bool(c.get("auto"))
    return c


def save_conf(c):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONF)


def valid_game(g):
    """Не даём добавить слишком общее имя (python, bash...) - иначе «игрой» станет полсистемы."""
    keys = [m.lower() for m in g.get("match", [])]
    if g.get("exec"):
        keys.append(os.path.basename(g["exec"]).lower())
    return bool(keys) and all(len(k) >= 4 and k not in GENERIC for k in keys)


def add_game(c, g):
    if len(c["games"]) >= MAX_GAMES:
        return "limit"
    if not valid_game(g):
        return "generic"
    if any(x["name"] == g["name"] for x in c["games"]):
        return "dup"
    c["games"].append(g)
    return ""


# ------------------------------------------------------------------ процессы
def scan():
    """Процессы текущего пользователя: pid -> dict"""
    uid, out = os.getuid(), {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat("/proc/" + d).st_uid != uid:
                continue
            s = open("/proc/%s/stat" % d).read()
            a = s.rfind(")")
            f = s[a + 2:].split()
            argv = [x for x in open("/proc/%s/cmdline" % d, "rb").read().decode("utf-8", "replace").split("\0") if x]
            try:
                exe = os.readlink("/proc/%s/exe" % d)
            except OSError:
                exe = ""
        except (OSError, IndexError):
            continue
        out[int(d)] = {"pid": int(d), "comm": s[s.find("(") + 1:a], "ppid": int(f[1]), "cpu": int(f[11]) + int(f[12]),
                       "argv": argv, "exe": exe,
                       "cl": " ".join(argv).replace("\\", "/").lower()}
    return out


def matches(g, p):
    c = p["comm"].lower()
    if c.startswith(("lisios-", "gamemode", "hyprland", "quickshell")):
        return False
    for m in g["match"]:
        m = m.replace("\\", "/").lower()
        if m and (m in p["cl"] or m == c):
            return True
    ex = g.get("exec")
    if ex:
        base = os.path.basename(ex).lower()
        if base and (os.path.basename(p["exe"]).lower() == base or c == base[:15] or
                     any(os.path.basename(a.replace("\\", "/")).lower() == base for a in p["argv"][:4])):
            return True
    return False


def game_pids(games, procs):
    """-> {имя игры: set(pid)} (совпавшие процессы и все их потомки)"""
    kids = {}
    for p in procs.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    res = {}
    for g in games:
        roots = [p["pid"] for p in procs.values() if matches(g, p)]
        seen, stack = set(), list(roots)
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(kids.get(x, []))
        res[g["name"]] = seen
    return res


class Cpu:
    """Нагрузка CPU по /proc/stat и доля процессорного времени игровых процессов (в % от всей машины)"""
    def __init__(self):
        self.t = self.i = None
        self.load = 0.0
        self.prev = {}

    def read(self):
        f = open("/proc/stat").readline().split()[1:]
        v = [int(x) for x in f[:8]]
        return sum(v), v[3] + v[4]

    def update(self, procs, pids):
        total, idle = self.read()
        dt = di = 0
        if self.t is not None:
            dt, di = total - self.t, idle - self.i
            if dt > 0:
                self.load = max(0.0, min(100.0, 100.0 * (dt - di) / dt))
        self.t, self.i = total, idle
        cur = {p: procs[p]["cpu"] for p in pids if p in procs}
        used = sum(max(0, cur[p] - self.prev.get(p, cur[p])) for p in cur)
        self.prev = cur
        return self.load, (min(100.0, 100.0 * used / dt) if dt > 0 else 0.0)


# ------------------------------------------------------------------ помощник (root через pkexec)
def helper(*args):
    try:
        r = subprocess.run(["pkexec", HELPER, *args], capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {"ok": False}


def write_status(d):
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATUS)


def read_status():
    try:
        return json.load(open(STATUS))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ демон
def daemon():
    lk = open(LOCK, "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0                       # уже запущен
    stop = []
    applied = False

    def bye(*_):
        stop.append(1)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    # аварийное восстановление после предыдущего сбоя
    if os.path.exists("/run/lisios-gamemode/%d.json" % os.getuid()):
        helper("restore")

    cpu = Cpu()
    privilege = True
    last_apply = 0.0
    last_key = None
    gone_since = None
    low_since = None
    throttling = False
    next_priv_try = 0.0
    last_out = None
    while not stop:
        conf = load_conf()
        want = conf["enabled"] or conf["auto"]
        out = {"v": 1, "enabled": conf["enabled"], "auto": conf["auto"], "active": False, "state": "off",
               "cpu": 0.0, "game_cpu": 0.0, "throttling": False, "privilege": privilege,
               "games": [{"name": g["name"], "running": False} for g in conf["games"]], "ts": int(time.time())}
        now = time.monotonic()
        if not want or not conf["games"]:
            if applied:
                helper("restore")
                applied = False
            throttling = False
            out["state"] = "off" if not want else "waiting"
            out["privilege"] = privilege
        else:
            procs = scan()
            gp = game_pids(conf["games"], procs)
            allp = set().union(*gp.values()) if gp else set()
            for g in out["games"]:
                g["running"] = bool(gp.get(g["name"]))
            load, gcpu = cpu.update(procs, allp)
            out["cpu"], out["game_cpu"] = round(load, 1), round(gcpu, 1)
            if allp:
                gone_since = None
                out["active"] = True
                out["state"] = "active"
                if load >= HI:
                    throttling, low_since = True, None
                elif load <= LO and throttling:
                    low_since = low_since or now
                    if now - low_since >= LO_HOLD:
                        throttling, low_since = False, None
                else:
                    low_since = None
                key = (tuple(sorted(allp)), throttling)
                if privilege or now >= next_priv_try:
                    if key != last_key or now - last_apply >= REAPPLY:
                        args = ["apply", "--games", ",".join(map(str, sorted(allp))),
                                "--protect", ",".join(conf.get("protect") or [])]
                        if throttling:
                            args.append("--throttle")
                        r = helper(*args)
                        last_apply, last_key = now, key
                        if r.get("ok"):
                            privilege, applied = True, True
                            out["boosted"] = r.get("game_threads", 0)
                            out["throttled"] = r.get("throttled_threads", 0)
                        else:
                            privilege, next_priv_try = False, now + 30
                out["throttling"] = throttling and privilege
                out["privilege"] = privilege
                if not privilege:
                    out["state"] = "no_privilege"
                elif throttling:
                    out["state"] = "throttling"
            else:
                out["state"] = "waiting"
                if applied:
                    gone_since = gone_since or now
                    if now - gone_since >= GRACE:     # игра закрылась (или упала) - возвращаем обычный режим
                        helper("restore")
                        applied, last_key, throttling, gone_since = False, None, False, None
        cmp = {k: v for k, v in out.items() if k != "ts"}
        if cmp != last_out or int(time.time()) % 10 == 0:
            write_status(out)
            last_out = cmp
        time.sleep(TICK_ACTIVE if (want and conf["games"]) else TICK_IDLE)
    if applied or os.path.exists("/run/lisios-gamemode/%d.json" % os.getuid()):
        helper("restore")
    try:
        write_status({"v": 1, "enabled": load_conf()["enabled"], "active": False, "state": "stopped", "games": []})
    except OSError:
        pass
    return 0


def ensure_daemon():
    """Запустить демон, если он ещё не работает (дубликат сам завершится из-за блокировки)."""
    subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "run.py"), "daemon"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def cli(argv):
    a = argv[1:] or ["status"]
    c = a[0]
    if c == "daemon":
        return daemon()
    conf = load_conf()
    if c in ("on", "off", "toggle"):
        conf["enabled"] = (not conf["enabled"]) if c == "toggle" else c == "on"
        save_conf(conf)
        ensure_daemon()
        print("enabled" if conf["enabled"] else "disabled")
    elif c == "auto" and len(a) > 1 and a[1] in ("on", "off"):
        conf["auto"] = a[1] == "on"
        save_conf(conf)
        ensure_daemon()
    elif c == "ensure":
        ensure_daemon()
    elif c == "restore":                       # аварийное восстановление исходных приоритетов
        conf["enabled"] = False
        save_conf(conf)
        print(json.dumps(helper("restore")))
    elif c == "status":
        print(json.dumps(read_status() or {"state": "off"}, ensure_ascii=False))
    elif c == "add" and len(a) >= 3:           # add "Имя" /путь/к/игре [подстрока-в-командной-строке ...]
        g = {"name": a[1], "exec": a[2] if "/" in a[2] or "." in a[2] else a[2], "match": a[3:]}
        r = add_game(conf, g)
        if r:
            print("ошибка:", r)
            return 1
        save_conf(conf)
    elif c == "remove" and len(a) > 1:
        conf["games"] = [g for g in conf["games"] if g["name"] != a[1]]
        save_conf(conf)
    elif c == "gui":
        sys.path.insert(0, HERE)
        import app
        return app.main()
    else:
        print("lisios-gamemode [status|on|off|toggle|auto on|off|add ИМЯ ФАЙЛ [строки]|remove ИМЯ|restore|gui|daemon]")
        return 2
    return 0
