"""
RTL AI Agent — 파이프라인 & 컨셉 다이어그램 (matplotlib 기반)
두 장 생성:
  diagram_pipeline.png  — 4단계 파이프라인 플로우
  diagram_concept.png   — 핵심 기술 컨셉 맵
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# macOS 한글 폰트 설정
plt.rcParams["font.family"] = "Apple SD Gothic Neo"
plt.rcParams["axes.unicode_minus"] = False
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import matplotlib.patheffects as pe
import numpy as np

# ── 공통 색상 ──────────────────────────────────────────────
BG      = "#0D1117"
NAVY    = "#1A1F35"
BLUE    = "#1E3A8A"
LBLUE   = "#3B82F6"
GOLD    = "#F59E0B"
GREEN   = "#10B981"
PURPLE  = "#7C3AED"
TEAL    = "#0D9488"
WHITE   = "#F8FAFC"
LGRAY   = "#94A3B8"
ORANGE  = "#F97316"

def set_bg(fig, ax, color=BG):
    fig.patch.set_facecolor(color)
    ax.set_facecolor(color)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")

def rbox(ax, x, y, w, h, color, alpha=1.0, radius=0.3):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle=f"round,pad=0,rounding_size={radius}",
                         facecolor=color, edgecolor="none", alpha=alpha,
                         zorder=2)
    ax.add_patch(box)
    return box

def arrow(ax, x0, y0, x1, y1, color=GOLD, lw=2):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                mutation_scale=18),
                zorder=3)

def txt(ax, x, y, s, size=10, color=WHITE, bold=False, ha="center", va="center", zorder=4):
    w = "bold" if bold else "normal"
    ax.text(x, y, s, fontsize=size, color=color, fontweight=w,
            ha=ha, va=va, zorder=zorder,
            path_effects=[pe.withStroke(linewidth=0, foreground=BG)])

# ══════════════════════════════════════════════════════════════
# DIAGRAM 1 — 4단계 파이프라인 플로우
# ══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(18, 9))
set_bg(fig, ax)

# 배경 타이틀
rbox(ax, 0.1, 7.8, 15.8, 1.0, BLUE, alpha=0.6)
txt(ax, 8, 8.32, "AI 기반 RTL 자동 생성 — 파이프라인 플로우", 18, bold=True)
txt(ax, 8, 7.95, "Spec 변경 입력부터 검증된 RTL 출력까지 4단계 자동화", 11, color=LGRAY)

# 단계 정의
stages = [
    {
        "label": "STEP 1",
        "title": "입력",
        "color": BLUE,
        "items": ["origin.v\n(기존 RTL)", "uArch Spec\n(변경 스펙)", "Algorithm\n(동작 모델)"],
        "x": 0.3,
        "icon": "📥"
    },
    {
        "label": "STEP 2",
        "title": "분석 · 빌드",
        "color": PURPLE,
        "items": ["RTL 파싱\n→ AST", "신호 인과관계\n그래프 구축", "스펙 청크\n벡터 인덱싱"],
        "x": 4.3,
        "icon": "🔍"
    },
    {
        "label": "STEP 3",
        "title": "AI 추론 · 생성",
        "color": TEAL,
        "items": ["Spec Agent\n스펙 분석", "Plan Agent\n변경 계획", "CodeGen LLM\nRTL 생성"],
        "x": 8.3,
        "icon": "🧠"
    },
    {
        "label": "STEP 4",
        "title": "검증 · 출력",
        "color": "#065F46",
        "items": ["신호 구조\n자동 검증", "실패 시\n자동 재생성", "✅ new.v\n최종 출력"],
        "x": 12.3,
        "icon": "✔"
    },
]

BOX_W = 3.7
for i, s in enumerate(stages):
    x = s["x"]
    # 메인 박스
    rbox(ax, x, 1.0, BOX_W, 6.5, NAVY, radius=0.25)
    rbox(ax, x, 6.6, BOX_W, 0.9, s["color"], radius=0.25)
    # 라벨
    txt(ax, x + BOX_W/2, 7.05, s["label"], 10, bold=True)
    txt(ax, x + BOX_W/2, 6.72, s["title"], 13, bold=True)
    # 아이템 박스 3개
    for j, item in enumerate(s["items"]):
        iy = 4.8 - j * 1.65
        rbox(ax, x + 0.2, iy, BOX_W - 0.4, 1.4, s["color"], alpha=0.35, radius=0.2)
        txt(ax, x + BOX_W/2, iy + 0.72, item, 10, color=WHITE)
    # 화살표 (마지막 제외)
    if i < 3:
        ax_x = x + BOX_W + 0.15
        arrow(ax, ax_x, 4.25, ax_x + 0.05, 4.25, color=GOLD, lw=2.5)

# 하단 요약 바
rbox(ax, 0.1, 0.1, 15.8, 0.75, BLUE, alpha=0.4, radius=0.2)
txt(ax, 8, 0.49, "기존: 수일 소요 (수작업)     →     신규: 수십 분 이내 (AI 자동화)", 11, color=LGRAY)

plt.tight_layout(pad=0)
plt.savefig("/Users/vegitime/.openclaw/workspace/projects/rtl-ai-agent/docs/diagram_pipeline.png",
            dpi=150, bbox_inches="tight", facecolor=BG)
plt.close()
print("✅ diagram_pipeline.png 생성 완료")


# ══════════════════════════════════════════════════════════════
# DIAGRAM 2 — 핵심 기술 컨셉 맵
# ══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(18, 9))
set_bg(fig, ax)

# 타이틀
rbox(ax, 0.1, 7.8, 15.8, 1.0, TEAL, alpha=0.5)
txt(ax, 8, 8.32, "AI 기반 RTL 자동 생성 — 핵심 기술 컨셉", 18, bold=True)
txt(ax, 8, 7.95, "신호 인과관계 지식 그래프 × Vector RAG × LLM Code Generation", 11, color=LGRAY)

# ── 중앙: AI Agent 허브 ──────────────────────────────────────
cx, cy = 8.0, 4.2
rbox(ax, cx-1.5, cy-1.0, 3.0, 2.0, TEAL, alpha=0.8, radius=0.3)
txt(ax, cx, cy+0.4, "🧠 AI Agent", 14, bold=True)
txt(ax, cx, cy-0.1, "Orchestrator", 11, color=LGRAY)
txt(ax, cx, cy-0.55, "(flow.py)", 10, color=LGRAY)

# ── 왼쪽 상단: 입력 ──────────────────────────────────────────
rbox(ax, 0.4, 5.8, 3.5, 1.9, BLUE, alpha=0.6, radius=0.25)
txt(ax, 2.15, 7.25, "📥 입력", 12, bold=True, color=GOLD)
txt(ax, 2.15, 6.75, "origin.v", 10, color=WHITE)
txt(ax, 2.15, 6.38, "uArch Spec (변경전/후)", 10, color=LGRAY)
txt(ax, 2.15, 6.02, "Algorithm (변경전/후)", 10, color=LGRAY)
arrow(ax, 3.9, 6.5, cx-1.5, cy+0.3, color=LBLUE, lw=2)

# ── 왼쪽 하단: 출력 ──────────────────────────────────────────
rbox(ax, 0.4, 1.5, 3.5, 1.9, "#065F46", alpha=0.6, radius=0.25)
txt(ax, 2.15, 2.95, "✅ 출력", 12, bold=True, color=GREEN)
txt(ax, 2.15, 2.48, "new.v (검증된 RTL)", 10, color=WHITE)
txt(ax, 2.15, 2.08, "analysis.md", 10, color=LGRAY)
txt(ax, 2.15, 1.68, "bundle.json", 10, color=LGRAY)
arrow(ax, cx-1.5, cy-0.5, 3.9, 2.5, color=GREEN, lw=2)

# ── 오른쪽 상단: Neo4j 지식 그래프 ──────────────────────────
rbox(ax, 12.1, 5.8, 3.5, 1.9, PURPLE, alpha=0.55, radius=0.25)
txt(ax, 13.85, 7.25, "🔗 신호 인과관계 그래프", 11, bold=True, color=GOLD)
txt(ax, 13.85, 6.72, "Neo4j Graph DB", 10, color=WHITE)
txt(ax, 13.85, 6.35, "DRIVES 엣지", 10, color=LGRAY)
txt(ax, 13.85, 5.98, "2-hop 컨텍스트 주입", 10, color=LGRAY)
arrow(ax, cx+1.5, cy+0.3, 12.1, 6.5, color=PURPLE, lw=2)

# ── 오른쪽 하단: Vector RAG ──────────────────────────────────
rbox(ax, 12.1, 1.5, 3.5, 1.9, ORANGE, alpha=0.45, radius=0.25)
txt(ax, 13.85, 2.93, "📚 Vector RAG", 12, bold=True, color=GOLD)
txt(ax, 13.85, 2.47, "FAISS + BGE-M3", 10, color=WHITE)
txt(ax, 13.85, 2.07, "스펙 시맨틱 검색", 10, color=LGRAY)
txt(ax, 13.85, 1.67, "관련 청크 자동 주입", 10, color=LGRAY)
arrow(ax, cx+1.5, cy-0.3, 12.1, 2.3, color=ORANGE, lw=2)

# ── 하단 중앙: 검증 루프 ─────────────────────────────────────
rbox(ax, 5.5, 0.8, 5.0, 1.5, "#7F1D1D", alpha=0.6, radius=0.25)
txt(ax, 8.0, 1.95, "🔄 자동 검증 루프", 12, bold=True, color="#FCA5A5")
txt(ax, 8.0, 1.5,  "신호 구조 검증 → 실패 시 피드백 → LLM 재생성", 10, color=LGRAY)
txt(ax, 8.0, 1.1,  "합격 기준 만족까지 자동 반복", 10, color=LGRAY)
arrow(ax, cx, cy-1.0, cx, 2.3, color="#FCA5A5", lw=2)

# 중앙 에이전트 내부 서브 모듈 표시
sub_agents = ["Spec\nAgent", "Plan\nAgent", "CodeGen\nLLM", "Verify\nAgent"]
sub_colors = [LBLUE, PURPLE, TEAL, GREEN]
for i, (name, c) in enumerate(zip(sub_agents, sub_colors)):
    sx = 3.2 + i * 2.6
    rbox(ax, sx, 3.4, 2.2, 1.25, c, alpha=0.5, radius=0.2)
    txt(ax, sx+1.1, 4.05, name, 9.5, color=WHITE, bold=True)
    if i < 3:
        arrow(ax, sx+2.2, 4.02, sx+2.25, 4.02, color=LGRAY, lw=1.5)

rbox(ax, 3.1, 3.3, 9.7, 1.5, "white", alpha=0.04, radius=0.2)
txt(ax, 8, 3.05, "Agent Pipeline", 9, color=LGRAY)

plt.tight_layout(pad=0)
plt.savefig("/Users/vegitime/.openclaw/workspace/projects/rtl-ai-agent/docs/diagram_concept.png",
            dpi=150, bbox_inches="tight", facecolor=BG)
plt.close()
print("✅ diagram_concept.png 생성 완료")
