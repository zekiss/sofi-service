# based on https://www.sofistik.de/documentation/2020/en/cdb_interfaces/python/examples/python_example2.html

from ctypes import sizeof, c_int
from sofistik_daten import *
import os
import platform

try:
    sofi_dir = r".\Sofistik"
    sofi_dir = os.path.abspath(sofi_dir)
    sofi_dir_interface = r".\Sofistik\interfaces\64bit"
    sofi_dir_interface = os.path.abspath(sofi_dir_interface)
    current_path = os.getcwd()

    # Get the DLLs (64bit DLL)
    sof_platform = str(platform.architecture())
    if sof_platform.find("32Bit") < 0:
        # Set DLL dir path
        os.chdir(sofi_dir)
        os.add_dll_directory(sofi_dir_interface)
        os.add_dll_directory(sofi_dir)

        # Get the DLL functions
        myDLL = cdll.LoadLibrary("sof_cdb_w_edu-70.dll")
        py_sof_cdb_get = cdll.LoadLibrary("sof_cdb_w_edu-70.dll").sof_cdb_get
        py_sof_cdb_get.restype = c_int

        py_sof_cdb_kenq = cdll.LoadLibrary("sof_cdb_w_edu-70.dll").sof_cdb_kenq_ex
        os.chdir(current_path)

except Exception as e:
    print("no sofistik files found")

def get_quad_forces_results(Index, result_dict):
    # 210: maximum forces of Quad elements
    temp = []
    datalen2 = c_int(0)
    ie2 = c_int(0)
    datalen2.value = sizeof(CQUAD_FOC)
    RecLen2 = c_int(sizeof(cquad_foc))
    while ie2.value < 2:
        ie2.value = py_sof_cdb_get(Index, 210, 1, byref(cquad_foc), byref(RecLen2), 1)

        temp.append(cquad_foc.m_nr)
        result_dict["quad_results"].append({"id": cquad_foc.m_nr})

    RecLen2 = c_int(sizeof(cquad_foc))
    print(temp)
    return result_dict
