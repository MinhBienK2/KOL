"""Convert ComfyUI UI-format workflow templates (subgraphs included) into API-format prompt graphs.

The pika H3 Flex workflows the gateway serves are Comfy-Org UI workflows: they carry widget
values positionally, nest a whole pipeline inside a *subgraph* and use dynamic (autogrow)
inputs. ``POST /prompt`` only accepts the API format, so every template must be converted
before it can be queued.

Two rules were established empirically against the running gateway (see ``docs/adr``):

1. Dynamic inputs keep their dotted path in the API graph (``values.a``,
   ``ref_images.ref_image_0``). The flat name (``a``) fails validation with
   ``Required input is missing: a``.
2. Widget values live in ``widgets_values_named`` (name -> value), not in a positional array.

The converter is pure: it needs the template plus the node schemas (``/object_info``) and
never touches the network.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: Frontend-only nodes that have no backend class and must not enter the API graph.
SKIP_TYPES = frozenset({"MarkdownNote", "Note", "Reroute", "PrimitiveNote"})

#: API node ids for expanded subgraph nodes are offset by this amount to stay unique.
SUBGRAPH_OFFSET = 1000


def class_spec(oi: Dict[str, Any], class_type: str) -> Dict[str, tuple]:
    """``{input_name: (section, io_type)}`` for one node class (empty when unknown)."""
    spec = oi.get(class_type)
    if not spec:
        return {}
    out: Dict[str, tuple] = {}
    for section in ("required", "optional"):
        for name, value in (spec["input"].get(section) or {}).items():
            io_type = value[0] if isinstance(value, list) else value
            if isinstance(io_type, list):
                io_type = io_type[0]
            out[name] = (section, io_type)
    return out


def coerce(value: Any, io_type: Any) -> Any:
    """Cast a widget value to the type its input expects (``INT``/``FLOAT``/``BOOLEAN``/text)."""
    if value is None:
        return None
    kind = io_type[0] if isinstance(io_type, list) else io_type
    if not isinstance(kind, str):
        return value
    try:
        if kind == "INT":
            return int(float(value))
        if kind == "FLOAT":
            return float(value)
        if kind == "BOOLEAN":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes")
            return bool(value)
    except (TypeError, ValueError):
        return value
    if kind in ("STRING", "COMBO") and not isinstance(value, str):
        return str(value)
    return value


def widget_values(node: Dict[str, Any]) -> Dict[str, Any]:
    """``{widget_name: value}`` for a node (the named form is the authoritative one)."""
    named = node.get("widgets_values_named")
    return dict(named) if named else {}


class InstanceRef:
    """Placeholder for a link whose origin is a subgraph instance output."""

    def __init__(self, inst_id: int, slot: int) -> None:
        self.inst_id = inst_id
        self.slot = slot

    def resolve(self, sources: Dict[int, List[Any]]) -> Any:
        return sources[self.inst_id][self.slot]


class Converter:
    """Converts one UI workflow (with optional subgraphs) into an API-format graph."""

    def __init__(self, workflow: Dict[str, Any], oi: Dict[str, Any]) -> None:
        self.wf = workflow
        self.oi = oi
        self.sg_defs = {
            s["id"]: s for s in (workflow.get("definitions", {}).get("subgraphs") or [])
        }
        self.top_links = {link[0]: link for link in workflow.get("links", [])}
        self.api: Dict[int, Dict[str, Any]] = {}
        self.instance_outputs: Dict[int, Dict[int, List[Any]]] = {}

    # -- top level ---------------------------------------------------------------
    def build(self) -> Dict[str, Dict[str, Any]]:
        for node in self.wf["nodes"]:
            if node["type"] in self.sg_defs or node["type"] in SKIP_TYPES:
                continue
            self.api[node["id"]] = self.build_node(node, self.resolve_top)
        for node in self.wf["nodes"]:
            if node["type"] in self.sg_defs:
                self.instance_outputs[node["id"]] = self.expand_instance(
                    node, self.sg_defs[node["type"]]
                )
        for api_node in self.api.values():
            for key, value in list(api_node["inputs"].items()):
                if isinstance(value, InstanceRef):
                    api_node["inputs"][key] = value.resolve(self.instance_outputs)
        return {str(k): v for k, v in sorted(self.api.items())}

    def _is_instance(self, node_id: int) -> bool:
        return any(n["id"] == node_id and n["type"] in self.sg_defs for n in self.wf["nodes"])

    def resolve_top(self, link_id: int) -> Any:
        link = self.top_links[link_id]
        origin_id, origin_slot = link[1], link[2]
        if self._is_instance(origin_id):
            return InstanceRef(origin_id, origin_slot)
        return [str(origin_id), origin_slot]

    # -- nodes -------------------------------------------------------------------
    def build_node(self, node: Dict[str, Any], resolve_link) -> Dict[str, Any]:
        class_type = node["type"]
        spec = class_spec(self.oi, class_type)
        widgets = widget_values(node)
        inputs: Dict[str, Any] = {}
        for entry in node.get("inputs") or []:
            name = entry.get("name")
            if name is None:
                continue
            link = entry.get("link")
            if link is not None:
                value = resolve_link(link)
            elif "widget" in entry:
                value = widgets.get(entry["widget"].get("name"))
            else:
                continue
            if value is None:
                continue
            if isinstance(value, InstanceRef):
                inputs[name] = value
                continue
            io_type = spec.get(name, (None, None))[1]
            inputs[name] = value if isinstance(value, list) else coerce(value, io_type)
        for wname, wval in widgets.items():
            if wname in inputs or wname not in spec:
                continue
            inputs[wname] = coerce(wval, spec[wname][1])
        out: Dict[str, Any] = {"class_type": class_type, "inputs": inputs}
        title = node.get("title") or (node.get("properties") or {}).get("Node name for S&R")
        if title:
            out["_meta"] = {"title": title}
        return out

    # -- subgraphs ---------------------------------------------------------------
    def expand_instance(self, inst: Dict[str, Any], sg: Dict[str, Any]) -> Dict[int, List[Any]]:
        sg_links = {link["id"]: link for link in sg["links"]}
        sg_inputs = sg["inputs"]
        inst_inputs = {entry["name"]: entry for entry in (inst.get("inputs") or [])}
        inst_widgets = widget_values(inst)

        def sg_input_value(slot: int) -> Any:
            """Value of a subgraph input: instance link > instance widget > inner node widget."""
            name = sg_inputs[slot]["name"]
            link_ids = sg_inputs[slot].get("linkIds", [])
            entry = inst_inputs.get(name)
            if entry is not None and entry.get("link") is not None:
                return self.resolve_top(entry["link"])
            if name in inst_widgets:
                return inst_widgets[name]
            for node in sg["nodes"]:
                for inner in node.get("inputs") or []:
                    if "widget" in inner and inner.get("link") in link_ids:
                        return widget_values(node).get(inner["widget"].get("name"))
            return None

        def resolve_inner(link_id: int) -> Any:
            link = sg_links[link_id]
            origin_id, origin_slot = link["origin_id"], link["origin_slot"]
            if origin_id == -10:
                return sg_input_value(origin_slot)
            if origin_id == -20:
                return None
            return [str(SUBGRAPH_OFFSET + origin_id), origin_slot]

        for node in sg["nodes"]:
            if node["type"] in SKIP_TYPES:
                continue
            self.api[SUBGRAPH_OFFSET + node["id"]] = self.build_node(node, resolve_inner)

        out_source: Dict[int, List[Any]] = {}
        for idx, out in enumerate(sg["outputs"]):
            for link_id in out.get("linkIds", []):
                link = sg_links[link_id]
                out_source[idx] = [str(SUBGRAPH_OFFSET + link["origin_id"]), link["origin_slot"]]
        return {idx: src for idx, src in out_source.items() if idx < len(inst.get("outputs") or [])}


def convert(template: Dict[str, Any], oi: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Convert a UI workflow into an API-format graph ``{node_id: {class_type, inputs}}``."""
    return Converter(template, oi).build()


