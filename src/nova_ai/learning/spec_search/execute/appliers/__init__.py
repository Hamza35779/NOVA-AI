"""Concrete EditApplier implementations.

Importing this package triggers registration of all appliers
in the EditApplierRegistry. Applier modules are imported in Task 6
once all implementations exist.

``lora.py`` holds the real LORA_FINETUNE applier (v2); ``lora_stub.py``
is kept as the torch-free fallback that refuses the op with the v1
"deferred" message.
"""
