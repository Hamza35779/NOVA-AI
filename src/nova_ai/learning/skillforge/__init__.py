"""Skill Foundry — synthesize skills from repeated tool-run patterns.

The forge mines traces for repeated multi-step tool sequences
(``PatternMiner``), has the local LLM synthesize a skill manifest
chaining those tools (``SkillSynthesizer``), verifies the candidate in a
three-gate gauntlet (``run_gauntlet``), and installs it only after manual
adoption (``adoption``). One entry point ties it together:
:func:`nova_ai.learning.skillforge.pipeline.run_skillforge`.
"""

from nova_ai.learning.skillforge.miner import PatternMiner
from nova_ai.learning.skillforge.pipeline import run_skillforge
from nova_ai.learning.skillforge.store import SkillForgeRunStore

__all__ = ["PatternMiner", "SkillForgeRunStore", "run_skillforge"]