# -- graph surgery helpers ------------------------------------------------------

def nodes_by_class(graph: Dict[str, Dict[str, Any]], class_type: str) -> List[str]:
    """Ids of every node of ``class_type`` in the graph."""
    return [node_id for node_id, node in graph.items() if node["class_type"] == class_type]


def link_target(graph: Dict[str, Dict[str, Any]], node_id: str, input_key: str) -> Optional[str]:
    """Id of the node feeding ``node_id.input_key`` when that input is a link."""
    value = (graph.get(node_id) or {}).get("inputs", {}).get(input_key)
    if isinstance(value, list) and value:
        return str(value[0])
    return None


def set_linked_image(graph: Dict[str, Dict[str, Any]], node_id: str, input_key: str, filename: str) -> bool:
    """Point a linked image input at ``filename`` (the node behind it must be a ``LoadImage``)."""
    target = link_target(graph, node_id, input_key)
    if target is None:
        return False
    target_node = graph.get(target)
    if not target_node or target_node["class_type"] != "LoadImage":
        return False
    target_node["inputs"]["image"] = filename
    return True


def add_load_image(graph: Dict[str, Dict[str, Any]], filename: str, node_id: str) -> str:
    """Add a ``LoadImage`` node and return its id."""
    graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
    return node_id


def drop_input(graph: Dict[str, Dict[str, Any]], node_id: str, input_key: str) -> None:
    """Remove an input (e.g. an unused last frame) from a node."""
    (graph.get(node_id) or {}).get("inputs", {}).pop(input_key, None)


def iter_nodes(graph: Dict[str, Dict[str, Any]], class_type: str) -> Iterable[tuple]:
    """``(node_id, node)`` pairs for every node of ``class_type``."""
    for node_id, node in graph.items():
        if node["class_type"] == class_type:
            yield node_id, node
