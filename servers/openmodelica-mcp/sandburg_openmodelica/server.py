"""MCP server for OpenModelica, headless via the compiler omc.

Tools:
  write_model    Write Modelica code to a .mo file and optionally check it
  check_model    Load libraries and files and check a model (equations, variables, errors)
  simulate       Compile and simulate a model, write the result as CSV
  read_results   List the variables of a result or return values, extremes and a series
  plot           Plot variables of a result as a PNG image (returned to the client)
  run_script     Run arbitrary OpenModelica scripting code (.mos), for everything else

Relative paths are resolved against SANDBURG_PROJECTS/openmodelica
(default: /workspace/projects/openmodelica). Compiler output (C code, executables)
goes to OPENMODELICA_BUILD_DIR so it doesn't clutter the project folder.
"""

from __future__ import annotations

import csv
import functools
import io
import math
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

PROJECTS = Path(os.environ.get("SANDBURG_PROJECTS", "/workspace/projects"))
WORKDIR = PROJECTS / "openmodelica"
BUILD_DIR = Path(os.environ.get("OPENMODELICA_BUILD_DIR", "/tmp/openmodelica-build"))
OMC = os.environ.get("OMC_BIN", "omc")
TIMEOUT = int(os.environ.get("OPENMODELICA_TIMEOUT", "1800"))
MAX_OUTPUT = 12000

# Modelica class names such as Modelica.Blocks.Examples.PID_Controller
CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# Library entries: "Modelica" or "Modelica:4.0.0"
LIBRARY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_.+ -]+))?$")
# Values for -override: plain numbers, identifiers, true/false
OVERRIDE_VALUE = re.compile(r"^[A-Za-z0-9_.+-]+$")
OVERRIDE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]]*$")

server = MCPServer(
    name="sandburg-openmodelica",
    instructions=(
        "OpenModelica (omc, without GUI) on the Sandburg. Write Modelica models with write_model "
        "as .mo files under /workspace/projects/openmodelica (relative paths are resolved against "
        "it), then use check_model, simulate, read_results and plot. The Modelica Standard Library is loaded by "
        "default. Results are CSV files under openmodelica/results/. To explore libraries, use "
        "run_script, e.g. 'loadModel(Modelica); getClassNames(Modelica.Electrical.Analog.Basic)' "
        "or 'list(Modelica.Blocks.Continuous.PID)'."
    ),
)


# --- Helpers ------------------------------------------------------------------


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else WORKDIR / p


def _existing(path: str) -> Path:
    p = _resolve(path)
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    return p


def _mo_string(value: str) -> str:
    """Modelica string literal"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _class_name(name: str) -> str:
    if not CLASS_NAME.match(name):
        raise ValueError(f"not a valid Modelica class name: {name!r}")
    return name


def _load_statements(files: list[str] | None, libraries: list[str] | None) -> list[str]:
    lines = []
    for lib in libraries or []:
        m = LIBRARY.match(lib.strip())
        if not m:
            raise ValueError(f"library must look like 'Modelica' or 'Modelica:4.0.0', got {lib!r}")
        name, version = m.groups()
        args = f'{name}, {{{_mo_string(version.strip())}}}' if version else name
        lines.append(f"loadModel({args}); getErrorString();")
    for f in files or []:
        lines.append(f"loadFile({_mo_string(str(_existing(f)))}); getErrorString();")
    return lines


def _run_omc(script: str, cwd: Path) -> str:
    """Runs a .mos script with omc in cwd and returns the transcript (results of each statement)."""
    cwd.mkdir(parents=True, exist_ok=True)
    mos = cwd / "sandburg.mos"
    mos.write_text(script + "\n", encoding="utf-8")
    # Own process group, so a timeout also stops a running simulation executable
    proc = subprocess.Popen(
        [OMC, str(mos)],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise RuntimeError(f"omc did not finish within {TIMEOUT} s and was stopped")
    if proc.returncode != 0:
        raise RuntimeError(f"omc failed with code {proc.returncode}:\n{out.strip()[-MAX_OUTPUT:]}")
    return out.strip()[-MAX_OUTPUT:]


def _read_csv(path: Path) -> tuple[list[str], list[list[float]]]:
    if path.suffix.lower() != ".csv":
        raise ValueError(
            f"{path.name} is not a CSV result. simulate writes CSV; in run_script use outputFormat=\"csv\"."
        )
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        columns: list[list[float]] = [[] for _ in header]
        for row in reader:
            if len(row) != len(header):
                continue
            for col, value in zip(columns, row):
                try:
                    col.append(float(value))
                except ValueError:
                    col.append(math.nan)
    return header, columns


def _column(header: list[str], columns: list[list[float]], name: str) -> list[float]:
    try:
        return columns[header.index(name)]
    except ValueError:
        close = [h for h in header if name.lower() in h.lower()][:20]
        hint = f" Similar: {', '.join(close)}" if close else ""
        raise ValueError(f"variable {name!r} is not in the result.{hint}") from None


def _downsample(values: list[float], max_points: int) -> list[float]:
    if len(values) <= max_points:
        return values
    step = (len(values) - 1) / (max_points - 1)
    return [values[round(i * step)] for i in range(max_points)]


def tool(fn: Any) -> Any:
    """Register fn as a tool whose errors reach the client with their message.

    The MCP SDK reports anything but ToolError only as "Error executing tool <name>",
    which hides both our own ValueErrors and the cause of crashes.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return server.tool()(wrapper)


