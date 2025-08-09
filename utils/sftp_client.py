import asyncssh
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
    # Download inside container then upload—kept simple; you can add streaming later.
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
        # read existing
        data = await sftp.read(settings.MC_PROPERTIES_PATH)
        lines = data.decode().splitlines()
        d = {}
        for line in lines:
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
        d.update(kv)
        new = "\n".join([f"{k}={v}" for k, v in d.items()]) + "\n"
        await sftp.write(settings.MC_PROPERTIES_PATH, new.encode())
