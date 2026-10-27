"""Automatic pattern discovery & consolidation (the research core).

Pipeline per observation (see pipeline.observe):
  observe -> embed -> route
     (a) matches an ACTIVE pattern  -> reinforce.py   (support/recency only; risk scores are
                                                        updated separately by feedback/updates.py)
     (b) otherwise                  -> quarantine.py  (join or create a candidate)
                                    -> coincidence.py (same-pattern vs coincidence filter)
                                    -> reviewer.py    (poison flags + synthetic/human validation)
                                    -> promote.py     (compact-encode into pattern_memory)
                                    -> consolidate.py (merge near-duplicates, forget lowest
                                                        utility under the fixed byte budget B)
No step in this package writes to the policies table.
"""
