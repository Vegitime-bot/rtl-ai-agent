import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from pathlib import Path
import matplotlib as mpl

mpl.rcParams['font.family'] = 'DejaVu Sans'

out_dir = Path(__file__).parent
out_dir.mkdir(parents=True, exist_ok=True)


def add_box(ax, x, y, w, h, text, fc="#f5f5f5", ec="#333333", fontsize=9, lw=1.5):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", linewidth=lw, edgecolor=ec, facecolor=fc)
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fontsize, wrap=True)


def add_arrow(ax, x1, y1, x2, y2, text=None, fontsize=8, color="#444444"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", linewidth=1.2, color=color))
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, text, ha='center', va='bottom', fontsize=fontsize, color=color)


# 1. System configuration diagram
fig, ax = plt.subplots(figsize=(10, 6))
ax.set_xlim(0, 10)
ax.set_ylim(0, 6)
ax.axis('off')

add_box(ax, 0.5, 2.3, 1.8, 1.4, "User\n(Yunkey)", fc="#e0f7fa")
add_box(ax, 3, 0.5, 4, 5, "OpenClaw Agent\n(Mac mini workspace)", fc="#fff3e0", fontsize=11)

ax.text(5, 4.6, "- projects/rtl-ai-agent\n- run_full_pipeline.sh\n- build/, outputs/\n- offline_wheels/", ha='center', va='center', fontsize=9)
ax.text(5, 3.1, "- .env: NEO4J_PASSWORD / MODEL_API_KEY\n- ~/.config/gmail-agent (credentials & token)\n- memory/, docs/", ha='center', va='center', fontsize=9)
ax.text(5, 1.7, "- OpenClaw CLI + skills\n- Python 3.9 env\n- logs/commands.log", ha='center', va='center', fontsize=9)

add_arrow(ax, 2.3, 3, 3, 3.2, "Tasks / feedback")

add_box(ax, 8, 4.5, 1.6, 1.1, "Neo4j Docker\n(bolt://127.0.0.1)", fc="#ede7f6")
add_box(ax, 8, 2.7, 1.6, 1.1, "LLM API\n(Claude Sonnet)", fc="#e8f5e9")
add_box(ax, 8, 1.0, 1.6, 1.1, "Gmail API", fc="#fce4ec")

add_arrow(ax, 7, 5, 8, 5, "graph ingest")
add_arrow(ax, 7, 3.2, 8, 3.2, "LLM calls")
add_arrow(ax, 7, 1.5, 8, 1.5, "Email reporting")

fig.savefig(out_dir / 'configuration.png', dpi=300, bbox_inches='tight')
plt.close(fig)


# 2. Architecture diagram
fig, ax = plt.subplots(figsize=(12, 6.5))
ax.set_xlim(0, 12)
ax.set_ylim(0, 7)
ax.axis('off')

add_box(ax, 0.4, 4.3, 2.5, 2.1, "Input sources\n─────────────\norigin.v\nalgorithm_origin.py\nalgorithm_new.py\nuArch_origin.txt\nuArch_new.txt", fc="#e1f5fe")
add_box(ax, 3.3, 4.3, 2.4, 2.1, "Preprocessing\n─────────────\nrun_surelog\nuhdm_extract\nbuild_graph\ndiff_pseudo / chunk_ma", fc="#fff3e0")
add_box(ax, 6.1, 4.3, 2.6, 2.1, "Data layer\n─────────────\nrtl_ast.json\ncausal_graph.json\npseudo_diff.json\nuarch_origin/new.json", fc="#ede7f6")
add_box(ax, 9.4, 4.9, 2.0, 1.2, "Neo4j\n(local Docker)", fc="#ede7f6", ec="#7e57c2", lw=2)
add_box(ax, 9.4, 3.2, 2.0, 1.1, "rag.db\n(SQLite)", fc="#ede7f6")
add_box(ax, 6.1, 1.5, 2.6, 2.0, "Orchestrator\nflow.py + Claude\nAnalysis-driven RTL", fc="#e8f5e9", ec="#2e7d32", lw=2)
add_box(ax, 3.3, 0.8, 2.4, 2.1, "Outputs & services\n─────────────\noutputs/new.v\nbundle.json\nanalysis.md\nGmail report", fc="#fce4ec")
add_box(ax, 0.4, 0.8, 2.5, 2.1, "External sharing\n─────────────\nGmail API\nZIP/report packages", fc="#f3e5f5")
add_box(ax, 3.3, 3.15, 2.4, 0.9, "Analysis plan / findings\n(bundle.json plan, pseudo diff)", fc="#fffde7")
add_box(ax, 9.4, 2.0, 2.0, 0.9, "neo4j_query.py\n(get_causal_context)", fc="#e8eaf6", ec="#3949ab", lw=2)

