import asyncio
import logging
import tempfile
import unittest

from hl7bridge import hl7v2 as h
from hl7bridge.mllp import MLLPServer
from hl7bridge.pipeline import Pipeline
from hl7bridge.sinks import DeadLetter, FileSink
from tests.helpers import OBR, PID, msg, obx

GOOD = msg(PID, OBR, obx())


async def send_and_recv(port: int, frames: list[bytes], read_count: int | None = None, pause: float = 0.0) -> list[bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    for f in frames:
        writer.write(f)
        if pause:
            await asyncio.sleep(pause)
    await writer.drain()
    out: list[bytes] = []
    want = read_count if read_count is not None else len(frames)
    try:
        for _ in range(want):
            buf = b""
            while not buf.endswith(h.EB + h.CR):
                chunk = await asyncio.wait_for(reader.read(4096), 5)
                if not chunk:
                    raise ConnectionError("connection closed early")
                buf += chunk
            out.append(buf)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return out


class MLLPServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.disable(logging.CRITICAL)
        self._dirs = [tempfile.TemporaryDirectory() for _ in range(2)]
        self.out, self.dead = (d.name for d in self._dirs)
        self.pipe = Pipeline(FileSink(self.out), DeadLetter(self.dead))
        self.server = MLLPServer(self.pipe, port=0, idle_timeout=2.0)
        self.port = await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        for d in self._dirs:
            d.cleanup()
        logging.disable(logging.NOTSET)

    async def test_single_message_gets_aa_ack(self):
        acks = await send_and_recv(self.port, [h.frame(GOOD.encode())])
        self.assertEqual(len(acks), 1)
        payload = acks[0][1:-2]
        self.assertIn(b"MSA|AA", payload)

    async def test_malformed_message_gets_ar_ack_and_connection_survives(self):
        acks = await send_and_recv(self.port, [h.frame(b"not hl7"), h.frame(GOOD.encode())], read_count=2)
        self.assertIn(b"MSA|AR", acks[0])
        self.assertIn(b"MSA|AA", acks[1])

    async def test_multiple_messages_same_connection_in_order(self):
        m1 = msg(PID, OBR, obx(), ctrl="C-1")
        m2 = msg(PID, OBR, obx(), ctrl="C-2")
        acks = await send_and_recv(self.port, [h.frame(m1.encode()), h.frame(m2.encode())], read_count=2)
        self.assertIn(b"MSA|AA|C-1", acks[0])
        self.assertIn(b"MSA|AA|C-2", acks[1])

    async def test_message_split_across_tcp_writes(self):
        payload = h.frame(GOOD.encode())
        mid = len(payload) // 2
        acks = await self._split_send(payload[:mid], payload[mid:])
        self.assertIn(b"MSA|AA", acks)

    async def _split_send(self, part1: bytes, part2: bytes) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(part1)
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(part2)
        await writer.drain()
        buf = b""
        while not buf.endswith(h.EB + h.CR):
            buf += await asyncio.wait_for(reader.read(4096), 5)
        writer.close()
        return buf

    async def test_two_connections_do_not_interfere(self):
        results = await asyncio.gather(
            send_and_recv(self.port, [h.frame(msg(PID, OBR, obx(), ctrl="CONN-A").encode())]),
            send_and_recv(self.port, [h.frame(msg(PID, OBR, obx(), ctrl="CONN-B").encode())]),
        )
        self.assertIn(b"MSA|AA|CONN-A", results[0][0])
        self.assertIn(b"MSA|AA|CONN-B", results[1][0])

    async def test_idle_connection_is_closed(self):
        server = MLLPServer(self.pipe, port=0, idle_timeout=0.2)
        port = await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            data = await asyncio.wait_for(reader.read(10), 2)
            self.assertEqual(data, b"")
            writer.close()
        finally:
            await server.stop()

    async def test_connection_limit_refuses_excess_connections(self):
        server = MLLPServer(self.pipe, port=0, max_connections=1, idle_timeout=5.0)
        port = await server.start()
        try:
            r1, w1 = await asyncio.open_connection("127.0.0.1", port)
            await asyncio.sleep(0.1)
            r2, w2 = await asyncio.open_connection("127.0.0.1", port)
            data = await asyncio.wait_for(r2.read(10), 2)
            self.assertEqual(data, b"")
            w1.close()
            w2.close()
        finally:
            await server.stop()


if __name__ == "__main__":
    unittest.main()
