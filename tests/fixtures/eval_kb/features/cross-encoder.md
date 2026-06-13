# Cross-encoder

A **cross-encoder** feeds the query and a candidate document through the model
together and emits a single relevance score. It is accurate but far too slow to
run over a whole index, so it only re-scores a shortlist of candidates.
