"""Search/Replace patch generation — model-friendly alternative to unified diffs.

Instead of asking a model to produce a unified diff (which requires correct line
numbers, counts, and verbatim context simultaneously), this package asks the model
for ``<<<<<<< SEARCH / ======= / >>>>>>> REPLACE`` blocks.  The model only needs
to copy the *content* it wants to change; forge does the file search, applies the
edits in memory, and generates a reviewable unified diff automatically.
"""

from forge.srp.applier import apply_blocks
from forge.srp.models import BlockApplication, SearchReplaceBlock, SearchReplaceResult
from forge.srp.parser import ParseError, parse_search_replace_blocks

__all__ = [
    "BlockApplication",
    "ParseError",
    "SearchReplaceBlock",
    "SearchReplaceResult",
    "apply_blocks",
    "parse_search_replace_blocks",
]
