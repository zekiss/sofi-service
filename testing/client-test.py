import asyncio
import socketio

sio = socketio.AsyncClient()


@sio.event
async def connect():
    print("connection established")


@sio.on("message")
async def receive_message(message):
    print(message["message"])


@sio.on("send file")
async def receive_file(message):
    with open("./test.cdb", "wb") as f:
        f.write(message["file_data"])  # writing to file
        f.close()


@sio.event
async def disconnect():
    print("disconnected from server")


async def send_file():
    with open("test.dat", "rb") as f:
        file_data = f.read()
    await sio.emit("send file", {"file_data": file_data})


async def main():
    await sio.connect("http://localhost:8001/")
    await send_file()
    try:
        await sio.wait()
    except ConnectionResetError as ex:
        print("Not connected anymore. Error:", ex)


if __name__ == "__main__":
    asyncio.run(main())