# --- Tools --------------------------------------------------------------------


@tool
def write_model(path: str, code: str, model: str | None = None, libraries: list[str] | None = None) -> dict:
    """Write Modelica code to a .mo file on the Sandburg, optionally checking it right away.

    Overwrites an existing file. To change a model, write the whole file again.

    Args:
        path: Destination, e.g. "Pt100SelfHeating.mo" (relative to /workspace/projects/openmodelica).
        code: Complete Modelica source of the file.
        model: If given, run check_model on this class from the new file right away.
        libraries: Libraries for the check. Default ["Modelica"].
    """
    dst = _resolve(path)
    if dst.suffix.lower() != ".mo":
        raise ValueError("path must end in .mo")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8")
    result: dict[str, Any] = {"path": str(dst), "bytes": dst.stat().st_size}
    if model:
        result["check"] = _check(model, [str(dst)], libraries)
    return result


@tool
def check_model(model: str, files: list[str] | None = None, libraries: list[str] | None = None) -> dict:
    """Check a model: loads the libraries and files, then runs checkModel.

    Reports the number of equations and variables and all errors and warnings.

    Args:
        model: Full class name, e.g. "Tank" or "MyLib.Examples.Test".
        files: .mo files to load (relative to /workspace/projects/openmodelica). A package
            stored as a folder is loaded via its package.mo.
        libraries: Libraries to load first. Default ["Modelica"] (Modelica Standard Library);
            a version can be given as "Modelica:4.0.0".
    """
    return _check(model, files, libraries)


def _check(model: str, files: list[str] | None, libraries: list[str] | None) -> dict:
    name = _class_name(model)
    libs = ["Modelica"] if libraries is None else libraries
    script = "\n".join([*_load_statements(files, libs), f"checkModel({name}); getErrorString();"])
    out = _run_omc(script, BUILD_DIR / "check")
    return {"ok": "completed successfully" in out, "output": out}


