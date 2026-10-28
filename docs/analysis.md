# Analysis and findings

What the 198 deforestation polygons tell us about JRC GFC2020 v4 and ForTy 2020
v1.0. All numbers are from the reference set, latest extraction, area-weighted at
10 m. Unless stated otherwise they cover the 172 polygons of at least one pixel
(see [design-decisions.md](design-decisions.md#6-polygons-smaller-than-one-pixel-are-left-out-of-statistics)).
Every figure can be reproduced from the `q_*` views on the Insights page.

## What the polygons can and cannot tell us

Each polygon marks land where trees were cleared some time after 2020. So in
2020 there were trees there: the polygons are positive examples of tree cover.

- A map that shows **no forest** inside a polygon has missed trees that existed
  (or classed them as something it does not call forest).
- A map that shows **forest** is consistent with the polygon, but this is not
  proof it is right: we have no negative examples, so false forest elsewhere is
  invisible to this test.
- Both maps are built from overlapping satellite archives, so agreement between
  them is not independent confirmation.

We therefore read the numbers as "how much known tree cover each map captures,
and how it labels it", not as accuracy.

## Headline

| | Polygons | GFC2020 forest | ForTy any tree class (1-5) | ForTy forest (1-4) | ForTy natural (1-2) | Same answer, same pixel | Polygons both call forest |
|---|---|---|---|---|---|---|---|
| All | 172 | 37.5% | 89.8% | 80.4% | 67.1% | 44.0% | 60 (35%) |
| Uganda | 81 | 18.7% | 89.4% | 88.2% | 88.2% | 29.3% | 13 (16%) |
| Brazil · west | 41 | 57.9% | 92.2% | 74.8% | 39.9% | 60.6% | 24 (59%) |
| Brazil · east | 50 | 51.3% | 88.7% | 72.3% | 55.1% | 54.3% | 23 (46%) |

*The share columns are mean shares of polygon area, each polygon counting once.
"Same answer, same pixel" is the share of pixels where both maps give the same
forest / not-forest answer (GFC2020 forest against ForTy classes 1-5). The last
column counts polygons where each map calls at least half the area forest.*

**1. ForTy captures far more of the cleared tree cover than GFC2020.** About nine
in ten cleared hectares were trees according to ForTy, against fewer than four in
ten for GFC2020. Even on the strictest ForTy reading (natural forest only) ForTy
is ahead by almost 30 points.

**2. Most of the gap is a disagreement about natural forest, not about definitions.**
Where GFC2020 says "not forest", ForTy mostly does *not* say "no trees". It says:

| Inside GFC2020's non-forest area | Natural forest | Plantation / planted | Tree crops | Other land |
|---|---|---|---|---|
| All | 68.0% | 0.5% | 15.8% | 15.8% |
| Uganda | 84.6% | 0% | 1.4% | 14.0% |
| Brazil · west | 42.1% | 1.6% | 37.6% | 18.7% |
| Brazil · east | 63.4% | 0.1% | 20.3% | 16.2% |

Only about one sixth of GFC2020's misses is land ForTy also sees as treeless,
and another sixth is tree crops or plantations, which a strict forest definition
would leave out anyway. Two thirds is land ForTy calls natural forest: there the
two maps simply disagree about whether forest was present.

**3. Uganda is where GFC2020 struggles most.** It sees forest on under a fifth of
Uganda's cleared area, while ForTy places almost all of it in natural forest.
These are small clearings in a mosaic of farms and woodland; GFC2020's
minimum-area and canopy rules are likely to drop such patches, while ForTy's
10 m classification keeps them. 60 of Uganda's 81 polygons are "ForTy only".

**4. In western Brazil the disagreement is about what counts as forest.**
Here the two maps agree most often (61% of pixels, 24 of 41 polygons), but where GFC2020 says non-forest,
ForTy calls almost two fifths of it tree crops. Under an EUDR-like definition
tree crops are not forest, so ForTy's 1-4 figure (75%) is the fairer comparison
than its 1-5 figure (92%).

## Polygon outcomes

| Category | Uganda | Brazil · west | Brazil · east | Total |
|---|---|---|---|---|
| Both forest | 13 | 24 | 23 | 60 |
| ForTy only | 60 | 15 | 24 | 99 |
| GFC2020 only | 0 | 0 | 2 | 2 |
| Neither | 8 | 2 | 1 | 11 |

GFC2020 almost never sees forest where ForTy does not (2 polygons). The
relationship is close to one-way: GFC2020's forest is largely a subset of
ForTy's tree cover in these polygons.

The 11 "neither" polygons, and the 13 where ForTy itself sees mostly no trees,
are worth a manual look: they may be clearings of sparse woodland, labelling
errors, or land that changed before 2020.

## What was lost (by ForTy class)

70.8 ha were cleared in total. By ForTy's 2020 class:

| ForTy class | Hectares | Share |
|---|---|---|
| Naturally regenerating forest | 40.3 | 57% |
| Plantation forest | 16.9 | 24% |
| Other land | 7.9 | 11% |
| Tree crops | 5.7 | 8% |
| Primary forest, planted forest | 0 | 0% |

- **Uganda** (20.5 ha): almost entirely naturally regenerating forest (17.7 ha).
- **Brazil · west** (30.5 ha): mostly plantation (15.0 ha) and naturally
  regenerating forest (9.0 ha), which fits harvest and replanting cycles.
- **Brazil · east** (19.8 ha): mostly naturally regenerating forest (13.6 ha).

No polygon falls in primary forest. Either the sample does not include clearing
of primary forest, or ForTy labels old-growth stands in these landscapes as
naturally regenerating; this sample cannot tell the two apart.

## Over time

| Year cleared | Polygons | GFC2020 forest | ForTy any tree class |
|---|---|---|---|
| 2021 | 27 | 59.2% | 88.9% |
| 2022 | 42 | 41.9% | 94.7% |
| 2023 | 49 | 29.7% | 91.1% |
| 2024 | 53 | 30.3% | 85.1% |

GFC2020's share falls with later years while ForTy's stays near 90%. This is
mostly a change in where the polygons are: later years contain more Ugandan
clearings, where GFC2020 is weak. It is a sampling effect, not evidence that
either map degrades. One polygon is dated 2026, outside the range a 2020 map can
be judged on; it is kept but noted.

## Polygon size matters

| Minimum size | Polygons | GFC2020 forest | ForTy 1-5 | Both forest |
|---|---|---|---|---|
| none | 198 | 37.1% | 90.7% | 42.3% |
| 100 m² (1 pixel, default) | 172 | 37.5% | 89.8% | 44.0% |
| 500 m² | 142 | 36.0% | 88.4% | |
| 1,000 m² | 106 | 39.5% | 90.3% | |
| 5,000 m² (0.5 ha) | 41 | 50.9% | 91.0% | 54.7% |

The polygons range from 2.5 m² to 4.8 ha, median 1,222 m² (about 12 pixels).
GFC2020 looks much better on large clearings, but 71% of the 0.5 ha+ polygons
are in Brazil. Within one region the effect is smaller: about +14 points in
Brazil and +1 point in Uganda. So GFC2020 does favour larger patches, but most
of the jump in the table is the regional mix again.

ForTy is stable across sizes, which fits its 10 m native resolution.

The 26 sub-pixel polygons are excluded because their value is decided by the
pixel they happen to touch rather than by the clearing itself.

## Confidence

ForTy's confidence (winning class score / 250) is high almost everywhere:
median 0.94 where both maps agree on forest and 0.97 where only ForTy sees
forest. So ForTy is not unsure in the cases that separate it from GFC2020.
Confidence is lowest in the two "GFC2020 only" polygons (median 0.77) and the
"neither" polygons (0.86) - the mixed or sparse cases. Uganda's mean (0.95) is
higher than Brazil's (0.86), where plantation, tree crops and natural forest are
harder to tell apart.

## Location clusters

K-means on polygon centroids (in 3-D Earth-centred km, k chosen by silhouette)
finds three groups with a silhouette of 0.89: Uganda, Brazil west and Brazil
east. The east-west split in Brazil is worth keeping: the two halves differ by
15 points in ForTy natural forest share and in what dominates the losses
(plantation in the west, natural regrowth in the east).

## Conclusions

1. For these clearings, ForTy captures the tree cover that existed in 2020 far
   more completely than GFC2020 (about 90% against 38% of the area).
2. Two thirds of the difference is land ForTy calls natural forest and GFC2020
   calls non-forest, mostly small, mixed or regrowing tree cover. Tree crops
   explain a smaller part, mainly in western Brazil, and there the right answer
   depends on the forest definition being applied.
3. When using ForTy for EUDR-style checks, use classes 1-4 (forest) rather than
   all tree classes; it removes tree crops and still captures 80% of the cleared
   area.
4. GFC2020 is a conservative map in these regions: when it says forest, ForTy
   agrees; when it says non-forest, there are often trees.
5. Regional and size mix drive many of the apparent trends; compare like with
   like (one cluster, one size range) before drawing conclusions.

## Limits

- 198 polygons in two countries; not a random sample of either country, and no
  non-forest reference points, so no false-positive rate can be measured.
- Both maps sampled on a 10 m EPSG:4326 grid; ForTy's native UTM grid can shift
  values for very small polygons.
- The 50% threshold for categories is a presentation choice; shares underneath
  are continuous.
- Results reflect the dataset versions recorded on each extraction run.
