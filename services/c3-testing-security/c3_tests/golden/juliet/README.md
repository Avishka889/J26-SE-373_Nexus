# A Juliet shaped fixture, written here rather than copied

Juliet is public domain, so its files could have been vendored. These are
hand written instead, for one reason: a real Juliet test case is 150 lines of
try/finally boilerplate around three interesting ones, and a fixture whose
point is the parser's edge cases should show those edges rather than bury
them.

The naming, the `bad`/`goodG2B`/`goodB2G` method convention, the `good()`
dispatcher and the variant 81 file split are copied exactly from the real
corpus, because those are the shapes under test. The bodies are not.

The parser is also run against the real 46,793 file corpus, by the test marked
`corpus`, which skips when the archive is not unpacked at
`~/datasets/juliet-java-1.3`. That is where the claim "the braces balance in
every extracted method" is actually checked.
