"""Turning a PDF into something a reconciler can read. P4.1.

`docs/03` P4.1 is explicit about the shape, and about why it is not "give the PDF to an
LLM": *"the cheap deterministic tools do the bulk reading; the LLM is the reconciliation
brain, not the pixel reader."* This package is the deterministic half - the part that runs
before any model is called, decides which pages are even readable, and hands over text and
tables it did not invent.

It calls no API and needs no key, which is the other reason it is separable: everything in
here can be built, tested and trusted while the model half is still a stub.
"""