@tool
def simulate(
    model: str,
    files: list[str] | None = None,
    libraries: list[str] | None = None,
    start_time: float | None = None,
    stop_time: float | None = None,
    number_of_intervals: int | None = None,
    tolerance: float | None = None,
    method: str | None = None,
    parameters: dict[str, float | int | bool | str] | None = None,
    variable_filter: str | None = None,
    output: str | None = None,
) -> dict:
    """Compile and simulate a model; the result is written as a CSV file.

    Unset options use the model's experiment annotation (or the OpenModelica defaults:
    0–1 s, 500 intervals, dassl). Compiling takes from a few seconds to minutes.

    Args:
        model: Full class name of the model to simulate.
        files: .mo files to load (relative to /workspace/projects/openmodelica).
        libraries: Libraries to load first. Default ["Modelica"].
        start_time: Start time in seconds.
        stop_time: Stop time in seconds.
        number_of_intervals: Number of output intervals.
        tolerance: Solver tolerance, e.g. 1e-6.
        method: Solver, e.g. "dassl", "ida", "euler", "rungekutta", "cvode".
        parameters: Override parameter values without recompiling, e.g.
            {"R1.R": 100, "tank.A": 2.5}. Structural parameters need a change in the model.
        variable_filter: Regular expression for the variables to store, e.g.
            "R1\\..*|C1\\.v". Default: all.
        output: Destination of the CSV result. Default results/<model>.csv.
    """
    name = _class_name(model)
    libs = ["Modelica"] if libraries is None else libraries
    prefix = name.replace(".", "_")
    dst = _resolve(output) if output else WORKDIR / "results" / f"{prefix}.csv"
    if dst.suffix.lower() != ".csv":
        raise ValueError("output must be a .csv file")

    args = [name, 'outputFormat="csv"', f"fileNamePrefix={_mo_string(prefix)}"]
    for key, value in (
        ("startTime", start_time),
        ("stopTime", stop_time),
        ("numberOfIntervals", number_of_intervals),
        ("tolerance", tolerance),
    ):
        if value is not None:
            args.append(f"{key}={value}")
    if method:
        args.append(f"method={_mo_string(method)}")
    if variable_filter:
        args.append(f"variableFilter={_mo_string(variable_filter)}")
    if parameters:
        overrides = []
        for key, value in parameters.items():
            text = str(value).lower() if isinstance(value, bool) else str(value)
            if not OVERRIDE_NAME.match(key) or not OVERRIDE_VALUE.match(text):
                raise ValueError(f"invalid parameter override {key}={value!r}")
            overrides.append(f"{key}={text}")
        args.append(f"simflags={_mo_string('-override=' + ','.join(overrides))}")

    build = BUILD_DIR / prefix
    result = build / f"{prefix}_res.csv"
    result.unlink(missing_ok=True)
    started = time.monotonic()
    script = "\n".join([*_load_statements(files, libs), f"simulate({', '.join(args)}); getErrorString();"])
    out = _run_omc(script, build)
    if not result.is_file():
        raise RuntimeError(f"simulation failed, no result was written:\n{out}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(result, dst)
    header, columns = _read_csv(dst)
    return {
        "result_file": str(dst),
        "seconds": round(time.monotonic() - started, 1),
        "points": len(columns[0]) if columns else 0,
        "variable_count": len(header),
        "variables": header[:200],
        "output": out,
    }


@tool
def read_results(result_file: str, variables: list[str] | None = None, max_points: int = 50) -> dict:
    """Read a CSV result: without `variables` it lists all variable names, otherwise it
    returns the final value, minimum, maximum and a series of each variable.

    Args:
        result_file: CSV result, e.g. "results/Tank.csv".
        variables: Variable names as listed, e.g. ["tank.h", "der(tank.h)"].
        max_points: Points per series (evenly sampled over time; 0 = no series).
    """
    path = _existing(result_file)
    header, columns = _read_csv(path)
    if not variables:
        return {"result_file": str(path), "variable_count": len(header), "variables": header}
    time_col = _column(header, columns, "time")
    data: dict[str, Any] = {}
    for var in variables:
        values = _column(header, columns, var)
        finite = [v for v in values if math.isfinite(v)]
        entry: dict[str, Any] = {
            "final": values[-1] if values else None,
            "min": min(finite) if finite else None,
            "max": max(finite) if finite else None,
        }
        if max_points > 0:
            entry["series"] = _downsample(values, max_points)
        data[var] = entry
    result: dict[str, Any] = {"result_file": str(path), "points": len(time_col), "variables": data}
    if max_points > 0:
        result["time"] = _downsample(time_col, max_points)
    return result


@tool
def plot(
    result_file: str | list[str],
    variables: list[str],
    labels: list[str] | None = None,
    x: str = "time",
    title: str | None = None,
    ylabel: str | None = None,
    output: str | None = None,
    width: float = 10,
    height: float = 5.5,
) -> Image:
    """Plot variables of one or more CSV results and return the plot as a PNG image.

    With several result files (e.g. one simulate run per parameter value), the variables
    of all files are drawn on top of each other, for comparing variants in one diagram.

    Args:
        result_file: CSV result, e.g. "results/Tank.csv", or a list of results.
        variables: Variables on the y axis (all in one diagram).
        labels: Legend names for the result files, e.g. ["1 mA", "5 mA", "10 mA"].
            Default: file names.
        x: Variable on the x axis, default "time" (e.g. a voltage for a characteristic curve).
        title: Diagram title. Default: file name for a single result.
        ylabel: Label of the y axis.
        output: Also save the PNG there, e.g. "plots/tank.png".
        width: Width in inches (at 120 dpi).
        height: Height in inches.
    """
    paths = [_existing(f) for f in ([result_file] if isinstance(result_file, str) else result_file)]
    if not paths:
        raise ValueError("no result file given")
    if labels is not None and len(labels) != len(paths):
        raise ValueError(f"{len(labels)} labels for {len(paths)} result files")
    names = labels or [p.stem for p in paths]
    fig, ax = plt.subplots(figsize=(width, height), dpi=120)
    try:
        for path, name in zip(paths, names):
            header, columns = _read_csv(path)
            xs = _column(header, columns, x)
            for var in variables:
                if len(paths) == 1:
                    label = var
                elif len(variables) == 1:
                    label = name
                else:
                    label = f"{name}: {var}"
                ax.plot(xs, _column(header, columns, var), label=label)
        ax.set_xlabel("time [s]" if x == "time" else x)
        if ylabel:
            ax.set_ylabel(ylabel)
        elif len(paths) > 1 and len(variables) == 1:
            ax.set_ylabel(variables[0])
        ax.set_title(title or (paths[0].stem if len(paths) == 1 else ""))
        ax.grid(True, alpha=0.3)
        if len(paths) * len(variables) > 1:
            ax.legend()
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
    finally:
        plt.close(fig)
    png = buf.getvalue()
    if output:
        dst = _resolve(output)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(png)
    return Image(data=png, format="png")


@tool
def run_script(script: str) -> dict:
    """Run OpenModelica scripting code (.mos) with omc and return the transcript.

    For everything the other tools don't cover: exploring libraries (getClassNames,
    list, getComponents), linearize, buildModel, exporting FMUs (buildModelFMU),
    installPackage and more. Statements are separated by ";"; each result is printed.
    Call getErrorString() to see errors. Libraries are not loaded automatically.

    The working directory is a scratch build directory, so use absolute paths under
    /workspace/projects/openmodelica for everything the user should receive.

    Args:
        script: e.g. 'loadModel(Modelica); getClassNames(Modelica.Electrical.Analog.Basic)'.
    """
    return {"output": _run_omc(script, BUILD_DIR / "script")}


def main() -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
