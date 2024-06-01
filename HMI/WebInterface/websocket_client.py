import asyncio
import websockets

async def test_websocket():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        while True:
            message = await websocket.recv()
            print(f"Received message: {message}")

asyncio.get_event_loop().run_until_complete(test_websocket())
