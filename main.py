import os
import logging
import platform
import shutil
import uvicorn
from typing import Optional
from fastapi import (
    FastAPI,
    File,
    UploadFile,
    HTTPException
)
from pydantic import BaseModel
from dotenv import load_dotenv

# ----------- for Upload files---------------------------#
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

# ----------- for SOFiSTiK-------------------------------#
import subprocess
from sofistik_connect import connect_to_cdb, close_cdb
from read_truss_cdb import get_truss_results, get_node_results
from read_plate_cdb import get_quad_forces_results

#from api.sofistik import read_truss_cdb # TODO: Check if this import is actually unused

# ----------- for socketio-------------------------------#
import socketio

sio = socketio.AsyncServer(async_mode="asgi", logger=False, engineio_logger=False)
socket_app = socketio.ASGIApp(sio)


load_dotenv()

log = logging.getLogger("sofi-service")
FORMAT_CONS = "%(asctime)s %(name)-12s %(levelname)8s\t%(message)s"
logging.basicConfig(level=logging.DEBUG, format=FORMAT_CONS)
logging.getLogger("websockets.protocol").setLevel(logging.ERROR)
log.debug(
    """

░██████╗░█████╗░░█████╗░██████╗░███████╗
██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝
╚█████╗░██║░░╚═╝██║░░██║██████╔╝█████╗░░
░╚═══██╗██║░░██╗██║░░██║██╔═══╝░██╔══╝░░
██████╔╝╚█████╔╝╚█████╔╝██║░░░░░███████╗
╚═════╝░░╚════╝░░╚════╝░╚═╝░░░░░╚══════╝
█                                       █
█  https://www.projekt-scope.de/        █
█        - sofi-service -               █

    """
)


app = FastAPI(
    title="Sofi Service",
    description="This API starts the calculation with SOFiSTiK.",
    version="0.1",
)


class Input(BaseModel):
    dat: str


class Result(BaseModel):
    id: str


def save_upload_file_tmp(upload_file: UploadFile):
    """Saves recieved dat and returns directory"""
    try:
        suffix = Path(upload_file.filename).suffix
        direc = mkdtemp(dir="dat")
        with NamedTemporaryFile(
            delete=False, suffix=suffix, dir=os.path.abspath(direc)
        ) as tmp:
            shutil.copyfileobj(upload_file.file, tmp)
            tmp_path = Path(tmp.name)
    finally:
        upload_file.file.close()
    return tmp_path, direc


def save_binary_tmp(binary, sid):
    """Saves recieved binary dat and returns directory"""

    # replacement strings
    WINDOWS_LINE_ENDING = b'\r\n'
    UNIX_LINE_ENDING = b'\n'

    os.mkdir("dat/" + sid)
    tmp_path = Path(f"dat/{sid}/{sid}.dat")
    binary = binary.replace(WINDOWS_LINE_ENDING, UNIX_LINE_ENDING)
    with open(tmp_path, "w") as f:
        f.write(binary.decode())  # writing to file
        f.close()


@app.post("/dat2calculationfile/")
async def building_2_dat_file(dat_file: Optional[UploadFile] = File(None)):
    """
        Start calculation from DAT and return directory of the result cdb
        @input: Dat-File
        @return: Name of CDB / directory where CDB is located
    """
    if dat_file is None:
        raise HTTPException(status_code=400, detail="*.dat file is required")
    return upload_and_calculate(dat_file)


@app.post("/dat2result/frame")
async def dat_2_result(dat_file: Optional[UploadFile] = File(None)):
    """
        Calculate dat and return result-json (truss and node results)
        @input: dat
        @return: result-json
    """
    if dat_file is None:
        raise HTTPException(status_code=400, detail="*.dat file is required")
    res = upload_and_calculate(dat_file)
    if type(res) == HTTPException:
        raise res
    return return_results_frame(res)


@app.post("/dat2result/building")
async def dat_2_result_building(dat_file: Optional[UploadFile] = File(None)):
    """
        Calculate 3D building dat and return result-json (for quad elements)
        @inupt: dat
        @return: result-json
    """
    if dat_file is None:
        raise HTTPException(status_code=400, detail="*.dat file is required")
    res = upload_and_calculate(dat_file)
    if type(res) == HTTPException:
        raise res
    return return_results_building(res)


@app.post("/returnResults/")
async def return_result(result: Result):
    """
        Returns result to corresponding calculation id (without starting the calculation again)
        @input: id (json)
        @return: result-json (truss & node results)
    """
    return await return_results_frame(result.id)


def upload_and_calculate(dat_file):
    tmp_path, direc = save_upload_file_tmp(dat_file)
    return _calculate(tmp_path, direc)


def _calculate(tmp_path, direc):
    try:
        program = os.getenv("SOFISTIK_PATH") + "wps.exe"
        subprocess.call([program, tmp_path, "-b"], timeout=60)
    except subprocess.TimeoutExpired as timeout_exc:
        raise HTTPException(
            status_code=500, detail="timeout in calculation"
        ) from timeout_exc
    except FileNotFoundError as file_error:
        log.error("SOFiSTiK is not installed")
        raise HTTPException(
            status_code=503, detail="SOFiSTiK is not installed"
        ) from file_error
    finally:
        tmp_path.unlink()  # Delete the temp file
        if platform.system() == "Linux":
            id_ = direc.split("/")[1]
        else:
            id_ = direc.split("\\")[1]
    return id_


async def calculation_from_socketio(sid):
    try:
        program = os.getenv("SOFISTIK_PATH") + "wps.exe"
        path_to_dat = Path(f"dat/{sid}/{sid}.dat")
        subprocess.call([program, path_to_dat, "-b"], timeout=60)
    except subprocess.TimeoutExpired as timeout_exc:
        print(str(timeout_exc))
        return False
    except FileNotFoundError as file_error:
        log.error(f"SOFiSTiK is not installed: {file_error}")
        return False
    return True


