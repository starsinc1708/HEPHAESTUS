You are resolving git merge conflicts. The working directory contains files with
conflict markers (<<<<<<<, =======, >>>>>>>).

Task intent (preserve this behavior):
{intent}

Files with conflicts:
{files}

Rules:
- Resolve each conflicted file so BOTH sides' intent is preserved.
- Include all imports from both sides. Preserve hook/initialization ordering
  (earlier side first / outer). Combine edits to the same function logically.
- Remove EVERY conflict marker (<<<<<<<, =======, >>>>>>>).
- Edit the files IN PLACE in the working directory. Do NOT touch any other files.
- Do not add features or refactor beyond resolving the conflict.

When done, output a one-line summary of how you resolved them.
