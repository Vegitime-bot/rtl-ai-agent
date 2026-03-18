#!/usr/bin/env python3
"""Convert UHDM JSON into a structured RTL summary."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# UHDM object type codes (subset)
UHDM_MODULE_INST = 2229
UHMD_PORT = 2268
UHMD_LOGIC_NET = 2211
UHMD_REF_OBJ = 2302
UHMD_REF_VAR = 2305
UHMD_ASSIGNMENT = 2027
UHMD_CONT_ASSIGN = 2082
UHMD_OPERATION = 2251
UHMD_CONSTANT = 2071
UHMD_RANGE = 2296
UHMD_REF_TYPESPEC = 2304
UHMD_LOGIC_TYPESPEC = 2212
UHMD_ALWAYS = 2013
UHDM_ALWAYS = UHMD_ALWAYS
UHMD_BEGIN = 2034
UHMD_EVENT_CONTROL = 2119
UHMD_IF_ELSE = 2165
UHMD_IF_STMT = 2166

DIRECTION_MAP = {
    1: "input",
    2: "output",
    3: "inout",
}


ALWAYS_KIND = {
    0: "always",
    1: "always_comb",
    2: "always_latch",
    3: "always_ff",
}


PREFIX_OPS = {
    3: "!",   # vpiNotOp
    4: "~",   # vpiBitNegOp
    5: "&",   # reduction AND
    6: "~&",  # reduction NAND
    7: "|",   # reduction OR
    8: "~|",  # reduction NOR
    9: "^",   # reduction XOR
    10: "~^",  # reduction XNOR
}

INFIX_OPS = {
    11: "-",    # subtraction
    12: "/",    # division
    13: "%",    # modulus
    14: "==",   # equality
    15: "!=",   # inequality
    16: "===",  # case equality
    17: "!==",  # case inequality
    18: ">",    # greater than
    19: ">=",   # greater equal
    20: "<",    # less than
    21: "<=",   # less equal
    22: "<<",   # left shift
    23: ">>",   # right shift
    24: "+",    # addition
    25: "*",    # multiplication
    26: "&&",   # logical AND
    27: "||",   # logical OR
    28: "&",    # bitwise AND
    29: "|",    # bitwise OR
    30: "^",    # bitwise XOR
    31: "^~",   # bitwise XNOR
    41: "<<<",  # arithmetic left shift
    42: ">>>",  # arithmetic right shift
    43: "**",   # power
}


class UHDMIndex:
    def __init__(self, data: dict):
        self.data = data
        self.symbols: List[str] = data.get("symbols", [])
        self.factories: Dict[str, List[dict]] = {
            key: value
            for key, value in data.items()
            if key.startswith("factory") and isinstance(value, list)
        }
        self.type_to_factory = {
            UHMD_PORT: "factoryPort",
            UHMD_LOGIC_NET: "factoryLogicnet",
            UHMD_REF_OBJ: "factoryRefobj",
            UHMD_REF_VAR: "factoryRefvar",
            UHMD_ASSIGNMENT: "factoryAssignment",
            UHMD_CONT_ASSIGN: "factoryContassign",
            UHMD_OPERATION: "factoryOperation",
            UHMD_CONSTANT: "factoryConstant",
            UHMD_RANGE: "factoryRange",
            UHMD_REF_TYPESPEC: "factoryReftypespec",
            UHMD_LOGIC_TYPESPEC: "factoryLogictypespec",
            UHDM_MODULE_INST: "factoryModuleinst",
            UHMD_ALWAYS: "factoryAlways",
            UHMD_BEGIN: "factoryBegin",
            UHMD_EVENT_CONTROL: "factoryEventcontrol",
            UHMD_IF_ELSE: "factoryIfelse",
            UHMD_IF_STMT: "factoryIfstmt",
        }
        self._first_cache: Dict[Tuple[int, str], Any] = {}
        self._parent_cache: Dict[int, Optional[dict]] = {}
        self._signal_cache: Dict[Tuple[int, int], List[str]] = {}
        self._expr_cache: Dict[Tuple[int, int], Optional[str]] = {}
        self._module_cache: Dict[int, Optional[str]] = {}
        self._resolve_cache: Dict[Tuple[int, int], Optional[dict]] = {}

    def symbol(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and value.isdigit():
            idx = int(value)
        elif isinstance(value, int):
            idx = value
        else:
            return None
        if 0 <= idx < len(self.symbols):
            text = self.symbols[idx]
            if text == "@@BAD_SYMBOL@@":
                return None
            return text
        return None

    def resolve(self, ref: dict | None) -> Tuple[Optional[dict], Optional[int]]:
        if not ref or ref == "0":
            return None, None
        if isinstance(ref, dict):
            idx_str = ref.get("index")
            type_str = ref.get("type")
        else:
            return None, None
        if idx_str is None or type_str is None or not str(idx_str).isdigit():
            return None, None
        idx = int(idx_str)
        type_code = int(type_str)
        cache_key = (type_code, idx)
        if cache_key in self._resolve_cache:
            return self._resolve_cache[cache_key], type_code
        factory_name = self.type_to_factory.get(type_code)
        if factory_name is None:
            self._resolve_cache[cache_key] = None
            return None, type_code
        arr = self.factories.get(factory_name, [])
        result = None
        if 1 <= idx <= len(arr):
            result = arr[idx - 1]
        elif 0 <= idx < len(arr):
            result = arr[idx]
        self._resolve_cache[cache_key] = result
        return result, type_code


    def resolve_by_factory(self, factory: str, idx: int) -> Optional[dict]:
        arr = self.factories.get(factory, [])
        if 0 <= idx < len(arr):
            return arr[idx]
        return None

    def extract_first(self, obj: dict, key: str) -> Any:
        if not isinstance(obj, (dict, list)):
            return None
        cache_key = None
        if isinstance(obj, dict):
            cache_key = (id(obj), key)
            if cache_key in self._first_cache:
                return self._first_cache[cache_key]

        result = self._extract_first_uncached(obj, key)
        if cache_key is not None:
            self._first_cache[cache_key] = result
        return result

    def _extract_first_uncached(self, obj: dict | list, key: str) -> Any:
        stack = [obj]
        seen: Set[int] = set()
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                ident = id(current)
                if ident in seen:
                    continue
                seen.add(ident)
                if key in current:
                    return current[key]
                base = current.get("base")
                if isinstance(base, dict):
                    stack.append(base)
                for value in current.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(current, list):
                for value in current:
                    if isinstance(value, (dict, list)):
                        stack.append(value)
        return None

    def extract_parent(self, obj: dict) -> Optional[dict]:
        cache_key = id(obj)
        if cache_key in self._parent_cache:
            return self._parent_cache[cache_key]

        if isinstance(obj, dict):
            layer = obj
            while isinstance(layer, dict):
                direct = layer.get("vpiParent")
                if isinstance(direct, dict) and "index" in direct and "type" in direct:
                    self._parent_cache[cache_key] = direct
                    return direct
                layer = layer.get("base")

        stack = [obj]
        seen: Set[int] = set()
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                ident = id(current)
                if ident in seen:
                    continue
                seen.add(ident)
                parent = current.get("vpiParent")
                if isinstance(parent, dict) and "index" in parent and "type" in parent:
                    self._parent_cache[cache_key] = parent
                    return parent
                for value in current.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(current, list):
                stack.extend(value for value in current if isinstance(value, (dict, list)))
        self._parent_cache[cache_key] = None
        return None

    def source_location(self, obj: dict) -> dict:
        file_idx = self.extract_first(obj, "vpiFile")
        line = self.extract_first(obj, "vpiLineNo")
        col = self.extract_first(obj, "vpiColumnNo")
        file_path = self.symbol(file_idx)
        return {
            "file": file_path,
            "line": line,
            "column": col,
        }

    def clean_name(self, raw: Optional[str]) -> Optional[str]:
        if raw is None:
            return None
        if "@" in raw:
            return raw.split("@", 1)[1]
        return raw

    def module_name_from_ref(self, ref: dict | None) -> Optional[str]:
        if not ref:
            return None
        parent_obj, parent_type = self.resolve(ref)
        if parent_type != UHDM_MODULE_INST or parent_obj is None:
            return None
        return self.clean_name(self.symbol(self.extract_first(parent_obj, "vpiFullName")))

    def find_enclosing_module(self, obj: dict, obj_type: int) -> Optional[str]:
        current = obj
        current_type = obj_type
        visited: List[int] = []
        while True:
            cache_key = id(current)
            if cache_key in self._module_cache:
                cached = self._module_cache[cache_key]
                for key in visited:
                    self._module_cache[key] = cached
                return cached
            visited.append(cache_key)

            parent_ref = self.extract_parent(current)
            if parent_ref is None:
                for key in visited:
                    self._module_cache[key] = None
                return None
            name = self.module_name_from_ref(parent_ref)
            if name:
                for key in visited:
                    self._module_cache[key] = name
                return name
            parent_obj, parent_type = self.resolve(parent_ref)
            if parent_obj is None or parent_obj is current or id(parent_obj) in visited:
                for key in visited:
                    self._module_cache[key] = None
                return None
            current = parent_obj
            current_type = parent_type or 0

    def expr_value(self, ref: dict | None) -> Optional[str]:
        cache_key: Optional[Tuple[int, int]] = None
        if isinstance(ref, dict):
            idx = ref.get("index")
            type_str = ref.get("type")
            if idx is not None and type_str is not None and str(idx).isdigit():
                cache_key = (int(type_str), int(idx))
                if cache_key in self._expr_cache:
                    return self._expr_cache[cache_key]

        obj, typ = self.resolve(ref)
        if obj is None:
            if cache_key is not None:
                self._expr_cache[cache_key] = None
            return None
        result: Optional[str]
        if typ == UHMD_CONSTANT:
            result = self.symbol(obj.get("base", {}).get("vpiDecompile"))
        elif typ in (UHMD_REF_OBJ, UHMD_REF_VAR):
            result = self.clean_name(self.symbol(obj.get("vpiName")))
        elif typ == UHMD_OPERATION:
            operands = [self.expr_value(op) for op in obj.get("operands", [])]
            operands = [p for p in operands if p]
            op_type_raw = obj.get("vpiOpType")
            if isinstance(op_type_raw, int):
                op_type = op_type_raw
            elif isinstance(op_type_raw, str) and op_type_raw.isdigit():
                op_type = int(op_type_raw)
            else:
                op_type = None
            result = self.format_operation(op_type, operands)
        else:
            result = None

        if cache_key is not None:
            self._expr_cache[cache_key] = result
        return result

    def _wrap_operand(self, value: str) -> str:
        if not value:
            return value
        trimmed = value.strip()
        if not trimmed:
            return trimmed
        if trimmed.startswith(("(", "{", "'")):
            return trimmed
        if " " in trimmed or trimmed.startswith(("!", "~")):
            return f"({trimmed})"
        return trimmed

    def format_operation(self, op_type: Optional[int], operands: List[str]) -> Optional[str]:
        if not operands:
            return None
        if op_type in PREFIX_OPS:
            symbol = PREFIX_OPS[op_type]
            return f"{symbol}{self._wrap_operand(operands[0])}"
        if op_type in INFIX_OPS:
            symbol = INFIX_OPS[op_type]
            if len(operands) >= 2:
                left = self._wrap_operand(operands[0])
                right = self._wrap_operand(operands[1])
                return f"({left} {symbol} {right})"
            return f" {symbol} ".join(operands)
        if op_type == 32 and len(operands) >= 3:
            return f"({operands[0]} ? {operands[1]} : {operands[2]})"
        if op_type == 33:
            return "{ " + ", ".join(operands) + " }"
        if op_type == 34 and len(operands) >= 2:
            repeat = operands[0]
            inner = ", ".join(operands[1:])
            return f"{{{{{repeat}{{{inner}}}}}}}"
        if op_type in (39, 40) and operands:
            keyword = "posedge" if op_type == 39 else "negedge"
            return f"{keyword} {operands[0]}"
        if len(operands) == 1:
            return operands[0]
        return " ".join(operands)

    def collect_signal_names(self, ref: dict | None) -> List[str]:
        names: List[str] = []
        visited: Set[int] = set()
        cache_key: Optional[Tuple[int, int]] = None

        if isinstance(ref, dict):
            idx = ref.get("index")
            type_str = ref.get("type")
            if idx is not None and type_str is not None and str(idx).isdigit():
                cache_key = (int(type_str), int(idx))
                cached = self._signal_cache.get(cache_key)
                if cached is not None:
                    return list(cached)

        def dfs(node: dict | None, typ: Optional[int]) -> None:
            if node is None:
                return
            ident = id(node)
            if ident in visited:
                return
            visited.add(ident)
            if typ in (UHMD_REF_OBJ, UHMD_REF_VAR):
                name = self.clean_name(self.symbol(node.get("vpiName")))
                if name:
                    names.append(name)
                return
            if typ == UHMD_OPERATION:
                for operand in node.get("operands", []):
                    obj, kind = self.resolve(operand)
                    dfs(obj, kind)
                return
            for key, value in node.items():
                if key == "vpiParent":
                    continue
                if isinstance(value, dict) and "index" in value and "type" in value:
                    obj, kind = self.resolve(value)
                    dfs(obj, kind)
                elif isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, dict) and "index" in entry and "type" in entry:
                            obj, kind = self.resolve(entry)
                            dfs(obj, kind)

        obj, typ = self.resolve(ref)
        dfs(obj, typ)
        if cache_key is not None:
            self._signal_cache[cache_key] = list(names)
        return names

    def decode_width(self, net_obj: dict) -> Optional[str]:
        typespec_ref = self.extract_first(net_obj, "typespec")
        ts_obj, ts_type = self.resolve(typespec_ref)
        if ts_type == UHMD_REF_TYPESPEC and ts_obj is not None:
            actual = ts_obj.get("actualtypespec")
            ts_obj, ts_type = self.resolve(actual)
        if ts_type != UHMD_LOGIC_TYPESPEC or ts_obj is None:
            return None
        ranges = ts_obj.get("ranges", [])
        if not ranges:
            return None
        idx = int(ranges[0])
        range_obj = self.resolve_by_factory("factoryRange", idx)
        if not range_obj:
            return None
        left = self.expr_value(range_obj.get("leftexpr"))
        right = self.expr_value(range_obj.get("rightexpr"))
        if left and right:
            return f"[{left}:{right}]"
        return None


def build_modules(index: UHDMIndex) -> Dict[str, dict]:
    modules: Dict[str, dict] = {}
    for inst in index.factories.get("factoryModuleinst", []):
        if not inst.get("vpiTopModule") and not inst.get("base", {}).get("vpiTop"):
            continue
        name = index.clean_name(index.symbol(index.extract_first(inst, "vpiFullName")))
        if not name:
            continue
        modules[name] = {
            "module": name,
            "file": index.symbol(index.extract_first(inst, "vpiFile")),
            "ports": [],
            "signals": {},
            "procedural_assignments": [],
            "continuous_assignments": [],
            "_port_seen": set(),
        }
    return modules


def attach_ports(index: UHDMIndex, modules: Dict[str, dict]) -> None:
    for port in index.factories.get("factoryPort", []):
        parent_ref = index.extract_parent(port)
        if not parent_ref:
            continue
        module_name = index.module_name_from_ref(parent_ref)
        if not module_name:
            continue
        module = modules.get(module_name)
        if not module:
            continue
        port_base = port.get("base", {})
        direction = DIRECTION_MAP.get(int(port_base.get("vpiDirection", "0")), "unknown")
        name = index.clean_name(index.symbol(port_base.get("vpiName")))
        net_name = None
        low_conn = port_base.get("lowconn")
        if low_conn:
            ref_obj, _ = index.resolve(low_conn)
            if ref_obj:
                net_name = index.clean_name(index.symbol(ref_obj.get("vpiName")))
        seen = module.setdefault("_port_seen", set())
        key = (name, direction)
        if key in seen:
            continue
        seen.add(key)
        module["ports"].append({
            "name": name,
            "direction": direction,
            "net": net_name or name,
        })


def attach_signals(index: UHDMIndex, modules: Dict[str, dict]) -> None:
    for net in index.factories.get("factoryLogicnet", []):
        parent_ref = index.extract_parent(net)
        if not parent_ref:
            continue
        module_name = index.module_name_from_ref(parent_ref)
        if not module_name:
            continue
        module = modules.get(module_name)
        if not module:
            continue
        name = index.clean_name(index.symbol(index.extract_first(net, "vpiName")))
        if not name:
            continue
        width = index.decode_width(net)
        module["signals"].setdefault(name, {"name": name, "width": width})


def summarize_assignment(index: UHDMIndex, assign: dict, kind: str) -> dict:
    lhs_name = None
    lhs_obj, lhs_type = index.resolve(assign.get("lhs"))
    if lhs_type in (UHMD_REF_OBJ, UHMD_REF_VAR) and lhs_obj:
        lhs_name = index.clean_name(index.symbol(lhs_obj.get("vpiName")))
    rhs_refs = index.collect_signal_names(assign.get("rhs"))
    rhs_expr = index.expr_value(assign.get("rhs"))
    location = index.source_location(assign)
    return {
        "kind": kind,
        "lhs": lhs_name,
        "rhs_signals": sorted(dict.fromkeys(rhs_refs)),
        "rhs_expr": rhs_expr,
        "source": location,
    }


def attach_assignments(index: UHDMIndex, modules: Dict[str, dict]) -> None:
    for assign in index.factories.get("factoryAssignment", []):
        module_name = index.find_enclosing_module(assign, UHMD_ASSIGNMENT)
        if not module_name or module_name not in modules:
            continue
        entry = summarize_assignment(index, assign, "nonblocking" if not assign.get("vpiBlocking") else "blocking")
        always_ctx = None
        parent_ref = index.extract_parent(assign)
        while parent_ref:
            parent_obj, parent_type = index.resolve(parent_ref)
            if parent_type == UHDM_ALWAYS and parent_obj:
                always_type = ALWAYS_KIND.get(int(parent_obj.get("vpiAlwaysType", 0)), "always")
                always_ctx = always_type
                break
            parent_ref = index.extract_parent(parent_obj) if parent_obj else None
        entry["always_type"] = always_ctx
        modules[module_name]["procedural_assignments"].append(entry)

    for assign in index.factories.get("factoryContassign", []):
        module_name = index.find_enclosing_module(assign, UHMD_CONT_ASSIGN)
        if not module_name or module_name not in modules:
            continue
        entry = summarize_assignment(index, assign, "continuous")
        modules[module_name]["continuous_assignments"].append(entry)


def format_modules(modules: Dict[str, dict]) -> List[dict]:
    formatted = []
    for module in modules.values():
        signals = sorted(module["signals"].values(), key=lambda item: item["name"])
        module_ports = module["ports"]
        formatted.append({
            "module": module["module"],
            "file": module["file"],
            "ports": module_ports,
            "signals": signals,
            "procedural_assignments": module["procedural_assignments"],
            "continuous_assignments": module["continuous_assignments"],
        })
    formatted.sort(key=lambda item: item["module"])
    return formatted


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract structured RTL data from UHDM JSON")
    parser.add_argument("source", type=Path, help="UHDM JSON file (capnp convert output)")
    parser.add_argument("--output", type=Path, default=Path("build/rtl_ast.json"), help="Structured JSON output path")
    args = parser.parse_args()

    data = json.loads(args.source.read_text())
    index = UHDMIndex(data)

    modules = build_modules(index)
    attach_ports(index, modules)
    attach_signals(index, modules)
    attach_assignments(index, modules)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "uhdm_version": data.get("version"),
        "source": str(args.source),
        "modules": format_modules(modules),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"[uhdm_extract] modules: {len(payload['modules'])} -> {args.output}")


if __name__ == "__main__":
    main()
