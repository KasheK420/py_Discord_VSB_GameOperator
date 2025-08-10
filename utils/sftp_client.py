# utils/sftp_client.py
import asyncssh
import stat as pystat
from contextlib import asynccontextmanager
from utils.config import settings

@asynccontextmanager
async def sftp_conn():
    conn = await asyncssh.connect(
        settings.SFTP_HOST,
        port=settings.SFTP_PORT,
        username=settings.SFTP_USERNAME,
        password=settings.SFTP_PASSWORD,
        known_hosts=None,
        keepalive_interval=30,
        keepalive_count_max=3,
    )
    try:
        sftp = await conn.start_sftp_client()
        yield sftp
    finally:
        conn.close()
        await conn.wait_closed()

async def upload_plugin_from_url(url: str, dest_dir: str | None = None):
    import tempfile, os, urllib.request
    dest_dir = dest_dir or settings.MC_PLUGINS_DIR
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, url.split("/")[-1])
        urllib.request.urlretrieve(url, local)
        async with sftp_conn() as sftp:
            await sftp.put(local, f"{dest_dir}/{local.split('/')[-1]}")
    return True

async def read_server_properties_text() -> str:
    async with sftp_conn() as sftp:
        async with (await sftp.open(settings.MC_PROPERTIES_PATH, "r")) as f:
            data = await f.read()
        # Some setups may already return str; normalize to str
        return data if isinstance(data, str) else data.decode(errors="replace")

async def edit_server_properties(kv: dict[str, str]) -> None:
    async with sftp_conn() as sftp:
        async with (await sftp.open(settings.MC_PROPERTIES_PATH, "r")) as f:
            data = await f.read()
        text = data if isinstance(data, str) else data.decode(errors="replace")
        lines = text.splitlines()
        d: dict[str, str] = {}
        for line in lines:
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k].strip() if False else None  # keep flake8 happy
            d[k.strip()] = v.strip()
        d.update(kv)
        new_text = "\n".join([f"{k}={v}" for k, v in d.items()]) + "\n"
        payload = new_text if isinstance(data, str) else new_text.encode()
        async with (await sftp.open(settings.MC_PROPERTIES_PATH, "w")) as f:
            await f.write(payload)

async def list_plugins(dir_path: str | None = None) -> list[str]:
    dir_path = dir_path or settings.MC_PLUGINS_DIR
    names: list[str] = []
    async with sftp_conn() as sftp:
        for name in await sftp.listdir(dir_path):
            try:
                attrs = await sftp.stat(f"{dir_path}/{name}")
                mark_dir = pystat.S_ISDIR(attrs.permissions)
                names.append(name + ("/" if mark_dir else ""))
            except Exception:
                names.append(name)
    jars = sorted([n for n in names if n.lower().endswith(".jar")])
    rest = sorted([n for n in names if n not in jars])
    return jars + rest
