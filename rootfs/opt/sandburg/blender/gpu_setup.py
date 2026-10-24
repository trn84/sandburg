"""On Blender startup: switch Cycles to the best available GPU.

Tries OptiX, then CUDA, HIP and oneAPI. Without a GPU, Cycles stays on the CPU.
Scenes (including .blend files loaded later) are set to device='GPU'.
"""

import bpy
from bpy.app.handlers import persistent

BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI")


def _configure_cycles():
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        print("[gpu_setup] Cycles addon not loaded")
        return None

    for backend in BACKENDS:
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue  # backend not available in this build
        refresh = getattr(prefs, "refresh_devices", None) or getattr(prefs, "get_devices", None)
        if refresh:
            refresh()
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for device in prefs.devices:
                device.use = device.type == backend
            print(f"[gpu_setup] Cycles uses {backend}: {', '.join(d.name for d in gpus)}")
            return backend

    prefs.compute_device_type = "NONE"
    print("[gpu_setup] No GPU found, Cycles renders on the CPU")
    return None


BACKEND = _configure_cycles()


@persistent
def _use_gpu_for_scenes(_dummy=None):
    if not BACKEND:
        return
    for scene in bpy.data.scenes:
        scene.cycles.device = "GPU"


if _use_gpu_for_scenes not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_use_gpu_for_scenes)
_use_gpu_for_scenes()
