"""Publishing Assistant: builds the upload package (titles, description, chapters, tags, sources,
synthetic-content disclosure). It never uploads: publishing needs explicit user approval and OAuth."""
from __future__ import annotations

from ..schemas import PublishPackage, ResearchDossier, Script, Storyboard


def _ts(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


def build_package(script: Script, storyboard: Storyboard, dossier: ResearchDossier | None,
                  credits: list[str], *, title_candidates: list[str] | None = None) -> PublishPackage:
    chapters, last_section = [], None
    seg_by_scene = {s.scene_id: s for s in script.segments}
    for scene in storyboard.scenes:
        seg = seg_by_scene.get(scene.scene_id)
        if seg and seg.section != last_section:
            chapters.append({"t": _ts(scene.start_s), "title": seg.section.replace("_", " ").title()})
            last_section = seg.section
    if chapters:
        chapters[0]["t"] = "0:00"                      # YouTube requires the first chapter at 0:00
    used = {sid for seg in script.segments for sid in seg.source_ids}
    if dossier:
        cited = {c.id for seg in script.segments for c in dossier.claims if c.id in seg.claim_ids}
        used |= {sid for c in dossier.claims if c.id in cited for sid in c.source_ids}
        sources = [s for s in dossier.sources if s.id in used and s.source_type != "dataset"]
    else:
        sources = []
    src_lines = [f"- {s.author + ': ' if s.author else ''}{s.title}"
                 f"{' (' + s.publisher + (', ' + s.year if s.year else '') + ')' if s.publisher else ''}"
                 f"{' ' + s.url if s.url else ''}" for s in sources]
    sources_block = "SOURCES\n" + "\n".join(src_lines) + "\n\nMAP DATA & CREDITS\n" + "\n".join(f"- {c}" for c in credits)
    spec_scenes = [s.scene_id for s in script.segments if s.classification == "SPECULATION"]
    description = (
        f"{script.title}\n\n"
        "This video separates documented history from speculation. Scenes marked ALTERNATE HISTORY are a "
        "hypothetical scenario, not historical fact. 3D cities are approximate reconstructions; borders on "
        "maps are approximate.\n\n"
        + "\n".join(f"{c['t']} {c['title']}" for c in chapters) + "\n\n" + sources_block)
    tags = sorted({"history", "alternate history", "roman empire", "what if", "fall of rome", "late antiquity",
                   "byzantine empire", "historical map", "3d reconstruction"})
    return PublishPackage(
        title_candidates=title_candidates or [script.title],
        description=description, chapters=chapters, tags=tags, sources_block=sources_block,
        synthetic_content_disclosure={
            "synthetic_voice": True, "cg_reconstructions": True, "speculative_scenes": spec_scenes,
            "recommendation": "Decide with the channel owner whether YouTube's altered/synthetic content "
                              "label applies; the description already states what is speculative.",
            "decided_by_user": False},
        language=script.language, approved_for_upload=False)
