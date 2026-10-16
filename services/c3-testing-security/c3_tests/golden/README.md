# Golden files: what the tools actually wrote

Not hand written. Every file here was produced by running the real tool on
`fixtures/node-sample` through the harness, and copied here unchanged except
that the absolute workspace path was replaced with `/workspace`, so the files
match on a machine that is not this one.

Their job is to let the parsers be tested in milliseconds without a network,
an install or a mutation pass, while still being tested against what the tools
really emit rather than against what a docstring says they emit. When a tool
changes its report shape, these files stop matching the tool rather than the
parser quietly going wrong, so re-capture them and read the diff.

## Provenance

| File | Produced by | Version | Date |
|---|---|---|---|
| `node/vitest.json` | `vitest run --reporter=json` | vitest 4.1.11 | 2026-08-29 |
| `node/coverage-summary.json` | `--coverage.provider=v8 --coverage.reporter=json-summary` | @vitest/coverage-v8 4.1.11 | 2026-08-29 |
| `node/mutation.json` | `stryker run --testRunner vitest --reporters json --disableBail` | @stryker-mutator/core 10.0.0, vitest-runner 10.0.0, vitest 3.2.7 | 2026-09-08 |
| `node/mutation-with-bail.json` | the same run without `--disableBail` | @stryker-mutator/core 10.0.0, vitest-runner 10.0.0, vitest 4.1.11 | 2026-08-29 |
| `java/surefire-TotalsTest.xml` | `./mvnw -B test` | maven-surefire-plugin 3.5.6, JUnit 5.12.2 | 2026-08-29 |
| `java/jacoco.xml` | the JaCoCo agent and report goal | jacoco-maven-plugin 0.8.13 | 2026-08-29 |
| `java/mutations.xml` | `org.pitest:pitest-maven:mutationCoverage -DfullMutationMatrix=true` | pitest-maven 1.19.1, pitest-junit5-plugin 1.2.2 | 2026-09-08 |
| `java/spotbugsXml.xml` | `./mvnw compile spotbugs-maven-plugin:4.9.3.0:spotbugs` | spotbugs-maven-plugin 4.9.3.0, findsecbugs-plugin 1.14.0 | 2026-09-10 |

Toolchain: node 22.17.0, npm 10.9.2, Maven 3.9.16 through the wrapper 3.3.4,
javac 21.0.12. Commit: the one that added this file.

`java/spotbugsXml.xml` keeps its five bug instances and its errors block; the
pattern catalogue, the class feature dump and the summary are removed on
capture, along with the two analysis timestamps, none of which the parser
reads and all of which are this machine's clock. What remains is unedited.

The surefire report's `<properties>` block is removed on capture. It records
the whole JVM environment, including the absolute classpath and this machine's
user, and none of it is the shape under test.

`node/mutation-with-bail.json` is kept deliberately, as the only evidence for a
one word flag. It is a real report over the same fixture with `disableBail` off,
in which a perfectly good test covers two mutants and kills none because another
test killed them first and the runner stopped. Without it, nothing in the
repository would show why `--disableBail` is passed, and the next person to
remove it for speed would find out slowly.

The two mutation reports were re-captured on 2026-09-08 with complete
attribution: `--disableBail` for Stryker and `fullMutationMatrix` for PIT. The
verdicts are unchanged by either flag (node 19.05 percent, java 52.63 percent,
the same before and after), so only who gets credit moved.

## Re-capturing

```
uv run pytest services/c3-testing-security -m sandbox   # runs the real tools
```

The lane tests write their workspace under pytest's `tmp_path` and the files
above are copied out of it with the workspace path replaced.
