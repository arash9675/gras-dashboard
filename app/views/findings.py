"""Findings: recommendations written from the current numbers of the selected set."""
from __future__ import annotations

import streamlit as st

import ui
from analytics import metrics as an

ui.page_header("Findings and recommendations")
full = ui.polygons()
if full.empty:
    st.info("No polygons in this set.")
    st.stop()
df = full[full["area_m2"] >= an.PIXEL_M2]  # sub-pixel polygons cannot be resolved at 10 m
n_sub = len(full) - len(df)
st.caption(f"Computed live from the {len(df)} polygons of the selected set that cover at least one 10 m pixel "
           f"(the {n_sub} smaller ones are discussed under Polygon size). Sidebar filters do not apply here.")

v = an.valid(df)
if v.empty:
    st.info("No results yet for this set. Calculate it on Choose data.")
    st.stop()
h = an.headline(df)
regs = [r for r in an.REGIONS if h.get(r, {}).get("n")]
NAMES = an.REGIONS


def nf_split(sub):
    mat = an.agreement_matrix(sub)
    nf = mat.loc["GFC non-forest"]
    tot = nf.sum() or 1
    return {"natural": (nf["Primary forest"] + nf["Naturally regenerating"]) / tot,
            "managed": (nf["Planted forest"] + nf["Plantation forest"]) / tot,
            "crops": nf["Tree crops / agroforestry"] / tot, "other": nf["Other land"] / tot, "nf": nf.sum()}


split = {r: nf_split(v[v["region"] == r]) for r in regs}
sens = an.sensitivity(full).set_index("min_area_m2")
s0, s1, s50 = sens.loc[0], sens.loc[100], sens.loc[5000]
size_line = an.size_effect_note(full)

conf = v.groupby("category")["forty_conf_mean"].mean()
c_both, c_fonly = conf.get("Both forest"), conf.get("ForTy only")
if c_both is not None and c_fonly is not None:
    if c_fonly < c_both - 0.03:
        conf_line = (f"ForTy's own score is lower where only ForTy sees forest ({ui.pct(c_fonly)}) than where "
                     f"both agree ({ui.pct(c_both)}), so ForTy itself signals some doubt in the disputed areas.")
    else:
        conf_line = (f"ForTy is about as confident where only it sees forest ({ui.pct(c_fonly)}) as where both "
                     f"agree ({ui.pct(c_both)}), so the disagreement is not just ForTy being unsure.")
else:
    conf_line = "Not enough polygons in both categories to compare ForTy's confidence."

mostly_real = all(split[r]["natural"] >= split[r]["crops"] + split[r]["managed"] for r in regs)
gap = h["forty_tree"] - h["gfc_forest"]

worst = min(regs, key=lambda r: h[r]["gfc_forest"]) if regs else None
crops_heavy = max(regs, key=lambda r: split[r]["crops"] + split[r]["managed"]) if regs else None
other_txt = ", ".join(f"{ui.pct(h[r]['forty_other'])} in {NAMES[r]}" for r in regs)
both_n = int((v["category"] == "Both forest").sum())
conf_head = (", but is less sure where the maps disagree" if (c_both is not None and c_fonly is not None and c_fonly < c_both - 0.03)
             else ", and is no less sure where the maps disagree")

st.markdown(f"""
### 1. GFC2020 leaves out most of the tree cover that was later cleared
Every polygon here had trees before it was cleared, yet GFC2020 marks only **{ui.pct(h['gfc_forest'])}** of the
polygon area as forest in 2020, against **{ui.pct(h['forty_tree'])}** in a ForTy tree class. The gap is widest in
**{NAMES[worst]}**, where GFC2020 maps {ui.pct(h[worst]['gfc_forest'])} as forest. The two maps give the same
forest/non-forest answer on {ui.pct(h['agreement'])} of pixels.
""")

table = "| | " + " | ".join(f"{NAMES[r]} ({h[r]['n']})" for r in regs) + " |\n|---|" + "---|" * len(regs) + "\n"
for label, col in [("GFC2020: forest", "gfc_forest"), ("ForTy: any tree class (1-5)", "forty_tree"),
                   ("ForTy: forest classes (1-4)", "forty_forest_eudr"), ("ForTy: natural forest (1-2)", "forty_natural"),
                   ("ForTy: tree crops / agroforestry", "forty_treecrops"), ("Same answer, same pixel", "pixel_agreement")]:
    table += f"| {label} | " + " | ".join(ui.pct(h[r][col]) for r in regs) + " |\n"
st.markdown(table + "\n<small>Mean share of each polygon; every clearing counts once. Intervals are on Overview.</small>",
            unsafe_allow_html=True)

nf_table = ("| Where GFC2020 says non-forest, ForTy says… | natural forest | planted / plantation | tree crops | no trees |\n"
            "|---|---|---|---|---|\n" + "".join(
                f"| {NAMES[r]} | **{ui.pct(split[r]['natural'])}** | {ui.pct(split[r]['managed'])} | "
                f"{ui.pct(split[r]['crops'])} | {ui.pct(split[r]['other'])} |\n" for r in regs))
