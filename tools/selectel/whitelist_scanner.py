#!/usr/bin/env python3
"""
Selectel Floating IP Scanner v3
Чередует регионы ru-2 (Москва) и ru-3 (Санкт-Петербург).
"""

import dataclasses
import itertools
import json
import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import ssl
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv, set_key


# ---------------------------------------------------------------------------
# TLS-адаптер (Python 3.12+ совместимость с selcloud.ru)
# ---------------------------------------------------------------------------

class _TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _TLSAdapter())
    return s


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent
SEL_AUTH_URL   = "https://cloud.api.selcloud.ru/identity/v3/auth/tokens"
REGIONS      = ["ru-2", "ru-3"]

PING_INTERNET_HOST  = "ya.ru"
PING_WHITELIST_HOST = "1.1.1.1"
PING_COUNT    = 3
PING_TIMEOUT  = 5
CURL_SNI      = "m.vk.com"   # SNI для curl-проверки
CURL_TIMEOUT  = 10          # секунды на curl

FIP_SETTLE_TIME   = 15
API_RETRY_PAUSE   = 30
WAIT_NO_INTERNET  = 60
WAIT_NO_WHITELIST = 60
DUPLICATE_PAUSE   = 600  # пауза если в батче есть дубли

VM_STATUS_POLL     = 10
VM_STATUS_ATTEMPTS = 18

BLACKLIST_FILE = str(PROJECT_ROOT / "subnet_blacklist.json")
ENV_FILE       = str(PROJECT_ROOT / ".env")

load_dotenv(ENV_FILE)

WIFI_IFACE    = os.getenv("WIFI_INTERFACE", "wlp3s0")
STOP_ON_FOUND = os.getenv("STOP_ON_FOUND", "true").lower() == "true"
BATCH_SIZE    = max(1, min(10, int(os.getenv("BATCH_SIZE",  "5"))))
ITER_PAUSE    = max(10, min(300, int(os.getenv("ITER_PAUSE", "120"))))

# ---------------------------------------------------------------------------
# Логирование: файл=INFO, консоль=WARNING + cprint
# ---------------------------------------------------------------------------

_file_handler = logging.FileHandler(PROJECT_ROOT / "ip_scanner.log", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

_con_handler = logging.StreamHandler(sys.stdout)
_con_handler.setLevel(logging.WARNING)
_con_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _con_handler])
log = logging.getLogger(__name__)


def cprint(msg: str) -> None:
    """Важное сообщение: всегда в консоль + в лог."""
    print(msg)
    log.info(msg)


# ---------------------------------------------------------------------------
# Состояние одного региона
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RegionState:
    region:      str
    server_id:   str
    neutron_url: str | None = None
    nova_url:    str | None = None
    ext_net_id:  str | None = None
    vm_port_id:  str | None = None

    @property
    def env_key(self) -> str:
        """Суффикс для ключей .env, напр. 'RU2' для 'ru-2'."""
        return self.region.upper().replace("-", "")

    def load_cached_urls(self) -> None:
        """Подгружает закешированные URL из .env."""
        k = self.env_key
        self.neutron_url = os.getenv(f"SEL_NEUTRON_URL_{k}") or None
        self.nova_url    = os.getenv(f"SEL_NOVA_URL_{k}")    or None

    def save_urls(self) -> None:
        """Кеширует URL в .env."""
        k = self.env_key
        if self.neutron_url:
            set_key(ENV_FILE, f"SEL_NEUTRON_URL_{k}", self.neutron_url)
        if self.nova_url:
            set_key(ENV_FILE, f"SEL_NOVA_URL_{k}", self.nova_url)

    def ready(self) -> bool:
        return bool(self.neutron_url and self.nova_url)


# ---------------------------------------------------------------------------
# Чёрный список IP-адресов
# ---------------------------------------------------------------------------