add_arrow(ax, 2.9, 5.3, 3.3, 5.3, "UHDM")
add_arrow(ax, 5.7, 5.3, 6.1, 5.3, "JSON")
add_arrow(ax, 8.7, 5.3, 9.4, 5.5, "neo4j_ingest")
add_arrow(ax, 8.7, 4.7, 9.4, 3.8, "rag.ingest")
add_arrow(ax, 10.4, 4.9, 10.4, 4.1, "Graph storage", color="#7e57c2")
add_arrow(ax, 10.4, 3.2, 10.4, 2.9, "RAG data")
add_arrow(ax, 10.4, 2.0, 8.7, 2.5, "Graph context", color="#3949ab")
add_arrow(ax, 6.1, 3.6, 7.4, 3.6, "rag.db context")
add_arrow(ax, 4.5, 3.15, 4.95, 3.4, "analysis guidance", color="#f9a825")
add_arrow(ax, 5.9, 2.4, 5.7, 2.4)
add_arrow(ax, 3.3, 1.8, 3.3, 2.8, "generate")
add_arrow(ax, 2.9, 1.8, 2.9, 1.8)
add_arrow(ax, 6.1, 1.5, 5.7, 1.8)
add_arrow(ax, 2.8, 1.8, 2.9, 1.8)
add_arrow(ax, 3.3, 1.8, 2.9, 1.8)
add_arrow(ax, 2.5, 1.8, 2.9, 1.8)
add_arrow(ax, 6.1, 1.2, 2.8, 1.9)
add_arrow(ax, 2.9, 1.8, 2.9, 1.8)

ax.text(10.4, 1.85, "Active inference:\nsignal causal context\n→ LLM prompt", ha='center', va='top', fontsize=7.5, color="#3949ab",
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#e8eaf6', edgecolor='#3949ab', linewidth=1))

fig.savefig(out_dir / 'architecture.png', dpi=300, bbox_inches='tight')
plt.close(fig)


# 3. Operation scheme diagram
steps = [
    "1. run_surelog\n(origin.v → UHDM)",
    "2. uhdm_extract\n(rtl_ast.json)",
    "3. build_graph\n(causal_graph)",
    "4. diff_pseudo\n(algorithm Δ)",
    "5. chunk_ma\n(uArch origin/new)",
    "6. rag.ingest\n(rag.db)",
    "7. neo4j_ingest\n(causal graph)",
    "8. neo4j_query + orchestrator\n(Graph + RAG context)",
    "9. outputs + Gmail\nReport",
]

fig, ax = plt.subplots(figsize=(12, 3.5))
ax.set_xlim(0, len(steps) + 1)
ax.set_ylim(0, 2)
ax.axis('off')

for idx, step in enumerate(steps, start=1):
    add_box(ax, idx - 0.4, 0.7, 0.9, 0.9, step, fc="#f5f5f5", fontsize=8, lw=1.2)
    if idx < len(steps):
        add_arrow(ax, idx + 0.5, 1.15, idx + 0.8, 1.15)

ax.text(0.5, 1.9, "run_full_pipeline.sh workflow", fontsize=13, fontweight='bold')
ax.text((len(steps) + 1) / 2, 0.2, "Each stage writes to build/ or outputs/ and stops immediately on failure (set -e)", ha='center', fontsize=9)

fig.savefig(out_dir / 'operation_scheme.png', dpi=300, bbox_inches='tight')
plt.close(fig)

print(f"diagrams saved to {out_dir}")
