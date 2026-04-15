# Import Notes

## Sources Used
- The prophecy catalog was imported from `sources/raw/351-list.docx/351-Old-Testament-Prophecies-Fulfilled-in-Jesus-Christ.docx`.
- The failed-criteria mapping was imported from `sources/raw/skeptic-criteria.docx/Prophecy criteria evaluation.docx`.
- The six-criteria definitions remain documented in [content/methodology.md](/workspaces/351-prophecies-project/content/methodology.md).

## Imported Automatically
- prophecy number
- title
- slug (preserved from the current dataset)
- Old Testament reference
- claim summary
- claimed New Testament fulfillment
- skeptic failed criteria
- status (preserved from the current dataset)

## What Matched Cleanly
- All 351 prophecy rows were extracted from the source list docx.
- All 351 failed-criteria rows were extracted from the criteria docx.
- Number-to-number matching between the two source documents was clean.

## What Needs Manual Review
- Existing chapter-level anchor pages are still being used for some first-in-sequence numbered claims.
- The project still contains one orphan page that is not part of the 351-entry dataset.
- Some older flagship page files still contain chapter-level placeholder wording that does not perfectly match the imported claim-level titles.
- Generated placeholder pages still need actual research content.

## Unclear Matches Or Placeholder Values
- Orphan page(s) with no matching YAML entry: micah-4.
- Every YAML entry currently has a matching prophecy page file.
- The import preserved the existing slug strategy rather than renaming files during this pass.
- Existing overview-style pages such as `isaiah-53.md` and `psalm-22.md` should be reviewed later to decide whether they remain overview pages or become strictly claim-level pages.

Examples of reused anchor pages:
- #22 exodus-12 <= Exodus 12:5
- #49 2-samuel-7 <= 2 Samuel 7:12
- #59 psalm-2 <= Psalm 2:1-3
- #70 psalm-16 <= Psalm 16:10
- #74 psalm-22 <= Psalm 22:1
- #148 psalm-110 <= Psalm 110:1
- #186 isaiah-11 <= Isaiah 11:1
- #210 isaiah-42 <= Isaiah 42:1-4
- #231 isaiah-50 <= Isaiah 50:3
- #242 isaiah-53 <= Isaiah 53:1
- #285 isaiah-61 <= Isaiah 61:1a
- #291 jeremiah-31 <= Jeremiah 31:22
