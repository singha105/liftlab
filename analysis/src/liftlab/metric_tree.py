"""The metric tree in docs/METRICS.md, drawn as a PNG for the dashboard and the README.

The Mermaid block in METRICS.md is the source. This parses it (node labels, `-->` and `-.-`
edges, the Guardrails subgraph) and lays it out as a tidy tree, so the picture can't drift
from the doc: change the doc, rerun `liftlab metric-tree`.
"""

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from liftlab import warehouse

METRICS = warehouse.REPO_DIR / "docs" / "METRICS.md"

_NODE = re.compile(r'^\s*(\w+)\["([^"]+)"\]\s*$')
_EDGE = re.compile(r"^\s*(\w+)\s*(-->|-\.-)\s*(\w+)\s*$")


@dataclass(frozen=True)
class Tree:
    labels: dict[str, list[str]]  # node id -> lines, the first is the name
    edges: list[tuple[str, str, bool]]  # parent, child, dotted
    guardrails: frozenset[str]
    root: str


def parse(markdown: str) -> Tree:
    """The first ```mermaid block of `markdown`."""
    match = re.search(r"```mermaid\n(.*?)```", markdown, re.S)
    if not match:
        raise ValueError("no mermaid block")
    labels, edges, guardrails, group = {}, [], set(), None
    for line in match.group(1).splitlines():
        if line.strip().startswith("subgraph"):
            group = line.split(None, 1)[1].strip()
        elif line.strip() == "end":
            group = None
        elif node := _NODE.match(line):
            labels[node[1]] = node[2].split("<br/>")
            if group == "Guardrails":
                guardrails.add(node[1])
        elif edge := _EDGE.match(line):
            edges.append((edge[1], edge[3], edge[2] == "-.-"))
    children = {child for _, child, _ in edges}
    roots = [node for node in labels if node not in children]
    if len(roots) != 1:
        raise ValueError(f"the tree needs exactly one root, found {roots}")
    return Tree(labels, edges, frozenset(guardrails), roots[0])


def layout(tree: Tree) -> dict[str, tuple[float, int]]:
    """(column, depth) per node: leaves left to right in order, parents over their children.

    A parent is centered over its solid-edge children; dotted ones (the guardrails) hang to
    the right without pulling it off center.
    """
    children: dict[str, list[tuple[str, bool]]] = {}
    for parent, child, dotted in tree.edges:
        children.setdefault(parent, []).append((child, dotted))
    position: dict[str, tuple[float, int]] = {}
    next_leaf = 0.0

    def place(node: str, depth: int) -> float:
        nonlocal next_leaf
        kids = children.get(node, [])
        if not kids:
            position[node] = (next_leaf, depth)
            next_leaf += 1
            return position[node][0]
        xs = [(place(child, depth + 1), dotted) for child, dotted in kids]
        solid = [x for x, dotted in xs if not dotted] or [x for x, _ in xs]
        position[node] = ((min(solid) + max(solid)) / 2, depth)
        return position[node][0]

    place(tree.root, 0)
    return position


def save(tree: Tree, out_dir: Path) -> list[Path]:
    from matplotlib.patches import FancyBboxPatch

    from liftlab import proof_charts as pc

    plt = pc.plt
    position = layout(tree)
    columns = max(x for x, _ in position.values()) + 1
    depth = max(d for _, d in position.values()) + 1
    box_w, box_h, row_h = 0.9, 0.62, 1.15
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for mode, theme in pc.THEMES.items():
        pc._figure(theme)  # fonts
        fig = plt.figure(figsize=(1.45 * columns, 1.5 * depth + 1.0))
        fig.patch.set_facecolor(theme["surface"])
        ax = fig.add_axes((0.01, 0.02, 0.98, 0.84))
        ax.set_axis_off()
        ax.set_xlim(-0.55, columns - 0.45)
        ax.set_ylim(-(depth - 1) * row_h - box_h / 2 - 0.1, box_h / 2 + 0.1)

        def top(node: str) -> tuple[float, float]:
            x, d = position[node]
            return x, -d * row_h + box_h / 2

        for parent, child, dotted in tree.edges:
            (px, pd), (cx, cy) = position[parent], top(child)
            py = -pd * row_h - box_h / 2
            mid = (py + cy) / 2
            ax.plot(
                [px, px, cx, cx], [py, mid, mid, cy],
                color=theme["muted"] if dotted else theme["axis"], linewidth=1.4,
                linestyle=(0, (2, 3)) if dotted else "-", zorder=0.5 if dotted else 1,
            )  # fmt: skip
        for node, lines in tree.labels.items():
            x, d = position[node]
            y = -d * row_h
            is_root, is_guard = node == tree.root, node in tree.guardrails
            ax.add_patch(
                FancyBboxPatch(
                    (x - box_w / 2, y - box_h / 2),
                    box_w,
                    box_h,
                    boxstyle="round,pad=0,rounding_size=0.06",
                    facecolor=theme["surface"],
                    edgecolor=theme["ink"] if is_root else theme["axis"],
                    linewidth=2.6 if is_root else 1.2,
                    linestyle=(0, (4, 3)) if is_guard else "-",
                    zorder=2,
                )  # fmt: skip
            )
            name = "\n".join(textwrap.wrap(lines[0], 18))
            detail = "\n".join(textwrap.wrap(" ".join(lines[1:]), 20))
            ax.text(
                x, y + (0.07 if detail else 0), name, ha="center", va="bottom" if detail else
                "center", color=theme["ink"], fontsize=9.5, fontweight="bold", zorder=3,
            )  # fmt: skip
            if detail:
                ax.text(
                    x, y - 0.02, detail, ha="center", va="top", color=theme["secondary"],
                    fontsize=8.5, zorder=3,
                )  # fmt: skip
        guard = [position[n][0] for n in tree.guardrails]
        if guard:
            ax.text(
                (min(guard) + max(guard)) / 2, -row_h + box_h / 2 + 0.06, "Guardrails",
                ha="center", va="bottom", color=theme["muted"], fontsize=9,
            )  # fmt: skip
        fig.text(
            0.01, 0.95, "StudySprint metric tree", color=theme["ink"], fontsize=13,
            fontweight="bold",
        )  # fmt: skip
        fig.text(
            0.01, 0.905, "The North Star, the inputs that move it, and the guardrails it can't "
            "trade away. From docs/METRICS.md.", color=theme["secondary"], fontsize=10,
        )  # fmt: skip
        path = out_dir / f"metric-tree-{mode}.png"
        fig.savefig(path, dpi=150, facecolor=theme["surface"])
        plt.close(fig)
        written.append(path)
    return written
