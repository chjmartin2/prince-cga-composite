# TITLE.DAT resource 54 transparency

Amir's 2026-08-30 `TITLE.DAT` resource 54 is a 272x65 four-bit title-logo
image. It needs two visually black states with different engine semantics:

- source index 0 is transparent and lets the title or high-score background
  show through;
- nonzero source indices that translate to CGA value `00` are opaque black and
  form the logo's letter outlines.

The work-in-progress archive baked background colors into 3,775 positions that
were index-zero in the original resource. It did not make any originally
opaque pixel transparent. V20W therefore restores the original resource-54
index-zero mask and retains Amir's authored source index everywhere outside
that mask.

The repaired resource contains 9,799 transparent pixels, 1,929 opaque-black
pixels, and 5,952 opaque nonblack pixels. The build verifies those counts, the
complete mask, every retained authored pixel, the LZG round trip, resource
order, DAT checksums, and deterministic hashes.

This is why copying the original mask is safe for this specific asset. It is
not a general rule for arbitrary edited resources: a deliberately redrawn
silhouette may legitimately need a newly authored mask.
