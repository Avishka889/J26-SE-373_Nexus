# node-sample

A hand written npm workspace with the shape C2 generates: a root that declares
`apps/*`, one app in `apps/web`, source under `src` and tests under
`src/__tests__`.

It exists so the MERN lane can be exercised in seconds against something this
repository owns, rather than by generating a project first. Nothing in here is
copied from anywhere: it is small enough to write, and that keeps the licence
question from arising at all.

Deliberately not all green. `total` has a branch no test reaches, so coverage
is a number rather than 100, and there is a mutant no test kills. A fixture
where everything passes would prove the harness can report success and nothing
else.
