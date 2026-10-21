from pathlib import Path
import py3Dmol

xyz = Path(
    "/work/AG_Presselt/MolCurator/"
    "target_validation/screen/pool_0359/"
    "xyz/pool_0359.xyz"
)

view = py3Dmol.view(width=700, height=500)
view.addModel(xyz.read_text(), "xyz")
view.setStyle({"stick": {"radius": 0.16}, "sphere": {"scale": 0.27}})
view.setBackgroundColor("white")
view.zoomTo()

Path("molecule_pool_0359.html").write_text(
    view._make_html(), encoding="utf-8"
)