#!/usr/bin/env python3
"""Chain SOCKS5 → Tor local. Escucha en 0.0.0.0:9051 y reenvía todo por Tor.

Uso: el contenedor de searxng apunta sus proxies a socks5h://host.docker.internal:9051
y así sus peticiones a motores salen por Tor (nunca IP real).
"""
import asyncio
import socket
import struct
import sys

UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 9050
LISTEN_PORT = 9052


async def relay(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def read_addr(reader):
    atyp = (await reader.readexactly(1))[0]
    if atyp == 1:
        return 1, socket.inet_ntoa(await reader.readexactly(4))
    if atyp == 3:
        ln = (await reader.readexactly(1))[0]
        return 3, (await reader.readexactly(ln)).decode()
    if atyp == 4:
        return 4, socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
    raise ValueError(f"atyp inválido: {atyp}")


async def handle_client(cr, cw):
    ur = uw = None
    try:
        await cr.readexactly(2)
        nmethods = (await cr.readexactly(1))[0]
        await cr.readexactly(nmethods)
        cw.write(b"\x05\x00")
        await cw.drain()

        req = await cr.readexactly(3)
        if req[1] != 1:
            cw.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await cw.drain()
            return
        atyp, addr = await read_addr(cr)
        port = struct.unpack("!H", await cr.readexactly(2))[0]

        ur, uw = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
        uw.write(b"\x05\x01\x00")
        await uw.drain()
        if (await ur.readexactly(2))[1] != 0:
            raise ValueError("Tor rechazó auth")

        if atyp == 3:
            encoded = b"\x03" + bytes([len(addr)]) + addr.encode()
        elif atyp == 1:
            encoded = b"\x01" + socket.inet_aton(addr)
        else:
            encoded = b"\x04" + socket.inet_pton(socket.AF_INET6, addr)
        uw.write(b"\x05\x01\x00" + encoded + struct.pack("!H", port))
        await uw.drain()

        tor_resp = await ur.readexactly(4)
        if tor_resp[1] != 0:
            cw.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            await cw.drain()
            return
        if tor_resp[3] == 1:
            await ur.readexactly(6)
        elif tor_resp[3] == 3:
            ln = (await ur.readexactly(1))[0]
            await ur.readexactly(ln + 2)
        elif tor_resp[3] == 4:
            await ur.readexactly(18)

        cw.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await cw.drain()

        t1 = asyncio.create_task(relay(cr, uw))
        t2 = asyncio.create_task(relay(ur, cw))
        await asyncio.gather(t1, t2, return_exceptions=True)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            cw.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            await cw.drain()
        except Exception:
            pass
    finally:
        for w in (cw, uw):
            try:
                if w:
                    w.close()
            except Exception:
                pass


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", LISTEN_PORT)
    print(f"chain SOCKS5 0.0.0.0:{LISTEN_PORT} → Tor {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