class IPBlacklist:
    def __init__(self, path: str = BLACKLIST_FILE) -> None:
        self.path = path
        self._ips: set[str] = set()
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                # Поддержка старого формата (subnets) и нового (ips)
                self._ips = set(data.get("ips", data.get("subnets", [])))
                if self._ips:
                    log.info(f"Чёрный список: {len(self._ips)} IP из {self.path}")
            except Exception as e:
                log.warning(f"Не удалось загрузить {self.path}: {e}")
                self._ips = set()

    def _save(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump(
                    {"ips": sorted(self._ips),
                     "updated": datetime.now(timezone.utc).isoformat()},
                    f, indent=2,
                )
        except Exception as e:
            log.error(f"Не удалось сохранить чёрный список: {e}")

    def is_blocked(self, ip: str) -> bool:
        return ip in self._ips

    def add(self, ip: str) -> None:
        if ip not in self._ips:
            self._ips.add(ip)
            self._save()
            log.info(f"IP {ip} -> чёрный список ({len(self._ips)} всего)")

    def __len__(self) -> int:
        return len(self._ips)

    def list_all(self) -> list:
        return sorted(self._ips)


# ---------------------------------------------------------------------------
# Белый список IP/подсетей (whitelist.txt)
# ---------------------------------------------------------------------------

import ipaddress as _ipaddress

WHITELIST_FILE = str(PROJECT_ROOT / "resources" / "selectel" / "whitelist.txt")


class IPWhitelist:
    """
    Загружает whitelist.txt — список IP и подсетей CIDR.
    Если IP совпадает — считается рабочим без сетевых проверок.

    Формат (по строке, # — комментарий):
        1.2.3.4
        5.6.7.0/24
    """

    def __init__(self, path: str = WHITELIST_FILE) -> None:
        self.path = path
        self._networks: list = []
        self._ips: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            log.info(f"whitelist.txt не найден ({self.path}) — работаем без него")
            return
        count = 0
        with open(self.path, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    if "/" in line:
                        self._networks.append(_ipaddress.IPv4Network(line, strict=False))
                    else:
                        self._ips.add(line)
                    count += 1
                except ValueError:
                    log.warning(f"Whitelist: неверная запись '{line}' — пропускаем")
        if count:
            cprint(f"Whitelist: загружено {count} записей из {self.path}")

    def contains(self, ip: str) -> bool:
        if ip in self._ips:
            return True
        try:
            addr = _ipaddress.IPv4Address(ip)
            return any(addr in net for net in self._networks)
        except ValueError:
            return False

    def __len__(self) -> int:
        return len(self._ips) + len(self._networks)


# ---------------------------------------------------------------------------
# Сетевые проверки
# ---------------------------------------------------------------------------

def ping(host: str, iface=None, count: int = PING_COUNT, timeout: int = PING_TIMEOUT) -> bool:
    cmd = ["ping", "-c", str(count), "-W", str(timeout)]
    if iface:
        cmd += ["-I", iface]
    cmd.append(host)
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def curl_check(ip: str, iface: str | None = None, timeout: int = CURL_TIMEOUT) -> bool:
    """Проверка через curl: https://<SNI> с подстановкой IP через --connect-to."""
    cmd = [
        "curl", "-s", "-o", "/dev/null",
        "--max-time", str(timeout),
        "--connect-to", f"::{ip}:443",
        f"https://{CURL_SNI}",
    ]
    if iface:
        cmd += ["--interface", iface]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def check_ip(ip: str, iface: str | None = None) -> tuple[bool, str]:
    """
    Проверяет IP двумя методами: ICMP ping и curl.
    Возвращает (прошла_ли_хоть_одна, описание результата).
    """
    icmp_ok = ping(ip, iface=iface, count=5, timeout=5)
    curl_ok = curl_check(ip, iface=iface)
    ok = icmp_ok or curl_ok
    method = []
    if icmp_ok: method.append("ICMP")
    if curl_ok: method.append("curl")
    desc = "+".join(method) if method else "none"
    return ok, desc


def check_internet() -> bool:
    return ping(PING_INTERNET_HOST, iface=WIFI_IFACE)


def check_whitelist_active() -> bool:
    return not ping(PING_WHITELIST_HOST, iface=WIFI_IFACE)


def wait_for_internet() -> None:
    while True:
        log.info(f"Проверка интернета ({PING_INTERNET_HOST})...")
        if check_internet():
            log.info("Интернет: OK")
            return
        log.warning(f"Интернет недоступен. Жду {WAIT_NO_INTERNET}с...")
        time.sleep(WAIT_NO_INTERNET)


def wait_for_whitelist() -> None:
    while True:
        log.info(f"Проверка белого списка ({PING_WHITELIST_HOST})...")
        if check_whitelist_active():
            log.info("Белый список: ВКЛЮЧЁН")
            return
        log.warning(f"Белый список ВЫКЛЮЧЕН. Жду {WAIT_NO_WHITELIST}с...")
        time.sleep(WAIT_NO_WHITELIST)
        wait_for_internet()


def run_prechecks() -> None:
    wait_for_internet()
    wait_for_whitelist()


def get_network_status() -> tuple[bool, bool]:
    """
    Неблокирующая проверка сети.
    Возвращает (internet_ok, whitelist_on).
    Если нет интернета — whitelist_on всегда False.
    """
    internet_ok  = check_internet()
    whitelist_on = check_whitelist_active() if internet_ok else False
    return internet_ok, whitelist_on


def countdown_sleep(seconds: int, label: str = "Следующая итерация") -> None:
    log.info(f"{label} через {seconds}с ({seconds // 60}м {seconds % 60}с)...")
    for remaining in range(seconds, 0, -10):
        if remaining <= 10:
            cprint(f"  ... {remaining}с")
            time.sleep(remaining)
            break
        cprint(f"  ... {remaining}с")
        time.sleep(10)


# ---------------------------------------------------------------------------
# Клиент Selectel
# ---------------------------------------------------------------------------

class SelectelClient:
    def __init__(self, regions: list[RegionState]) -> None:
        required = {
            "SEL_USERNAME":     "логин сервисного пользователя",
            "SEL_PASSWORD":     "пароль сервисного пользователя",
            "SEL_ACCOUNT_ID":   "ID аккаунта (числовой, 6 цифр)",
            "SEL_PROJECT_NAME": "имя проекта",
        }
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            for k in missing:
                log.error(f"Не задана переменная {k} ({required[k]})")
            sys.exit(1)

        self.username     = os.getenv("SEL_USERNAME")
        self.password     = os.getenv("SEL_PASSWORD")
        self.account_id   = os.getenv("SEL_ACCOUNT_ID")
        self.project_name = os.getenv("SEL_PROJECT_NAME")

        self.token: str | None = os.getenv("SEL_TOKEN") or None
        self.token_expires: datetime | None = None
        exp_str = os.getenv("SEL_TOKEN_EXPIRES")
        if exp_str:
            try:
                dt = datetime.fromisoformat(exp_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                self.token_expires = dt
            except ValueError:
                pass

        # Регионы: dict region_name -> RegionState
        self._regions: dict[str, RegionState] = {r.region: r for r in regions}
        for r in regions:
            r.load_cached_urls()

        self._s = _session()

    # --- Токен ---

    def _token_valid(self) -> bool:
        if not self.token or not self.token_expires:
            return False
        return datetime.now(timezone.utc) < self.token_expires - timedelta(minutes=5)

    def authenticate(self) -> None:
        log.info("Аутентификация в Selectel Keystone...")
        for domain_key in ("name", "id"):
            payload = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": self.username,
                                "password": self.password,
                                "domain": {domain_key: self.account_id},
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": self.project_name,
                            "domain": {"name": self.account_id},
                        }
                    },
                }
            }
            resp = self._s.post(SEL_AUTH_URL, json=payload, timeout=30)
            if resp.status_code == 401:
                log.warning(f"401 с domain key='{domain_key}': {resp.text[:200]}")
                continue
            resp.raise_for_status()
            break
        else:
            log.error("Аутентификация не удалась. Проверь SEL_USERNAME, SEL_PASSWORD, "
                      "SEL_ACCOUNT_ID, SEL_PROJECT_NAME")
            raise requests.HTTPError("Authentication failed (401)")

        self.token = resp.headers["X-Subject-Token"]
        body = resp.json()
        exp_raw = body["token"]["expires_at"].rstrip("Z")
        self.token_expires = datetime.fromisoformat(exp_raw).replace(tzinfo=timezone.utc)

        # Парсим service catalog — заполняем URL для каждого известного региона
        for service in body["token"].get("catalog", []):
            stype = service.get("type")
            for ep in service.get("endpoints", []):
                region = ep.get("region_id")
                if ep.get("interface") != "public" or region not in self._regions:
                    continue
                url = ep["url"].rstrip("/")
                rs = self._regions[region]
                if stype == "network" and not rs.neutron_url:
                    rs.neutron_url = url
                elif stype == "compute" and not rs.nova_url:
                    rs.nova_url = url

        # Проверяем что все регионы получили URL
        for rs in self._regions.values():
            if not rs.ready():
                raise RuntimeError(
                    f"Не найдены endpoints для региона {rs.region} в service catalog"
                )
            rs.save_urls()

        set_key(ENV_FILE, "SEL_TOKEN",        self.token)
        set_key(ENV_FILE, "SEL_TOKEN_EXPIRES", self.token_expires.isoformat())
        log.info(f"Аутентификация OK. Токен до {self.token_expires}")

    def ensure_auth(self) -> None:
        if not self._token_valid():
            self.authenticate()

    def _h(self) -> dict:
        return {"X-Auth-Token": self.token, "Content-Type": "application/json"}

    def _rs(self, region: str) -> RegionState:
        return self._regions[region]

    # --- VM управление ---

    def get_server_status(self, region: str) -> str:
        self.ensure_auth()
        rs = self._rs(region)
        resp = self._s.get(
            f"{rs.nova_url}/servers/{rs.server_id}",
            headers=self._h(), timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["server"]["status"]

    def _server_action(self, region: str, action: dict, name: str) -> None:
        self.ensure_auth()
        rs = self._rs(region)
        resp = self._s.post(
            f"{rs.nova_url}/servers/{rs.server_id}/action",
            headers=self._h(), json=action, timeout=30,
        )
        resp.raise_for_status()
        log.info(f"[{region}] VM: команда '{name}' принята")

    def _wait_vm(self, region: str, target: str, attempts: int = VM_STATUS_ATTEMPTS) -> bool:
        for i in range(attempts):
            time.sleep(VM_STATUS_POLL)
            try:
                status = self.get_server_status(region)
                log.info(f"[{region}] VM статус: {status} (цель: {target}, {i+1}/{attempts})")
                if status == target:
                    return True
                if status == "ERROR":
                    log.error(f"[{region}] VM в статусе ERROR!")
                    return False
            except Exception as e:
                log.warning(f"[{region}] Ошибка проверки статуса VM: {e}")
        log.error(f"[{region}] Таймаут ожидания статуса {target}")
        return False

    def ensure_vm_running(self, region: str) -> bool:
        try:
            status = self.get_server_status(region)
        except Exception as e:
            log.error(f"[{region}] Не удалось получить статус VM: {e}")
            return False

        log.info(f"[{region}] Статус VM: {status}")

        if status == "ACTIVE":
            log.info(f"[{region}] VM уже запущена")
            return True
        elif status == "SHUTOFF":
            log.info(f"[{region}] VM выключена -> os-start...")
            self._server_action(region, {"os-start": None}, "os-start")
            return self._wait_vm(region, "ACTIVE")
        elif status == "PAUSED":
            log.info(f"[{region}] VM на паузе -> unpause...")
            self._server_action(region, {"unpause": None}, "unpause")
            return self._wait_vm(region, "ACTIVE")
        elif status == "SUSPENDED":
            log.info(f"[{region}] VM suspended -> resume...")
            self._server_action(region, {"resume": None}, "resume")
            return self._wait_vm(region, "ACTIVE")
        elif status in ("SHELVED", "SHELVED_OFFLOADED"):
            log.info(f"[{region}] VM shelved -> unshelve...")
            self._server_action(region, {"unshelve": None}, "unshelve")
            return self._wait_vm(region, "ACTIVE")
        else:
            log.error(f"[{region}] Неизвестный статус VM: {status}")
            return False

    def suspend_vm(self, region: str) -> None:
        try:
            status = self.get_server_status(region)
            if status != "ACTIVE":
                log.info(f"[{region}] VM уже не активна ({status}), пропускаем заморозку")
                return
            self._server_action(region, {"suspend": None}, "suspend")
            log.info(f"[{region}] VM заморожена (suspend)")
        except Exception as e:
            log.error(f"[{region}] Ошибка заморозки VM: {e}")

    # --- Сеть ---

    def get_external_network_id(self, region: str) -> str:
        rs = self._rs(region)
        if rs.ext_net_id:
            return rs.ext_net_id
        self.ensure_auth()
        resp = self._s.get(
            f"{rs.neutron_url}/v2.0/networks",
            headers=self._h(),
            params={"router:external": True, "status": "ACTIVE"},
            timeout=30,
        )
        resp.raise_for_status()
        nets = resp.json()["networks"]
        if not nets:
            raise RuntimeError(f"[{region}] Внешние сети не найдены")
        rs.ext_net_id = nets[0]["id"]
        log.info(f"[{region}] Внешняя сеть: {nets[0].get('name', '')} ({rs.ext_net_id})")
        return rs.ext_net_id

    def list_floating_ips(self, region: str) -> list[dict]:
        """Возвращает все floating IP в регионе."""
        self.ensure_auth()
        rs = self._rs(region)
        resp = self._s.get(
            f"{rs.neutron_url}/v2.0/floatingips",
            headers=self._h(), timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("floatingips", [])

    def cleanup_orphan_fips(self, region: str, known_ids: set[str]) -> int:
        """
        Удаляет FIP в регионе, которые:
          - не привязаны к порту (port_id is None)
          - не входят в known_ids (т.е. не отслеживаются скриптом)
        Возвращает количество удалённых.
        """
        removed = 0
        try:
            all_fips = self.list_floating_ips(region)
        except Exception as e:
            log.warning(f"[{region}] Не удалось получить список FIP для очистки: {e}")
            return 0

        for fip in all_fips:
            if fip["id"] in known_ids:
                continue
            if fip.get("port_id") is not None:
                continue  # привязан — не трогаем
            try:
                self.delete_floating_ip(region, fip["id"], fip["floating_ip_address"])
                log.warning(f"[{region}] Удалён осиротевший FIP: {fip['floating_ip_address']} (таймаут при создании)")
                removed += 1
            except Exception as e:
                log.error(f"[{region}] Не удалось удалить осиротевший FIP {fip['floating_ip_address']}: {e}")
        return removed

    def get_vm_port_id(self, region: str) -> str:
        rs = self._rs(region)
        if rs.vm_port_id:
            return rs.vm_port_id
        self.ensure_auth()
        resp = self._s.get(
            f"{rs.nova_url}/servers/{rs.server_id}/os-interface",
            headers=self._h(), timeout=30,
        )
        resp.raise_for_status()
        attachments = resp.json().get("interfaceAttachments", [])
        if not attachments:
            raise RuntimeError(f"[{region}] У VM {rs.server_id} нет сетевых интерфейсов")
        rs.vm_port_id = attachments[0]["port_id"]
        log.info(f"[{region}] Port ID VM: {rs.vm_port_id}")
        return rs.vm_port_id

    # --- Floating IP ---

    def create_floating_ip(self, region: str) -> dict:
        self.ensure_auth()
        rs = self._rs(region)
        net_id = self.get_external_network_id(region)
        resp = self._s.post(
            f"{rs.neutron_url}/v2.0/floatingips",
            headers=self._h(),
            json={"floatingip": {"floating_network_id": net_id}},
            timeout=30,
        )
        resp.raise_for_status()
        fip = resp.json()["floatingip"]
        log.info(f"[{region}] Создан FIP: {fip['floating_ip_address']} ({fip['id']})")
        return fip

    def associate_floating_ip(self, region: str, fip_id: str, port_id: str) -> None:
        self.ensure_auth()
        rs = self._rs(region)
        resp = self._s.put(
            f"{rs.neutron_url}/v2.0/floatingips/{fip_id}",
            headers=self._h(),
            json={"floatingip": {"port_id": port_id}},
            timeout=30,
        )
        resp.raise_for_status()
        log.info(f"[{region}] FIP {fip_id} привязан к порту {port_id}")

    def disassociate_floating_ip(self, region: str, fip_id: str) -> None:
        self.ensure_auth()
        rs = self._rs(region)
        resp = self._s.put(
            f"{rs.neutron_url}/v2.0/floatingips/{fip_id}",
            headers=self._h(),
            json={"floatingip": {"port_id": None}},
            timeout=30,
        )
        resp.raise_for_status()

    def delete_floating_ip(self, region: str, fip_id: str, fip_addr: str) -> None:
        self.ensure_auth()
        rs = self._rs(region)
        try:
            self.disassociate_floating_ip(region, fip_id)
        except Exception as e:
            log.debug(f"[{region}] Отвязка перед удалением: {e} (игнорируем)")
        resp = self._s.delete(
            f"{rs.neutron_url}/v2.0/floatingips/{fip_id}",
            headers=self._h(), timeout=30,
        )
        resp.raise_for_status()
        log.info(f"[{region}] Удалён FIP: {fip_addr} ({fip_id})")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Читаем конфиг регионов ---
    region_configs = {
        "ru-2": os.getenv("SEL_SERVER_ID_RU2"),
        "ru-3": os.getenv("SEL_SERVER_ID_RU3"),
    }
    missing_vms = [k for k, v in region_configs.items() if not v]
    if missing_vms:
        for k in missing_vms:
            log.error(f"Не задана переменная SEL_SERVER_ID_{k.upper().replace('-', '')} "
                      f"(UUID VM в регионе {k})")
        sys.exit(1)

    region_states = [
        RegionState(region=r, server_id=sid)
        for r, sid in region_configs.items()
    ]

    log.info("=" * 60)
    log.info("Selectel IP Scanner v3")
    log.info(f"Регионы: {', '.join(REGIONS)}")
    log.info(f"Режим: {'СТОП после первого' if STOP_ON_FOUND else 'Продолжать'}")
    log.info(f"WiFi: {WIFI_IFACE} | Пауза: {ITER_PAUSE}с (дубли: {DUPLICATE_PAUSE}с) | Батч: {BATCH_SIZE}")
    log.info("=" * 60)
    cprint(
        f"Selectel IP Scanner v3 | регионы: {', '.join(REGIONS)} | "
        f"режим: {'СТОП' if STOP_ON_FOUND else 'Продолжать'} | WiFi: {WIFI_IFACE}"
    )

    client    = SelectelClient(region_states)
    blacklist = IPBlacklist()
    whitelist = IPWhitelist()

    if len(blacklist) > 0:
        cprint(f"Чёрный список: {len(blacklist)} IP загружено")

    # Аутентификация (заодно заполняет URL для всех регионов)
    try:
        client.ensure_auth()
    except Exception as e:
        log.error(f"Ошибка аутентификации: {e}")
        sys.exit(1)

    # Запускаем VM — только если белый список сейчас включён
    _inet, _wl = get_network_status()
    if _wl:
        for rs in region_states:
            cprint(f"[{rs.region}] Проверяем/запускаем VM...")
            if not client.ensure_vm_running(rs.region):
                log.error(f"[{rs.region}] Не удалось запустить VM.")
                sys.exit(1)
            try:
                client.get_vm_port_id(rs.region)
            except Exception as e:
                log.error(f"[{rs.region}] Не удалось получить port ID VM: {e}")
                sys.exit(1)
    else:
        cprint("Белый список выключен при старте — VM не проверяем, запустим при необходимости")
        # Всё же получаем port ID заранее (без запуска VM)
        for rs in region_states:
            try:
                client.get_vm_port_id(rs.region)
            except Exception:
                pass  # не страшно — получим позже когда понадобится

    found_ips:  list[tuple[str, str]] = []  # (region, ip)
    iteration  = 0
    skipped_bl = 0
    stop_requested = False

    region_cycle = itertools.cycle(REGIONS)

    while not stop_requested:
        region = next(region_cycle)
        iteration += 1
        cprint(
            f"[#{iteration}] [{region}] найдено: {len(found_ips)} | "
            f"блэклист: {skipped_bl} пропущено, {len(blacklist)} подсетей"
        )

        # Шаг 1: определяем режим работы (неблокирующая проверка)
        internet_ok, whitelist_on = get_network_status()
        wl_only = not internet_ok or not whitelist_on

        if wl_only:
            reason = "нет интернета" if not internet_ok else "белый список ВЫКЛЮЧЕН"
            cprint(f"  [{region}] Режим whitelist-only ({reason})")
        else:
            # Белый список включён — проверяем статус VM
            status = None
            try:
                status = client.get_server_status(region)
                log.info(f"[{region}] Статус VM: {status}")
            except Exception as e:
                log.warning(f"[{region}] Не удалось получить статус VM: {e}")

            if status and status != "ACTIVE":
                cprint(f"  [{region}] VM не активна ({status}), запускаем...")
                if not client.ensure_vm_running(region):
                    log.error(f"[{region}] Не удалось запустить VM, пропускаем итерацию")
                    countdown_sleep(ITER_PAUSE, "Следующая итерация")
                    continue
                # Обновляем port ID если ещё не получен
                if not client._rs(region).vm_port_id:
                    try:
                        client.get_vm_port_id(region)
                    except Exception as e:
                        log.error(f"[{region}] Не удалось получить port ID: {e}")
                        countdown_sleep(ITER_PAUSE, "Следующая итерация")
                        continue

        vm_port_id = client._rs(region).vm_port_id

        # Шаг 2: создаём батч FIP
        created: list[dict] = []
        for _ in range(BATCH_SIZE):
            try:
                fip = client.create_floating_ip(region)
                created.append(fip)
            except Exception as e:
                log.error(f"[{region}] Ошибка создания FIP: {e}")
                known_ids = {f["id"] for f in created}
                n = client.cleanup_orphan_fips(region, known_ids)
                if n:
                    cprint(f"  [{region}] Очищено {n} осиротевших FIP после таймаута")
                break

        if not created:
            cprint(f"  [{region}] Не удалось создать ни одного FIP, ждём...")
            countdown_sleep(API_RETRY_PAUSE, "Повтор")
            continue

        cprint(f"  [{region}] Создано {len(created)} FIP: "
               f"{', '.join(f['floating_ip_address'] for f in created)}")

        # Шаг 3: фильтр блэклиста
        to_check: list[dict] = []
        for fip in created:
            if blacklist.is_blocked(fip["floating_ip_address"]):
                cprint(f"  БЛЭКЛИСТ: {fip['floating_ip_address']} — пропускаем")
                skipped_bl += 1
                try:
                    client.delete_floating_ip(region, fip["id"], fip["floating_ip_address"])
                except Exception as e:
                    log.error(f"[{region}] Ошибка удаления заблокированного FIP: {e}")
            else:
                to_check.append(fip)

        # Шаг 4: проверяем каждый IP
        for fip in to_check:
            if stop_requested:
                try:
                    client.delete_floating_ip(region, fip["id"], fip["floating_ip_address"])
                except Exception:
                    pass
                continue

            fip_id   = fip["id"]
            fip_addr = fip["floating_ip_address"]

            # ── РЕЖИМ WHITELIST-ONLY ──────────────────────────────────────
            if wl_only:
                if whitelist.contains(fip_addr):
                    ip_ok, method = True, "whitelist"
                    cprint(f"  [{region}] {fip_addr} в whitelist ✓")
                else:
                    # Не в whitelist — удаляем, не привязывая к VM
                    log.info(f"[{region}] {fip_addr} не в whitelist — удаляем")
                    try:
                        client.delete_floating_ip(region, fip_id, fip_addr)
                    except Exception as e:
                        log.error(f"[{region}] Ошибка удаления FIP: {e}")
                    continue

            # ── ПОЛНЫЙ РЕЖИМ (интернет + белый список) ───────────────────
            else:
                # Если IP в whitelist — не нужно привязывать и проверять пингом
                if whitelist.contains(fip_addr):
                    # Всё же привязываем к VM (IP нужен рабочим на сервере)
                    try:
                        client.associate_floating_ip(region, fip_id, vm_port_id)
                        log.info(f"[{region}] Ждём {FIP_SETTLE_TIME}с (маршрутизация)...")
                        time.sleep(FIP_SETTLE_TIME)
                    except Exception as e:
                        log.error(f"[{region}] Ошибка привязки {fip_addr}: {e}")
                        try:
                            client.delete_floating_ip(region, fip_id, fip_addr)
                        except Exception:
                            pass
                        continue
                    ip_ok, method = True, "whitelist"
                    cprint(f"  [{region}] {fip_addr} в whitelist ✓")

                else:
                    # Стандартная проверка: привязка → ping → curl
                    try:
                        client.associate_floating_ip(region, fip_id, vm_port_id)
                    except Exception as e:
                        log.error(f"[{region}] Ошибка привязки {fip_addr}: {e}")
                        try:
                            client.delete_floating_ip(region, fip_id, fip_addr)
                        except Exception:
                            pass
                        continue

                    log.info(f"[{region}] Ждём {FIP_SETTLE_TIME}с (маршрутизация {fip_addr})...")
                    time.sleep(FIP_SETTLE_TIME)

                    # Перепроверяем интернет перед пингом
                    if not check_internet():
                        log.warning(f"Интернет пропал при проверке {fip_addr}. Удаляем FIP...")
                        try:
                            client.delete_floating_ip(region, fip_id, fip_addr)
                        except Exception:
                            pass
                        continue

                    cprint(f"  Проверка {fip_addr} [{region}] (ICMP + curl)...")
                    ip_ok, method = check_ip(fip_addr, iface=WIFI_IFACE)
                    if ip_ok:
                        cprint(f"  [{region}] Метод: {method}")

            # ── Результат ────────────────────────────────────────────────
            if ip_ok:
                cprint(f"{'=' * 55}")
                cprint(f"  НАЙДЕН РАБОЧИЙ IP: {fip_addr}  [{region}]  ({method})")
                cprint(f"{'=' * 55}")
                found_ips.append((region, fip_addr))

                if STOP_ON_FOUND:
                    log.info("STOP_ON_FOUND=true -> замораживаем все VM, завершаем")
                    for rs in region_states:
                        cprint(f"Замораживаем VM [{rs.region}]...")
                        client.suspend_vm(rs.region)
                    stop_requested = True
            else:
                blacklist.add(fip_addr)
                cprint(f"  ЗАБЛОКИРОВАНО: {fip_addr} [{region}]")
                try:
                    client.delete_floating_ip(region, fip_id, fip_addr)
                except Exception as e:
                    log.error(f"[{region}] Ошибка удаления FIP: {e}")

        if not stop_requested:
            all_duplicates = len(created) > 0 and len(created) - len(to_check) > 1
            pause = DUPLICATE_PAUSE if all_duplicates else ITER_PAUSE
            if all_duplicates:
                cprint(f"  Весь батч — дубли. Пауза {pause}с...")
            countdown_sleep(pause, "Следующая итерация")

    # --- Итог ---
    log.info("=" * 60)
    cprint(f"Готово. Найдено рабочих IP: {len(found_ips)}")
    for region, ip in found_ips:
        cprint(f"  OK: {ip}  [{region}]")
    log.info(f"Заблокировано подсетей: {len(blacklist)}")
    for s in blacklist.list_all():
        log.info(f"  BLOCKED: {s}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Остановлено пользователем (Ctrl+C)")
        sys.exit(0)