st.markdown(f"""
### 2. {'Most of the gap is a conflict over natural forest, not a difference in definitions' if mostly_real else 'Much of the gap comes from what each map counts as forest'}
GFC2020 deliberately leaves tree crops and agroforestry out of its forest class, so some disagreement is expected.
That explains only a small part of it. On the pixels GFC2020 calls non-forest, ForTy mostly sees natural forest:

{nf_table}
These pixels are the real open question: either GFC2020 misses natural forest there, or ForTy calls forest where
there was none. This data cannot tell which.

### 3. Where the definitions differ, GFC2020 behaves as designed
The definitional share is largest in **{NAMES[crops_heavy]}** ({ui.pct(split[crops_heavy]['crops'] + split[crops_heavy]['managed'])}
of GFC2020's non-forest is tree crops or plantations in ForTy). Coffee and similar tree crops are not forest under
the EUDR, so GFC2020 calling them non-forest is correct, and ForTy users have to drop class 5 to get the same
meaning.

### 4. ForTy almost always sees the trees{conf_head}
ForTy puts only a small share of the cleared area in *other land* ({other_txt}). {conf_line}

### 5. Polygon size does not change the conclusions
{n_sub} polygons are smaller than one 10 m pixel. Earth Engine scores each by the whole pixel it touches, so up
to {(1 - full['area_m2'].min() / an.PIXEL_M2) * 100:.0f}% of that pixel lies outside the clearing; they are left out
here. Adding them back moves GFC2020 from {ui.pct(s1['gfc_forest'])} to {ui.pct(s0['gfc_forest'])}; keeping only
clearings of 0.5 ha or more ({int(s50['n'])}) gives {ui.pct(s50['gfc_forest'])}. {size_line}
""")

st.header("How far each result goes")
ui.callout("High agreement would not prove either map right: both are built from overlapping satellite inputs and "
           "could share errors. Use the comparison to see <i>where and why</i> they differ, and read every result "
           "below at the level of evidence it actually has.", "info")
st.markdown(f"""
| Level | What we did here | What it supports | What it cannot support |
|---|---|---|---|
| **Describing the difference** | Shares, pixel cross-tab and categories for every polygon, by cluster, year and size | Where and how much the maps differ: they agree on {ui.pct(h['agreement'])} of pixels; GFC2020 maps {ui.pct(h['gfc_forest'])} as forest, ForTy {ui.pct(h['forty_tree'])} as trees | Which map is right |
| **Checking plausibility** | Tested each map against known facts: every polygon had trees before clearing | GFC2020 leaves out much of that known tree cover; ForTy rarely does. Also flags odd labels ({int((v['forty_other'] > 0.5).sum())} polygons ForTy sees as mostly treeless) | False forest: there are no treeless reference points, so overstatement is invisible |
| **Validation** | Not possible with these polygons alone | Nothing yet | Accuracy, error rates, confidence that agreement is right |
| **Fitness for a product** | Read the results against a product need (EUDR-style 2020 baseline) | Which classes to use (ForTy 1-4), which map misses known trees, where to spend review effort | A go/no-go decision before a validation sample exists |

To move a result up a level, the next step is a labelled sample of reference points, including stable non-forest,
in each cluster (see below).
""")

st.header("What we recommend")
st.markdown(f"""
- **Do not use GFC2020 alone as the 2020 baseline for a deforestation product.** On land known to have lost trees
  after 2020 it shows forest on only {ui.pct(h['gfc_forest'])} of the area, so clearings of what ForTy sees as
  natural forest would go unreported.
- **Use ForTy's forest classes (1-4), not all its tree classes,** when the product follows the EUDR: class 5 (tree
  crops and agroforestry) is exactly where GFC2020's narrower definition is right.
- **Treat agreement as a filter, not a verdict.** The {both_n} polygons both maps call forest are the safest to
  report. The disagreement layer on the Map is the review list: that is where effort should go.
- **Settle the natural-forest conflict before choosing a map.** Label a few hundred points inside the
  disagreement zone, per cluster, on very high resolution imagery from 2019-2020, and add points of stable forest
  and stable non-forest. That shows which map is wrong there and how often each one raises false alarms, which
  these polygons alone cannot.
- **Set a minimum clearing size** of one pixel for any statistic (five or more is safer), and check sub-pixel
  clearings by other means.
""")

st.header("What this data cannot tell us")
st.markdown("""
- **Whether the cleared land met the EUDR forest definition.** The polygons show trees were removed, not what kind
  of tree cover it was.
- **How often each map calls forest where there is none.** Every polygon is a place that had trees; there are no
  samples of land that never had them.
- **Whether matching answers are right.** Both maps are built from overlapping satellite imagery, so they
  can share the same mistake.
- **How the polygons were drawn** (source imagery, minimum size), which matters for edges and the smallest
  clearings. One polygon is dated 2026, outside the 2021-2024 range of the rest, and should be checked.
""")
