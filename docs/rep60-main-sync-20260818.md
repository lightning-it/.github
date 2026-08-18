# REP-60 protected-branch ancestry sync

This one-time record accompanies the normal merge that reconnects the protected
`main` and `develop` histories before the current-revision verifier is promoted.

- Develop tip before the ancestry merge: `301da48ea24fe41968554b14c0b2b9efb3a587db`
- Main tip merged into the sync branch: `8c576504dc69bf24e740f9fe21feee3f446dd1b4`
- Local two-parent ancestry merge: `5e9dd688df95f97bceb4cd5e194c18154e741d54`

The merge preserved the current `develop` tree. This evidence file gives the
normal human-authored pull request a reviewable change without bypassing branch
protection, rewriting history, or writing directly to either protected branch.
