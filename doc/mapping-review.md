# Human-readable mapping review

Reconciliation can find an Intention node and a Reality symbol with the same normalized name and
structural type. That narrows the search; it does not prove they have the same responsibility or
that the implementation satisfies the intent.

Run the read-only review before any identity marker is written:

```powershell
uv run dag-tool mapping review `
  --project-path X:\absolute\project `
  --intent-id <guid>
```

The default output is a human decision brief in this order:

1. **What is intended:** responsibility, approval state, confidence, acceptance criteria, and named
   relationships to other Intention nodes.
2. **What exists:** exact Python class or function, source location, docstring, bases, public API,
   and bounded test functions that contain an exact symbol reference.
3. **What was established:** unique structural and source-location facts.
4. **What still needs human judgment:** responsibility equivalence, behavioral evidence, each
   unverified acceptance criterion, and open Intent IR ambiguities.
5. **Decision choices:** approve, reject, or defer. Defer is the default.
6. **Audit metadata:** GUIDs and the digest needed by the approval command.

Related tests are discovery aids, not behavioral proof. Mapping approval means only “this exact
source symbol is the canonical implementation identity for this Intention node.” It does not approve
the Intent IR, close ambiguities, or mark acceptance criteria as satisfied.

Use JSON only for automation or complete evidence inspection:

```powershell
uv run dag-tool mapping review `
  --project-path X:\absolute\project `
  --intent-id <guid> `
  --format json
```

The evidence digest binds the full reviewed Intent semantics, the exact candidate source hash, the
human decision brief, and displayed related-test evidence. The approval command regenerates the
review under lock and rejects changed evidence.
