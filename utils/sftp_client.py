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

async def edit_server_properties(kv: dict[str, str]) -> None:
    async with sftp_conn() as sftp:
        async with (await sftp.open(settings.Mc_PROPERTIES_PATH, "r")) as f:  # <-- keep name exactly as in your settings
            data = await f.read()
        lines = data.decode(errors="replace").splitlines()
        d: dict[str, str] = {}
        for line in lines:
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
        d.update(kv)
        new = "\n".join([f"{k}={v}" for k, v in d.items()]) + "\n"
        async with (await sftp.open(settings.MC_PROPERTIES_PATH, "w")) as f:
            await f.write(new.encode())

# NEW: read whole server.properties as text
async def read_server_properties_text() -> str:
    async with sftp_conn() as sftp:
        async with (await sftp.open(settings.MC_PROPERTIES_PATH, "r")) as f:
            data = await f.read()
        return data.decode(errors="replace")
    
# NEW: list plugin directory (marks folders with /)
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
    # Put jars first (sorted), then folders/others
    jars = sorted([n for n in names if n.lower().endswith(".jar")])
    rest = sorted([n for n in names if n not in jars])
    return jars + rest
