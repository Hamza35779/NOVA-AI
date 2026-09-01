"""Model Proving Ground — A/B new models against your own workloads.

The proving ground answers one question per query class: *is the candidate
model actually better than the incumbent on THIS user's traces?* A
benchmark is synthesized from high-feedback interaction traces
(``PersonalBenchmarkSynthesizer``), both models answer the same questions
under the same judge (``EvalRunner`` + ``PersonalBenchmarkScorer``), and
accuracy is compared per query class (``code``/``math``/``short``/``long``/
``general``).

The gauntlet itself is read-only. The only mutation is adopting winners
into the routing policy map (``adoption.py``), which requires either
``[learning.proving] auto_adopt`` or an explicit ``nova prove adopt``.

Modules:

- ``pipeline`` — ``run_proving()``: the head-to-head gauntlet
- ``store`` — ``ProvingRunStore``: SQLite run records
- ``adoption`` — policy map persistence + adoption/revert
- ``watcher`` — new-model detection + auto-prove gating
"""