def return_results_frame(id_):
    """
        FRAME: Return results to corresponding id
    """
    result_dict = {
        "calculation_id": "",
        "truss_results": [],
        "node_results": [],
    }
    filepath = search_cdb_in_folder(id_)
    index, cdb_stat = connect_to_cdb(filepath)
    result_dict = get_truss_results(index, result_dict)
    result_dict = get_node_results(index, result_dict)
    close_cdb(index, cdb_stat)
    path = Path(os.path.abspath("dat/" + id_))
    # BE CAREFUL WITH `rmtree` !
    shutil.rmtree(path)

    return result_dict


def return_results_building(id_):
    """
        BUILDING: Return results to corresponding id
    """
    result_dict = {"calculation_id": "", "quad_results": []}
    filepath = search_cdb_in_folder(id_)
    index, cdb_stat = connect_to_cdb(filepath)
    result_dict = get_quad_forces_results(index, result_dict)
    close_cdb(index, cdb_stat)
    path = Path(os.path.abspath("dat/" + id_))
    # BE CAREFUL WITH `rmtree` !
    shutil.rmtree(path)

    return result_dict


def search_cdb_in_folder(folder):
    for file in os.listdir("dat/" + folder):
        if file.endswith(".cdb"):
            return os.path.abspath(os.path.join("dat/" + folder, file))


# ------------------------------- Server socketio -------------------------------#
@sio.event
async def connect(sid, environ):
    print("connected to ", sid, flush=True)
    await sio.emit(
        "message",
        {"message": f"Hello, you are now connected to the Sofi-Service. Your id is {sid}."},
        room=sid,
    )


@sio.on("send dat")
async def receive_dat(sid, message):
    binary = message["file_data"]
    viz_sid = message["viz_sid"]
    print("IIIIIIIIIID" + viz_sid)

    # save received dat
    save_binary_tmp(binary, sid)

    print("saved binary")

    await sio.sleep(1)

    # respond: DAT received
    await sio.emit("message", 
        {
            "message": "Sofi-Service: DAT file recieved, starting the calculation",
            "project_id": message["project_id"]
        }, 
        room=sid,
        )

    # start SOFiSTiK calculation and send back the CDB
    calculation_success = await calculation_from_socketio(sid)
    if calculation_success:
        await sio.emit(
            "message",
            {
                "message": "Sofi-Service: Calculation was successfull. I will send you the cdb now.",
                "project_id": message["project_id"]
            },
            room=sid,
        )
        path_to_cdb = Path(f"dat/{sid}/{sid}.cdb")
        with open(path_to_cdb, "rb") as f:
            file_data = f.read()
        await sio.emit(
            "send file", # Gets sent to ModelCreation (sofi_socket.py)!
            {
                "file_data": file_data,
                "viz_sid": viz_sid,
                "original_params": message["original_params"], # NEW, had been missing and used in sofi_socket!
                "frontend_sid": message["frontend_sid"],
                "project_id": message["project_id"]
            },
            room=sid
        )
        await sio.disconnect(sid)
    else:
        await sio.emit(
            "message",
            {
                "message": "Sofi-Service: ERROR - calculation not successful.",
                "project_id": message["project_id"]
            },
            room=sid,
        )
        await sio.disconnect(sid)
    print(calculation_success, flush=True)


@sio.on("send dat model update")
async def receive_dat(sid, message):

    sid_for_path = ''.join(e for e in sid if e.isalnum())

    binary = message["file_data"]
    viz_sid = message["viz_sid"]
    print("IIIIIIIIIID" + viz_sid)

    # save received dat
    save_binary_tmp(binary, sid_for_path)

    print("saved binary")

    await sio.sleep(1)

    # respond: DAT received
    await sio.emit("message", 
        {
            "message": "Sofi-Service: DAT file recieved, starting the calculation",
            "project_id": message["project_id"]
        }, 
        room=sid,
        )

    # start SOFiSTiK calculation and send back the CDB
    calculation_success = await calculation_from_socketio(sid_for_path)
    if calculation_success:
        await sio.emit(
            "message",
            {
                "message": "Sofi-Service: Calculation was successfull. I will send you the cdb now.",
                "project_id": message["project_id"]
            },
            room=sid,
        )
        path_to_cdb = Path(f"dat/{sid_for_path}/{sid_for_path}.cdb")
        with open(path_to_cdb, "rb") as f:
            file_data = f.read()
        await sio.emit(
            "send file model update",
            {
                "file_data": file_data,
                "viz_sid": viz_sid,
                "frontend_sid": message["frontend_sid"],
                "project_id": message["project_id"]
            },
            room=sid
        )
        await sio.disconnect(sid)
    else:
        await sio.emit(
            "message",
            {
                "message": "Sofi-Service: ERROR - calculation not successful.",
                "project_id": message["project_id"]
            },
            room=sid,
        )
        await sio.disconnect(sid)
    print(calculation_success, flush=True)


@sio.on("message")
async def receive_message(sid, data):
    print(f"message:{data} from {sid} ", flush=True)


@sio.event
async def disconnect(sid):
    # delete folder when a client gets disconnected
    print(f"I will disconnect {sid} now.", flush=True)
    try:
        path = Path(os.path.abspath("dat/" + sid))
        # BE CAREFUL WITH `rmtree` !
        shutil.rmtree(path)
    except FileNotFoundError as ex:
        print("Error removing: ", ex, flush=True)
    print("disconnect ", sid)


app.mount("/", socket_app)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port="8011")
